"""Keeping the control panel from covering the board it is watching."""

from __future__ import annotations

from chessmaster.common import Rect

GAP = 12


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def _clamp(r: Rect, area: Rect) -> Rect:
    x = min(max(r.x, area.x), max(area.x, area.right - r.w))
    y = min(max(r.y, area.y), max(area.y, area.bottom - r.h))
    return Rect(x, y, r.w, r.h)


def _overlap_area(a: Rect, b: Rect) -> int:
    w = min(a.right, b.right) - max(a.x, b.x)
    h = min(a.bottom, b.bottom) - max(a.y, b.y)
    return max(0, w) * max(0, h)


def panel_position(panel: Rect, board: Rect, screen: Rect) -> Rect | None:
    """Where to move `panel` so it does not cover `board`; None if it already doesn't.

    Tries right of, left of, below and above the board, then the screen corner with the least overlap.
    """
    if not _overlaps(panel, board):
        return None
    w, h = panel.w, panel.h
    options = [
        Rect(board.right + GAP, board.y, w, h),
        Rect(board.x - GAP - w, board.y, w, h),
        Rect(board.x, board.bottom + GAP, w, h),
        Rect(board.x, board.y - GAP - h, w, h),
    ]
    for r in options:
        if r.x >= screen.x and r.right <= screen.right and r.y >= screen.y and r.bottom <= screen.bottom:
            return _clamp(r, screen)
    for r in options:
        r = _clamp(r, screen)
        if not _overlaps(r, board):
            return r
    corners = [
        Rect(screen.x, screen.y, w, h), Rect(screen.right - w, screen.y, w, h),
        Rect(screen.x, screen.bottom - h, w, h), Rect(screen.right - w, screen.bottom - h, w, h),
    ]
    return min(corners, key=lambda r: _overlap_area(r, board))
