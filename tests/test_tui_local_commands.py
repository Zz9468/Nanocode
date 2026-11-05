"""Local commands must execute through real input dispatch and preserve sessions."""

import threading

import pytest

import nanocode.history as history_module
import nanocode.permissions as permissions_module
import nanocode.session as session_module
from nanocode.permissions import PermissionManager
from nanocode.session import FileCheckpoint, SessionData, load_session, save_session
from nanocode.tooling import ToolContext, ToolRegistry
from nanocode.tui.chrome import strip_ansi, string_display_width
from nanocode.tui.event_flow import _handle_event
from nanocode.tui.input_handler import _handle_input
from nanocode.tui.input_parser import KeyEvent, MouseEvent, TextEvent, WheelEvent, parse_input_chunk
from nanocode.tui.navigation import _get_max_transcript_scroll_offset
from nanocode.tui.renderer import _get_transcript_snapshot, _render_screen
from nanocode.tui.selection import SelectionPoint, TranscriptSelection
from nanocode.tui.session_flow import install_permission_prompt, refresh_tty_session_snapshot
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


@pytest.fixture
def terminal_dimensions(monkeypatch):
    import time
    import nanocode.tui.chrome as chrome_module

    # Configure cached terminal dimensions without replacing layout or I/O code.
    def resize(columns, rows):
        monkeypatch.setattr(chrome_module, "_ts_cache", (columns, rows))
        monkeypatch.setattr(chrome_module, "_ts_cache_time", time.monotonic())
        monkeypatch.setattr(chrome_module, "_TS_TTL", 60)

    return resize


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


@pytest.mark.parametrize("command", ["/cost", "/cost --detailed"])
def test_cost_command_reports_live_usage_without_changing_model_messages(local_runtime, command):
    from nanocode.cost_tracker import CostTracker

    args, state = local_runtime
    state.cost_tracker = CostTracker()
    state.cost_tracker.add_usage("lesson-model", 1000, 500, duration_ms=250)
    original_messages = list(args.messages)

    submit(state, args, command)

    body = state.transcript[-1].body
    assert "Cost & Usage Report" in body
    assert "Total API calls: 1" in body
    assert "Total tokens: 1,500" in body
    assert "Unknown command" not in body
    assert args.messages == original_messages
    if command.endswith("--detailed"):
        assert "lesson-model" in body
        assert "Input: 1,000" in body
        assert "Output: 500" in body


def test_cost_without_live_tracker_does_not_invent_zero_usage(local_runtime):
    args, state = local_runtime
    submit(state, args, "/cost")
    assert "not available" in state.transcript[-1].body.lower()
    assert "Total cost: $0.0000" not in state.transcript[-1].body


def test_cost_rejects_unknown_arguments(local_runtime):
    args, state = local_runtime
    submit(state, args, "/cost --unknown")
    assert state.transcript[-1].body == "Usage: /cost [--detailed]"


def test_cost_command_uses_same_tracker_as_live_provider_store(local_runtime):
    from nanocode.state import record_api_usage
    from nanocode.tui.session_flow import build_tty_runtime_state

    initial_args, initial_state = local_runtime
    args, state = build_tty_runtime_state(
        initial_args.runtime, initial_args.tools, initial_args.model,
        initial_args.messages, initial_args.cwd, initial_args.permissions,
        initial_state.session,
    )
    state.app_state.set_state(record_api_usage("lesson-model", 42, 8))
    submit(state, args, "/cost --detailed")

    assert state.cost_tracker is state.app_state.get_state().cost_tracker
    assert "Total API calls: 1" in state.transcript[-1].body
    assert "Total tokens: 50" in state.transcript[-1].body
    assert "Input: 42" in state.transcript[-1].body


@pytest.mark.parametrize("operation", ["edit", "command", "external_read"])
@pytest.mark.parametrize("allow", [True, False], ids=["allow", "deny"])
def test_tool_shortcut_keeps_input_responsive_during_real_approval(
    local_runtime, tmp_path, capsys, operation, allow,
):
    import sys
    from pathlib import Path

    from nanocode.tools.edit_file import edit_file_tool
    from nanocode.tools.read_file import read_file_tool
    from nanocode.tools.run_command import run_command_tool

    args, state = local_runtime
    target = Path(args.cwd, "lesson.txt")
    target.write_text("status=pending\n", encoding="utf-8")
    marker = Path(args.cwd, "command-ran.txt")
    probe = Path(args.cwd, "probe.py")
    probe.write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('command-ran.txt').write_text('approved', encoding='utf-8')\n"
        "print('APPROVED_COMMAND')\n",
        encoding="utf-8",
    )
    external = tmp_path.parent / (tmp_path.name + "-outside.txt")
    external.write_text("EXTERNAL_SAMPLE", encoding="utf-8")
    args.tools = ToolRegistry([edit_file_tool, read_file_tool, run_command_tool])
    command = {
        "edit": "/edit lesson.txt::status=pending::status=approved",
        "command": f"/cmd {sys.executable} -B probe.py",
        "external_read": f"/read {external}",
    }[operation]
    dispatched, pending, completed = (threading.Event() for _ in range(3))

    def rerender():
        if state.pending_approval is not None:
            pending.set()
        if not state.is_busy and any(e.kind == "tool" for e in state.transcript):
            completed.set()

    approval_event, approval_result, _ = install_permission_prompt(args, state, rerender)

    def send_event(event):
        _handle_event(args, state, event, rerender, approval_event, approval_result, _handle_input)

    def dispatch():
        send_event(TextEvent(command, ctrl=False, meta=False))
        send_event(KeyEvent("return", ctrl=False, meta=False))
        dispatched.set()

    input_thread = threading.Thread(target=dispatch, daemon=True)
    input_thread.start()
    try:
        assert dispatched.wait(2), "Shortcut blocked the UI input loop while waiting for approval"
        assert pending.wait(2), "Real permission request was not published"
        assert state.is_busy
        assert target.read_text(encoding="utf-8") == "status=pending\n"
        assert not marker.exists(), "Command ran before approval"
        assert not any("EXTERNAL_SAMPLE" in e.body for e in state.transcript)
        _render_screen(args, state)
        frame = strip_ansi(capsys.readouterr().out)
        assert "allow" in frame.lower() or "apply" in frame.lower()
        key = ("1" if allow else "5") if operation == "edit" else ("y" if allow else "n")
        send_event(TextEvent(key, ctrl=False, meta=False))
        assert completed.wait(5), "Tool did not finish after the permission key"
        result = next(e for e in reversed(state.transcript) if e.kind == "tool")
        assert result.status == ("success" if allow else "error")
        assert state.pending_approval is None and not state.is_busy
        if operation == "edit":
            assert target.read_text(encoding="utf-8") == f"status={'approved' if allow else 'pending'}\n"
            assert len(state.session.checkpoints) == 1 + int(allow)
        elif operation == "command":
            assert marker.exists() == allow
            if allow:
                assert marker.read_text(encoding="utf-8") == "approved"
                assert "APPROVED_COMMAND" in result.body
        else:
            assert ("EXTERNAL_SAMPLE" in result.body) == allow
        assert args.messages == [{"role": "user", "content": "Remember the README task"}]
        assert not args.permissions.turn_allowed_edits and not args.permissions.turn_allow_all_edits
    finally:
        # Release a broken implementation only after the assertion failed;
        # cleanup cannot turn a stalled input loop into a passing result.
        if state.pending_approval is not None:
            send_event(KeyEvent("escape", ctrl=False, meta=False))
        input_thread.join(timeout=3)
        worker = getattr(state, "tool_thread", None)
        if worker is not None:
            worker.join(timeout=3)


def test_permission_key_received_during_render_is_not_lost(local_runtime):
    from pathlib import Path

    from nanocode.tools.edit_file import edit_file_tool

    args, state = local_runtime
    target = Path(args.cwd, "lesson.txt")
    target.write_text("status=pending\n", encoding="utf-8")
    args.tools = ToolRegistry([edit_file_tool])
    completed = threading.Event()
    answered = threading.Event()

    def rerender():
        if state.pending_approval is not None and not answered.is_set():
            answered.set()
            _handle_event(
                args, state, TextEvent("1", ctrl=False, meta=False), lambda: None,
                approval_event, approval_result, _handle_input,
            )
        if not state.is_busy and any(e.kind == "tool" for e in state.transcript):
            completed.set()

    approval_event, approval_result, _ = install_permission_prompt(args, state, rerender)

    def dispatch():
        _handle_input(
            args, state, rerender,
            submitted_raw_input="/edit lesson.txt::status=pending::status=approved",
        )

    input_thread = threading.Thread(target=dispatch, daemon=True)
    input_thread.start()
    try:
        assert completed.wait(3), "Approval received while rendering was cleared before the wait"
        assert answered.is_set()
        assert target.read_text(encoding="utf-8") == "status=approved\n"
        assert state.pending_approval is None
    finally:
        approval_event.set()
        input_thread.join(timeout=3)
        worker = getattr(state, "tool_thread", None)
        if worker is not None:
            worker.join(timeout=3)


def test_shortcut_turn_edit_grant_expires_before_next_submission(local_runtime):
    from pathlib import Path

    from nanocode.tools.edit_file import edit_file_tool

    args, state = local_runtime
    target = Path(args.cwd, "lesson.txt")
    target.write_text("status=pending\n", encoding="utf-8")
    args.tools = ToolRegistry([edit_file_tool])
    pending = threading.Event()

    def rerender():
        if state.pending_approval is not None:
            pending.set()

    approval_event, approval_result, _ = install_permission_prompt(args, state, rerender)
    for before, after, key in [("pending", "approved", "2"), ("approved", "pending", "5")]:
        pending.clear()
        _handle_input(
            args, state, rerender,
            submitted_raw_input=f"/edit lesson.txt::status={before}::status={after}",
        )
        try:
            assert pending.wait(2), "Previous turn's grant suppressed a fresh approval"
            _handle_event(
                args, state, TextEvent(key, ctrl=False, meta=False), rerender,
                approval_event, approval_result, _handle_input,
            )
            state.tool_thread.join(timeout=3)
            assert not state.tool_thread.is_alive()
        finally:
            if state.pending_approval is not None and not approval_event.is_set():
                _handle_event(
                    args, state, KeyEvent("escape", ctrl=False, meta=False), rerender,
                    approval_event, approval_result, _handle_input,
                )
            state.tool_thread.join(timeout=3)
        assert not state.tool_thread.is_alive()
        assert not state.is_busy
        assert not args.permissions.turn_allowed_edits
        assert not args.permissions.turn_allow_all_edits
    assert target.read_text(encoding="utf-8") == "status=approved\n"
    assert state.transcript[-1].status == "error"
    assert len(state.session.checkpoints) == 2


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


def toggle_coordinates(state, frame, text="[展开]", character_offset=0):
    """Use actual frame cells, including panel padding and CJK display width."""
    lines = strip_ansi(frame).splitlines()
    for row in state.transcript_viewport.rows:
        line = lines[row.screen_row - 1]
        if text in line:
            index = line.index(text) + character_offset
            return string_display_width(line[:index]) + 1, row.screen_row
    raise AssertionError(f"No visible {text} control in frame")


def click_tool(state, args, x, y, native=False):
    # Exercise the terminal parser and real event dispatch, including release.
    stream = f"\x1b[<0;{x};{y}M\x1b[<0;{x};{y}m"
    if native:
        from nanocode.tui.windows_console import MouseRecord, mouse_record_text

        stream = "".join(mouse_record_text(MouseRecord(x=x - 1, y=y - 1, buttons=buttons)) for buttons in (1, 0))
    for event in parse_input_chunk(stream).events:
        send(state, args, event)


@pytest.mark.parametrize("native", [False, True], ids=["terminal-sgr", "windows-console"])
def test_read_file_output_expands_scrolls_and_collapses_through_real_dispatch(local_runtime, capsys, native):
    from pathlib import Path
    from nanocode.tools.read_file import read_file_tool
    from nanocode.tui.tool_lifecycle import _collapse_tool_entry, _push_transcript_entry

    args, state = local_runtime
    content = "\n".join(f"source line {index:03}: 中文正文" for index in range(90))
    Path(args.cwd, "readme.txt").write_text(content, encoding="utf-8")
    args.tools = ToolRegistry([read_file_tool])
    result = args.tools.execute("read_file", {"path": "readme.txt"}, ToolContext(args.cwd, args.permissions))
    assert result.ok and content in result.output
    state.transcript_view_start = len(state.transcript)
    entry_id = _push_transcript_entry(state, kind="tool", toolName="read_file", status="success", body=result.output)
    _collapse_tool_entry(state, entry_id, "FILE: readme.txt")
    entry = state.transcript[-1]
    draft = state.input, state.cursor_offset

    _render_screen(args, state)
    frame = capsys.readouterr().out
    assert "source line 000" not in frame
    x, y = toggle_coordinates(state, frame, character_offset=1)
    revision = state.transcript_revision
    click_tool(state, args, x + 1, y, native=native)  # Second cell of a Chinese character.
    assert not entry.collapsed and entry.collapsePhase is None
    assert state.transcript_revision == revision + 1
    assert state.transcript_selection is None
    _render_screen(args, state)
    frame = capsys.readouterr().out
    assert "[收起]" in frame and "source line 000" in frame
    assert toggle_coordinates(state, frame, "[收起]")[1] == y
    assert "PREVIOUS_OUTPUT" not in frame

    # Wheel reaches the middle, then PageDown reaches the complete result tail.
    old_offset = state.transcript_scroll_offset
    send(state, args, WheelEvent("down"))
    assert state.transcript_scroll_offset < old_offset
    for _ in range(100):
        send(state, args, KeyEvent("pagedown", ctrl=False, meta=False))
        if state.transcript_scroll_offset == 0:
            break
    _render_screen(args, state)
    frame = capsys.readouterr().out
    assert "source line 089" in frame
    assert "output truncated in transcript" not in frame
    send(state, args, KeyEvent("home", ctrl=True, meta=False))
    _render_screen(args, state)
    frame = capsys.readouterr().out
    click_tool(state, args, *toggle_coordinates(state, frame, "[收起]"), native=native)
    _render_screen(args, state)
    frame = capsys.readouterr().out
    assert entry.collapsed and "[展开]" in frame
    assert "source line 000" not in frame
    assert entry.body == result.output
    assert (state.input, state.cursor_offset) == draft


@pytest.mark.parametrize("phase", [None, 3])
def test_short_collapsed_tool_has_a_working_toggle(local_runtime, capsys, phase):
    from nanocode.tui.tool_lifecycle import _push_transcript_entry

    args, state = local_runtime
    state.transcript_view_start = len(state.transcript)
    _push_transcript_entry(
        state, kind="tool", toolName="read_file", status="success",
        body="FILE: short.txt\n正文", collapsed=True,
        collapsedSummary="FILE: short.txt", collapsePhase=phase,
    )
    _render_screen(args, state)
    frame = capsys.readouterr().out
    click_tool(state, args, *toggle_coordinates(state, frame, character_offset=2))
    _render_screen(args, state)
    frame = capsys.readouterr().out
    assert "正文" in frame and "[收起]" in frame
    assert state.transcript[-1].collapsePhase is None
    click_tool(state, args, *toggle_coordinates(state, frame, "[收起]"))
    assert state.transcript[-1].collapsed


def test_tool_toggle_hitbox_excludes_header_text_and_drag_gestures(local_runtime, capsys):
    from nanocode.tui.tool_lifecycle import _push_transcript_entry

    args, state = local_runtime
    state.transcript_view_start = len(state.transcript)
    _push_transcript_entry(
        state, kind="tool", toolName="read_file", status="success",
        body="FILE: demo.txt\n" + "body\n" * 30,
        collapsed=True, collapsedSummary="FILE: demo.txt",
    )
    _render_screen(args, state)
    frame = capsys.readouterr().out
    x, y = toggle_coordinates(state, frame)
    click_tool(state, args, x - 1, y)
    assert state.transcript[-1].collapsed and state.transcript_selection is None
    send(state, args, MouseEvent("press", x, y))
    send(state, args, MouseEvent("drag", x + 3, y))
    assert state.transcript_selection.moved
    send(state, args, MouseEvent("release", x, y))
    assert state.transcript[-1].collapsed
    send(state, args, KeyEvent("escape", ctrl=False, meta=False))
    send(state, args, MouseEvent("press", x, y, shift=True))
    send(state, args, MouseEvent("release", x, y, shift=True))
    assert state.transcript[-1].collapsed and state.transcript_selection is None


@pytest.mark.parametrize("header_remainder", [0, 2, 4])
def test_wrapped_tool_header_toggle_uses_its_actual_screen_cells(local_runtime, capsys, header_remainder):
    import time
    from nanocode.tui.tool_lifecycle import _push_transcript_entry
    from nanocode.tui.transcript import _transcript_panel_width

    args, state = local_runtime
    state.transcript_view_start = len(state.transcript)
    inner = _transcript_panel_width() - 4
    # Place the control on the next row or split it across two visual rows.
    name = "x" * (inner - string_display_width("▶ tool  ok  ") - header_remainder)
    _push_transcript_entry(
        state, kind="tool", toolName=name, status="success", body="FULL_BODY_TEXT",
        collapsed=True, collapsedSummary="summary",
    )
    # Start a separate screen after the frame throttle and Windows clock tick.
    time.sleep(0.04)
    _render_screen(args, state)
    frame = capsys.readouterr().out
    click_tool(state, args, *toggle_coordinates(state, frame, "开"))
    _render_screen(args, state)
    frame = capsys.readouterr().out
    assert not state.transcript[-1].collapsed and "FULL_BODY_TEXT" in frame
    click_tool(state, args, *toggle_coordinates(state, frame, "起"))
    assert state.transcript[-1].collapsed


def test_manual_tool_toggle_survives_pending_auto_collapse(local_runtime, capsys):
    from nanocode.tui.tool_lifecycle import _push_transcript_entry, _schedule_tool_auto_collapse

    args, state = local_runtime
    state.transcript_view_start = len(state.transcript)
    output = "FILE: demo.txt\n" + "source line\n" * 30
    entry_id = _push_transcript_entry(state, kind="tool", toolName="read_file", status="success", body=output)
    completed = threading.Event()
    _schedule_tool_auto_collapse(state, entry_id, output, completed.set)
    _render_screen(args, state)
    frame = capsys.readouterr().out
    # Initially expanded: collapse, then expand before the delayed default fires.
    send(state, args, KeyEvent("home", ctrl=True, meta=False))
    _render_screen(args, state)
    frame = capsys.readouterr().out
    click_tool(state, args, *toggle_coordinates(state, frame, "[收起]"))
    _render_screen(args, state)
    frame = capsys.readouterr().out
    click_tool(state, args, *toggle_coordinates(state, frame))
    assert completed.wait(2), "Delayed collapse did not finish"
    assert not state.transcript[-1].collapsed


@pytest.mark.parametrize("columns,rows", [(180, 52), (100, 40), (80, 30), (80, 24)])
def test_full_frame_with_session_summaries_keeps_mouse_coordinates_on_visible_text(
    local_runtime, capsys, terminal_dimensions, columns, rows,
):
    from nanocode.tui.selection import selected_text
    from nanocode.tui.tool_lifecycle import _push_transcript_entry
    from nanocode.tui.transcript import _strip_ansi

    terminal_dimensions(columns, rows)
    args, state = local_runtime
    state.session.checkpoints.clear()
    state.session.metadata.readiness_summary = "readiness: warning (custom) [Primary provider is ready, but no configured or default fallback models are available.]"
    state.session.metadata.instruction_summary = "6 layer(s): global-claude, global-user, global-managed..."
    state.session.metadata.hook_summary = "hooks: none registered"
    state.session.metadata.delegation_summary = "delegation: 0 running, 5/5 slots free"
    state.transcript_view_start = len(state.transcript)
    _push_transcript_entry(
        state, kind="progress", body="Runtime phase: execute", category="runtime",
        runtimeKind="phase", runtimeStep=2, runtimePhase="execute",
    )
    _push_transcript_entry(
        state, kind="tool", toolName="read_file", status="success",
        body="FILE: README.md\n正文内容\n" + "detail\n" * 80,
        collapsed=True, collapsedSummary="FILE: README.md",
    )
    _push_transcript_entry(state, kind="assistant", body="TEXT_TO_SELECT 中文🙂 tail\n" * 60)
    send(state, args, KeyEvent("home", ctrl=True, meta=False))
    _render_screen(args, state)
    frame = capsys.readouterr().out
    rendered_rows = _strip_ansi(frame).splitlines()
    assert len(rendered_rows) <= rows, f"Frame overflows by {len(rendered_rows) - rows} terminal rows"
    assert all(string_display_width(line) <= columns for line in rendered_rows)
    # Locate screen cells independently of transcript_viewport's hit-test map.
    for _ in range(10):
        hit = next(((y, line) for y, line in enumerate(rendered_rows, 1) if "[展开]" in line), None)
        if hit is not None:
            y, line = hit
            x = string_display_width(line[:line.index("[展开]")]) + 1
            break
        send(state, args, WheelEvent("down"))
        _render_screen(args, state)
        rendered_rows = _strip_ansi(capsys.readouterr().out).splitlines()
        assert len(rendered_rows) <= rows
    else:
        raise AssertionError("Tool toggle is not visible")
    click_tool(state, args, x, y, native=True)
    assert not state.transcript[-2].collapsed

    send(state, args, KeyEvent("end", ctrl=True, meta=False))
    _render_screen(args, state)
    rendered_rows = _strip_ansi(capsys.readouterr().out).splitlines()
    assert len(rendered_rows) <= rows
    y, line = next((y, line) for y, line in enumerate(rendered_rows, 1) if "TEXT_TO_SELECT" in line)
    start = line.index("TEXT_TO_SELECT")
    x = string_display_width(line[:start]) + 1
    send(state, args, MouseEvent("press", x, y))
    send(state, args, MouseEvent("drag", x + len("TEXT_TO_SELECT"), y))
    assert selected_text(state.transcript_selection) == "TEXT_TO_SELECT"


def test_selection_stays_at_visible_chinese_text_with_multiline_paste_and_resizing(
    local_runtime, capsys, terminal_dimensions,
):
    from nanocode.tui.selection import selected_text
    from nanocode.tui.tool_lifecycle import _push_transcript_entry
    from nanocode.tui.transcript import _strip_ansi

    args, state = local_runtime
    state.transcript_view_start = len(state.transcript)
    _push_transcript_entry(state, kind="assistant", body="ROW: 中文🙂 target\n" * 80)
    pasted = "\n".join(f"pasted line {index:03} 中文正文" for index in range(40))
    for event in parse_input_chunk(f"\x1b[200~{pasted}\x1b[201~").events:
        send(state, args, event)
    for columns, rows in [(180, 52), (100, 40), (80, 24), (140, 45)]:
        terminal_dimensions(columns, rows)
        _render_screen(args, state)
        frame = _strip_ansi(capsys.readouterr().out)
        rendered_rows = frame.splitlines()
        assert len(rendered_rows) <= rows
        assert all(string_display_width(line) <= columns for line in rendered_rows)
        assert "pasted line 039" in frame
        assert state.input == pasted and state.cursor_offset == len(pasted)
        assert state.transcript_selection is None
        y, line = next((y, line) for y, line in enumerate(rendered_rows, 1) if "ROW:" in line)
        start = line.index("中文🙂")
        x = string_display_width(line[:start]) + 1
        send(state, args, MouseEvent("press", x, y))
        send(state, args, MouseEvent("drag", x + string_display_width("中文🙂"), y))
        assert selected_text(state.transcript_selection) == "中文🙂"
        _render_screen(args, state)
        frame = _strip_ansi(capsys.readouterr().out)
        assert len(frame.splitlines()) <= rows
