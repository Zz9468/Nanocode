from Package.AgentMemory.Src.Adapter.Out.Module.DatabaseBinding import database
from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings
def test_supplier_surface_connects_to_mysql():
    db=database(load_settings('.', overrides={'NANOCODE_MYSQL_DATABASE':'nanocode_memory_test'}).database)
    with db.transaction() as tx:
        assert tx.query('SELECT 1 AS alive')[0]['alive'] == 1
