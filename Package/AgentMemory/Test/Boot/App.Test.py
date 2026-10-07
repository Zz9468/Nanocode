from Package.AgentMemory.Src.Boot.App import createApp
from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings
def test_runtime_surface_uses_independent_schema(tmp_path):
    app=createApp({'workspace':str(tmp_path),'overrides':{'NANOCODE_MYSQL_DATABASE':'nanocode_memory_test','NANOCODE_MEMORY_OWNER':tmp_path.name}})
    production = load_settings(tmp_path).database['database']
    assert app.settings.database['database'] != production
    with app.repository.db.transaction() as tx:
        assert tx.query('SELECT DATABASE() AS name')[0]['name'] == app.settings.database['database']
    assert set(app.namespaces) == {'project','local','user'}
    assert app.ledger.summary()['accounted_cny'] <= 25
