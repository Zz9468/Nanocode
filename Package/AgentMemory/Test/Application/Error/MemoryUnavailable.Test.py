import socket
import pytest
from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings
from Package.AgentMemory.Src.Adapter.Out.Module.MySqlMemoryRepository import MySqlMemoryRepository
from Package.AgentMemory.Src.Application.Error.MemoryUnavailable import MemoryUnavailable

def test_unreachable_mysql_uses_the_public_error_contract(tmp_path):
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        settings = load_settings(tmp_path, overrides={"NANOCODE_MYSQL_PORT": str(endpoint.getsockname()[1])})
        with pytest.raises(MemoryUnavailable, match="mysql_unavailable"):
            MySqlMemoryRepository(settings.database)
