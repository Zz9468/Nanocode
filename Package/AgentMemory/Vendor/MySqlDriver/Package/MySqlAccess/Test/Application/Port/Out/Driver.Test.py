from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Port.Out.Driver import Driver
import inspect
def test_driver_contract_owns_connect():
 assert Driver._is_protocol and list(inspect.signature(Driver.connect).parameters)==['self']
