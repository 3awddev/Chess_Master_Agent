"""Thin ctypes wrappers around the few Win32 calls the app needs."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from chessmaster.common import Rect

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL

HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000


def set_dpi_awareness() -> None:
    """Opt into per-monitor DPI awareness so all coordinates are physical pixels.

    Qt does this itself; this exists for code paths that run without Qt.
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def set_window_rect(hwnd: int, rect: Rect, topmost: bool = True) -> None:
    """Move/resize a window in physical pixels without activating it."""
    if not IS_WINDOWS:
        return
    after = HWND_TOPMOST if topmost else 0
    ok = user32.SetWindowPos(
        hwnd, after, rect.x, rect.y, rect.w, rect.h,
        SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW,
    )
    if not ok:
        log.warning("SetWindowPos failed: %s", ctypes.get_last_error())


SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004


def move_window(hwnd: int, x: int, y: int) -> None:
    """Move a window's top-left corner to physical pixel (x, y), keeping its size and z-order."""
    if not IS_WINDOWS:
        return
    if not user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE):
        log.warning("SetWindowPos failed: %s", ctypes.get_last_error())


def make_overlay_window(hwnd: int) -> None:
    """Ensure the window is click-through, never activated and hidden from Alt+Tab."""
    if not IS_WINDOWS:
        return
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)


def get_window_rect(hwnd: int) -> Rect | None:
    """Physical-pixel rectangle of a visible, non-minimized window."""
    if not IS_WINDOWS:
        return None
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


GA_ROOT = 2


def top_window_at(x: int, y: int) -> int | None:
    """Top-level window visible at a physical screen point (click-through windows are skipped)."""
    if not IS_WINDOWS:
        return None
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return None
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def register_hotkey(hotkey_id: int, modifiers: int, vk: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk))


def unregister_hotkey(hotkey_id: int) -> None:
    if IS_WINDOWS:
        user32.UnregisterHotKey(None, hotkey_id)


def parse_hotkey_message(message_ptr: int) -> int | None:
    """Return the hotkey id if the native MSG at `message_ptr` is WM_HOTKEY."""
    msg = wintypes.MSG.from_address(message_ptr)
    if msg.message == WM_HOTKEY:
        return int(msg.wParam)
    return None
