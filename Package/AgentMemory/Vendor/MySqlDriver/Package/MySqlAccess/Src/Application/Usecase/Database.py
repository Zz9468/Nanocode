from contextlib import contextmanager
from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Port.Out.Driver import Driver


class Database:
    def __init__(self, driver: Driver):
        self._driver = driver

    @contextmanager
    def transaction(self):
        session = self._driver.connect()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

