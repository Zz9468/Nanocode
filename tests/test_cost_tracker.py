from __future__ import annotations

import pytest

from nanocode.cost_tracker import calculate_cost


def test_calculate_cost_handles_float_pricing_for_known_model() -> None:
    cost = calculate_cost(
        "claude-sonnet-4-20250514",
        input_tokens=1_000,
        output_tokens=500,
        cache_read_tokens=250,
        cache_creation_tokens=100,
    )

    assert isinstance(cost, float)
    assert cost == pytest.approx(0.01095)


def test_provider_usage_updates_live_report_and_legacy_totals_once():
    from nanocode.state import create_app_store, record_api_usage

    store = create_app_store()
    store.set_state(record_api_usage("claude-sonnet-4-20250514", 1000, 500, duration_ms=250))
    state = store.get_state()
    usage = state.cost_tracker.get_model_usage("claude-sonnet-4-20250514")
    assert state.api_calls == state.cost_tracker.get_total_calls() == 1
    assert state.total_cost_usd == pytest.approx(calculate_cost("claude-sonnet-4-20250514", 1000, 500))
    assert state.total_cost_usd == state.cost_tracker.total_cost_usd
    assert usage.input_tokens == 1000 and usage.output_tokens == 500
    assert usage.total_duration_ms == 250


def test_free_response_is_counted_and_missing_usage_is_disclosed():
    from nanocode.state import create_app_store, record_api_usage

    store = create_app_store()
    store.set_state(record_api_usage("lesson-model", 0, 0))
    store.set_state(record_api_usage("lesson-model", 0, 0, usage_source="unavailable"))
    tracker = store.get_state().cost_tracker
    assert tracker.get_total_calls() == store.get_state().api_calls == 2
    report = tracker.format_cost_report(detailed=True)
    assert "Without token usage: 1" in report
    assert "unpriced" in report.lower()


def test_cost_counters_are_isolated_between_process_stores_and_record_errors():
    from nanocode.state import create_app_store, record_api_usage, record_api_error

    first, second = create_app_store(), create_app_store()
    first.set_state(record_api_usage("lesson-model", 10, 5, usage_source="estimated"))
    first.set_state(record_api_error("lesson-model"))
    assert first.get_state().cost_tracker.get_total_calls() == 2
    assert first.get_state().cost_tracker.get_total_errors() == 1
    assert first.get_state().cost_tracker.get_model_usage("lesson-model").estimated_calls == 1
    assert second.get_state().cost_tracker.get_total_calls() == 0
