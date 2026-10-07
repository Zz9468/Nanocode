from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings

def test_omnihelm_mapping_and_cap(tmp_path):
    path = tmp_path/"config.env"
    path.write_text("OMNIHELM_LLM_MODEL=model-x\nOMNIHELM_EMBEDDING_DIMENSION=1024\nNANOCODE_MODEL_BUDGET_CNY=30\n", "utf-8")
    settings = load_settings(tmp_path, path)
    assert settings.models["generation_model"] == "model-x"
    assert settings.models["dimensions"] == 1024
    assert settings.budget_cny == 25

def test_strategy_parameters_and_invalid_budget_are_enforced(tmp_path):
    import pytest
    settings = load_settings(tmp_path, overrides={"OMNIHELM_RAG_RRF_K":"42", "NANOCODE_MEMORY_CURATOR_INTERVAL":"3"})
    assert settings.rrf_k == 42 and settings.curator_interval == 3
    for value in ("nan", "inf", "-1"):
        with pytest.raises(ValueError):
            load_settings(tmp_path, overrides={"NANOCODE_MODEL_BUDGET_CNY":value})

def test_test_database_setting_preserves_existing_physical_database(tmp_path):
    path = tmp_path / "runtime.env"
    path.write_text("NANOCODE_MYSQL_DATABASE=existing_memory\nNANOCODE_MYSQL_TEST_DATABASE=existing_memory_test\n", "utf-8")
    assert load_settings(tmp_path, path).database["database"] == "existing_memory"
    settings = load_settings(tmp_path, path, overrides={"NANOCODE_MYSQL_DATABASE": "nanocode_memory_test"})
    assert settings.database["database"] == "existing_memory_test"
