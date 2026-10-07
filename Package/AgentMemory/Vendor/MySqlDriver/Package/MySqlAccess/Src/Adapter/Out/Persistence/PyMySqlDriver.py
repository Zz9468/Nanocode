"""Only this supplier adapter can load the locally owned PyMySQL distribution."""
from __future__ import annotations
import importlib.util
import ssl
import sys
import threading
from pathlib import Path
from Package.AgentMemory.Vendor.MySqlDriver.Package.MySqlAccess.Src.Application.Dto.DatabaseSettings import DatabaseSettings

_LOAD_LOCK = threading.Lock()


def _package():
    root = Path(__file__).parents[4] / "ThirdParty"
    with _LOAD_LOCK:
        if "pymysql" in sys.modules:
            loaded = sys.modules["pymysql"]
            if not Path(loaded.__file__).is_relative_to(root):
                raise ImportError("PyMySQL must resolve to the owned supplier distribution")
            return loaded
        source = root / "pymysql" / "__init__.py"
        spec = importlib.util.spec_from_file_location("pymysql", source, submodule_search_locations=[str(source.parent)])
        if spec is None or spec.loader is None:
            raise ImportError("Owned PyMySQL distribution is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules["pymysql"] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop("pymysql", None)
            raise
        return module


class SqlSession:
    """Return ordinary rows and counts, never expose SDK connection objects."""
    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement: str, parameters=()) -> int:
        with self._connection.cursor() as cursor:
            return cursor.execute(statement, parameters)

    def query(self, statement: str, parameters=()) -> list[dict]:
        with self._connection.cursor() as cursor:
            cursor.execute(statement, parameters)
            return list(cursor.fetchall())

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


class PyMySqlDriver:
    def __init__(self, settings: DatabaseSettings):
        self.settings = settings

    def connect(self) -> SqlSession:
        package = _package()
        options = dict(host=self.settings.host, port=self.settings.port,
                       user=self.settings.user, password=self.settings.password,
                       database=self.settings.database, charset="utf8mb4",
                       autocommit=False, connect_timeout=self.settings.connect_timeout,
                       read_timeout=30, write_timeout=30,
                       cursorclass=package.cursors.DictCursor)
        if self.settings.tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            options["ssl"] = context
        return SqlSession(package.connect(**options))

