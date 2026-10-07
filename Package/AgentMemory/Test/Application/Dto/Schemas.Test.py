from Package.AgentMemory.Src.Application.Dto.Schemas import extraction_schema, insight_schema

def test_evidence_ids_are_constrained_strings():
    schema=extraction_schema(["e0","e1"])
    candidate=schema["properties"]["candidates"]["items"]
    assert candidate["properties"]["evidence_refs"]["items"] == {"type":"string","enum":["e0","e1"]}
    assert set(candidate["required"])==set(candidate["properties"])
    assert insight_schema(["source"])["properties"]["insights"]["items"]["properties"]["source_ids"]["items"]["enum"]==["source"]
