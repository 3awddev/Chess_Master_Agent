"""Mapping between screen cells [row, col] (row 0 at the top) and chess squares."""

from __future__ import annotations

import chess
import numpy as np

from chessmaster.vision.profile import EMPTY, PIECE_SYMBOLS


def screen_to_square(row: int, col: int, white_bottom: bool) -> chess.Square:
    if white_bottom:
        return chess.square(col, 7 - row)
    return chess.square(7 - col, row)


def square_to_screen(square: chess.Square, white_bottom: bool) -> tuple[int, int]:
    f, r = chess.square_file(square), chess.square_rank(square)
    if white_bottom:
        return 7 - r, f
    return r, 7 - f


def piece_label(piece: chess.Piece | None) -> int:
    return EMPTY if piece is None else PIECE_SYMBOLS.index(piece.symbol()) + 1


def label_piece(label: int) -> chess.Piece | None:
    return None if label <= EMPTY else chess.Piece.from_symbol(PIECE_SYMBOLS[label - 1])


def screen_labels(board: chess.BaseBoard, white_bottom: bool) -> np.ndarray:
    """(8, 8) screen-order labels for a board."""
    out = np.zeros((8, 8), np.int8)
    for sq, piece in board.piece_map().items():
        r, c = square_to_screen(sq, white_bottom)
        out[r, c] = piece_label(piece)
    return out


def square_labels(screen: np.ndarray, white_bottom: bool) -> tuple[int, ...]:
    """Screen-order labels converted to a 64-tuple indexed by chess square."""
    out = [0] * 64
    for row in range(8):
        for col in range(8):
            out[screen_to_square(row, col, white_bottom)] = int(screen[row, col])
    return tuple(out)
