import chess
import numpy as np
import pytest

from chessmaster.board_coords import screen_labels, square_to_screen
from chessmaster.game.tracker import GameTracker
from chessmaster.vision.profile import UNCERTAIN

NO_HIGHLIGHT = np.zeros((8, 8), bool)


class Feeder:
    def __init__(self, tracker: GameTracker, white_bottom: bool = True) -> None:
        self.tracker = tracker
        self.white_bottom = white_bottom
        self.now = 0.0

    def show(self, board: chess.BaseBoard, frames: int = 3, highlighted=NO_HIGHLIGHT,
             uncertain: list[chess.Square] = ()) -> bool:
        labels = screen_labels(board, self.white_bottom)
        for sq in uncertain:
            labels[square_to_screen(sq, self.white_bottom)] = UNCERTAIN
        changed = False
        for _ in range(frames):
            self.now += 0.1
            changed |= self.tracker.update(labels, highlighted, self.now)
        return changed


def play(board: chess.Board, *sans: str) -> chess.Board:
    for san in sans:
        board.push_san(san)
    return board


@pytest.fixture
def feeder():
    return Feeder(GameTracker())


def test_new_game_then_moves(feeder):
    assert feeder.show(chess.Board())
    assert feeder.tracker.board.fen() == chess.STARTING_FEN
    truth = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6"):
        truth.push_san(san)
        assert feeder.show(truth)
    assert feeder.tracker.board.fen() == truth.fen()
    assert feeder.tracker.turn_certain


def test_unstable_frames_are_ignored(feeder):
    feeder.show(chess.Board())
    v = feeder.tracker.version
    assert not feeder.show(play(chess.Board(), "e4"), frames=2)
    assert feeder.tracker.version == v


@pytest.mark.parametrize("moves", [
    ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"],
    ["d4", "d5", "Nc3", "Nc6", "Bf4", "Bf5", "Qd2", "Qd7", "O-O-O"],
    ["e4", "a6", "e5", "d5", "exd6"],
    ["h4", "g5", "hxg5", "a6", "g6", "a5", "gxh7", "a4", "hxg8=Q"],
    ["h4", "g5", "hxg5", "a6", "g6", "a5", "gxh7", "a4", "hxg8=N"],
])
def test_special_moves(feeder, moves):
    feeder.show(chess.Board())
    truth = chess.Board()
    for san in moves:
        truth.push_san(san)
        feeder.show(truth)
    assert feeder.tracker.board.fen() == truth.fen()


def test_premove_pair_is_inferred(feeder):
    feeder.show(chess.Board())
    truth = play(chess.Board(), "e4", "e5")
    feeder.show(truth)
    assert feeder.tracker.board.fen() == truth.fen()
    assert len(feeder.tracker.board.move_stack) == 2


def test_uncertain_squares_are_wildcards(feeder):
    feeder.show(chess.Board())
    truth = play(chess.Board(), "e4")
    feeder.show(truth, uncertain=[chess.A2, chess.H7])
    assert feeder.tracker.board.fen() == truth.fen()


def test_black_at_bottom_new_game():
    tracker = GameTracker(white_bottom=True)
    feeder = Feeder(tracker, white_bottom=False)
    feeder.show(chess.Board())
    assert tracker.white_bottom is False
    truth = play(chess.Board(), "d4")
    feeder.show(truth)
    assert tracker.board.fen() == truth.fen()


def test_midgame_pickup_uses_last_move_highlight(feeder):
    truth = play(chess.Board(), "e4", "c5", "Nf3")
    highlighted = np.zeros((8, 8), bool)
    for sq in (chess.G1, chess.F3):
        highlighted[square_to_screen(sq, True)] = True
    assert feeder.show(truth, highlighted=highlighted)
    board = feeder.tracker.board
    assert board.turn == chess.BLACK and feeder.tracker.turn_certain
    assert board.castling_rights == truth.castling_rights


def test_midgame_pickup_sets_en_passant(feeder):
    truth = play(chess.Board(), "e4", "a6", "e5", "d5")
    highlighted = np.zeros((8, 8), bool)
    for sq in (chess.D7, chess.D5):
        highlighted[square_to_screen(sq, True)] = True
    feeder.show(truth, highlighted=highlighted)
    assert feeder.tracker.board.ep_square == chess.D6
    assert chess.Move.from_uci("e5d6") in feeder.tracker.board.legal_moves


def test_midgame_pickup_check_decides_turn(feeder):
    truth = play(chess.Board(), "e4", "f5", "Qh5+")
    feeder.show(truth)
    assert feeder.tracker.board.turn == chess.BLACK and feeder.tracker.turn_certain


def test_unknown_turn_accepts_either_color(feeder):
    truth = play(chess.Board(), "e4", "e5", "Nf3")
    feeder.show(truth)
    assert feeder.tracker.board.turn == chess.WHITE and not feeder.tracker.turn_certain
    truth.push_san("Nc6")
    feeder.show(truth)
    assert feeder.tracker.board.board_fen() == truth.board_fen()
    assert feeder.tracker.board.turn == chess.WHITE and feeder.tracker.turn_certain


def test_unexplained_change_resyncs_after_delay(feeder):
    feeder.show(chess.Board())
    jumped = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    feeder.show(jumped, frames=3)
    assert feeder.tracker.board.fen() == chess.STARTING_FEN
    feeder.show(jumped, frames=12)
    assert feeder.tracker.board.board_fen() == jumped.board_fen()


def test_return_to_start_is_new_game(feeder):
    feeder.show(chess.Board())
    feeder.show(play(chess.Board(), "e4"))
    assert feeder.show(chess.Board())
    assert feeder.tracker.board.fen() == chess.STARTING_FEN
