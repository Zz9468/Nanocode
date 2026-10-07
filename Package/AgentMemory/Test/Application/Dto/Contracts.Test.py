from Package.AgentMemory.Src.Application.Dto.Contracts import MemoryRecord, RetrievalResult

def test_record_defaults_are_not_shared():
    left = MemoryRecord("a", "ns", "project", "fact", "fact A")
    right = MemoryRecord("b", "ns", "project", "fact", "fact B")
    left.metadata["evidence"] = 1
    assert right.metadata == {} and left.revision == 1 and left.status == "active"
    assert RetrievalResult().records == []
