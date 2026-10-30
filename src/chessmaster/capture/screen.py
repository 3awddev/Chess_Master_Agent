from __future__ import annotations

import threading

import mss
import numpy as np

from chessmaster.common import Rect


class ScreenCapture:
    """Grabs screen regions as BGR numpy arrays in physical pixels.

    mss holds GDI handles that are bound to the creating thread, so each thread
    gets its own mss instance.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def _sct(self) -> mss.base.MSSBase:
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._local.sct = sct
        return sct

    def monitors(self) -> list[Rect]:
        return [
            Rect(m["left"], m["top"], m["width"], m["height"])
            for m in self._sct().monitors[1:]
        ]

    def virtual_desktop(self) -> Rect:
        m = self._sct().monitors[0]
        return Rect(m["left"], m["top"], m["width"], m["height"])

    def grab(self, rect: Rect) -> np.ndarray:
        shot = self._sct().grab(
            {"left": rect.x, "top": rect.y, "width": rect.w, "height": rect.h}
        )
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            self._local.sct = None
