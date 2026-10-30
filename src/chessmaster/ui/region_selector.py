"""Full-screen drag-to-select of the board, one dimmed window per monitor."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from chessmaster.common import Rect
from chessmaster.platform import win32


class _MonitorShade(QWidget):
    def __init__(self, selector: RegionSelector, monitor: Rect) -> None:
        super().__init__(None)
        self._selector = selector
        self._monitor = monitor
        self._start: QPointF | None = None
        self._end: QPointF | None = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def show_on_monitor(self) -> None:
        self.show()
        win32.set_window_rect(int(self.winId()), self._monitor)
        QTimer.singleShot(50, lambda: win32.set_window_rect(int(self.winId()), self._monitor))
        self.activateWindow()
        self.setFocus()

    def _to_physical(self, p: QPointF) -> tuple[int, int]:
        sx = self._monitor.w / max(1, self.width())
        sy = self._monitor.h / max(1, self.height())
        return int(self._monitor.x + p.x() * sx), int(self._monitor.y + p.y() * sy)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Segoe UI", 14))
        p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   "Drag a rectangle around the chessboard (Esc to cancel)")
        if self._start is not None and self._end is not None:
            r = QRectF(self._start, self._end).normalized()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(r, QColor(0, 0, 0, 1))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(0, 200, 255), 2))
            p.drawRect(r)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = self._end = e.position()
            self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._start is not None:
            self._end = e.position()
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._start is None or e.button() != Qt.MouseButton.LeftButton:
            return
        x0, y0 = self._to_physical(self._start)
        x1, y1 = self._to_physical(e.position())
        self._start = self._end = None
        rect = Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        if rect.w >= 64 and rect.h >= 64:
            self._selector.finish(rect)
        else:
            self.update()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self._selector.finish(None)


class RegionSelector(QObject):
    """Emits `selected` with a physical-pixel Rect, or None if cancelled."""

    selected = Signal(object)

    def __init__(self, monitors: list[Rect]) -> None:
        super().__init__()
        self._shades = [_MonitorShade(self, m) for m in monitors]

    def start(self) -> None:
        for s in self._shades:
            s.show_on_monitor()

    def finish(self, rect: Rect | None) -> None:
        for s in self._shades:
            s.close()
            s.deleteLater()
        self._shades = []
        self.selected.emit(rect)
