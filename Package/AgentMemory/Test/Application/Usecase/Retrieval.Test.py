from Package.AgentMemory.Src.Boot.App import createApp
def test_bm25_source_change_and_no_search_usage_side_effect(tmp_path):
    (tmp_path/'config.txt').write_text('v1','utf-8')
    app=createApp({'workspace':str(tmp_path),'overrides':{'NANOCODE_MYSQL_DATABASE':'nanocode_memory_test','NANOCODE_MEMORY_OWNER':tmp_path.name}})
    hashes=app.files.fingerprints(str(tmp_path), ['config.txt'])
    record=app.remember('配置文件规定 MySQL 是当前项目的记忆存储。',metadata={'file_hashes':hashes})
    result=app.retrieve('MySQL',mode='bm25')
    assert [r.id for r in result.records] == [record.id]
    assert app.repository.get(record.id,list(app.namespaces.values())).usage_count == 0
    (tmp_path/'config.txt').write_text('v2','utf-8')
    assert app.retrieve('MySQL',mode='bm25').records == []
