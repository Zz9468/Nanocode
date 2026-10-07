from pathlib import Path
from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Adapter.Out.Persistence.PyMySqlDriver import _package
def test_driver_is_owned_not_ambient():
 package=_package()
 assert Path(package.__file__).resolve().is_relative_to(Path('Package/AgentMemory/Vendor/MySqlDriver/Package/MySqlAccess/ThirdParty').resolve())
 assert hasattr(package,'connect')
