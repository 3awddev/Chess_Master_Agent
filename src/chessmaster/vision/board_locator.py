"""Finding a 2D chessboard in a screenshot.

The detector looks for "X-corners": grid points where four squares meet, so the
diagonal quadrants share a color and adjacent quadrants differ. The internal
corners of a chessboard form a regular 7x7 lattice, which is what we search for.
Candidates are confirmed by checking that square colors alternate light/dark.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

import cv2
import numpy as np

from chessmaster.common import Rect
from chessmaster.vision.squares import checkerboard_score, split_squares, square_backgrounds

log = logging.getLogger(__name__)

MIN_VALID_SCORE = 0.8
MAX_POINTS = 4000


@dataclass(frozen=True)
class BoardCandidate:
    rect: Rect
    score: float
    light: np.ndarray
    dark: np.ndarray


def x_corner_response(img_bgr: np.ndarray, r: int) -> np.ndarray:
    """Response map; value at [y, x] describes the grid point at the top-left corner of pixel (x, y)."""
    h, w = img_bgr.shape[:2]
    out = np.zeros((h + 1, w + 1), np.float32)
    if h < 2 * r + 2 or w < 2 * r + 2:
        return out
    f = img_bgr.astype(np.float32)
    box = cv2.boxFilter(f, -1, (r, r), normalize=True, anchor=(0, 0), borderType=cv2.BORDER_REPLICATE)
    ny, nx = h - 2 * r + 1, w - 2 * r + 1
    tl = box[0:ny, 0:nx]
    tr = box[0:ny, r:r + nx]
    bl = box[r:r + ny, 0:nx]
    br = box[r:r + ny, r:r + nx]
    contrast = np.abs(tl + br - tr - bl).sum(axis=2) * 0.5
    diag = (np.abs(tl - br).sum(axis=2) + np.abs(tr - bl).sum(axis=2)) * 0.5
    out[r:r + ny, r:r + nx] = contrast - 1.5 * diag
    return out


def find_corner_points(img_bgr: np.ndarray, r: int, threshold: float = 30.0) -> np.ndarray:
    resp = x_corner_response(img_bgr, r)
    k = 2 * r + 1
    dil = cv2.dilate(resp, np.ones((k, k), np.uint8))
    ys, xs = np.nonzero((resp >= dil) & (resp > threshold))
    if len(xs) > MAX_POINTS:
        order = np.argsort(-resp[ys, xs])[:MAX_POINTS]
        ys, xs = ys[order], xs[order]
    return np.stack([xs, ys], axis=1).astype(np.int32) if len(xs) else np.zeros((0, 2), np.int32)

class _PointIndex:
    """Vectorized "is there a point near p + offset" queries over integer pixel points."""

    def __init__(self, pts: np.ndarray, shape: tuple[int, int]) -> None:
        self.pts = pts.astype(np.int64)
        self.stride = shape[1] + 1024
        keys = (self.pts[:, 1] + 512) * self.stride + self.pts[:, 0] + 512
        self.order = np.argsort(keys)
        self.keys = keys[self.order]

    def neighbors(self, src: np.ndarray, dx: float, dy: float, tol: float) -> tuple[np.ndarray, np.ndarray]:
        """Pairs (i, j) with point j within `tol` of point i + (dx, dy), for i in `src`."""
        t = int(np.ceil(tol))
        base = self.pts[src]
        bx = base[:, 0] + int(round(dx)) + 512
        by = base[:, 1] + int(round(dy)) + 512
        out_i, out_j = [], []
        if len(self.keys) == 0:
            return np.zeros(0, int), np.zeros(0, int)
        for oy in range(-t, t + 1):
            for ox in range(-t, t + 1):
                q = (by + oy) * self.stride + bx + ox
                pos = np.minimum(np.searchsorted(self.keys, q), len(self.keys) - 1)
                hit = self.keys[pos] == q
                out_i.append(src[hit])
                out_j.append(self.order[pos[hit]])
        return np.concatenate(out_i), np.concatenate(out_j)


def _nearest_right(pts: np.ndarray, min_sq: int, max_sq: int) -> np.ndarray:
    """Distance from each point to the nearest point to its right on (nearly) the same row; 0 if none."""
    dx = np.zeros(len(pts), np.int64)
    rows: dict[int, np.ndarray] = {}
    for y in np.unique(pts[:, 1]):
        rows[int(y)] = np.sort(pts[pts[:, 1] == y, 0])
    for i, (x, y) in enumerate(pts):
        best = 0
        for yy in (y - 1, y, y + 1):
            xs = rows.get(int(yy))
            if xs is None:
                continue
            j = np.searchsorted(xs, x + min_sq)
            if j < len(xs) and xs[j] - x <= max_sq and (best == 0 or xs[j] - x < best):
                best = xs[j] - x
        dx[i] = best
    return dx


def _candidate_spacings(pts: np.ndarray, index: _PointIndex, min_sq: int, max_sq: int) -> list[float]:
    """Square sizes worth trying, best first.

    Spacings come from nearest right-hand neighbours, then are ranked by how many of those
    points also have a neighbour one spacing below; text and UI rarely form such 2D lattices.
    """
    dx = _nearest_right(pts, min_sq, max_sq)
    valid = dx > 0
    if not valid.any():
        return []
    hist = np.bincount(dx[valid], minlength=max_sq + 2).astype(np.float32)
    smooth = hist.copy()
    smooth[1:] += hist[:-1]
    smooth[:-1] += hist[1:]
    scored = []
    for s in np.nonzero(smooth >= 6)[0]:
        s = int(s)
        if s < min_sq:
            continue
        tol = max(1.5, 0.03 * s)
        src = np.nonzero(valid & (np.abs(dx - s) <= tol))[0]
        i, _ = index.neighbors(src, 0, s, tol)
        count = len(np.unique(i))
        if count >= 16:
            scored.append((count, s))
    spacings: list[float] = []
    for _, s in sorted(scored, reverse=True):
        if any(abs(s - t) <= 2 for t in spacings):
            continue
        near = dx[valid & (np.abs(dx - s) <= 1.5)]
        spacings.append(float(near.mean()) if len(near) else float(s))
        if len(spacings) == 3:
            break
    return spacings


def _lattice_components(pts: np.ndarray, index: _PointIndex, s: float) -> list[dict[int, tuple[int, int]]]:
    tol = max(1.5, 0.03 * s)
    everyone = np.arange(len(pts))
    links: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for dx, dy, di, dj in ((s, 0, 1, 0), (0, s, 0, 1)):
        src, dst = index.neighbors(everyone, dx, dy, tol)
        for a, b in zip(src.tolist(), dst.tolist()):
            links[a].append((b, di, dj))
            links[b].append((a, -di, -dj))
    seen: set[int] = set()
    comps = []
    for start in list(links):
        if start in seen:
            continue
        coords = {start: (0, 0)}
        stack = [start]
        seen.add(start)
        while stack:
            p = stack.pop()
            pi, pj = coords[p]
            for q, di, dj in links[p]:
                if q not in seen:
                    seen.add(q)
                    coords[q] = (pi + di, pj + dj)
                    stack.append(q)
        if len(coords) >= 20:
            comps.append(coords)
    return comps




def _validate(img: np.ndarray, rect: Rect) -> tuple[float, np.ndarray, np.ndarray]:
    h, w = img.shape[:2]
    if rect.x < 0 or rect.y < 0 or rect.right > w or rect.bottom > h or rect.w < 64:
        return 0.0, np.zeros(3), np.zeros(3)
    crop = img[rect.y:rect.bottom, rect.x:rect.right]
    return checkerboard_score(square_backgrounds(split_squares(crop)))


def _boards_from_component(img: np.ndarray, pts: np.ndarray, coords: dict[int, tuple[int, int]]) -> list[BoardCandidate]:
    idx = np.fromiter(coords.keys(), int)
    ij = np.array([coords[k] for k in idx])
    xy = pts[idx].astype(np.float64)
    ax, bx = np.polyfit(ij[:, 0], xy[:, 0], 1) if len(np.unique(ij[:, 0])) > 1 else (0.0, 0.0)
    ay, by = np.polyfit(ij[:, 1], xy[:, 1], 1) if len(np.unique(ij[:, 1])) > 1 else (0.0, 0.0)
    if ax <= 0 or ay <= 0 or abs(ax - ay) > 0.05 * max(ax, ay):
        return []
    s = (ax + ay) / 2
    imin, imax = ij[:, 0].min(), ij[:, 0].max()
    jmin, jmax = ij[:, 1].min(), ij[:, 1].max()
    if imax - imin < 4 or jmax - jmin < 4:
        return []
    starts_i = range(imax - 6, imin + 1) if imax - imin <= 6 else range(imin, imax - 5)
    starts_j = range(jmax - 6, jmin + 1) if jmax - jmin <= 6 else range(jmin, jmax - 5)
    out = []
    for i0 in starts_i:
        for j0 in starts_j:
            inside = ((ij[:, 0] >= i0) & (ij[:, 0] < i0 + 7) & (ij[:, 1] >= j0) & (ij[:, 1] < j0 + 7)).sum()
            if inside < 24:
                continue
            left = bx + (i0 - 1) * ax
            top = by + (j0 - 1) * ay
            size = int(round(8 * s))
            rect = Rect(int(round(left)), int(round(top)), size, size)
            score, light, dark = _validate(img, rect)
            if score >= MIN_VALID_SCORE:
                out.append(BoardCandidate(rect, score, light, dark))
    return out


def _locate_single_scale(img: np.ndarray, r: int, min_sq: int) -> list[BoardCandidate]:
    h, w = img.shape[:2]
    pts = find_corner_points(img, r)
    if len(pts) < 24:
        return []
    max_sq = max(min_sq + 1, min(h, w) // 7)
    index = _PointIndex(pts, (h, w))
    found: list[BoardCandidate] = []
    for s in _candidate_spacings(pts, index, min_sq, max_sq):
        for comp in _lattice_components(pts, index, s):
            found.extend(_boards_from_component(img, pts, comp))
    return found


def _dedupe(cands: list[BoardCandidate]) -> list[BoardCandidate]:
    out: list[BoardCandidate] = []
    for c in sorted(cands, key=lambda c: (-c.rect.w, -c.score)):
        if all(_iou(c.rect, o.rect) < 0.5 for o in out):
            out.append(c)
    return out


def _iou(a: Rect, b: Rect) -> float:
    inter = a.intersection(b)
    if inter is None:
        return 0.0
    ia = inter.w * inter.h
    return ia / (a.w * a.h + b.w * b.h - ia)


def locate_boards(img: np.ndarray, min_square: int = 18) -> list[BoardCandidate]:
    """All boards found in `img`, largest first. Rects are in image coordinates."""
    h, w = img.shape[:2]
    scale = 1
    while max(h, w) / scale > 2000:
        scale *= 2
    if scale == 1:
        return _dedupe(_locate_single_scale(img, 4, min_square))
    small = cv2.resize(img, (w // scale, h // scale), interpolation=cv2.INTER_AREA)
    coarse = _locate_single_scale(small, 3, max(8, min_square // scale))
    refined = []
    for c in coarse:
        approx = Rect(c.rect.x * scale, c.rect.y * scale, c.rect.w * scale, c.rect.h * scale)
        better = refine_board(img, approx)
        refined.append(better or BoardCandidate(approx, c.score, c.light, c.dark))
    return _dedupe(refined)


def refine_board(img: np.ndarray, approx: Rect) -> BoardCandidate | None:
    """Snap a rough board rectangle (e.g. drawn by the user) to the exact grid."""
    h, w = img.shape[:2]
    margin = max(8, approx.w // 8)
    region = approx.expanded(margin).intersection(Rect(0, 0, w, h))
    if region is None:
        return None
    crop = img[region.y:region.bottom, region.x:region.right]
    min_sq = max(8, approx.w // 16)
    best = None
    for c in _locate_single_scale(crop, 4, min_sq):
        rect = c.rect.translated(region.x, region.y)
        overlap = _iou(rect, approx)
        if overlap > 0.5 and (best is None or overlap > best[0]):
            best = (overlap, BoardCandidate(rect, c.score, c.light, c.dark))
    return best[1] if best else None


def board_from_selection(img: np.ndarray, selection: Rect) -> BoardCandidate | None:
    """Manual fallback: snap the selection to the grid, or trust it if it is a checkerboard."""
    snapped = refine_board(img, selection)
    if snapped is not None:
        return snapped
    size = min(selection.w, selection.h)
    rect = Rect(selection.x, selection.y, size, size)
    score, light, dark = _validate(img, rect)
    if score >= MIN_VALID_SCORE:
        return BoardCandidate(rect, score, light, dark)
    return None
