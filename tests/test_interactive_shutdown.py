"""Real unavailable-DB, filesystem and signal coverage for interactive shutdown."""

import signal
import socket
import threading
import time

import pytest

from nanocode.main import _shutdown_resources
from nanocode.memory import MemoryManager
from nanocode.memory_backend import shutdown_memory
from nanocode.tooling import ToolRegistry


@pytest.fixture
def unavailable_manager(tmp_path):
    # A bound, non-listening port can drop SYNs until the OS connect timeout.
    # Instead close real TCP connections before any MySQL handshake data;
    # the production driver/repository still handle the actual network error.
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        endpoint.settimeout(0.1)
        stopped = threading.Event()

        def disconnect_connections():
            while not stopped.is_set():
                try:
                    connection, _ = endpoint.accept()
                except socket.timeout:
                    continue
                connection.close()

        listener = threading.Thread(target=disconnect_connections, daemon=True)
        listener.start()
        try:
            manager = MemoryManager(tmp_path, backend="mysql", backend_env={
                "NANOCODE_MYSQL_HOST": "127.0.0.1",
                "NANOCODE_MYSQL_PORT": str(endpoint.getsockname()[1]),
                "NANOCODE_MYSQL_DATABASE": "nanocode_shutdown_test",
                "NANOCODE_MEMORY_OWNER": "shutdown-" + tmp_path.name,
                "NANOCODE_MEMORY_DATA_DIR": str(tmp_path / "memory"),
                "NANOCODE_MODEL_LEDGER_PATH": str(tmp_path / "costs.json"),
                "OMNIHELM_RAG_PIPELINE_FAIL_OPEN": "true",
            })
            try:
                yield manager
            finally:
                manager._service.close(1, drain=False)
        finally:
            stopped.set()
            listener.join(1)
            assert not listener.is_alive(), "TCP failure endpoint did not stop"


def capture_pending(manager):
    service = manager._service
    service.capture_turn("shutdown persistence check", [
        {"role": "user", "content": "Retain this pending capture across shutdown."},
    ])
    pending = service.files.replay()
    assert len(pending) == 1
    from pathlib import Path

    return {path: Path(path).read_bytes() for path, _ in pending}


def test_interactive_shutdown_wakes_retrying_worker_and_preserves_outbox(unavailable_manager, tmp_path, capsys):
    from pathlib import Path

    manager = unavailable_manager
    pending = capture_pending(manager)
    service = manager._service
    service.start_worker()
    deadline = time.monotonic() + 5
    worker_report = service.last_diagnostics.get("worker")
    while worker_report is None and time.monotonic() < deadline:
        time.sleep(0.01)
        worker_report = service.last_diagnostics.get("worker")
    assert worker_report is not None, f"Worker did not report its state: {service.last_diagnostics}"
    assert worker_report.get("degraded") is True, worker_report
    resource = (tmp_path / "tool-resource.txt").open("w", encoding="utf-8")
    tools = ToolRegistry([], disposer=resource.close)
    started = time.monotonic()
    _shutdown_resources(manager, tools, interactive=True)
    assert time.monotonic() - started < 2.5
    assert service._closed and service._worker_stop.is_set()
    assert service._worker is None
    assert resource.closed
    assert {path: Path(path).read_bytes() for path in pending} == pending
    assert len(service.files.replay()) == 1
    assert "up to 2s" in capsys.readouterr().out


def test_quick_shutdown_does_not_start_an_idle_unavailable_worker(unavailable_manager):
    service = unavailable_manager._service
    assert service._worker is None
    started = time.monotonic()
    report = shutdown_memory(unavailable_manager, timeout=1, drain=False)
    assert time.monotonic() - started < 0.5
    assert report == {"worker_stopped": True}
    assert service._worker is None and service._closed


def test_explicit_drain_still_reports_pending_outbox_on_real_db_failure(unavailable_manager):
    pending = capture_pending(unavailable_manager)
    report = shutdown_memory(unavailable_manager, timeout=0)
    assert report == {"unavailable": True, "outbox_pending": 1}
    assert len(unavailable_manager._service.files.replay()) == len(pending)


def test_real_sigint_during_disposal_is_handled_and_resource_is_closed(tmp_path):
    resource = (tmp_path / "signal-resource.txt").open("w", encoding="utf-8")

    def close_and_interrupt():
        resource.close()
        signal.raise_signal(signal.SIGINT)

    _shutdown_resources(None, ToolRegistry([], disposer=close_and_interrupt), interactive=True)
    assert resource.closed
