from Package.AgentMemory.Src.Application.Port.In.MemoryApi import MemoryApi
import inspect
def test_capture_contract():
    assert list(inspect.signature(MemoryApi.capture_turn).parameters) == ['self','task','messages','context']
    assert MemoryApi._is_protocol
