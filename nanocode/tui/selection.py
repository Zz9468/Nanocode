"""Transcript selection anchored to document rows rather than screen cells."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from nanocode.tui.clipboard import copy_text
from nanocode.tui.chrome import string_display_width, wrap_panel_body_line
from nanocode.tui.input_parser import KeyEvent, MouseEvent, TextEvent, WheelEvent
from nanocode.tui.transcript import (
    _char_display_width,
    _render_transcript_lines,
    _strip_ansi,
    format_transcript_window,
    get_transcript_window_bounds,
)

if TYPE_CHECKING:
    from nanocode.tui.state import ScreenState


@dataclass(frozen=True, order=True)
class SelectionPoint:
    row: int
    column: int


@dataclass(frozen=True)
class ViewportRow:
    screen_row: int
    source_row: int
    column_offset: int = 0


@dataclass(frozen=True)
class TranscriptViewport:
    rows: tuple[ViewportRow, ...]
    source_start: int
    window_size: int
    width: int
    left: int = 3  # Panel border and its single padding cell are not text.


@dataclass
class TranscriptSelection:
    lines: tuple[str, ...]
    anchor: SelectionPoint
    focus: SelectionPoint
    scroll_offset: int
    width: int
    dragging: bool = True
    moved: bool = False
    pointer_x: int = 0
    pointer_y: int = 0
    last_scroll: float = 0.0


def build_transcript_viewport(raw_body: str, decorated_body: str, header: str, source_start: int, source_end: int, window_size: int, width: int) -> TranscriptViewport:
    prefix = decorated_body[:-len(raw_body)] if raw_body else decorated_body
    prefix_height = sum(len(wrap_panel_body_line(line, width)) for line in prefix.splitlines())
    # Header, blank row, panel top/title/divider, then the body (1-based).
    screen_row = len(header.splitlines()) + 5 + prefix_height
    rows = []
    for index, line in enumerate(raw_body.split("\n")[:source_end - source_start]):
        column_offset = 0
        for part in wrap_panel_body_line(line, width):
            rows.append(ViewportRow(screen_row, source_start + index, column_offset))
            screen_row += 1
            column_offset += string_display_width(part)
    return TranscriptViewport(tuple(rows), source_start, window_size, width)


def selected_text(selection: TranscriptSelection) -> str:
    start, end = sorted((selection.anchor, selection.focus))
    if start == end:
        return ""
    if start.row == end.row:
        return selection.lines[start.row][start.column:end.column]
    return "\n".join((
        selection.lines[start.row][start.column:],
        *selection.lines[start.row + 1:end.row],
        selection.lines[end.row][:end.column],
    ))


def _highlight_line(selection: TranscriptSelection, row: int) -> str:
    text = selection.lines[row]
    start, end = sorted((selection.anchor, selection.focus))
    if not start.row <= row <= end.row or start == end:
        return text
    left = start.column if row == start.row else 0
    right = end.column if row == end.row else len(text)
    if left == right:
        return text
    return text[:left] + "\x1b[7m" + text[left:right] + "\x1b[0m" + text[right:]


def render_selected_transcript(selection: TranscriptSelection, window_size: int) -> str:
    start, end, offset, maximum = get_transcript_window_bounds(len(selection.lines), selection.scroll_offset, window_size)
    return format_transcript_window([_highlight_line(selection, row) for row in range(start, end)], offset, maximum)


def _index_at_cell(text: str, column: int) -> int:
    cells = 0
    for index, char in enumerate(text):
        cells += _char_display_width(char)
        if cells > column:
            return index
    return len(text)


def _pointer_point(selection: TranscriptSelection, view: TranscriptViewport, x: int, y: int, clamp: bool) -> SelectionPoint | None:
    if not view.rows:
        return None
    hits = [row for row in view.rows if row.screen_row == y]
    if not hits and not clamp:
        return None
    if not clamp and not view.left <= x < view.width - 1:
        return None
    hit = hits[0] if hits else min(view.rows, key=lambda row: abs(row.screen_row - y))
    start, end, _, _ = get_transcript_window_bounds(len(selection.lines), selection.scroll_offset, view.window_size)
    row = max(start, min(end - 1, hit.source_row + start - view.source_start))
    column = max(0, x - view.left + hit.column_offset)
    return SelectionPoint(row, _index_at_cell(selection.lines[row], column))


def _update_focus(selection: TranscriptSelection, view: TranscriptViewport) -> None:
    point = _pointer_point(selection, view, selection.pointer_x, selection.pointer_y, True)
    if point is not None:
        selection.focus = point


def clear_transcript_selection(state: ScreenState) -> None:
    if state.transcript_selection is not None:
        state.transcript_scroll_offset = state.transcript_selection.scroll_offset
    state.transcript_selection = None
    if state.status and state.status.startswith(("Copied ", "Copy failed:")):
        state.status = None


def copy_transcript_selection(state: ScreenState) -> bool:
    if state.transcript_selection is None:
        return False
    text = selected_text(state.transcript_selection)
    if not text:
        return False
    try:
        copy_text(text)
        state.status = f"Copied {len(text)} characters; Esc clears selection"
    except (OSError, UnicodeError) as exc:
        state.status = f"Copy failed: {exc}"
    return True


def _scroll_selection(state: ScreenState, delta: int) -> bool:
    selection, view = state.transcript_selection, state.transcript_viewport
    if selection is None or view is None:
        return False
    _, _, offset, _ = get_transcript_window_bounds(len(selection.lines), selection.scroll_offset + delta, view.window_size)
    changed = offset != selection.scroll_offset
    selection.scroll_offset = offset
    if selection.dragging:
        _update_focus(selection, view)
    return changed


def tick_transcript_selection(state: ScreenState, now: float | None = None) -> bool:
    selection, view = state.transcript_selection, state.transcript_viewport
    if selection is None or view is None or not view.rows or not selection.dragging or not selection.moved:
        return False
    now = time.monotonic() if now is None else now
    if now - selection.last_scroll < 0.08:
        return False
    direction = 1 if selection.pointer_y <= view.rows[0].screen_row else (-1 if selection.pointer_y >= view.rows[-1].screen_row else 0)
    if not direction:
        return False
    selection.last_scroll = now
    return _scroll_selection(state, direction * 2)


def handle_transcript_selection(
    state: ScreenState,
    event,
    on_click: Callable[[SelectionPoint], bool] | None = None,
) -> bool:
    """Consume selection gestures before prompt editing or Ctrl+C exit."""
    selection, view = state.transcript_selection, state.transcript_viewport
    if isinstance(event, MouseEvent):
        if event.shift or view is None:
            return False
        if event.action == "press" and event.button == 0:
            lines = selection.lines if selection else tuple(_strip_ansi(line) for line in _render_transcript_lines(list(state.visible_transcript)))
            if not lines:
                return False
            offset = selection.scroll_offset if selection else state.transcript_scroll_offset
            candidate = TranscriptSelection(lines, SelectionPoint(0, 0), SelectionPoint(0, 0), offset, view.width)
            point = _pointer_point(candidate, view, event.x, event.y, False)
            if point is None:
                clear_transcript_selection(state)
                return selection is not None
            candidate.anchor = candidate.focus = point
            candidate.pointer_x, candidate.pointer_y = event.x, event.y
            state.transcript_selection = candidate
            return True
        if selection is not None and selection.dragging and event.button == 0:
            selection.pointer_x, selection.pointer_y = event.x, event.y
            _update_focus(selection, view)
            if (event.action == "release" and not selection.moved
                    and _pointer_point(selection, view, event.x, event.y, False) == selection.anchor
                    and on_click is not None and on_click(selection.anchor)):
                return True
            selection.moved = True
            if event.action == "release":
                selection.dragging = False
                if not copy_transcript_selection(state):
                    clear_transcript_selection(state)
            return True
        return False
    if selection is None:
        return False
    if isinstance(event, WheelEvent):
        if selection.dragging:
            selection.pointer_x = event.x if event.x is not None else selection.pointer_x
            selection.pointer_y = event.y if event.y is not None else selection.pointer_y
            selection.moved = True
        _scroll_selection(state, 3 if event.direction == "up" else -3)
        return True
    if isinstance(event, KeyEvent):
        if event.name == "escape":
            clear_transcript_selection(state)
            return True
        if (event.name == "c" and event.ctrl) or event.name == "return":
            return copy_transcript_selection(state)
        if event.name in ("pageup", "pagedown"):
            _scroll_selection(state, view.window_size - 1 if event.name == "pageup" else 1 - view.window_size)
            return True
        if event.ctrl and event.name in ("home", "end"):
            _scroll_selection(state, len(selection.lines) if event.name == "home" else -len(selection.lines))
            return True
    if isinstance(event, TextEvent) and not event.ctrl:
        clear_transcript_selection(state)
    return False
