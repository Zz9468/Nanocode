"""Regression cases for terminal paste boundaries and scrolling input."""

import pytest

from nanocode.tui.input_parser import KeyEvent, TextEvent, WheelEvent, parse_input_chunk


@pytest.mark.parametrize("text", ["", "你好，Nanocode", "first\nsecond", "你好\r\n世界", "first\rsecond"])
def test_bracketed_paste_is_text_and_never_submits(text):
    result = parse_input_chunk("\x1b[200~" + text + "\x1b[201~")
    expected = text.replace("\r\n", "\n").replace("\r", "\n")
    assert result.rest == ""
    assert result.events == [TextEvent(text=expected, ctrl=False, meta=False)]


def test_bracketed_paste_survives_every_possible_two_chunk_boundary():
    stream = "\x1b[200~读取 README\r\n中文与 emoji 🚀\x1b[201~\r"
    for boundary in range(1, len(stream)):
        first = parse_input_chunk(stream[:boundary])
        second_chunk = stream[boundary:]
        second = parse_input_chunk(first.rest + second_chunk, incoming_chunk=second_chunk)
        assert second.rest == "", boundary
        assert first.events + second.events == [
            TextEvent(text="读取 README\n中文与 emoji 🚀", ctrl=False, meta=False),
            KeyEvent(name="return", ctrl=False, meta=False),
        ], boundary


def test_pasted_control_keys_cannot_exit_or_execute_commands():
    result = parse_input_chunk("\x1b[200~hello\x03\x16\x1bworld\n/exit\x1b[201~")
    assert result.events == [TextEvent(text="helloworld\n/exit", ctrl=False, meta=False)]
    assert result.rest == ""


def test_multiple_pastes_and_typed_enter_remain_separate_events():
    result = parse_input_chunk("\x1b[200~one\x1b[201~\x1b[200~two\x1b[201~\r")
    assert result.events == [
        TextEvent(text="one", ctrl=False, meta=False),
        TextEvent(text="two", ctrl=False, meta=False),
        KeyEvent(name="return", ctrl=False, meta=False),
    ]


def test_mouse_scroll_sequences_do_not_become_prompt_text():
    result = parse_input_chunk("\x1b[<64;10;8M\x1b[<65;10;8M")
    assert result.events == [WheelEvent(direction="up"), WheelEvent(direction="down")]


def test_drag_selection_events_are_retained_with_coordinates():
    result = parse_input_chunk("\x1b[<0;5;10M\x1b[<32;15;12M\x1b[<0;15;12m")
    assert len(result.events) == 3
    assert [(event.action, event.x, event.y) for event in result.events] == [
        ("press", 5, 10), ("drag", 15, 12), ("release", 15, 12),
    ]


def test_native_windows_record_layout_matches_console_abi():
    import ctypes
    from nanocode.tui.windows_console import InputRecord, KeyRecord, MouseRecord

    assert ctypes.sizeof(KeyRecord) == 16
    assert ctypes.sizeof(MouseRecord) == 16
    assert ctypes.sizeof(InputRecord) == 20
    assert InputRecord.data.offset == 4


def test_native_unicode_and_key_repeats_are_preserved():
    from nanocode.tui.input_handler import _WIN_SCANCODE_TO_ANSI
    from nanocode.tui.windows_console import KeyRecord, key_record_text

    for text in ("中", "à", "a"):
        key = KeyRecord(down=1, repeat=3, character=ord(text))
        assert key_record_text(key, _WIN_SCANCODE_TO_ANSI) == text * 3
        key.down = 0
        assert key_record_text(key, _WIN_SCANCODE_TO_ANSI) == ""


def test_native_ctrl_home_and_pageup_produce_navigation_events():
    from nanocode.tui.input_handler import _WIN_SCANCODE_TO_ANSI
    from nanocode.tui.windows_console import KeyRecord, key_record_text

    home = KeyRecord(down=1, repeat=1, scan_code=71, modifiers=8)
    page = KeyRecord(down=1, repeat=1, scan_code=73)
    result = parse_input_chunk(key_record_text(home, _WIN_SCANCODE_TO_ANSI) + key_record_text(page, _WIN_SCANCODE_TO_ANSI))
    assert result.events == [
        KeyEvent(name="home", ctrl=True, meta=False),
        KeyEvent(name="pageup", ctrl=False, meta=False),
    ]


@pytest.mark.parametrize("delta", [120, -120, 240, -240])
def test_native_mouse_wheel_reaches_the_input_parser(delta):
    from nanocode.tui.windows_console import MouseRecord, mouse_record_text

    mouse = MouseRecord(x=10, y=5, buttons=(delta & 0xffff) << 16, flags=4)
    result = parse_input_chunk(mouse_record_text(mouse))
    assert result.events == [WheelEvent(direction="up" if delta > 0 else "down")] * (abs(delta) // 120)
    mouse.flags = 1  # MOUSE_MOVED must not flood or edit the prompt.
    assert mouse_record_text(mouse) == ""


def test_wheel_and_ctrl_home_end_scroll_the_transcript_without_editing_input():
    import threading
    from nanocode.tui.chrome import _cached_terminal_size
    from nanocode.tui.event_flow import _handle_event
    from nanocode.tui.state import ScreenState
    from nanocode.tui.types import TranscriptEntry

    state = ScreenState(input="keep this prompt", cursor_offset=4)
    state.transcript = [TranscriptEntry(id=1, kind="assistant", body="line\n" * (_cached_terminal_size()[1] + 100))]
    renders = []
    for event in (WheelEvent(direction="up"), KeyEvent(name="home", ctrl=True, meta=False)):
        # Navigation does not need an agent, tools or a submit callback.
        _handle_event(None, state, event, lambda: renders.append(True), threading.Event(), {}, None)
        assert state.transcript_scroll_offset > 0
        assert state.input == "keep this prompt" and state.cursor_offset == 4
    _handle_event(None, state, KeyEvent(name="end", ctrl=True, meta=False), lambda: renders.append(True), threading.Event(), {}, None)
    assert state.transcript_scroll_offset == 0
    assert state.cursor_offset == 4
    assert len(renders) == 3


def test_ctrl_c_still_exits_instead_of_disappearing_in_the_input_handler():
    import threading
    from nanocode.tui.event_flow import _handle_event
    from nanocode.tui.state import ScreenState

    with pytest.raises(SystemExit) as exit_info:
        _handle_event(None, ScreenState(), KeyEvent(name="c", ctrl=True, meta=False), lambda: None, threading.Event(), {}, None)
    assert exit_info.value.code == 0
