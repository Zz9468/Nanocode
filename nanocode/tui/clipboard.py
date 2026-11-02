"""Copy selected terminal text using the platform clipboard."""

from __future__ import annotations

import base64
import sys


def copy_text(text: str) -> None:
    if sys.platform != "win32":
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sys.stdout.write(f"\x1b]52;c;{encoded}\x07")
        sys.stdout.flush()
        return

    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.DestroyWindow.restype = wintypes.BOOL
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.EmptyClipboard.argtypes = []
    user.EmptyClipboard.restype = wintypes.BOOL
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    user.CloseClipboard.argtypes = []
    user.CloseClipboard.restype = wintypes.BOOL
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalUnlock.restype = wintypes.BOOL
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.restype = wintypes.HGLOBAL

    # A message-only window supplies a valid clipboard owner without opening
    # a visible window. Ownership is required by EmptyClipboard/SetClipboardData.
    owner = user.CreateWindowExW(0, "STATIC", "Nanocode clipboard", 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
    if not owner:
        raise ctypes.WinError(ctypes.get_last_error())
    allocation = None
    opened = False
    try:
        data = (text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le")
        allocation = kernel.GlobalAlloc(2, len(data))  # GMEM_MOVEABLE
        if not allocation:
            raise ctypes.WinError(ctypes.get_last_error())
        pointer = kernel.GlobalLock(allocation)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel.GlobalUnlock(allocation)
        if not user.OpenClipboard(owner):
            raise ctypes.WinError(ctypes.get_last_error())
        opened = True
        if not user.EmptyClipboard() or not user.SetClipboardData(13, allocation):
            raise ctypes.WinError(ctypes.get_last_error())
        allocation = None  # The operating system now owns this memory.
    finally:
        if opened:
            user.CloseClipboard()
        if allocation:
            kernel.GlobalFree(allocation)
        user.DestroyWindow(owner)
