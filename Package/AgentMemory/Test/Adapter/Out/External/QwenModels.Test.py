from Package.AgentMemory.Src.Boot.App import createApp
def test_actual_generation_embedding_and_rerank(tmp_path):
    app=createApp({'workspace':str(tmp_path),'overrides':{'NANOCODE_MYSQL_DATABASE':'nanocode_memory_test','NANOCODE_MEMORY_OWNER':tmp_path.name}})
    assert app.models.generate('返回JSON对象包含ok:true。',{'acceptance':'live API'})['ok'] is True
    assert len(app.models.embed(['MySQL保存记忆'])[0]) == 1024
    ranked=app.models.rerank('记忆存储', ['记忆保存在MySQL数据库','界面使用深色主题'],2)
    assert ranked[0][0] == 0 and ranked[0][1] > ranked[1][1]
    assert app.ledger.summary()['accounted_cny'] < 25
