"""Windows console input records and explicit Unicode clipboard paste.

ReadConsoleInputW retains mouse events that msvcrt.getwch discards. Its keyboard
records also carry the VT sequences emitted by Windows Terminal.
"""

from __future__ import annotations

import codecs
import ctypes


class KeyRecord(ctypes.Structure):
    _fields_ = [
        ("down", ctypes.c_int32), ("repeat", ctypes.c_uint16),
        ("virtual_key", ctypes.c_uint16), ("scan_code", ctypes.c_uint16),
        ("character", ctypes.c_uint16), ("modifiers", ctypes.c_uint32),
    ]


class MouseRecord(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int16), ("y", ctypes.c_int16),
        ("buttons", ctypes.c_uint32), ("modifiers", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
    ]


class RecordData(ctypes.Union):
    _fields_ = [("key", KeyRecord), ("mouse", MouseRecord), ("padding", ctypes.c_uint32 * 4)]


class InputRecord(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_uint16), ("data", RecordData)]


def read_clipboard_text() -> str:
    """Read Unicode text only when a paste key reaches the application."""
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.GetClipboardData.argtypes = [wintypes.UINT]
    user.GetClipboardData.restype = wintypes.HANDLE
    user.CloseClipboard.argtypes = []
    user.CloseClipboard.restype = wintypes.BOOL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalUnlock.restype = wintypes.BOOL
    if not user.OpenClipboard(None):
        return ""
    try:
        handle = user.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel.GlobalUnlock(handle)
    finally:
        user.CloseClipboard()


def key_record_text(key: KeyRecord, scan_codes: dict[int, str]) -> str:
    if not key.down:
        return ""
    if key.character == 0x16 or (key.virtual_key == 0x2D and key.modifiers & 0x10):
        # Ctrl+V / Shift+Insert can be forwarded by the terminal. Pasted text
        # must not become a submit or a control key, even when it spans lines.
        text = read_clipboard_text().replace("\r\n", "\n").replace("\r", "\n")
        text = "".join(c for c in text if c.isprintable() or c in "\n\t")
        return "\x1b[200~" + text + "\x1b[201~"
    if key.character:
        return chr(key.character) * max(1, key.repeat)
    sequence = scan_codes.get(key.scan_code, "")
    if sequence.startswith("\x1b[") and len(sequence) == 3:
        modifier = 1 + bool(key.modifiers & 0x10) + 2 * bool(key.modifiers & 0x03) + 4 * bool(key.modifiers & 0x0C)
        if modifier != 1:
            sequence = f"\x1b[1;{modifier}{sequence[-1]}"
    return sequence * max(1, key.repeat)


def mouse_record_text(mouse: MouseRecord) -> str:
    x, y = max(1, mouse.x + 1), max(1, mouse.y + 1)
    modifier = 4 if mouse.modifiers & 0x10 else 0
    if mouse.flags == 0x0004:  # MOUSE_WHEELED
        delta = ctypes.c_int16(mouse.buttons >> 16).value
        if not delta:
            return ""
        button = (64 if delta > 0 else 65) + modifier
        return f"\x1b[<{button};{x};{y}M" * max(1, abs(delta) // 120)
    if mouse.flags == 1 and mouse.buttons & 1:
        return f"\x1b[<{32 + modifier};{x};{y}M"
    if mouse.flags in (0, 2):  # Button transition / double click.
        if mouse.buttons & 1:
            return f"\x1b[<{modifier};{x};{y}M"
        if mouse.buttons & 2:
            return f"\x1b[<{2 + modifier};{x};{y}M"
        if not mouse.buttons:
            return f"\x1b[<{modifier};{x};{y}m"
    return ""


class WindowsConsoleInput:
    def __init__(self, scan_codes: dict[int, str]) -> None:
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        self.kernel.GetStdHandle.restype = wintypes.HANDLE
        self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetConsoleMode.restype = wintypes.BOOL
        self.kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.SetConsoleMode.restype = wintypes.BOOL
        self.kernel.GetNumberOfConsoleInputEvents.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetNumberOfConsoleInputEvents.restype = wintypes.BOOL
        self.kernel.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(InputRecord), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.ReadConsoleInputW.restype = wintypes.BOOL
        self.handle = self.kernel.GetStdHandle(-10)
        mode = wintypes.DWORD()
        if not self.kernel.GetConsoleMode(self.handle, ctypes.byref(mode)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.original_mode = mode.value
        self.scan_codes = scan_codes
        self.decoder = codecs.getincrementaldecoder("utf-16-le")(errors="replace")
        # Preserve the input mode for the shell, enable VT/mouse/resize events,
        # and disable echo, line buffering, Quick Edit and system Ctrl+C.
        raw_mode = (mode.value | 0x0080 | 0x0200 | 0x0010 | 0x0008) & ~(0x0001 | 0x0002 | 0x0004 | 0x0040)
        if not self.kernel.SetConsoleMode(self.handle, raw_mode):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self) -> str:
        count = ctypes.c_uint32()
        if not self.kernel.GetNumberOfConsoleInputEvents(self.handle, ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not count.value:
            return ""
        records = (InputRecord * min(count.value, 4096))()
        if not self.kernel.ReadConsoleInputW(self.handle, records, len(records), ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        text = []
        for record in records[:count.value]:
            if record.kind == 1:
                text.append(key_record_text(record.data.key, self.scan_codes))
            elif record.kind == 2:
                text.append(mouse_record_text(record.data.mouse))
            elif record.kind == 4:
                from nanocode.tui.chrome import invalidate_terminal_size_cache
                invalidate_terminal_size_cache()
                text.append("\x1b[I")
        # Native key records contain UTF-16 units, possibly split across reads.
        return self.decoder.decode("".join(text).encode("utf-16-le", errors="surrogatepass"))

    def close(self) -> None:
        if not self.kernel.SetConsoleMode(self.handle, self.original_mode):
            raise ctypes.WinError(ctypes.get_last_error())
