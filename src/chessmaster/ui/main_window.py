"""The control panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import chess
import chess.svg
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QCloseEvent
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from chessmaster.engine.stockfish import Hint
from chessmaster.game.tracker import TrackerState
from chessmaster.pipeline import PipelineStatus

if TYPE_CHECKING:
    from chessmaster.app import AppController

PREVIEW_PX = 260


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._c = controller
        self.setWindowTitle("ChessMaster")
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        root.addLayout(top)
        self.preview = QSvgWidget()
        self.preview.setFixedSize(PREVIEW_PX, PREVIEW_PX)
        top.addWidget(self.preview)

        info = QFormLayout()
        top.addLayout(info)
        self.lbl_board = QLabel("Searching...")
        self.lbl_profile = QLabel("-")
        self.lbl_game = QLabel("-")
        self.lbl_turn = QLabel("-")
        self.lbl_move = QLabel("-")
        self.lbl_move.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.lbl_eval = QLabel("-")
        for name, label in (("Board", self.lbl_board), ("Profile", self.lbl_profile), ("Game", self.lbl_game),
                            ("To move", self.lbl_turn), ("Best move", self.lbl_move), ("Evaluation", self.lbl_eval)):
            info.addRow(name + ":", label)

        buttons = QGridLayout()
        root.addLayout(buttons)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_calibrate = QPushButton("Calibrate")
        self.btn_calibrate.setToolTip("Show a board in the starting position, then click.")
        self.btn_calibrate.clicked.connect(controller.calibrate)
        self.btn_select = QPushButton("Select board")
        self.btn_select.setToolTip("Drag a rectangle around the board if it is not found automatically.")
        self.btn_select.clicked.connect(controller.select_board)
        self.btn_resync = QPushButton("Resync")
        self.btn_resync.setToolTip("Re-read the position from the screen (Ctrl+Alt+R).")
        self.btn_resync.clicked.connect(controller.resync)
        self.btn_flip = QPushButton("Flip board")
        self.btn_flip.setToolTip("Use when White/Black at the bottom was detected wrongly.")
        self.btn_flip.clicked.connect(controller.flip)
        self.btn_settings = QPushButton("Settings...")
        self.btn_settings.clicked.connect(controller.open_settings)
        for i, b in enumerate((self.btn_pause, self.btn_calibrate, self.btn_select,
                               self.btn_resync, self.btn_flip, self.btn_settings)):
            buttons.addWidget(b, i // 3, i % 3)

        self.chk_hints = QCheckBox("Show move hints on the board (Ctrl+Alt+H)")
        self.chk_hints.setChecked(True)
        self.chk_hints.toggled.connect(controller.set_hints_enabled)
        root.addWidget(self.chk_hints)

        self.lbl_message = QLabel(
            "First time with a board style: open a board in the starting position and click Calibrate."
        )
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setStyleSheet("color: #555;")
        root.addWidget(self.lbl_message)

        self._state: TrackerState | None = None
        self._hint: Hint | None = None
        self._render_preview()

    def _on_pause(self, paused: bool) -> None:
        self.btn_pause.setText("Resume" if paused else "Pause")
        self._c.set_paused(paused)

    def set_hints_checked(self, enabled: bool) -> None:
        self.chk_hints.blockSignals(True)
        self.chk_hints.setChecked(enabled)
        self.chk_hints.blockSignals(False)

    def show_message(self, text: str) -> None:
        self.lbl_message.setText(text)

    def show_status(self, st: PipelineStatus) -> None:
        if st.paused:
            self.lbl_board.setText("Paused")
        elif st.board_rect is None:
            self.lbl_board.setText("Searching the screen...")
        else:
            r = st.board_rect
            extra = f", {st.uncertain} unclear square(s)" if st.uncertain else ""
            self.lbl_board.setText(f"Found at ({r.x}, {r.y}), {r.w} px{extra}")
        if st.profile_name:
            self.lbl_profile.setText(st.profile_name)
        elif st.needs_calibration:
            self.lbl_profile.setText("Not calibrated - show the start position and click Calibrate")
        else:
            self.lbl_profile.setText("-")

    def show_state(self, state: TrackerState | None) -> None:
        self._state = state
        self._hint = None
        self.lbl_move.setText("-")
        self.lbl_eval.setText("-")
        if state is None or state.board is None:
            self.lbl_game.setText("-")
            self.lbl_turn.setText("-")
        else:
            board = state.board
            if not state.valid:
                self.lbl_game.setText("Position not legal (check recognition)")
            elif board.is_game_over():
                self.lbl_game.setText(f"Game over: {board.result()}")
            else:
                last = state.last_move.uci() if state.last_move else "none"
                self.lbl_game.setText(f"Tracking (last move {last})")
            turn = "White" if board.turn == chess.WHITE else "Black"
            self.lbl_turn.setText(turn if state.turn_certain else f"{turn} (assumed)")
        self._render_preview()

    def show_hint(self, hint: Hint | None) -> None:
        self._hint = hint
        if hint is not None:
            self.lbl_move.setText(hint.san)
            self.lbl_eval.setText(f"{hint.score} (depth {hint.depth})")
        self._render_preview()

    def show_waiting(self, text: str) -> None:
        self.lbl_move.setText(text)

    def _render_preview(self) -> None:
        state = self._state
        board = state.board if state is not None and state.board is not None else chess.Board(None)
        orientation = chess.WHITE if state is None or state.white_bottom else chess.BLACK
        arrows = []
        if self._hint is not None:
            arrows.append(chess.svg.Arrow(self._hint.move.from_square, self._hint.move.to_square, color="#20c040cc"))
        svg = chess.svg.board(
            board, size=PREVIEW_PX, orientation=orientation, coordinates=False,
            lastmove=state.last_move if state is not None else None, arrows=arrows,
        )
        self.preview.load(QByteArray(svg.encode()))

    def closeEvent(self, e: QCloseEvent) -> None:
        self._c.shutdown()
        super().closeEvent(e)
