from Package.AgentMemory.Src.Domain.Policy import content_hash, redact, validate_candidate

def test_evidence_scope_and_success_gates():
    events = {"u": {"role": "user"}, "f": {"role": "tool_result", "isError": True}, "s": {"role": "tool_result", "isError": False}}
    c = {"content": "修复后必须实际执行测试并确认通过。", "kind": "lesson", "scope": "project", "evidence_refs": ["f"]}
    assert validate_candidate(c, events)
    c["evidence_refs"] = ["s"]
    assert validate_candidate(c, events) is None
    c["scope"] = "user"
    assert validate_candidate(c, events)
    c["evidence_refs"].append("u")
    assert validate_candidate(c, events) is None
    c["evidence_refs"] = ["invented"]
    assert validate_candidate(c, events)

def test_hash_and_secret_redaction():
    assert content_hash("AbC  xyz") == content_hash("AbC xyz")
    assert content_hash("AbC") != content_hash("abc")
    assert redact({"password": "private", "text": "api_key=private"}) == {"password": "[REDACTED]", "text": "api_key=[REDACTED]"}
