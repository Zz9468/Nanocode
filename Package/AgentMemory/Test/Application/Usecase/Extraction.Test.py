from Package.AgentMemory.Src.Application.Usecase.Extraction import extract
from Package.AgentMemory.Src.Boot.App import createApp
def test_rule_gate_avoids_generation_for_missing_evidence(tmp_path):
    app=createApp({'workspace':str(tmp_path),'overrides':{'NANOCODE_MYSQL_DATABASE':'nanocode_memory_test','NANOCODE_MEMORY_OWNER':tmp_path.name}})
    before=app.ledger.summary()['calls']
    assert extract(app.models, {'task':'任务完成','events':[{'id':'a','role':'assistant','content':'我已经成功了'}]}, []) == ([],[])
    assert app.ledger.summary()['calls'] == before
