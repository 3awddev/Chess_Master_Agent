"""Click-through, always-on-top window over the board that draws the hint rectangles."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from chessmaster.common import Rect
from chessmaster.platform import win32
from chessmaster.vision.squares import OVERLAY_BAND, SQUARE_PX

FROM_COLOR = QColor(230, 30, 30, 235)
TO_COLOR = QColor(30, 200, 60, 235)
MAX_THICKNESS = OVERLAY_BAND / SQUARE_PX
"""Outlines must stay inside the outer band of each square that recognition ignores."""


@dataclass(frozen=True)
class OverlayHint:
    from_cell: tuple[int, int]
    to_cell: tuple[int, int]
    promotion: str | None = None


class HintOverlay(QWidget):
    def __init__(self, thickness: float = 0.06) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._board: Rect | None = None
        self._hint: OverlayHint | None = None
        self.thickness = thickness
        self._screen_hooked = False

    @property
    def thickness(self) -> float:
        return self._thickness

    @thickness.setter
    def thickness(self, value: float) -> None:
        self._thickness = max(0.01, min(MAX_THICKNESS, value))
        self.update()

    def set_board_rect(self, rect: Rect | None) -> None:
        self._board = rect
        if rect is None:
            self.hide()
            return
        if not self.isVisible():
            self.show()
            win32.make_overlay_window(int(self.winId()))
            if not self._screen_hooked and self.windowHandle() is not None:
                self.windowHandle().screenChanged.connect(lambda _s: self._apply_geometry())
                self._screen_hooked = True
        self._apply_geometry()
        # A DPI change triggered by the move may make Qt resize the window; re-apply once settled.
        QTimer.singleShot(100, self._apply_geometry)

    def _apply_geometry(self) -> None:
        if self._board is not None and self.isVisible():
            win32.set_window_rect(int(self.winId()), self._board)

    def show_hint(self, hint: OverlayHint | None) -> None:
        self._hint = hint
        self.update()

    def clear_hint(self) -> None:
        self.show_hint(None)

    @property
    def hint(self) -> OverlayHint | None:
        return self._hint

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._hint is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sq_w, sq_h = self.width() / 8, self.height() / 8
        pw = max(2.0, min(sq_w, sq_h) * self._thickness)
        for (row, col), color in ((self._hint.from_cell, FROM_COLOR), (self._hint.to_cell, TO_COLOR)):
            p.setPen(QPen(color, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(col * sq_w + pw / 2, row * sq_h + pw / 2, sq_w - pw, sq_h - pw))
        if self._hint.promotion:
            row, col = self._hint.to_cell
            box = QRectF(col * sq_w + pw, row * sq_h + pw, sq_w * 0.22, sq_h * 0.22)
            font = QFont("Segoe UI", 1, QFont.Weight.Bold)
            font.setPixelSize(max(8, int(box.height())))
            p.setFont(font)
            p.setPen(TO_COLOR)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self._hint.promotion)
        p.end()
