"""Calibration profiles: square colors and piece sprites for one board theme / piece set."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from chessmaster.vision.squares import color_distance

log = logging.getLogger(__name__)

PIECE_SYMBOLS = "PNBRQKpnbrqk"
"""Label k (1..12) is PIECE_SYMBOLS[k - 1]; 0 is an empty square, -1 is uncertain."""

EMPTY = 0
UNCERTAIN = -1

PROFILE_MATCH_TOLERANCE = 60.0


@dataclass
class Profile:
    name: str
    light: np.ndarray
    dark: np.ndarray
    sprites: np.ndarray
    """(12, N, N, 3) float32 BGR piece colors, indexed by label - 1."""
    alphas: np.ndarray
    """(12, N, N) float32 coverage of each piece pixel."""
    white_bottom: bool = True
    square_px: float = 0.0
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def color_distance_to(self, light: np.ndarray, dark: np.ndarray) -> float:
        return float(color_distance(self.light, light) + color_distance(self.dark, dark)) / 2

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_slug(self.name)}.npz"
        meta = {"name": self.name, "white_bottom": self.white_bottom,
                "square_px": self.square_px, "created": self.created}
        np.savez_compressed(
            path, light=self.light, dark=self.dark, sprites=self.sprites.astype(np.float16),
            alphas=self.alphas.astype(np.float16), meta=np.array(json.dumps(meta)),
        )
        return path

    @staticmethod
    def load(path: Path) -> Profile:
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            return Profile(
                name=meta["name"], light=data["light"].astype(np.float32),
                dark=data["dark"].astype(np.float32), sprites=data["sprites"].astype(np.float32),
                alphas=data["alphas"].astype(np.float32), white_bottom=meta["white_bottom"],
                square_px=meta["square_px"], created=meta["created"],
            )


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "profile"


def load_profiles(directory: Path) -> list[Profile]:
    profiles = []
    for path in sorted(directory.glob("*.npz")):
        try:
            profiles.append(Profile.load(path))
        except Exception:
            log.exception("Could not load profile %s", path)
    return profiles


def match_profile(profiles: list[Profile], light: np.ndarray, dark: np.ndarray) -> Profile | None:
    """The profile whose square colors are closest to the observed board, if close enough."""
    best = min(profiles, key=lambda p: p.color_distance_to(light, dark), default=None)
    if best is not None and best.color_distance_to(light, dark) <= PROFILE_MATCH_TOLERANCE:
        return best
    return None
