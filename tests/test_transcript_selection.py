"""Selection must survive scrolling the application viewport, not just one screen."""

import pytest

from nanocode.tui.chrome import _cached_terminal_size, render_panel, strip_ansi, string_display_width
from nanocode.tui.input_parser import MouseEvent, WheelEvent
from nanocode.tui.selection import (
    SelectionPoint,
    TranscriptSelection,
    _index_at_cell,
    build_transcript_viewport,
    clear_transcript_selection,
    handle_transcript_selection,
    render_selected_transcript,
    selected_text,
    tick_transcript_selection,
)
from nanocode.tui.state import ScreenState
from nanocode.tui.transcript import _compute_total_lines, get_transcript_window_bounds, render_transcript
from nanocode.tui.types import TranscriptEntry


def refresh_view(state, window_size=6, prefix=""):
    width = max(40, _cached_terminal_size()[0])
    if state.transcript_selection:
        selection = state.transcript_selection
        total, offset = len(selection.lines), selection.scroll_offset
        raw = render_selected_transcript(selection, window_size)
    else:
        total, offset = _compute_total_lines(state.transcript), state.transcript_scroll_offset
        raw = render_transcript(state.transcript, offset, window_size)
    start, end, _, _ = get_transcript_window_bounds(total, offset, window_size)
    header = render_panel("header", "project\nmodel")
    decorated = prefix + raw
    state.transcript_viewport = build_transcript_viewport(raw, decorated, header, start, end, window_size, width)
    return header + "\n\n" + render_panel("session feed", decorated, min_body_lines=window_size)


def document_at_top():
    state = ScreenState(input="keep my draft", cursor_offset=4)
    state.transcript = [TranscriptEntry(id=1, kind="assistant", body="\n".join(f"line-{i:03}" for i in range(80)))]
    state.transcript_scroll_offset = _compute_total_lines(state.transcript) - 6
    refresh_view(state)
    return state


def test_held_drag_and_wheel_keep_one_continuous_range_across_many_screens():
    state = document_at_top()
    view = state.transcript_viewport
    assert handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row))
    anchor = state.transcript_selection.anchor
    for _ in range(10):
        view = state.transcript_viewport
        assert handle_transcript_selection(state, WheelEvent("down", x=view.width - 3, y=view.rows[-1].screen_row))
        refresh_view(state)
        assert state.transcript_selection.anchor == anchor
    selection = state.transcript_selection
    lines = [line.strip() for line in selected_text(selection).splitlines()]
    last = int(lines[-1].split("-")[1])
    assert lines == [f"line-{i:03}" for i in range(last + 1)]
    assert last > 20
    assert state.input == "keep my draft" and state.cursor_offset == 4
    assert "\x1b" not in selected_text(selection)
    assert "\x1b[7m" in render_selected_transcript(selection, 6)


def test_backward_selection_retains_anchor_when_scrolling_up():
    state = document_at_top()
    state.transcript_scroll_offset = 0
    refresh_view(state)
    view = state.transcript_viewport
    handle_transcript_selection(state, MouseEvent("press", view.width - 3, view.rows[-1].screen_row))
    anchor = state.transcript_selection.anchor
    for _ in range(8):
        view = state.transcript_viewport
        handle_transcript_selection(state, WheelEvent("up", x=view.left + 2, y=view.rows[0].screen_row))
        refresh_view(state)
    selection = state.transcript_selection
    assert selection.anchor == anchor
    assert selection.focus.row < anchor.row - 12
    lines = [line.strip() for line in selected_text(selection).splitlines()]
    first, last = (int(line.split("-")[1]) for line in (lines[0], lines[-1]))
    assert lines == [f"line-{i:03}" for i in range(first, last + 1)]


def test_dragging_beyond_edge_auto_scrolls_without_new_mouse_events():
    state = document_at_top()
    view = state.transcript_viewport
    handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row))
    handle_transcript_selection(state, MouseEvent("drag", view.width - 3, view.rows[-1].screen_row + 2))
    before = state.transcript_selection.scroll_offset
    assert tick_transcript_selection(state, now=1.0)
    refresh_view(state)
    assert state.transcript_selection.scroll_offset < before
    assert not tick_transcript_selection(state, now=1.04)
    assert tick_transcript_selection(state, now=1.1)
    refresh_view(state)
    assert "line-006" in selected_text(state.transcript_selection)


def test_click_without_drag_does_not_start_edge_auto_scroll():
    state = document_at_top()
    view = state.transcript_viewport
    handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row))
    assert not tick_transcript_selection(state, now=10)
    assert selected_text(state.transcript_selection) == ""


def test_clicking_outside_feed_clears_selection_and_requests_redraw():
    state = document_at_top()
    view = state.transcript_viewport
    handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row))
    assert handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[-1].screen_row + 5))
    assert state.transcript_selection is None
    assert state.input == "keep my draft"


def test_shift_drag_remains_available_to_the_terminal():
    state = document_at_top()
    view = state.transcript_viewport
    assert not handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row, shift=True))
    assert state.transcript_selection is None


def test_selected_snapshot_survives_streaming_and_scroll_reset():
    state = document_at_top()
    view = state.transcript_viewport
    handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row))
    handle_transcript_selection(state, MouseEvent("drag", view.width - 3, view.rows[-1].screen_row))
    selection = state.transcript_selection
    original = selected_text(selection)
    original_offset = selection.scroll_offset
    state.transcript[0].body += "\nnew streaming text"
    state.transcript_revision += 1
    state.transcript_scroll_offset = 0
    assert selected_text(selection) == original
    assert "new streaming text" not in render_selected_transcript(selection, 6)
    assert selection.scroll_offset == original_offset
    state.status = "Copied 30 characters; Esc clears selection"
    clear_transcript_selection(state)
    assert state.transcript_selection is None
    assert state.transcript_scroll_offset == original_offset
    assert state.status is None


@pytest.mark.parametrize("cell,index", [(0, 0), (1, 0), (2, 1), (3, 1), (4, 2), (5, 3)])
def test_selection_cell_coordinates_do_not_split_chinese_or_emoji(cell, index):
    assert _index_at_cell("中🙂A", cell) == index


def test_exact_multiline_range_includes_offscreen_rows_and_partial_ends():
    lines = tuple(f"row-{i:03}: 中文🙂 tail" for i in range(100))
    selection = TranscriptSelection(lines, SelectionPoint(3, 4), SelectionPoint(88, 12), 0, 80)
    expected = lines[3][4:] + "\n" + "\n".join(lines[4:88]) + "\n" + lines[88][:12]
    assert selected_text(selection) == expected
    selection.anchor, selection.focus = selection.focus, selection.anchor
    assert selected_text(selection) == expected


def test_mouse_hit_rows_match_rendered_panel_after_wrapped_summaries():
    state = document_at_top()
    width = max(40, _cached_terminal_size()[0])
    prefix = "summary: " + "x" * (width * 2) + "\n\n"
    frame = refresh_view(state, prefix=prefix)
    rendered = [strip_ansi(line) for line in frame.splitlines()]
    for hit in state.transcript_viewport.rows:
        expected = f"line-{hit.source_row - 1:03}"
        assert expected in rendered[hit.screen_row - 1]
    view = state.transcript_viewport
    handle_transcript_selection(state, MouseEvent("press", view.left + 2, view.rows[0].screen_row))
    assert state.transcript_selection.anchor == SelectionPoint(1, 2)


def test_scrollbar_does_not_force_full_width_content_onto_an_extra_row():
    width = max(60, _cached_terminal_size()[0])
    entries = [TranscriptEntry(id=1, kind="assistant", body="中" * width)]
    body = render_transcript(entries, 0, 20)
    from nanocode.tui.chrome import wrap_panel_body_line
    for line in body.splitlines():
        assert string_display_width(line) <= width - 4
        assert len(wrap_panel_body_line(line, width)) == 1
