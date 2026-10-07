import getpass
import hashlib
import json
import os
import platform
import math
from pathlib import Path
from Package.AgentMemory.Src.Application.Dto.Contracts import MemorySettings

def read_env(path):
    result = {}
    for line in Path(path).read_text("utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip("\"'")
    return result

def load_settings(workspace, path=None, overrides=None):
    module = Path(__file__).parents[4]
    local = module / "Data" / "Local"
    path = Path(path or os.environ.get("NANOCODE_MEMORY_ENV", local / "runtime.env"))
    values = read_env(path) if path.exists() else {}
    values.update({k: v for k, v in os.environ.items() if k.startswith(("NANOCODE_", "OMNIHELM_"))})
    values.update(overrides or {})
    database = values.get("NANOCODE_MYSQL_DATABASE", "nanocode_memory")
    # Reuse an existing isolated test database without renaming or rewriting it.
    if database == "nanocode_memory_test":
        database = values.get("NANOCODE_MYSQL_TEST_DATABASE", database)
    defaults = json.loads((module / "Config" / "Defaults.json").read_text("utf-8"))
    budget = float(values.get("NANOCODE_MODEL_BUDGET_CNY", defaults["model_budget_cny"]))
    if not math.isfinite(budget) or budget < 0:
        raise ValueError("budget must be a finite nonnegative amount")
    interval = int(values.get("NANOCODE_MEMORY_CURATOR_INTERVAL", defaults["curator_interval"]))
    rrf_k = int(values.get("OMNIHELM_RAG_RRF_K", defaults["rrf_k"]))
    if interval < 1 or rrf_k < 1:
        raise ValueError("curator interval and RRF k must be positive")
    workspace = str(Path(workspace).resolve())
    return MemorySettings(workspace=workspace,
        database={"host": values.get("NANOCODE_MYSQL_HOST", "127.0.0.1"), "port": int(values.get("NANOCODE_MYSQL_PORT", 3306)),
            "user": values.get("NANOCODE_MYSQL_USER", "nanocode_memory"), "password": values.get("NANOCODE_MYSQL_PASSWORD", ""),
            "database": database, "tls": True},
        models={"generation_url": values.get("OMNIHELM_LLM_BASE_URL", ""), "generation_key": values.get("OMNIHELM_LLM_API_KEY", ""),
            "generation_model": values.get("OMNIHELM_LLM_MODEL", "qwen3.8-flash"),
            "embedding_url": values.get("OMNIHELM_EMBEDDING_BASE_URL", ""), "embedding_key": values.get("OMNIHELM_EMBEDDING_API_KEY", ""),
            "embedding_model": values.get("OMNIHELM_EMBEDDING_MODEL", "qwen3.7-text-embedding"),
            "dimensions": int(values.get("OMNIHELM_EMBEDDING_DIMENSION", 1024)),
            "rerank_url": values.get("OMNIHELM_RERANK_BASE_URL", ""), "rerank_model": values.get("OMNIHELM_RERANK_MODEL", "qwen3.7-text-rerank"),
            "rerank_key": values.get("OMNIHELM_RERANK_API_KEY", values.get("OMNIHELM_LLM_API_KEY", ""))},
        owner_id=values.get("NANOCODE_MEMORY_OWNER", getpass.getuser()), machine_id=platform.node(),
        project_id=values.get("NANOCODE_MEMORY_PROJECT", hashlib.sha256(workspace.casefold().encode()).hexdigest()),
        data_dir=str(values.get("NANOCODE_MEMORY_DATA_DIR", local)),
        ledger_path=str(values.get("NANOCODE_MODEL_LEDGER_PATH", local / "model_costs.json")),
        candidate_top_k=int(values.get("OMNIHELM_RAG_CANDIDATE_TOP_K", defaults["candidate_top_k"])),
        max_candidate_top_k=int(values.get("OMNIHELM_RAG_MAX_CANDIDATE_TOP_K", 50)),
        rerank_enabled=values.get("OMNIHELM_RAG_RERANK_ENABLED", "true").lower() == "true",
        fail_open=values.get("OMNIHELM_RAG_PIPELINE_FAIL_OPEN", "true").lower() == "true",
        rrf_k=rrf_k, curator_interval=interval, budget_cny=min(25, budget))
