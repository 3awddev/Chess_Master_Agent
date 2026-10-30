"""Turning a stream of recognized board images into a consistent chess game."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import chess
import numpy as np

from chessmaster.board_coords import label_piece, screen_labels, screen_to_square, square_labels
from chessmaster.vision.profile import PIECE_SYMBOLS, UNCERTAIN

log = logging.getLogger(__name__)

START_SCREEN = {wb: screen_labels(chess.Board(), wb) for wb in (True, False)}
WHITE_LABELS = set(range(1, 7))
BLACK_LABELS = set(range(7, 13))


@dataclass(frozen=True)
class TrackerState:
    board: chess.Board | None
    white_bottom: bool
    turn_certain: bool
    valid: bool
    last_move: chess.Move | None
    version: int


def board_labels(board: chess.BaseBoard) -> tuple[int, ...]:
    out = [0] * 64
    for sq, piece in board.piece_map().items():
        out[sq] = PIECE_SYMBOLS.index(piece.symbol()) + 1
    return tuple(out)


def matches(actual: tuple[int, ...], observed: tuple[int, ...]) -> bool:
    """Observed labels equal the actual board, treating uncertain squares as wildcards."""
    return all(o == UNCERTAIN or o == a for a, o in zip(actual, observed))


def _screen_matches(expected: np.ndarray, observed: np.ndarray) -> bool:
    return bool(np.all((observed == UNCERTAIN) | (observed == expected)))


class GameTracker:
    def __init__(self, white_bottom: bool = True, stable_frames: int = 3,
                 resync_delay: float = 1.0, max_uncertain: int = 6) -> None:
        self.stable_frames = stable_frames
        self.resync_delay = resync_delay
        self.max_uncertain = max_uncertain
        self.white_bottom = white_bottom
        self.assumed_turn: chess.Color | None = None
        """Side assumed to move when it cannot be inferred; None means the bottom side."""
        self.board: chess.Board | None = None
        self.turn_certain = False
        self.last_move: chess.Move | None = None
        self.version = 0
        self._cand_key: bytes | None = None
        self._cand_count = 0
        self._pending: tuple[bytes, float] | None = None
        self._force_resync = False

    # -- public API -------------------------------------------------------

    def state(self) -> TrackerState:
        board = self.board.copy(stack=False) if self.board is not None else None
        valid = board is not None and board.is_valid()
        return TrackerState(board, self.white_bottom, self.turn_certain, valid, self.last_move, self.version)

    def reset(self) -> None:
        self.board = None
        self.turn_certain = False
        self.last_move = None
        self._cand_key = None
        self._cand_count = 0
        self._pending = None
        self._changed()

    def request_resync(self) -> None:
        self._force_resync = True
        self._cand_count = 0

    def set_orientation(self, white_bottom: bool) -> None:
        if white_bottom != self.white_bottom:
            self.white_bottom = white_bottom
            self.request_resync()

    def update(self, labels: np.ndarray, highlighted: np.ndarray, now: float) -> bool:
        """Feed one recognized frame (screen order). Returns True when the game state changed."""
        key = labels.tobytes()
        if key != self._cand_key:
            self._cand_key = key
            self._cand_count = 1
        else:
            self._cand_count += 1

        if self._cand_count == self.stable_frames:
            if self._force_resync:
                self._force_resync = False
                if (labels == UNCERTAIN).sum() == 0:
                    return self._resync(labels, highlighted)
            return self._accept(labels, highlighted, now)

        if (self._pending is not None and self._pending[0] == key
                and self._cand_count > self.stable_frames and now - self._pending[1] >= self.resync_delay):
            self._pending = None
            return self._resync(labels, highlighted)
        return False

    # -- internals --------------------------------------------------------

    def _changed(self) -> bool:
        self.version += 1
        return True

    def _accept(self, labels: np.ndarray, highlighted: np.ndarray, now: float) -> bool:
        n_uncertain = int((labels == UNCERTAIN).sum())
        if n_uncertain > self.max_uncertain:
            return False

        if n_uncertain <= 2:
            for wb in (self.white_bottom, not self.white_bottom):
                if _screen_matches(START_SCREEN[wb], labels):
                    if (self.board is not None and wb == self.white_bottom
                            and board_labels(self.board) == board_labels(chess.Board())):
                        self._pending = None
                        return False
                    log.info("Starting position detected (white at %s)", "bottom" if wb else "top")
                    self.white_bottom = wb
                    self.board = chess.Board()
                    self.turn_certain = True
                    self.last_move = None
                    self._pending = None
                    return self._changed()

        placement = square_labels(labels, self.white_bottom)
        if self.board is not None:
            if matches(board_labels(self.board), placement):
                self._pending = None
                return False
            moves = self._infer(placement)
            if moves:
                board, seq = moves
                for m in seq:
                    log.info("Move detected: %s", board.san(m))
                    board.push(m)
                self.board = board
                self.turn_certain = True
                self.last_move = seq[-1]
                self._pending = None
                return self._changed()

        if n_uncertain:
            return False
        if self.board is None:
            return self._resync(labels, highlighted)
        self._pending = (labels.tobytes(), now)
        return False

    def _candidate_boards(self) -> list[chess.Board]:
        assert self.board is not None
        boards = [self.board.copy()]
        if not self.turn_certain:
            flipped = self.board.copy(stack=False)
            flipped.turn = not flipped.turn
            flipped.ep_square = None
            if not flipped.status() & chess.STATUS_OPPOSITE_CHECK:
                boards.append(flipped)
        return boards

    def _infer(self, placement: tuple[int, ...]) -> tuple[chess.Board, list[chess.Move]] | None:
        for depth in (1, 2):
            found: list[tuple[chess.Board, list[chess.Move]]] = []
            for board in self._candidate_boards():
                for seq in self._sequences(board, placement, depth):
                    found.append((board, seq))
            if found:
                return _pick(found)
        return None

    def _sequences(self, board: chess.Board, placement: tuple[int, ...], depth: int):
        for m1 in list(board.legal_moves):
            board.push(m1)
            if depth == 1:
                if matches(board_labels(board), placement):
                    yield [m1]
            else:
                for m2 in list(board.legal_moves):
                    board.push(m2)
                    if matches(board_labels(board), placement):
                        yield [m1, m2]
                    board.pop()
            board.pop()

    def _resync(self, labels: np.ndarray, highlighted: np.ndarray) -> bool:
        self._detect_orientation(labels)
        placement = square_labels(labels, self.white_bottom)
        board = chess.Board(None)
        for sq, label in enumerate(placement):
            piece = label_piece(label)
            if piece is not None:
                board.set_piece_at(sq, piece)

        hl = [screen_to_square(r, c, self.white_bottom) for r, c in zip(*np.nonzero(highlighted))]
        turn, certain = self._infer_turn(board, hl)
        board.turn = turn
        board.castling_rights = _castling_rights(board)
        board.ep_square = _ep_square(board, hl)
        if board.status() & chess.STATUS_OPPOSITE_CHECK:
            board.turn = not board.turn
            board.ep_square = None
            certain = True

        log.info("Resynced: %s (turn %s)", board.fen(), "certain" if certain else "assumed")
        self.board = board
        self.turn_certain = certain
        self.last_move = None
        return self._changed()

    def _detect_orientation(self, labels: np.ndarray) -> None:
        rows = np.indices((8, 8))[0]
        white = np.isin(labels, list(WHITE_LABELS))
        black = np.isin(labels, list(BLACK_LABELS))
        if not white.any() or not black.any():
            return
        score = rows[white].mean() - rows[black].mean()
        if score > 1.5:
            self.white_bottom = True
        elif score < -1.5:
            self.white_bottom = False

    def _infer_turn(self, board: chess.Board, highlighted: list[chess.Square]) -> tuple[chess.Color, bool]:
        if len(highlighted) == 2:
            occupied = [sq for sq in highlighted if board.piece_at(sq) is not None]
            if len(occupied) == 1:
                mover = board.piece_at(occupied[0]).color
                return (not mover), True
        in_check = []
        for color in (chess.WHITE, chess.BLACK):
            king = board.king(color)
            if king is not None and board.is_attacked_by(not color, king):
                in_check.append(color)
        if len(in_check) == 1:
            return in_check[0], True
        if self.assumed_turn is not None:
            return self.assumed_turn, False
        return (chess.WHITE if self.white_bottom else chess.BLACK), False


def _pick(found: list[tuple[chess.Board, list[chess.Move]]]) -> tuple[chess.Board, list[chess.Move]] | None:
    """The unique explanation, preferring queen promotion when only the promotion piece is unknown."""
    if len(found) == 1:
        return found[0]
    queen = [f for f in found if all(m.promotion in (None, chess.QUEEN) for m in f[1])]
    if len(queen) == 1:
        return queen[0]
    log.debug("Ambiguous move: %s", [[m.uci() for m in seq] for _, seq in found])
    return None


def _castling_rights(board: chess.Board) -> chess.Bitboard:
    rights = chess.BB_EMPTY
    for color, king_sq, rooks in ((chess.WHITE, chess.E1, (chess.A1, chess.H1)),
                                  (chess.BLACK, chess.E8, (chess.A8, chess.H8))):
        if board.piece_at(king_sq) == chess.Piece(chess.KING, color):
            for rook_sq in rooks:
                if board.piece_at(rook_sq) == chess.Piece(chess.ROOK, color):
                    rights |= chess.BB_SQUARES[rook_sq]
    return rights


def _ep_square(board: chess.Board, highlighted: list[chess.Square]) -> chess.Square | None:
    """En passant target when the highlighted last move was a two-square pawn push."""
    if len(highlighted) != 2:
        return None
    a, b = highlighted
    for frm, to in ((a, b), (b, a)):
        piece = board.piece_at(to)
        if (piece is not None and piece.piece_type == chess.PAWN and piece.color != board.turn
                and board.piece_at(frm) is None and abs(to - frm) == 16
                and chess.square_file(to) == chess.square_file(frm)):
            return (to + frm) // 2
    return None
