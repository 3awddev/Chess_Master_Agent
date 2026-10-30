"""System-wide hotkeys via RegisterHotKey, delivered through Qt's native event filter."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

from chessmaster.platform import win32

log = logging.getLogger(__name__)


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        QCoreApplication.instance().installNativeEventFilter(self)

    def register(self, modifiers: int, key: str, callback: Callable[[], None]) -> bool:
        hotkey_id = 0xC000 + len(self._callbacks)
        if not win32.register_hotkey(hotkey_id, modifiers, ord(key.upper())):
            log.warning("Hotkey %s is already in use by another program", key)
            return False
        self._callbacks[hotkey_id] = callback
        return True

    def unregister_all(self) -> None:
        for hotkey_id in self._callbacks:
            win32.unregister_hotkey(hotkey_id)
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            hotkey_id = win32.parse_hotkey_message(int(message))
            callback = self._callbacks.get(hotkey_id) if hotkey_id is not None else None
            if callback is not None:
                callback()
                return True, 0
        return False, 0
