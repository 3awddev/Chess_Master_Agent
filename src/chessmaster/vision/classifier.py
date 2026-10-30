"""Per-square piece recognition against a calibration profile."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from chessmaster.vision.profile import UNCERTAIN, Profile
from chessmaster.vision.squares import COMPARE_MASK, SQUARE_PX, color_distance, parity_grid, split_squares, square_backgrounds

MAX_ERROR = 140.0
"""RMS per-pixel color error above which even the best candidate is rejected."""
MIN_MARGIN = 10.0
"""Required gap between the best and second-best candidate's error."""
HIGHLIGHT_DISTANCE = 45.0
"""Background this far from the expected light/dark color marks a highlighted square."""

_F = 2
"""Matching runs at SQUARE_PX / _F resolution, which also smooths anti-aliasing."""
_SHIFTS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
"""Template offsets (at matching resolution) that absorb a pixel or two of board misalignment."""


def _downsample(a: np.ndarray) -> np.ndarray:
    n = a.shape[1] // _F
    return a.reshape(a.shape[0], n, _F, n, _F, *a.shape[3:]).mean(axis=(2, 4))


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(a)
    n = a.shape[1]
    ys, yd = (slice(0, n - dy), slice(dy, n)) if dy >= 0 else (slice(-dy, n), slice(0, n + dy))
    xs, xd = (slice(0, n - dx), slice(dx, n)) if dx >= 0 else (slice(-dx, n), slice(0, n + dx))
    out[:, yd, xd] = a[:, ys, xs]
    return out


_MASK = COMPARE_MASK.reshape(SQUARE_PX // _F, _F, SQUARE_PX // _F, _F).all(axis=(1, 3))


@dataclass
class Recognition:
    labels: np.ndarray
    """(8, 8) int labels in screen order [row, col]; see profile.PIECE_SYMBOLS."""
    errors: np.ndarray
    margins: np.ndarray
    backgrounds: np.ndarray
    highlighted: np.ndarray
    """(8, 8) bool, background differs from the theme's light/dark color."""
    board_match: float
    """Fraction of squares whose background is the theme's light/dark color (highlights count against it)."""

    @property
    def uncertain_count(self) -> int:
        return int((self.labels == UNCERTAIN).sum())


class SquareClassifier:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        sprites = _downsample(profile.sprites)
        alphas = _downsample(profile.alphas)
        shifted_s = np.stack([_shift(sprites, dy, dx) for dy, dx in _SHIFTS], axis=1)  # (12, S, n, n, 3)
        shifted_a = np.stack([_shift(alphas, dy, dx) for dy, dx in _SHIFTS], axis=1)   # (12, S, n, n)
        s = shifted_s[:, :, _MASK].reshape(-1, _MASK.sum(), 3).astype(np.float64)   # (K, P, 3)
        a = shifted_a[:, :, _MASK].reshape(-1, _MASK.sum()).astype(np.float64)      # (K, P)
        # Precomputed terms of ||D - A*(S - b)||^2 with D = obs - b, expanded so that
        # each frame needs only a couple of matrix products.
        self._as = (a[..., None] * s).reshape(len(a), -1)                           # (K, P*3)
        self._a = a                                                                  # (K, P)
        self._as_sq = (self._as ** 2).sum(1)                                         # (K,)
        self._a2s = ((a ** 2)[..., None] * s).sum(1)                                 # (K, 3)
        self._a2 = (a ** 2).sum(1)                                                   # (K,)
        self._p = _MASK.sum()
        self._expected_bg = np.where(parity_grid()[..., None], profile.light, profile.dark).astype(np.float32)

    def classify(self, board_bgr: np.ndarray) -> Recognition:
        squares = split_squares(board_bgr)
        bg = square_backgrounds(squares).astype(np.float32)
        small = split_squares(board_bgr, SQUARE_PX // _F).reshape(64, SQUARE_PX // _F, SQUARE_PX // _F, 3)
        b = bg.reshape(64, 3).astype(np.float64)
        d = small[:, _MASK].astype(np.float64) - b[:, None]                   # (64, P, 3)

        sse_empty = (d ** 2).sum(axis=(1, 2))                                  # (64,)
        d_as = d.reshape(64, -1) @ self._as.T                                  # (64, K)
        d_ab = (d * b[:, None]).sum(-1) @ self._a.T                            # (64, K)
        model_sq = self._as_sq[None] - 2 * b @ self._a2s.T + (b ** 2).sum(1, keepdims=True) * self._a2[None]
        sse = sse_empty[:, None] - 2 * (d_as - d_ab) + model_sq
        sse_pieces = sse.reshape(64, 12, len(_SHIFTS)).min(axis=2)

        errors = np.sqrt(np.maximum(np.concatenate([sse_empty[:, None], sse_pieces], axis=1), 0) / self._p)
        order = np.argsort(errors, axis=1)
        best = order[:, 0]
        e1 = np.take_along_axis(errors, order[:, :1], 1)[:, 0]
        e2 = np.take_along_axis(errors, order[:, 1:2], 1)[:, 0]
        margins = e2 - e1
        labels = best.copy()
        labels[(e1 > MAX_ERROR) | (margins < MIN_MARGIN)] = UNCERTAIN

        highlighted = color_distance(bg, self._expected_bg) > HIGHLIGHT_DISTANCE
        return Recognition(
            labels=labels.reshape(8, 8).astype(np.int8),
            errors=e1.reshape(8, 8),
            margins=margins.reshape(8, 8),
            backgrounds=bg,
            highlighted=highlighted,
            board_match=float((~highlighted).mean()),
        )
