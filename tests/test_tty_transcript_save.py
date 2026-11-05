import threading

import pytest

import nanocode.history as history_module
import nanocode.permissions as permissions_module
from nanocode.permissions import PermissionManager
from nanocode.tooling import ToolRegistry
from nanocode.tui.event_flow import _handle_event
from nanocode.tui.input_handler import _handle_input
from nanocode.tui.input_parser import TextEvent
from nanocode.tui.session_flow import install_permission_prompt
from nanocode.tui.state import ScreenState, TtyAppArgs
from nanocode.tui.types import TranscriptEntry


@pytest.fixture
def transcript_input(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(history_module, "NANO_CODE_DIR", runtime_dir)
    monkeypatch.setattr(history_module, "NANO_CODE_HISTORY_PATH", runtime_dir / "history.json")
    monkeypatch.setattr(history_module, "_history_cache", None)
    monkeypatch.setattr(permissions_module, "NANO_CODE_PERMISSIONS_PATH", runtime_dir / "permissions.json")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    args = TtyAppArgs(
        runtime=None,
        tools=ToolRegistry([]),
        model=None,
        messages=[{"role": "system", "content": "local commands only"}],
        cwd=str(workspace),
        permissions=PermissionManager(str(workspace)),
    )
    state = ScreenState(
        transcript=[
            TranscriptEntry(id=1, kind="user", body="P08 第一阶段，恢复后继续"),
            TranscriptEntry(id=2, kind="assistant", body="第二阶段完成"),
        ],
        transcript_view_start=1,
        next_entry_id=3,
    )
    return args, state, workspace


def test_transcript_save_dispatch_exports_hidden_history_and_spaced_path(transcript_input):
    args, state, workspace = transcript_input
    command = "/transcript-save exports/session notes.txt"
    assert _handle_input(args, state, threading.Event().set, command) is False
    assert state.tool_thread is not None
    state.tool_thread.join(timeout=5)

    target = workspace / "exports" / "session notes.txt"
    assert not state.tool_thread.is_alive()
    assert target.read_text(encoding="utf-8") == (
        "you\n  P08 第一阶段，恢复后继续\n\n---\n\nassistant\n  第二阶段完成"
    )
    assert state.transcript[-1].body == f"Saved transcript to {target}"
    assert not state.is_busy
    assert state.agent_thread is None
    assert args.messages == [{"role": "system", "content": "local commands only"}]


@pytest.mark.parametrize("command", ["/transcript-save", "/transcript-save   "])
def test_transcript_save_requires_a_path(transcript_input, command):
    args, state, workspace = transcript_input
    assert _handle_input(args, state, threading.Event().set, command) is False
    assert state.transcript[-1].body == "Usage: /transcript-save <path>"
    assert state.tool_thread is None
    assert not state.is_busy
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("decision_key, should_write", [("y", True), ("n", False)])
def test_transcript_save_outside_cwd_uses_live_approval_events(
    transcript_input, tmp_path, decision_key, should_write,
):
    args, state, workspace = transcript_input
    target = tmp_path / "outside" / "session.txt"
    prompt_visible = threading.Event()

    def rerender():
        if state.pending_approval is not None:
            prompt_visible.set()

    approval_event, approval_result, _ = install_permission_prompt(args, state, rerender)
    assert _handle_input(args, state, rerender, f"/transcript-save {target}") is False
    assert state.tool_thread is not None
    try:
        assert prompt_visible.wait(timeout=5)
        assert state.pending_approval.request["kind"] == "path"
        assert state.is_busy
        assert not target.exists()
        _handle_event(
            args, state, TextEvent(text=decision_key, ctrl=False, meta=False),
            rerender, approval_event, approval_result, _handle_input,
        )
        state.tool_thread.join(timeout=5)
        assert not state.tool_thread.is_alive()
        assert target.exists() is should_write
        if should_write:
            assert "P08 第一阶段" in target.read_text(encoding="utf-8")
            assert state.transcript[-1].body == f"Saved transcript to {target}"
        else:
            assert "Could not save transcript:" in state.transcript[-1].body
            assert "Access denied" in state.transcript[-1].body
            assert not target.parent.exists()
        assert state.pending_approval is None
        assert not state.is_busy
        assert state.agent_thread is None
    finally:
        approval_result["decision"] = "deny_once"
        approval_event.set()
        state.tool_thread.join(timeout=5)


def test_transcript_save_reports_io_error_and_releases_busy_state(transcript_input):
    args, state, workspace = transcript_input
    target = workspace / "existing-directory"
    target.mkdir()
    assert _handle_input(args, state, threading.Event().set, f"/transcript-save {target}") is False
    assert state.tool_thread is not None
    state.tool_thread.join(timeout=5)
    assert not state.tool_thread.is_alive()
    assert "Could not save transcript:" in state.transcript[-1].body
    assert "Saved transcript to" not in state.transcript[-1].body
    assert target.is_dir()
    assert not state.is_busy
