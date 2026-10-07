from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Usecase.Database import Database
import inspect
def test_transaction_public_contract_is_context_manager():
 assert hasattr(Database.transaction,'__wrapped__')
 assert list(inspect.signature(Database.transaction).parameters)==['self']
