from importlib import import_module
import inspect
def test_binding_exposes_supplier_boot_contract():
    binding=import_module('Package.AgentMemory.Src.Import.0-Vendor-MySqlDriver-Package-MySqlAccess')
    assert list(inspect.signature(binding.createApp).parameters) == ['env']
    assert binding.createApp.__module__.endswith('MySqlAccess.Src.Boot.App')
