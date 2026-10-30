import threading
from pathlib import Path

import chess
import pytest
from PySide6.QtCore import Qt

from chessmaster.engine.stockfish import EngineOptions, EngineWorker

ENGINE = Path(__file__).resolve().parents[1] / "engine" / "stockfish.exe"

pytestmark = pytest.mark.skipif(not ENGINE.exists(), reason="Stockfish not downloaded")


def _collect(worker: EngineWorker):
    hints = []
    done = threading.Event()

    def on_hint(h):
        hints.append(h)
        done.set()

    worker.hintReady.connect(on_hint, Qt.ConnectionType.DirectConnection)
    return hints, done


def test_finds_mate_in_one():
    worker = EngineWorker(str(ENGINE), EngineOptions(threads=1, hash_mb=16, think_time=0.3))
    hints, done = _collect(worker)
    worker.start()
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    worker.request(board)
    assert done.wait(10)
    worker.shutdown()
    assert hints[0].move == chess.Move.from_uci("a1a8")
    assert hints[0].score == "#1"
    assert hints[0].fen == board.fen()


def test_superseded_request_is_dropped():
    worker = EngineWorker(str(ENGINE), EngineOptions(threads=1, hash_mb=16, think_time=1.0))
    hints, done = _collect(worker)
    worker.start()
    first = chess.Board()
    second = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    worker.request(first)
    worker.request(second)
    assert done.wait(10)
    worker.shutdown()
    assert [h.fen for h in hints] == [second.fen()]
