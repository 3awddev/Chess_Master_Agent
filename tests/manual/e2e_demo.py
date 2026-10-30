"""End-to-end check on the real desktop.

Shows a fake chess site (a board window), starts ChessMaster against it, calibrates,
then plays: White follows ChessMaster's hint, Black plays random moves. Screenshots
of the board with the overlay are written to tests/output/.

Run:  .venv\\Scripts\\python.exe tests\\manual\\e2e_demo.py
"""

from __future__ import annotations

import logging
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="chessmaster-e2e-")

import chess
import chess.svg
import cv2
import mss
import numpy as np
from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QApplication

from chessmaster.app import AppController
from chessmaster.platform import win32

OUT = Path(__file__).resolve().parents[1] / "output"
OUT.mkdir(exist_ok=True)
log = logging.getLogger("e2e")


class FakeSite(QSvgWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fake chess site")
        self.board = chess.Board()
        self.last: chess.Move | None = None
        self.setFixedSize(520, 520)
        self.render_board()

    def render_board(self) -> None:
        check = self.board.king(self.board.turn) if self.board.is_check() else None
        svg = chess.svg.board(self.board, size=520, lastmove=self.last, check=check,
                              colors={"square light": "#eeeed2", "square dark": "#769656",
                                      "square light lastmove": "#f6f669", "square dark lastmove": "#baca2b"})
        self.load(QByteArray(svg.encode()))

    def play(self, move: chess.Move) -> None:
        log.info("Fake site plays %s", self.board.san(move))
        self.board.push(move)
        self.last = move
        self.render_board()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    site = FakeSite()
    site.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    site.move(80, 80)
    site.show()
    site.raise_()
    controller = AppController(app)
    controller.start()
    controller.window.move(800, 80)
    rng = random.Random(7)
    shots = {"n": 0}
    results = {"hints_followed": 0, "errors": []}

    def screenshot(tag: str) -> None:
        rect = win32.get_window_rect(int(site.winId()))
        with mss.MSS() as sct:
            img = np.ascontiguousarray(
                np.asarray(sct.grab({"left": rect.x, "top": rect.y, "width": rect.w, "height": rect.h}))[:, :, :3])
        shots["n"] += 1
        cv2.imwrite(str(OUT / f"e2e_{shots['n']:02d}_{tag}.png"), img)

    def step() -> None:
        b = site.board
        if b.is_game_over() or len(b.move_stack) >= 16:
            finish()
            return
        if b.turn == chess.WHITE:
            hint = controller.overlay.hint
            state = controller._state
            if hint is None or state is None or state.board is None or state.board.fen() != b.fen():
                QTimer.singleShot(300, step)
                return
            move = next((m for m in b.legal_moves
                         if (m.from_square, m.to_square) == _cells_to_squares(hint)), None)
            if move is None:
                results["errors"].append(f"hint not legal: {hint} in {b.fen()}")
                finish()
                return
            screenshot(f"hint_{b.san(move)}")
            results["hints_followed"] += 1
            site.play(move)
        else:
            site.play(rng.choice(list(b.legal_moves)))
        QTimer.singleShot(1200, step)

    def _cells_to_squares(hint):
        from chessmaster.board_coords import screen_to_square
        return (screen_to_square(*hint.from_cell, True), screen_to_square(*hint.to_cell, True))

    def finish() -> None:
        log.info("RESULT hints_followed=%d errors=%s final=%s",
                 results["hints_followed"], results["errors"], site.board.fen())
        controller.shutdown()
        app.quit()

    def on_calibrated(ok: bool, text: str) -> None:
        log.info("Calibration: %s %s", ok, text)
        if not ok:
            results["errors"].append(text)
            finish()
            return
        QTimer.singleShot(1500, step)

    controller.pipeline.calibrationFinished.connect(on_calibrated)
    QTimer.singleShot(3000, controller.calibrate)
    QTimer.singleShot(120_000, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
