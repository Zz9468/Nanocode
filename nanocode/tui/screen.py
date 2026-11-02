from __future__ import annotations

import os
import sys

ENTER_ALT_SCREEN = "\u001b[?1049h"
EXIT_ALT_SCREEN = "\u001b[?1049l"
ERASE_SCREEN_AND_HOME = "\u001b[2J\u001b[H"
# Mouse tracking sequence breakdown:
#   ?1000h  — basic X10 mouse reporting (button press/release)
#   ?1002h  — button-event tracking (only reports while button pressed, can interfere)
#   ?1003h  — any-event tracking (reports all mouse events including scroll without button)
#   ?1006h  — SGR extended encoding (supports coordinates > 223, required for modern terminals)
# Report motion while a button is held for application-owned drag selection.
ENABLE_MOUSE_TRACKING = "\u001b[?1000h\u001b[?1002h\u001b[?1006h"
DISABLE_MOUSE_TRACKING = "\u001b[?1006l\u001b[?1003l\u001b[?1002l\u001b[?1000l"

ENABLE_BRACKETED_PASTE = "\u001b[?2004h"
DISABLE_BRACKETED_PASTE = "\u001b[?2004l"
ENABLE_FOCUS_TRACKING  = "[?1004h"
ENABLE_SYNC_OUTPUT  = "[?2026h"
DISABLE_SYNC_OUTPUT = "[?2026l"
DISABLE_FOCUS_TRACKING = "[?1004l"
# Terminal types that do not support alternate screen or mouse tracking.
# NOTE: the empty string is intentionally NOT included. On Windows the TERM
# environment variable is unset by default, so treating "" as dumb would skip
# the alternate screen buffer and cause every redraw frame to accumulate in the
# terminal scrollback (garbled "stacked frame" output when scrolling up —
# GitHub issue #7). Pipes / non-interactive output are handled separately via
# the isatty() guard in _is_dumb_terminal().
_DUMB_TERMS = frozenset({"dumb", "linux"})


# ---------------------------------------------------------------------------
# Windows VT processing
# ---------------------------------------------------------------------------

_vt_enabled = False


def _enable_windows_vt_processing() -> None:
    """Enable ANSI / VT escape sequence processing on Windows 10+.

    Without this call the console ignores escape codes for colours,
    alternate-screen, cursor visibility, mouse tracking, etc.
    The function is a no-op on non-Windows platforms or when the
    underlying API call is unavailable.
    """
    global _vt_enabled
    if _vt_enabled:
        return

    if sys.platform != "win32":
        _vt_enabled = True
        return

    try:
        import ctypes
        import ctypes.wintypes as wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_PROCESSED_OUTPUT = 0x0001

        for handle_id in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            handle = kernel32.GetStdHandle(handle_id)
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT
                kernel32.SetConsoleMode(handle, new_mode)

        # Input modes belong to _RawModeContext, which saves and restores them.
        _vt_enabled = True
    except Exception:
        # If ctypes is unavailable or the call fails (e.g. old Windows),
        # fall through silently — ANSI codes will simply not render.
        _vt_enabled = True


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def hide_cursor() -> None:
    _enable_windows_vt_processing()
    sys.stdout.write("\u001b[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write("\u001b[?25h")
    sys.stdout.flush()


def _is_dumb_terminal() -> bool:
    """Return True if the terminal likely doesn't support escape sequences.

    Windows has no ``TERM`` variable by default, but modern Windows consoles
    support the alternate-screen buffer and mouse tracking once VT processing is
    enabled (done in :func:`_enable_windows_vt_processing`). We therefore guard
    against non-interactive (piped) output with ``isatty()`` rather than treating
    an empty ``TERM`` as dumb — otherwise Windows would skip the alternate screen
    and redraw frames would pile up in the scrollback (issue #7).
    """
    if not sys.stdout.isatty():
        return True
    return os.environ.get("TERM", "") in _DUMB_TERMS


def enter_alternate_screen() -> None:
    _enable_windows_vt_processing()
    if _is_dumb_terminal():
        # Dumb terminals (e.g. 'linux' console, 'dumb', piped output)
        # don't support alternate screen or mouse tracking.
        return
    sys.stdout.write(DISABLE_MOUSE_TRACKING + ENTER_ALT_SCREEN + ERASE_SCREEN_AND_HOME + ENABLE_MOUSE_TRACKING + ENABLE_BRACKETED_PASTE + ENABLE_FOCUS_TRACKING + ENABLE_SYNC_OUTPUT)
    sys.stdout.flush()


def exit_alternate_screen() -> None:
    if _is_dumb_terminal():
        return
    sys.stdout.write(DISABLE_MOUSE_TRACKING + EXIT_ALT_SCREEN + DISABLE_BRACKETED_PASTE + ENABLE_SYNC_OUTPUT + DISABLE_FOCUS_TRACKING)
    sys.stdout.flush()


def clear_screen() -> None:
    sys.stdout.write("\u001b[H\u001b[J")
    sys.stdout.flush()
