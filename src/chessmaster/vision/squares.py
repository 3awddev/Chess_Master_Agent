"""Splitting a board image into normalized squares and sampling their background."""

from __future__ import annotations

import cv2
import numpy as np

SQUARE_PX = 48
"""Every square is resampled to SQUARE_PX x SQUARE_PX before analysis."""

OVERLAY_BAND = 4
"""Outer band of each normalized square reserved for the hint overlay; never analysed."""

RING_INNER = 7


def _ring_mask() -> np.ndarray:
    m = np.zeros((SQUARE_PX, SQUARE_PX), bool)
    m[OVERLAY_BAND:SQUARE_PX - OVERLAY_BAND, OVERLAY_BAND:SQUARE_PX - OVERLAY_BAND] = True
    m[RING_INNER:SQUARE_PX - RING_INNER, RING_INNER:SQUARE_PX - RING_INNER] = False
    return m


def _compare_mask() -> np.ndarray:
    """Central window used for piece matching: no overlay band, no corners (coordinate labels)."""
    m = np.zeros((SQUARE_PX, SQUARE_PX), bool)
    m[OVERLAY_BAND:SQUARE_PX - OVERLAY_BAND, OVERLAY_BAND:SQUARE_PX - OVERLAY_BAND] = True
    c = 11
    for ys in (slice(0, c), slice(SQUARE_PX - c, SQUARE_PX)):
        for xs in (slice(0, c), slice(SQUARE_PX - c, SQUARE_PX)):
            m[ys, xs] = False
    return m


RING_MASK = _ring_mask()
COMPARE_MASK = _compare_mask()


def split_squares(board_bgr: np.ndarray, n: int = SQUARE_PX) -> np.ndarray:
    """Return float32 array (8, 8, n, n, 3) indexed [screen_row, screen_col]."""
    img = cv2.resize(board_bgr, (8 * n, 8 * n), interpolation=cv2.INTER_AREA).astype(np.float32)
    return np.ascontiguousarray(img.reshape(8, n, 8, n, 3).transpose(0, 2, 1, 3, 4))


def square_backgrounds(squares: np.ndarray) -> np.ndarray:
    """Median color of each square's inner ring, shape (8, 8, 3).

    Pieces and coordinate labels cover only a minority of the ring, so the median
    is the square's own (possibly highlighted) background color.
    """
    ring = squares[:, :, RING_MASK]
    return np.median(ring, axis=2)


def parity_grid() -> np.ndarray:
    """True for light squares. The top-left square is light in either orientation."""
    r, c = np.indices((8, 8))
    return (r + c) % 2 == 0


def color_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """L1 distance over BGR channels along the last axis."""
    return np.abs(np.asarray(a, np.float32) - np.asarray(b, np.float32)).sum(axis=-1)


def checkerboard_score(backgrounds: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """How well the square backgrounds follow a light/dark checkerboard.

    Returns (fraction of squares closer to their parity color, light color, dark color).
    """
    light_mask = parity_grid()
    light = np.median(backgrounds[light_mask], axis=0)
    dark = np.median(backgrounds[~light_mask], axis=0)
    if color_distance(light, dark) < 40:
        return 0.0, light, dark
    d_light = color_distance(backgrounds, light)
    d_dark = color_distance(backgrounds, dark)
    ok = np.where(light_mask, d_light < d_dark, d_dark < d_light)
    return float(ok.mean()), light, dark
