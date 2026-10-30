"""Background loop: find the board, recognize it every frame, and track the game."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import chess
from PySide6.QtCore import QObject, Signal

from chessmaster.capture.screen import ScreenCapture
from chessmaster.common import Rect
from chessmaster.game.tracker import GameTracker
from chessmaster.platform import win32
from chessmaster.vision.board_locator import BoardCandidate, board_from_selection, locate_boards, refine_board
from chessmaster.vision.calibration import CalibrationError, calibrate
from chessmaster.vision.classifier import SquareClassifier
from chessmaster.vision.profile import Profile, load_profiles, match_profile
from chessmaster.vision.squares import checkerboard_score, split_squares, square_backgrounds

log = logging.getLogger(__name__)

SCAN_INTERVAL = 1.0
LOST_AFTER = 1.0
"""Seconds the board may fail validation before it is considered gone."""
REALIGN_AFTER = 2.0
"""Seconds of many uncertain squares before trying to re-snap the board rectangle."""
MIN_BOARD_MATCH = 0.75

BUILTIN_PROFILES = Path(__file__).resolve().parent / "profiles"
"""Profiles shipped with the app for common site defaults (e.g. lichess' brown board)."""


@dataclass(frozen=True)
class PipelineStatus:
    board_rect: Rect | None
    profile_name: str | None
    uncertain: int
    paused: bool
    needs_calibration: bool


class VisionPipeline(QObject):
    boardChanged = Signal(object)
    """Rect of the board in physical pixels, or None when it is lost."""
    stateChanged = Signal(object)
    """TrackerState after every change to the tracked game."""
    status = Signal(object)
    message = Signal(str)
    calibrationFinished = Signal(bool, str)

    def __init__(self, profile_dir: Path, fps: float = 10.0) -> None:
        super().__init__()
        self._profile_dir = profile_dir
        self._fps = fps
        self._commands: queue.Queue[Callable[[], None]] = queue.Queue()
        self._running = False
        self._paused = False
        self._excluded: list[int] = []
        self._thread = threading.Thread(target=self._run, name="vision", daemon=True)

        self._capture = ScreenCapture()
        self._tracker = GameTracker()
        self._profiles: list[Profile] = []
        self._profile: Profile | None = None
        self._classifier: SquareClassifier | None = None
        self._board: Rect | None = None
        self._needs_calibration = False
        self._uncertain = 0

    # -- thread-safe API (called from the GUI thread) ----------------------

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._thread.join(timeout=3)

    def monitors(self) -> list[Rect]:
        return self._capture.monitors()

    def set_paused(self, paused: bool) -> None:
        self._commands.put(lambda: self._do_pause(paused))

    def set_fps(self, fps: float) -> None:
        self._fps = max(1.0, fps)

    def set_excluded_windows(self, hwnds: list[int]) -> None:
        """Windows (e.g. the control panel with its preview board) never treated as the game board."""
        self._excluded = list(hwnds)

    def set_assumed_turn(self, color: chess.Color | None) -> None:
        self._commands.put(lambda: setattr(self._tracker, "assumed_turn", color))

    def request_calibration(self) -> None:
        self._commands.put(self._do_calibrate)

    def set_manual_region(self, rect: Rect) -> None:
        self._commands.put(lambda: self._do_manual_region(rect))

    def request_resync(self) -> None:
        self._commands.put(self._tracker.request_resync)

    def flip_orientation(self) -> None:
        self._commands.put(lambda: self._tracker.set_orientation(not self._tracker.white_bottom))

    # -- worker thread ---------------------------------------------------

    def _run(self) -> None:
        self._profiles = self._load_profiles()
        log.info("Loaded %d profile(s): %s", len(self._profiles), ", ".join(p.name for p in self._profiles))
        last_scan = -SCAN_INTERVAL
        last_status = 0.0
        invalid_since: float | None = None
        uncertain_since: float | None = None
        while self._running:
            t0 = time.monotonic()
            self._drain_commands()
            if self._paused:
                self._emit_status()
                time.sleep(0.1)
                continue
            try:
                if self._board is None:
                    if t0 - last_scan >= SCAN_INTERVAL:
                        last_scan = t0
                        cand = self._scan()
                        if cand is not None:
                            self._set_board(cand)
                else:
                    img = self._capture.grab(self._board)
                    ok = self._process(img, t0)
                    if not ok:
                        invalid_since = invalid_since or t0
                        if t0 - invalid_since >= LOST_AFTER:
                            log.info("Board lost")
                            self._set_board(None)
                            invalid_since = None
                    else:
                        invalid_since = None
                        if self._uncertain > 4:
                            uncertain_since = uncertain_since or t0
                            if t0 - uncertain_since >= REALIGN_AFTER:
                                self._realign()
                                uncertain_since = None
                        else:
                            uncertain_since = None
            except Exception:
                log.exception("Vision loop error")
                self._set_board(None)
                time.sleep(0.5)
            if t0 - last_status >= 0.25:
                last_status = t0
                self._emit_status()
            elapsed = time.monotonic() - t0
            time.sleep(max(0.005, 1.0 / self._fps - elapsed))
        self._capture.close()

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                cmd()
            except Exception:
                log.exception("Pipeline command failed")

    def _emit_message(self, text: str) -> None:
        log.info("%s", text)
        self.message.emit(text)

    def _emit_calibration(self, ok: bool, text: str) -> None:
        log.info("Calibration %s: %s", "succeeded" if ok else "failed", text)
        self.calibrationFinished.emit(ok, text)

    def _load_profiles(self) -> list[Profile]:
        """User profiles first, so they win ties against the built-in ones."""
        return load_profiles(self._profile_dir) + load_profiles(BUILTIN_PROFILES)

    def _emit_status(self) -> None:
        self.status.emit(PipelineStatus(
            self._board, self._profile.name if self._profile else None,
            self._uncertain, self._paused, self._needs_calibration,
        ))

    def _do_pause(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self._set_board(None)

    def _scan(self) -> BoardCandidate | None:
        best: BoardCandidate | None = None
        for mon in self._capture.monitors():
            img = self._capture.grab(mon)
            for cand in locate_boards(img):
                rect = cand.rect.translated(mon.x, mon.y)
                if win32.top_window_at(*rect.center) in self._excluded:
                    continue
                if best is None or rect.w > best.rect.w:
                    best = BoardCandidate(rect, cand.score, cand.light, cand.dark)
        return best

    def _set_board(self, cand: BoardCandidate | None) -> None:
        new_rect = cand.rect if cand is not None else None
        if new_rect == self._board:
            return
        self._board = new_rect
        self._uncertain = 0
        if cand is not None:
            log.info("Board at %s", new_rect)
            self._select_profile(cand)
        self.boardChanged.emit(new_rect)

    def _select_profile(self, cand: BoardCandidate) -> None:
        profile = match_profile(self._profiles, cand.light, cand.dark)
        if profile is not self._profile:
            self._profile = profile
            self._classifier = SquareClassifier(profile) if profile else None
            if profile is not None:
                log.info("Using profile %s", profile.name)
                self._tracker.white_bottom = profile.white_bottom
                self._tracker.reset()
        if profile is None and not self._needs_calibration:
            self._emit_message("New board style. Show the starting position and click Calibrate.")
        self._needs_calibration = profile is None

    def _process(self, img, now: float) -> bool:
        """Recognize one frame. Returns False if the image no longer looks like the board."""
        if self._classifier is None:
            score, light, dark = checkerboard_score(square_backgrounds(split_squares(img)))
            if score < 0.8:
                return False
            if self._profiles:
                self._select_profile(BoardCandidate(self._board, score, light, dark))
            return True
        rec = self._classifier.classify(img)
        self._uncertain = rec.uncertain_count
        if rec.board_match < MIN_BOARD_MATCH:
            return False
        if self._tracker.update(rec.labels, rec.highlighted, now):
            self.stateChanged.emit(self._tracker.state())
        return True

    def _realign(self) -> None:
        if self._board is None:
            return
        region = self._board.expanded(self._board.w // 8)
        img = self._capture.grab(region)
        local = self._board.translated(-region.x, -region.y)
        cand = refine_board(img, local)
        if cand is not None:
            rect = cand.rect.translated(region.x, region.y)
            if rect != self._board:
                log.info("Realigned board %s -> %s", self._board, rect)
                self._board = rect
                self.boardChanged.emit(rect)

    def _do_manual_region(self, selection: Rect) -> None:
        region = selection.expanded(max(8, selection.w // 8))
        img = self._capture.grab(region)
        cand = board_from_selection(img, selection.translated(-region.x, -region.y))
        if cand is None:
            self._emit_message("That area does not look like a chessboard. Try selecting just the 8x8 squares.")
            return
        self._paused = False
        self._board = None
        self._set_board(BoardCandidate(cand.rect.translated(region.x, region.y), cand.score, cand.light, cand.dark))
        log.info("Board selected manually: %s", self._board)
        if self._profile is not None:
            self._emit_message("Board selected.")

    def _do_calibrate(self) -> None:
        if self._board is None:
            cand = self._scan()
            if cand is None:
                self._emit_calibration(
                    False, "No chessboard found on screen. Use 'Select board' to mark it manually.")
                return
            self._set_board(cand)
        img = self._capture.grab(self._board)
        try:
            score, light, dark = checkerboard_score(square_backgrounds(split_squares(img)))
            existing = match_profile(self._profiles, light, dark)
            name = existing.name if existing else f"Board {datetime.now():%Y-%m-%d %H.%M.%S}"
            profile = calibrate(img, name)
        except CalibrationError as exc:
            self._emit_calibration(False, str(exc))
            return
        profile.save(self._profile_dir)
        self._profiles = self._load_profiles()
        self._profile = next((p for p in self._profiles if p.name == name), profile)
        self._classifier = SquareClassifier(self._profile)
        self._needs_calibration = False
        self._tracker.white_bottom = profile.white_bottom
        self._tracker.reset()
        side = "White" if profile.white_bottom else "Black"
        self._emit_calibration(True, f"Calibrated '{name}' ({side} at the bottom).")
