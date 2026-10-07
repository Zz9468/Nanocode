"""Wire contracts for constrained generation, independent of providers."""
def extraction_schema(event_ids):
    event = {"type":"string", "enum":list(event_ids)}
    quote = {"type":"object", "additionalProperties":False, "properties":{"event_id":event,"quote":{"type":"string"}}, "required":["event_id","quote"]}
    properties = {"kind":{"type":"string","enum":["fact","preference","decision","procedure","lesson"]},
        "scope":{"type":"string","enum":["project","local","user"]}, "content":{"type":"string"},
        "evidence_refs":{"type":"array","items":event}, "evidence_quotes":{"type":"array","items":quote},
        "tags":{"type":"array","items":{"type":"string"}}, "domains":{"type":"array","items":{"type":"string"}},
        "operation":{"type":"string","enum":["add","update"]}, "memory_id":{"type":"string"}, "expected_revision":{"type":"integer"}}
    candidate={"type":"object","additionalProperties":False,"properties":properties,"required":list(properties)}
    return {"type":"object","additionalProperties":False,"properties":{"candidates":{"type":"array","items":candidate}},"required":["candidates"]}

def insight_schema(source_ids):
    item={"type":"object","additionalProperties":False,"properties":{"content":{"type":"string"},
        "source_ids":{"type":"array","items":{"type":"string","enum":list(source_ids)}}},"required":["content","source_ids"]}
    return {"type":"object","additionalProperties":False,"properties":{"insights":{"type":"array","items":item}},"required":["insights"]}
