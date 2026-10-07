from Package.AgentMemory.Src.Application.Usecase.MemoryService import MemoryService
from Package.AgentMemory.Src.Application.Usecase.Retrieval import Retrieval
from Package.AgentMemory.Src.Adapter.Out.Module.MySqlMemoryRepository import MySqlMemoryRepository
from Package.AgentMemory.Src.Adapter.Out.External.QwenModels import QwenModels
from Package.AgentMemory.Src.Adapter.Out.Persistence.Files import Files
from Package.AgentMemory.Src.Adapter.Out.Persistence.CostLedger import CostLedger
from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings

def createApp(env):
    settings = env.get("settings") or load_settings(env["workspace"], env.get("env_file"), env.get("overrides"))
    repository = MySqlMemoryRepository(settings.database, fail_open=settings.fail_open)
    ledger = CostLedger(env.get("ledger_path") or settings.ledger_path or settings.data_dir + "/model_costs.json", settings.budget_cny)
    models = QwenModels(settings.models, ledger)
    files = Files(settings.data_dir)
    retrieval = Retrieval(repository, models, files, settings)
    return MemoryService(repository, models, files, retrieval, settings, ledger)
