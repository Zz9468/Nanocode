"""Memory factory configuration without live database or model dependencies."""
import os
from contextlib import contextmanager
from nanocode.memory_backend import create_memory_manager


@contextmanager
def environment(**values):
    previous = {key:os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value



def test_factory_honors_custom_bom_environment_file(tmp_path):
    config = tmp_path/"memory.env"
    config.write_text('\ufeff NANOCODE_MEMORY_BACKEND = "json"\n', encoding="utf-8")
    with environment(NANOCODE_MEMORY_ENV=str(config), NANOCODE_MEMORY_BACKEND=None):
        manager = create_memory_manager(tmp_path)
    assert manager._service is None

