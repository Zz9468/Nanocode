from importlib import import_module


def database(env: dict):
    binding = import_module("Package.AgentMemory.Src.Import.0-Vendor-MySqlDriver-Package-MySqlAccess")
    return binding.createApp(env)

