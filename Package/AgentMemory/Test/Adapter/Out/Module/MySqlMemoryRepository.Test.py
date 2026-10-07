from Package.AgentMemory.Src.Adapter.Out.Module.MySqlMemoryRepository import MySqlMemoryRepository
from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings
import uuid
def test_namespace_identity_is_deterministic_and_scope_sensitive():
    repo=MySqlMemoryRepository(load_settings('.',overrides={'NANOCODE_MYSQL_DATABASE':'nanocode_memory_test'}).database)
    identity=uuid.uuid4().hex
    assert repo.namespace('project',identity) == repo.namespace('project',identity)
    assert repo.namespace('project',identity) != repo.namespace('user',identity)
