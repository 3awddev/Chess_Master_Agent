"""User settings and on-disk locations."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "ChessMaster"
HINT_SIDES = ("auto", "white", "black", "both")


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    path = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_dir() -> Path:
    return app_data_dir() / "profiles"


def log_path() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "chessmaster.log"


def _default_threads() -> int:
    return max(1, min(4, (os.cpu_count() or 2) // 2))


@dataclass
class Settings:
    engine_path: str = ""
    think_time: float = 1.0
    threads: int = _default_threads()
    hash_mb: int = 128
    capture_fps: float = 10.0
    hint_side: str = "auto"
    """auto = the side at the bottom of the board, or white / black / both."""
    thickness: float = 0.06
    """Rectangle outline width as a fraction of the square size."""

    @staticmethod
    def path() -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except Exception:
            log.exception("Could not read settings; using defaults")
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in data.items() if k in known})
        if s.hint_side not in HINT_SIDES:
            s.hint_side = "auto"
        return s

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def _bundle_dirs() -> list[Path]:
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
    dirs.append(Path(__file__).resolve().parents[2])
    return dirs


def find_engine(settings: Settings) -> str | None:
    if settings.engine_path and Path(settings.engine_path).is_file():
        return settings.engine_path
    for d in _bundle_dirs():
        candidate = d / "engine" / "stockfish.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("stockfish")
