"""Local commands must execute through real input dispatch and preserve sessions."""

import threading

import pytest

import nanocode.history as history_module
import nanocode.permissions as permissions_module
import nanocode.session as session_module
from nanocode.permissions import PermissionManager
from nanocode.session import FileCheckpoint, SessionData, load_session, save_session
from nanocode.tooling import ToolRegistry
from nanocode.tui.event_flow import _handle_event
from nanocode.tui.input_handler import _handle_input
from nanocode.tui.input_parser import KeyEvent, TextEvent, parse_input_chunk
from nanocode.tui.navigation import _get_max_transcript_scroll_offset
from nanocode.tui.renderer import _get_transcript_snapshot, _render_screen
from nanocode.tui.selection import SelectionPoint, TranscriptSelection
from nanocode.tui.session_flow import refresh_tty_session_snapshot
from nanocode.tui.state import ScreenState, TtyAppArgs
from nanocode.tui.types import TranscriptEntry


@pytest.fixture
def local_runtime(tmp_path, monkeypatch):
    # Redirect storage paths only; history and sessions use real filesystem I/O.
    home = tmp_path / "home"
    monkeypatch.setattr(history_module, "NANO_CODE_DIR", home)
    monkeypatch.setattr(history_module, "NANO_CODE_HISTORY_PATH", home / "history.json")
    monkeypatch.setattr(history_module, "_history_cache", None)
    monkeypatch.setattr(session_module, "SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr(permissions_module, "NANO_CODE_PERMISSIONS_PATH", home / "permissions.json")
    messages = [{"role": "user", "content": "Remember the README task"}]
    session = SessionData("local-command-regression", 1.0, 1.0, str(tmp_path))
    session.checkpoints.append(FileCheckpoint("checkpoint-1", 1.0, "demo.txt", False, ""))
    args = TtyAppArgs(
        runtime={}, tools=ToolRegistry([]), model=None, messages=messages,
        cwd=str(tmp_path), permissions=PermissionManager(str(tmp_path)),
    )
    state = ScreenState(
        transcript=[TranscriptEntry(id=1, kind="assistant", body="PREVIOUS_OUTPUT\n" * 80)],
        next_entry_id=2, session=session, history=["README task"],
    )
    return args, state


def send(state, args, event):
    _handle_event(args, state, event, lambda: None, threading.Event(), {}, _handle_input)


def submit(state, args, command):
    send(state, args, TextEvent(command, ctrl=False, meta=False))
    send(state, args, KeyEvent("return", ctrl=False, meta=False))


def test_clear_command_is_handled_instead_of_suggesting_itself(local_runtime):
    args, state = local_runtime
    _handle_input(args, state, lambda: None, submitted_raw_input="/clear")
    body = "\n".join(entry.body for entry in _get_transcript_snapshot(state))
    assert "Unknown command" not in body
    assert "PREVIOUS_OUTPUT" not in body
    assert "cleared" in body.lower()


def test_clear_removes_old_view_and_selection_but_retains_durable_data(local_runtime):
    args, state = local_runtime
    refresh_tty_session_snapshot(args, state)
    save_session(state.session, force_full=True)
    state.transcript_scroll_offset = 40
    state.transcript_selection = TranscriptSelection(
        ("PREVIOUS_OUTPUT",), SelectionPoint(0, 0), SelectionPoint(0, 5), 20, 80,
    )
    expected_messages = list(args.messages)
    expected_checkpoints = list(state.session.checkpoints)
    _handle_input(args, state, lambda: None, submitted_raw_input="/clear")
    assert state.transcript_selection is None
    assert state.transcript_scroll_offset == 0
    assert _get_max_transcript_scroll_offset(args, state) == 0
    assert args.messages == expected_messages
    assert state.history == ["README task", "/clear"]
    assert state.session.checkpoints == expected_checkpoints
    refresh_tty_session_snapshot(args, state)
    save_session(state.session)
    restored = load_session(state.session.session_id)
    assert restored.messages == expected_messages
    assert restored.checkpoints == expected_checkpoints
    assert "PREVIOUS_OUTPUT" in restored.transcript_entries[0]["body"]
    assert restored.history == ["README task", "/clear"]


def test_clear_runs_on_enter_and_repeated_clear_does_not_reveal_old_entries(local_runtime):
    args, state = local_runtime
    for _ in range(2):
        submit(state, args, "/clear")
        assert state.input == ""
        visible = _get_transcript_snapshot(state)
        assert len(visible) == 1
        assert "cleared" in visible[0].body.lower()
    assert len(state.transcript) == 3


def test_history_reads_real_recent_history_without_an_agent_turn(local_runtime):
    args, state = local_runtime
    submit(state, args, "/history")
    assert state.input == ""
    assert state.transcript[-1].body == "1. README task\n2. /history"
    assert history_module.load_history_entries() == ["README task", "/history"]
    assert (history_module.NANO_CODE_DIR / "history.json").is_file()
    assert args.messages == [{"role": "user", "content": "Remember the README task"}]
    assert not state.is_busy


def test_tab_completion_then_enter_executes_the_selected_command(local_runtime):
    args, state = local_runtime
    send(state, args, TextEvent("/his", ctrl=False, meta=False))
    send(state, args, KeyEvent("tab", ctrl=False, meta=False))
    assert state.input.strip() == "/history"
    send(state, args, KeyEvent("return", ctrl=False, meta=False))
    assert state.input == ""
    assert "README task" in state.transcript[-1].body


def test_pasted_complete_command_executes_with_a_separate_enter(local_runtime):
    args, state = local_runtime
    for event in parse_input_chunk("\x1b[200~/clear\x1b[201~\r").events:
        send(state, args, event)
    assert state.input == ""
    assert "cleared" in state.transcript[-1].body.lower()


def test_unknown_command_is_reported_without_selecting_an_unrelated_command(local_runtime):
    args, state = local_runtime
    submit(state, args, "/zzzzzzz")
    assert state.input == ""
    assert "Unknown command" in state.transcript[-1].body


@pytest.mark.parametrize("command, expected", [
    ("/help", "Available Commands"),
    ("/session", "Session inspect: local-co"),
    ("/session local-command-regression", "Session inspect: local-co"),
])
def test_complete_commands_with_or_without_arguments_are_submitted(local_runtime, command, expected):
    args, state = local_runtime
    submit(state, args, command)
    assert state.input == ""
    assert expected in state.transcript[-1].body
    assert not state.is_busy


def test_screen_and_mouse_selection_use_only_the_visible_transcript(local_runtime, capsys):
    args, state = local_runtime
    _render_screen(args, state)
    assert "PREVIOUS_OUTPUT" in capsys.readouterr().out
    submit(state, args, "/clear")
    _render_screen(args, state)
    output = capsys.readouterr().out
    assert "PREVIOUS_OUTPUT" not in output
    assert "cleared" in output.lower()
    view = state.transcript_viewport
    from nanocode.tui.input_parser import MouseEvent

    send(state, args, MouseEvent("press", view.left + 1, view.rows[0].screen_row))
    assert state.transcript_selection is not None
    assert "PREVIOUS_OUTPUT" not in "\n".join(state.transcript_selection.lines)
