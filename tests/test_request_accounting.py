"""Real request serialization, state accounting and compactor integration (no model doubles)."""
import copy
import json
import time
from decimal import Decimal

import pytest

from nanocode.openai_adapter import OpenAIModelAdapter
from nanocode.anthropic_adapter import AnthropicModelAdapter
from nanocode.tooling import ToolRegistry
from nanocode.tools.read_file import read_file_tool
from nanocode.model_policy import resolve_model_policy
from nanocode.context_manager import ContextManager, estimate_messages_tokens
from nanocode.context_compactor import ContextCompactor
from nanocode.context_cybernetics import ContextCyberneticsOrchestrator
from nanocode.cost_tracker import CostTracker
from nanocode.state import create_app_store


def runtime():
    return {"model": "qwen3.8-flash", "openaiBaseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1"}


def adapter():
    return OpenAIModelAdapter(runtime(), ToolRegistry([read_file_tool]))


def messages():
    return [{"role": "system", "content": "中文回答，只读文件。"}, {"role": "user", "content": "P11 initial constraints"}]


def test_official_policy_and_unpriced_third_party_channel():
    policy = resolve_model_policy("qwen3.8-flash", runtime())
    assert policy.context_window == 1_000_000
    assert policy.price.currency == "CNY"
    assert policy.price.calculate(5858, 56) == Decimal("0.0048376")
    assert resolve_model_policy("qwen3.8-flash", endpoint="https://relay.example/v1").price is None
    assert resolve_model_policy("never-priced-model").price is None


def test_supported_stream_requests_usage_without_changing_input_fingerprint():
    model = adapter()
    normal = model.build_request_body(messages())
    stream = model.build_request_body(messages(), stream=True)
    assert stream["stream_options"] == {"include_usage": True}
    assert model.token_accounting.request_hash(normal) == model.token_accounting.request_hash(stream)
    proxy = OpenAIModelAdapter({"model": "unknown", "openaiBaseUrl": "https://relay.example/v1"}, ToolRegistry([]))
    assert "stream_options" not in proxy.build_request_body(messages(), stream=True)


def test_unanchored_budget_covers_the_recorded_real_streaming_sample():
    model = adapter()
    prompt = [{"role": "system", "content": "只读验证。不得调用工具或读写文件。"},
              {"role": "user", "content": "只回复 P11_ACCOUNTING_OK，不要解释，不调用工具。"}]
    # The actual 2026-11-05 verification returned 358 input tokens. The prior
    # chars/4 request estimate returned 198; it must not be treated as safe.
    assert model.token_accounting.measure(prompt).input_tokens >= 358


def test_complete_request_counts_tool_definitions_and_invalidates_schema_changes():
    model = adapter()
    prompt = messages()
    with_tools = model.token_accounting.measure(prompt)
    assert with_tools.input_tokens > estimate_messages_tokens(prompt)
    body = model.build_request_body(prompt)
    model.token_accounting.observe(body, {"prompt_tokens": 1000}, 1000)
    assert model.token_accounting.measure(prompt).source == "provider_usage"
    # Use a real independent registry so the global tool definition stays untouched.
    changed_tool = copy.deepcopy(read_file_tool)
    changed_tool.input_schema["description"] = "schema changed " * 200
    model.tools = ToolRegistry([changed_tool])
    changed = model.token_accounting.measure(prompt)
    assert changed.source.endswith("request_estimate") and not changed.exact
    assert model.build_request_body(prompt)["tools"] != body["tools"]
    snapshot = model.build_request_body(prompt)
    old_description = snapshot["tools"][0]["function"]["parameters"]["description"]
    changed_tool.input_schema["description"] = "another schema version"
    assert snapshot["tools"][0]["function"]["parameters"]["description"] == old_description


def test_provider_anchor_uses_input_only_and_new_visible_messages():
    model = adapter()
    prompt = messages()
    body = model.build_request_body(prompt)
    model.record_response_usage(body, {"prompt_tokens": 5858, "completion_tokens": 500,
        "completion_tokens_details": {"reasoning_tokens": 490}}, None, time.monotonic())
    assert model.token_accounting.measure(prompt).input_tokens == 5858
    result = model.token_accounting.measure(prompt + [{"role": "assistant", "content": "OK"}])
    assert 5858 < result.input_tokens < 6100
    assert result.source == "provider_usage_plus_estimate" and not result.exact
    prompt[0]["content"] += "新增项目记忆"
    assert model.token_accounting.measure(prompt).source.endswith("request_estimate")


def test_cached_tokens_are_in_context_once_and_priced_once():
    model = adapter()
    store = create_app_store()
    body = model.build_request_body(messages())
    raw = {"prompt_tokens": 100, "completion_tokens": 20,
           "prompt_tokens_details": {"cached_tokens": 40, "cache_creation_input_tokens": 10}}
    model.record_response_usage(body, raw, store, time.monotonic())
    record = store.get_state().cost_tracker.records[-1]
    assert record["tokens"] == {"input": 50, "output": 20, "cache_read": 40, "cache_write": 10}
    assert model.token_accounting.measure(messages()).input_tokens == 100
    assert record["raw_usage"] == raw and record["request_hash"]


def test_anthropic_cache_fields_are_additive_input_and_prepare_is_pure():
    model = AnthropicModelAdapter({"model": "claude-sonnet-4-20250514", "baseUrl": "https://api.anthropic.com"}, ToolRegistry([]))
    model._thinking_blocks = [{"type": "thinking", "thinking": "retained", "signature": "sig"}]
    prompt = messages() + [{"role": "assistant", "content": "previous"}]
    body = model.build_request_body(prompt)
    assert model.build_request_body(prompt) == body and model._thinking_blocks
    model.record_response_usage(body, {"input_tokens": 50, "output_tokens": 900,
        "cache_read_input_tokens": 40, "cache_creation_input_tokens": 10}, None, time.monotonic())
    assert model.token_accounting.measure(prompt).input_tokens == 100


def test_ui_compactor_and_cybernetics_share_full_request_count(tmp_path):
    model = adapter()
    prompt = messages()
    model.token_accounting.observe(model.build_request_body(prompt), {"prompt_tokens": 5858}, 5858)
    manager = ContextManager(model="qwen3.8-flash", messages=prompt)
    manager.configure_accounting(model)
    compactor = ContextCompactor(context_window=manager.effective_input, workspace=tmp_path,
                                total_count_fn=manager.count_tokens)
    orch = ContextCyberneticsOrchestrator(compactor)
    orch.run_cycle(prompt)
    assert manager.get_stats().total_tokens == compactor.count_tokens(prompt) == 5858
    assert orch.sensor.get_recent_readings(1)[0].token_count == 5858
    assert manager.output_reserve == model.build_request_body(prompt)["max_tokens"]
    assert manager.effective_input < manager.context_window


def configured_price(version, rate):
    return {"model": "qwen3.8-flash", "endpoint": "https://dashscope.aliyuncs.com", "pricing": {
        "currency": "CNY", "input": rate, "output": "2.7", "cacheRead": "0.1", "cacheWrite": "1.25",
        "version": version, "sourceUrl": "https://help.aliyun.com/en/model-studio/qwen3-8-flash", "verifiedAt": "2026-11-05"}}


def test_tariff_update_does_not_reprice_history_or_mix_currency():
    config = runtime() | {"modelPolicies": [configured_price("v1", "0.8")]}
    tracker = CostTracker()
    tracker.add_usage("qwen3.8-flash", 1000, 0, runtime=config)
    original = copy.deepcopy(tracker.records[0])
    config["modelPolicies"][0] = configured_price("v2", "1.6")
    tracker.add_usage("qwen3.8-flash", 1000, 0, runtime=config)
    tracker.add_usage("gpt-4o", 1000, 0)
    assert tracker.records[0] == original
    assert tracker.totals_by_currency == {"CNY": Decimal("0.0024"), "USD": Decimal("0.0025")}
    assert tracker.total_cost_usd == pytest.approx(0.0025)
    assert "CNY" in tracker.format_cost_report() and "USD" in tracker.format_cost_report()


def test_unknown_price_preserves_raw_usage_and_never_reports_free():
    tracker = CostTracker()
    tracker.add_usage("unknown", 1000, 200, raw_usage={"prompt_tokens": 1000})
    assert tracker.records[0]["amount"] is None and tracker.records[0]["pricing"] is None
    assert "Unpriced responses: 1" in tracker.format_cost_report()
    assert "unpriced" in tracker.format_cost_report(True)


@pytest.mark.parametrize("rate", ["-1", "NaN", "Infinity"])
def test_invalid_configured_prices_are_rejected(rate):
    with pytest.raises(ValueError):
        resolve_model_policy("qwen3.8-flash", runtime() | {"modelPolicies": [configured_price("invalid", rate)]})


def test_model_registry_does_not_reapply_official_price_to_relay():
    from nanocode.model_registry import resolve_model_info
    info = resolve_model_info("gpt-4o", runtime={"openaiBaseUrl": "https://relay.example/v1"})
    assert info.pricing_input is None and info.pricing_currency is None


def test_session_keeps_cost_records_without_restarting_process_counters(tmp_path, monkeypatch):
    import nanocode.session as session_module
    from nanocode.session import SessionData, save_session, load_session
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    session = SessionData("pricing-record", 1.0, 1.0, str(tmp_path))
    tracker = CostTracker()
    tracker.add_usage("qwen3.8-flash", 5858, 56, runtime=runtime())
    session.cost_records = tracker.records
    save_session(session)
    loaded = load_session("pricing-record")
    assert loaded.cost_records == tracker.records
    assert CostTracker().get_total_calls() == 0


def test_saved_context_keeps_count_source_but_mutation_invalidates_it(tmp_path, monkeypatch):
    import nanocode.context_manager as context_module
    monkeypatch.setattr(context_module, "NANO_CODE_DIR", tmp_path)
    model = adapter()
    prompt = messages()
    model.token_accounting.observe(model.build_request_body(prompt), {"prompt_tokens": 5858}, 5858)
    manager = ContextManager(model="qwen3.8-flash", messages=prompt)
    manager.configure_accounting(model)
    context_module.save_context_state(manager)
    loaded = context_module.load_context_state()
    assert loaded.get_stats().total_tokens == 5858
    assert loaded.get_stats().accounting_source == "provider_usage"
    loaded.messages[0]["content"] += "changed"
    assert loaded.get_stats().accounting_source == "message_estimate"


def test_compaction_retains_initial_constraints_and_active_task(tmp_path):
    from nanocode.context_compactor import AutoCompactConfig
    model = adapter()
    prompt = messages() + [{"role": "assistant", "content": "old result " * 600}] * 20
    prompt.append({"role": "user", "content": "current active task"})
    manager = ContextManager(model="qwen3.8-flash", messages=prompt)
    manager.configure_accounting(model)
    compactor = ContextCompactor(context_window=2000, workspace=tmp_path,
        total_count_fn=manager.count_tokens, config=AutoCompactConfig(threshold_ratio=0.5))
    result = compactor.process_request(prompt)
    assert messages()[1] in result.messages
    assert prompt[-1] in result.messages
    assert manager.count_tokens(result.messages) < manager.count_tokens(prompt)
    emergency = compactor.reactive._aggressive_truncate(prompt)
    assert messages()[1] in emergency.messages and prompt[-1] in emergency.messages
    assert emergency.boundary.tokens_before == manager.count_tokens(prompt)
    assert emergency.boundary.tokens_after == manager.count_tokens(emergency.messages)


def test_output_reserve_blocks_oversized_request_before_any_transport():
    config = runtime() | {"modelPolicies": [{"model": "qwen3.8-flash", "endpoint": "https://dashscope.aliyuncs.com",
        "contextWindow": 4096, "maxInputTokens": 3800, "maxOutputTokens": 512, "outputReserve": 512, "safetyMargin": 64}]}
    model = OpenAIModelAdapter(config, ToolRegistry([]))
    with pytest.raises(ValueError, match="effective input budget"):
        model.next([{"role": "user", "content": "long input " * 10000}])
    assert model.token_accounting.last_usage is None


def test_counting_origin_validation_keeps_fallback_visible_without_sending_credentials():
    config = runtime() | {"tokenCounting": {"endpoint": "https://other.example/count", "thresholdRatio": 0}}
    model = OpenAIModelAdapter(config, ToolRegistry([]))
    result = model.token_accounting.measure(messages(), allow_remote=True)
    assert not result.exact and result.input_tokens > 0
    assert "counting unavailable" in result.reason
    assert model.token_accounting.count_requests == 0
    assert "counting unavailable" in model.token_accounting.measure(messages()).reason


def test_incomplete_usage_is_unpriced_even_when_the_tariff_is_known():
    tracker = CostTracker()
    tracker.add_usage("qwen3.8-flash", 100, 0, runtime=runtime(), usage_source="unavailable")
    assert tracker.records[0]["pricing"]["currency"] == "CNY"
    assert tracker.records[0]["amount"] is None
    assert tracker.totals_by_currency == {}
    assert "Unpriced responses: 1" in tracker.format_cost_report()


def test_price_tier_uses_full_input_including_cache():
    entry = configured_price("tiered", "0.8")
    entry["pricing"]["tiers"] = [{"maxInputTokens": 32000, "input": "0.8"},
                                 {"maxInputTokens": 64000, "input": "1.6", "output": "5.4"}]
    config = runtime() | {"modelPolicies": [entry]}
    tracker = CostTracker()
    tracker.add_usage("qwen3.8-flash", 30000, 1, cache_read_tokens=5000, runtime=config)
    record = tracker.records[0]
    assert record["pricing"]["input"] == "1.6" and record["pricing"]["tier_limit"] == 64000
    assert Decimal(record["amount"]) == Decimal("0.0485054")


def test_region_specific_quote_overrides_generic_quote_without_currency_guessing():
    generic = configured_price("generic", "0.8")
    regional = configured_price("regional", "1.6") | {"region": "cn-beijing"}
    policy = resolve_model_policy("qwen3.8-flash", runtime() | {"modelPolicies": [generic, regional]})
    assert policy.price.version == "regional"
    unknown = resolve_model_policy("qwen3.8-flash", runtime() | {"modelRegion": "unverified-region"})
    assert unknown.price is None


def test_cost_only_delta_writer_preserves_every_price_version(tmp_path, monkeypatch):
    import nanocode.session as session_module
    from nanocode.session import SessionData, save_session, load_session
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    session = SessionData("cost-only-delta", 1.0, 1.0, str(tmp_path))
    tracker = CostTracker()
    tracker.add_usage("qwen3.8-flash", 10, 1, runtime=runtime())
    session.cost_records = list(tracker.records)
    save_session(session)
    tracker.add_usage("qwen3.8-flash", 20, 1, runtime=runtime() | {"modelPolicies": [configured_price("new", "1.6")]})
    session.cost_records = list(tracker.records)
    session_module._save_delta(session)
    loaded = load_session("cost-only-delta")
    assert loaded.cost_records == tracker.records
    assert len(list(tmp_path.rglob("delta_*.json"))) == 1


def test_current_context_command_never_reads_another_sessions_snapshot():
    from nanocode.cli_commands import try_handle_local_command
    manager = ContextManager(model="default", messages=[{"role": "user", "content": "current"}])
    result = try_handle_local_command("/context", context_manager=manager)
    assert "Messages: 1" in result
    assert "message_estimate" in result
    assert "current session" in try_handle_local_command("/context", context_manager=ContextManager())


def test_cost_control_reads_currency_ledger_and_rejects_mixed_units():
    from nanocode.agent_loop import _update_cost_control
    from nanocode.cost_control import CostControlLoop
    model = adapter()
    store = create_app_store()
    model.record_response_usage(model.build_request_body(messages()), {"prompt_tokens": 5858, "completion_tokens": 56}, store, time.monotonic())
    controller = CostControlLoop(currency="CNY")
    _update_cost_control(controller, store)
    assert controller.last_reading.cost_usd == pytest.approx(0.0048376)  # Legacy sensor field; currency is explicit.
    assert controller.get_stats()["currency"] == "CNY"
    with pytest.raises(ValueError, match="currency"):
        controller.run_in_currency(amount=1, currency="USD", total_tokens=100, total_calls=1)


def _real_budget_read(tmp_path):
    from nanocode.tooling import ToolContext

    source = tmp_path / "source.txt"
    source.write_text("只读数据，不得改写。\n" * 1500, encoding="utf-8")
    result = read_file_tool.run(
        {"path": source.name, "offset": 0, "limit": 20000},
        ToolContext(cwd=str(tmp_path)),
    )
    assert result.ok
    return messages() + [
        {"role": "assistant_tool_call", "toolName": "read_file", "toolUseId": "budget-read",
         "input": {"path": source.name}},
        {"role": "tool_result", "toolName": "read_file", "toolUseId": "budget-read", "content": result.output},
        {"role": "user", "content": "P11_BUDGET_CHECK; retain the read-only constraint"},
    ]


def test_request_budget_persists_real_output_even_when_pressure_controller_does_not_act(tmp_path):
    from pathlib import Path
    from nanocode.agent_loop import _prepare_tool_result_budget

    prompt = _real_budget_read(tmp_path)
    original = copy.deepcopy(prompt)
    manager = ContextManager(model="qwen3.8-flash", messages=prompt)
    manager.configure_accounting(adapter())
    compactor = ContextCompactor(
        context_window=manager.effective_input, workspace=tmp_path,
        total_count_fn=manager.count_tokens,
    )
    unchanged, result, action = ContextCyberneticsOrchestrator(compactor).run_cycle(prompt)
    assert unchanged == prompt and result is None and not action.force_execution
    measurement_before = manager.measure(prompt)

    prepared, removed = _prepare_tool_result_budget(prompt, compactor, manager)
    tool_result = prepared[-2]
    persisted = Path(tool_result["_persisted_path"])
    assert removed > 0 and len(tool_result["content"]) <= 500
    assert persisted.read_text(encoding="utf-8").split("\n---CONTENT---\n", 1)[1] == original[-2]["content"]
    assert str(persisted) in tool_result["content"]
    assert prepared[1] == original[1] and prepared[-1] == original[-1]
    assert prompt == original  # Original evidence is not rewritten.
    assert manager.messages is prepared
    measurement_after = manager.measure(prepared)
    assert measurement_after.request_hash != measurement_before.request_hash
    assert measurement_after.input_tokens < measurement_before.input_tokens
    body = manager.accounting.prepare(prepared)
    assert original[-2]["content"] not in json.dumps(body, ensure_ascii=False)


def test_request_budget_checks_a_new_tool_result_before_the_next_model_step(tmp_path):
    from nanocode.agent_loop import _prepare_tool_result_budget

    prompt = _real_budget_read(tmp_path)
    compactor = ContextCompactor(workspace=tmp_path)
    clean, removed = _prepare_tool_result_budget(prompt[:2], compactor)
    assert clean == prompt[:2] and removed == 0
    assert not (tmp_path / ".nanocode-tool-results").exists()

    prepared, removed = _prepare_tool_result_budget(clean + prompt[2:], compactor)
    assert removed > 0 and prepared[-2]["_persisted_path"]
    assert len(list((tmp_path / ".nanocode-tool-results").glob("*.txt"))) == 1


def test_saved_preview_is_idempotent_after_json_restore_with_a_new_manager(tmp_path):
    from nanocode.agent_loop import _prepare_tool_result_budget

    first = ContextCompactor(workspace=tmp_path)
    prepared, _ = _prepare_tool_result_budget(_real_budget_read(tmp_path), first)
    restored = json.loads(json.dumps(prepared, ensure_ascii=False))
    existing = {p.name: p.read_bytes() for p in (tmp_path / ".nanocode-tool-results").glob("*.txt")}
    second = ContextCompactor(workspace=tmp_path)
    second.tool_budget._persist_threshold = 100  # A valid preview can exceed a later, tighter limit.
    repeated, removed = _prepare_tool_result_budget(restored, second)
    assert repeated == restored and removed == 0
    assert {p.name: p.read_bytes() for p in (tmp_path / ".nanocode-tool-results").glob("*.txt")} == existing


def test_changed_tool_body_does_not_reuse_preview_exemption_or_overwrite_original(tmp_path):
    from pathlib import Path
    from nanocode.agent_loop import _prepare_tool_result_budget

    compactor = ContextCompactor(workspace=tmp_path)
    prepared, _ = _prepare_tool_result_budget(_real_budget_read(tmp_path), compactor)
    original_path = Path(prepared[-2]["_persisted_path"])
    original_bytes = original_path.read_bytes()
    changed = copy.deepcopy(prepared)
    changed[-2]["content"] += "\nadditional result" * 1000
    replaced, removed = _prepare_tool_result_budget(changed, compactor)
    new_path = Path(replaced[-2]["_persisted_path"])
    assert removed > 0 and new_path != original_path
    assert original_path.read_bytes() == original_bytes
    assert new_path.read_text(encoding="utf-8").split("\n---CONTENT---\n", 1)[1] == changed[-2]["content"]


def test_oversized_body_cannot_bypass_budget_with_matching_preview_metadata(tmp_path):
    import hashlib
    from nanocode.agent_loop import _prepare_tool_result_budget

    prompt = _real_budget_read(tmp_path)
    prompt[-2]["content"] = "[Tool result persisted to disk]\n" + prompt[-2]["content"]
    prompt[-2]["_persisted_path"] = "untrusted-preview.txt"
    prompt[-2]["_budget_preview_hash"] = hashlib.sha256(prompt[-2]["content"].encode("utf-8")).hexdigest()
    prepared, removed = _prepare_tool_result_budget(prompt, ContextCompactor(workspace=tmp_path))
    assert removed > 0 and prepared[-2]["_persisted_path"] != "untrusted-preview.txt"
    assert len(prepared[-2]["content"]) <= 500


def test_budget_persistence_failure_preserves_original_messages(tmp_path):
    from nanocode.agent_loop import _prepare_tool_result_budget

    prompt = _real_budget_read(tmp_path)
    original = copy.deepcopy(prompt)
    (tmp_path / ".nanocode-tool-results").write_text("This path is an ordinary file.", encoding="utf-8")
    manager = ContextManager(model="qwen3.8-flash", messages=prompt)
    with pytest.raises(OSError):
        _prepare_tool_result_budget(prompt, ContextCompactor(workspace=tmp_path), manager)
    assert prompt == original and manager.messages == original
