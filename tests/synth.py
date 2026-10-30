"""Synthetic board screenshots rendered with python-chess SVG and Qt."""

from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import chess
import chess.svg
import cv2
import numpy as np
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from chessmaster.common import Rect

_app = None

THEMES = [
    {},
    {"square light": "#f0d9b5", "square dark": "#b58863"},
    {"square light": "#eeeed2", "square dark": "#769656",
     "square light lastmove": "#f6f669", "square dark lastmove": "#baca2b"},
    {"square light": "#dee3e6", "square dark": "#8ca2ad"},
]


def qt_app() -> QGuiApplication:
    global _app
    _app = QGuiApplication.instance() or QApplication([])
    return _app


def svg_to_bgr(svg: str, width: int, height: int) -> np.ndarray:
    qt_app()
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    ptr = image.constBits()
    arr = np.frombuffer(ptr, np.uint8).reshape(height, image.bytesPerLine() // 4, 4)
    return np.ascontiguousarray(arr[:, :width, :3])


def render_board(
    board: chess.BaseBoard,
    size: int,
    orientation: chess.Color = chess.WHITE,
    coordinates: bool = False,
    lastmove: chess.Move | None = None,
    check: chess.Square | None = None,
    colors: dict | None = None,
) -> tuple[np.ndarray, Rect]:
    """Render a board; returns (BGR image, rect of the 8x8 playing area in that image)."""
    svg = chess.svg.board(
        board, size=size, orientation=orientation, coordinates=coordinates,
        lastmove=lastmove, check=check, colors=colors or {},
    )
    margin = 15 if coordinates else 0
    full = 2 * margin + 8 * chess.svg.SQUARE_SIZE
    scale = size / full
    img = svg_to_bgr(svg, size, size)
    off = margin * scale
    inner = 8 * chess.svg.SQUARE_SIZE * scale
    return img, Rect(int(round(off)), int(round(off)), int(round(inner)), int(round(inner)))


def cluttered_desktop(w: int, h: int, seed: int) -> np.ndarray:
    """A fake desktop with panels, text and buttons around where a board will go."""
    rng = random.Random(seed)
    img = np.full((h, w, 3), rng.randint(30, 240), np.uint8)
    for _ in range(40):
        x0, y0 = rng.randrange(w), rng.randrange(h)
        x1, y1 = x0 + rng.randint(20, 400), y0 + rng.randint(10, 200)
        color = tuple(rng.randint(0, 255) for _ in range(3))
        cv2.rectangle(img, (x0, y0), (x1, y1), color, -1 if rng.random() < 0.7 else 2)
    for _ in range(60):
        cv2.putText(img, "Lorem ipsum 1. e4 e5 2. Nf3", (rng.randrange(w), rng.randrange(h)),
                    cv2.FONT_HERSHEY_SIMPLEX, rng.uniform(0.4, 1.0),
                    tuple(rng.randint(0, 255) for _ in range(3)), 1, cv2.LINE_AA)
    return img


def paste(desktop: np.ndarray, img: np.ndarray, x: int, y: int) -> np.ndarray:
    out = desktop.copy()
    out[y:y + img.shape[0], x:x + img.shape[1]] = img
    return out


def random_game_board(rng: random.Random, plies: int) -> tuple[chess.Board, chess.Move | None]:
    board = chess.Board()
    last = None
    for _ in range(plies):
        moves = list(board.legal_moves)
        if not moves:
            break
        captures = [m for m in moves if board.is_capture(m)]
        last = rng.choice(captures) if captures and rng.random() < 0.5 else rng.choice(moves)
        board.push(last)
    return board, last
