from Package.AgentMemory.Src.Application.Port.Out.Capabilities import ModelGateway, MemoryRepository, SourceReader
def test_required_outbound_contracts():
    assert {'generate','embed','rerank'} <= set(ModelGateway.__dict__)
    assert {'namespace','commit','enqueue','list_records'} <= set(MemoryRepository.__dict__)
    assert {'spool','replay','acknowledge','validate','export'} <= set(SourceReader.__dict__)
