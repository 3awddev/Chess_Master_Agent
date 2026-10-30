"""Wires capture, recognition, tracking, the engine and the overlay together."""

from __future__ import annotations

import logging

import chess
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from chessmaster.board_coords import square_to_screen
from chessmaster.common import Rect
from chessmaster.config import Settings, find_engine, profiles_dir
from chessmaster.engine.stockfish import EngineOptions, EngineWorker, Hint
from chessmaster.game.tracker import TrackerState
from chessmaster.pipeline import PipelineStatus, VisionPipeline
from chessmaster.platform import win32
from chessmaster.ui.hotkeys import GlobalHotkeys
from chessmaster.ui.main_window import MainWindow
from chessmaster.ui.overlay import HintOverlay, OverlayHint
from chessmaster.ui.placement import panel_position
from chessmaster.ui.region_selector import RegionSelector
from chessmaster.ui.settings_dialog import SettingsDialog

log = logging.getLogger(__name__)

ASSUMED_TURN = {"white": chess.WHITE, "black": chess.BLACK}


class AppController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self.settings = Settings.load()
        self._state: TrackerState | None = None
        self._board_rect: Rect | None = None
        self._hints_enabled = True
        self._selector: RegionSelector | None = None
        self._shut_down = False

        self.overlay = HintOverlay(self.settings.thickness)
        self.window = MainWindow(self)
        self.pipeline = VisionPipeline(profiles_dir(), self.settings.capture_fps)
        self.pipeline.set_assumed_turn(ASSUMED_TURN.get(self.settings.hint_side))
        self.engine: EngineWorker | None = None
        self._start_engine()

        self.pipeline.boardChanged.connect(self._on_board_changed)
        self.pipeline.stateChanged.connect(self._on_state)
        self.pipeline.status.connect(self._on_status)
        self.pipeline.message.connect(self.window.show_message)
        self.pipeline.calibrationFinished.connect(self._on_calibrated)
        self.pipeline.set_excluded_windows([int(self.window.winId())])

        self.hotkeys = GlobalHotkeys()
        mods = win32.MOD_CONTROL | win32.MOD_ALT
        self.hotkeys.register(mods, "H", self.toggle_hints)
        self.hotkeys.register(mods, "R", self.resync)

    def start(self) -> None:
        self.window.show()
        # Qt centers new windows, which is exactly where web boards usually are.
        area = self.window.screen().availableGeometry()
        frame = self.window.frameGeometry()
        self.window.move(area.right() - frame.width() - 16, area.top() + 16)
        self.pipeline.start()

    def _keep_panel_clear(self, board: Rect) -> None:
        """Move the control panel off the board so it neither hides squares nor gets mistaken for them."""
        hwnd = int(self.window.winId())
        panel = win32.get_window_rect(hwnd)
        if panel is None:
            return
        cx, cy = board.center
        screens = self.pipeline.monitors()
        screen = next((m for m in screens if m.contains_point(cx, cy)), screens[0] if screens else None)
        if screen is None:
            return
        pos = panel_position(panel, board, screen)
        if pos is not None:
            win32.move_window(hwnd, pos.x, pos.y)

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.hotkeys.unregister_all()
        self.pipeline.stop()
        if self.engine is not None:
            self.engine.shutdown()
        self.overlay.close()

    # -- engine ------------------------------------------------------------

    def _engine_options(self) -> EngineOptions:
        s = self.settings
        return EngineOptions(threads=s.threads, hash_mb=s.hash_mb, think_time=s.think_time)

    def _start_engine(self) -> None:
        path = find_engine(self.settings)
        if path is None:
            self.window.show_message(
                "Stockfish was not found. Run scripts\\get_stockfish.ps1 or choose an engine in Settings.")
            return
        log.info("Engine: %s", path)
        self.engine = EngineWorker(path, self._engine_options())
        self.engine.hintReady.connect(self._on_hint)
        self.engine.error.connect(self.window.show_message)
        self.engine.start()

    # -- pipeline events ---------------------------------------------------

    def _on_board_changed(self, rect: Rect | None) -> None:
        self._board_rect = rect
        if rect is not None:
            self._keep_panel_clear(rect)
        self.overlay.clear_hint()
        self.overlay.set_board_rect(rect)
        if rect is None:
            self._state = None
            self.window.show_state(None)
            if self.engine is not None:
                self.engine.cancel()
        else:
            self._request_hint()

    def _on_state(self, state: TrackerState) -> None:
        self._state = state
        self.overlay.clear_hint()
        self.window.show_state(state)
        self._request_hint()

    def _on_status(self, st: PipelineStatus) -> None:
        self.window.show_status(st)

    def _on_calibrated(self, ok: bool, text: str) -> None:
        self.window.show_message(text)
        if not ok:
            QMessageBox.warning(self.window, "Calibration", text)

    def _wants_hint(self, state: TrackerState) -> bool:
        if state.board is None or not state.valid or state.board.is_game_over():
            return False
        side = self.settings.hint_side
        if side == "both":
            return True
        mine = ASSUMED_TURN.get(side, chess.WHITE if state.white_bottom else chess.BLACK)
        return state.board.turn == mine

    def _request_hint(self) -> None:
        state = self._state
        if self.engine is None:
            return
        if state is None or not self._wants_hint(state):
            self.engine.cancel()
            if state is not None and state.board is not None and state.valid:
                self.window.show_waiting("Waiting for the opponent")
            return
        self.window.show_waiting("Thinking...")
        self.engine.request(state.board)

    def _on_hint(self, hint: Hint) -> None:
        state = self._state
        if state is None or state.board is None or state.board.fen() != hint.fen:
            return
        self.window.show_hint(hint)
        self._show_overlay_hint(hint, state)

    def _show_overlay_hint(self, hint: Hint, state: TrackerState) -> None:
        if not self._hints_enabled:
            self.overlay.clear_hint()
            return
        move = hint.move
        promo = None
        if move.promotion and move.promotion != chess.QUEEN:
            promo = chess.piece_symbol(move.promotion).upper()
        self.overlay.show_hint(OverlayHint(
            square_to_screen(move.from_square, state.white_bottom),
            square_to_screen(move.to_square, state.white_bottom),
            promo,
        ))

    # -- user actions ------------------------------------------------------

    def set_paused(self, paused: bool) -> None:
        self.pipeline.set_paused(paused)

    def calibrate(self) -> None:
        self.overlay.clear_hint()
        self.window.show_message("Calibrating...")
        if self._board_rect is not None:
            self._keep_panel_clear(self._board_rect)
        QTimer.singleShot(150, self.pipeline.request_calibration)

    def select_board(self) -> None:
        self._selector = RegionSelector(self.pipeline.monitors())
        self._selector.selected.connect(self._on_selected)
        self.window.showMinimized()
        QTimer.singleShot(250, self._selector.start)

    def _on_selected(self, rect: Rect | None) -> None:
        self._selector = None
        self.window.showNormal()
        if rect is not None:
            QTimer.singleShot(100, lambda: self._use_selection(rect))

    def _use_selection(self, rect: Rect) -> None:
        self._keep_panel_clear(rect)
        QTimer.singleShot(150, lambda: self.pipeline.set_manual_region(rect))

    def resync(self) -> None:
        self.window.show_message("Re-reading the position from the screen...")
        self.pipeline.request_resync()

    def flip(self) -> None:
        self.pipeline.flip_orientation()

    def toggle_hints(self) -> None:
        self.set_hints_enabled(not self._hints_enabled)
        self.window.set_hints_checked(self._hints_enabled)

    def set_hints_enabled(self, enabled: bool) -> None:
        self._hints_enabled = enabled
        if not enabled:
            self.overlay.clear_hint()
        else:
            self._request_hint()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self.window)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        old = self.settings
        self.settings = dlg.result_settings()
        self.settings.save()
        self.overlay.thickness = self.settings.thickness
        self.pipeline.set_fps(self.settings.capture_fps)
        self.pipeline.set_assumed_turn(ASSUMED_TURN.get(self.settings.hint_side))
        if self.settings.engine_path != old.engine_path or self.engine is None:
            if self.engine is not None:
                self.engine.shutdown()
                self.engine = None
            self._start_engine()
        elif self.engine is not None:
            self.engine.set_options(self._engine_options())
        self._request_hint()
