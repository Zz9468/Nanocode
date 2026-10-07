from Package.AgentMemory.Src.Application.Dto.MemoryRecord import MemoryRecord


def test_mutable_record_defaults_are_owned_by_each_record():
    left = MemoryRecord("a", "ns", "project", "fact", "fact A")
    right = MemoryRecord("b", "ns", "project", "fact", "fact B")
    left.tags.append("left")
    left.domains.append("backend")
    left.metadata["evidence"] = 1
    left.evidence_refs.append("turn-a")
    assert right.tags == [] and right.domains == []
    assert right.metadata == {} and right.evidence_refs == []
    assert right.revision == 1 and right.status == "active"
