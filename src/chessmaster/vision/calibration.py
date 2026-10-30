"""Building a profile from a board showing the starting position."""

from __future__ import annotations

import chess
import cv2
import numpy as np

from chessmaster.board_coords import piece_label, screen_labels, screen_to_square
from chessmaster.vision.classifier import SquareClassifier
from chessmaster.vision.profile import Profile
from chessmaster.vision.squares import (
    COMPARE_MASK, OVERLAY_BAND, SQUARE_PX, color_distance, parity_grid, split_squares, square_backgrounds,
)

FOREGROUND_DISTANCE = 45.0
EMPTY_MAX_ERROR = 45.0
"""Mean L1 deviation from the square's background; textured (wood, marble) themes reach ~30 when empty."""


class CalibrationError(Exception):
    pass


def _piece_mask(square: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Filled silhouette of the piece on a square, as float32 0/1."""
    n = SQUARE_PX
    fg = (color_distance(square, bg) > FOREGROUND_DISTANCE).astype(np.uint8)
    inner = np.zeros_like(fg)
    inner[OVERLAY_BAND:n - OVERLAY_BAND, OVERLAY_BAND:n - OVERLAY_BAND] = 1
    fg &= inner
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(fg)
    lo, hi = 0.2 * n, 0.8 * n
    for c in contours:
        m = cv2.moments(c)
        if m["m00"] <= 0:
            continue
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        if lo <= cx <= hi and lo <= cy <= hi:
            cv2.drawContours(mask, [c], -1, 1, thickness=cv2.FILLED)
    return mask.astype(np.float32)


def calibrate(board_bgr: np.ndarray, name: str) -> Profile:
    """Learn square colors and piece sprites from a board in the starting position."""
    squares = split_squares(board_bgr)
    bg = square_backgrounds(squares)
    light_grid = parity_grid()
    middle = np.zeros((8, 8), bool)
    middle[2:6] = True
    light = np.median(bg[middle & light_grid], axis=0).astype(np.float32)
    dark = np.median(bg[middle & ~light_grid], axis=0).astype(np.float32)
    if color_distance(light, dark) < 40:
        raise CalibrationError("Could not tell the light and dark squares apart.")

    for row in range(2, 6):
        for col in range(8):
            err = np.abs(squares[row, col][COMPARE_MASK] - bg[row, col]).sum(-1).mean()
            if err > EMPTY_MAX_ERROR:
                raise CalibrationError(
                    "The middle of the board is not empty. Show the starting position and try again."
                )

    masks = np.zeros((8, 8, SQUARE_PX, SQUARE_PX), np.float32)
    brightness = np.zeros((8, 8), np.float32)
    for row in (0, 1, 6, 7):
        for col in range(8):
            m = _piece_mask(squares[row, col], bg[row, col])
            if m.mean() < 0.05:
                raise CalibrationError("Expected pieces on the first and last two rows of the board.")
            masks[row, col] = m
            gray = squares[row, col].mean(-1)
            brightness[row, col] = (gray * m).sum() / m.sum()
    white_bottom = bool(brightness[6:].mean() > brightness[:2].mean())

    start = chess.Board()
    color_sum = np.zeros((12, SQUARE_PX, SQUARE_PX, 3), np.float32)
    mask_sum = np.zeros((12, SQUARE_PX, SQUARE_PX), np.float32)
    counts = np.zeros(12, np.float32)
    for row in (0, 1, 6, 7):
        for col in range(8):
            label = piece_label(start.piece_at(screen_to_square(row, col, white_bottom)))
            m = masks[row, col]
            color_sum[label - 1] += squares[row, col] * m[..., None]
            mask_sum[label - 1] += m
            counts[label - 1] += 1
    sprites = color_sum / np.maximum(mask_sum, 1e-6)[..., None]
    alphas = mask_sum / counts[:, None, None]

    profile = Profile(
        name=name, light=light, dark=dark, sprites=sprites.astype(np.float32),
        alphas=alphas.astype(np.float32), white_bottom=white_bottom,
        square_px=board_bgr.shape[1] / 8,
    )
    rec = SquareClassifier(profile).classify(board_bgr)
    expected = screen_labels(start, white_bottom)
    wrong = int((rec.labels != expected).sum())
    if wrong:
        raise CalibrationError(
            f"Self-test failed: {wrong} square(s) were not recognized. Make sure nothing covers the board."
        )
    return profile
