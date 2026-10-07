from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Dto.DatabaseSettings import DatabaseSettings
from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Usecase.Database import Database
from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Adapter.Out.Persistence.PyMySqlDriver import PyMySqlDriver


def createApp(env: dict) -> Database:
    return Database(PyMySqlDriver(DatabaseSettings(**env)))

