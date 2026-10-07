from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Dto.DatabaseSettings import DatabaseSettings
import dataclasses,pytest
def test_settings_are_immutable():
 s=DatabaseSettings()
 assert s.port==3306 and s.tls
 with pytest.raises(dataclasses.FrozenInstanceError): s.port=1234
