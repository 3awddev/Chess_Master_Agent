"""Board location, calibration and recognition on synthetic and real screenshots."""

from __future__ import annotations

import json
import random
from pathlib import Path

import chess
import cv2
import numpy as np
import pytest

from synth import THEMES, cluttered_desktop, paste, random_game_board, render_board

from chessmaster.board_coords import screen_labels
from chessmaster.common import Rect
from chessmaster.vision.board_locator import board_from_selection, locate_boards, refine_board
from chessmaster.vision.calibration import CalibrationError, calibrate
from chessmaster.vision.classifier import SquareClassifier
from chessmaster.pipeline import BUILTIN_PROFILES
from chessmaster.vision.profile import UNCERTAIN, load_profiles, match_profile
from chessmaster.vision.squares import checkerboard_score, split_squares, square_backgrounds

FIXTURES = Path(__file__).parent / "fixtures"


def _crop(img: np.ndarray, r: Rect) -> np.ndarray:
    return img[r.y:r.bottom, r.x:r.right]


def _assert_rect_close(found: Rect, expected: Rect, tol: int = 2) -> None:
    assert abs(found.x - expected.x) <= tol, (found, expected)
    assert abs(found.y - expected.y) <= tol, (found, expected)
    assert abs(found.right - expected.right) <= tol, (found, expected)
    assert abs(found.bottom - expected.bottom) <= tol, (found, expected)


def _wrong(rec, board: chess.BaseBoard, white_bottom: bool) -> int:
    return int((rec.labels != screen_labels(board, white_bottom)).sum())


@pytest.mark.parametrize(
    "seed,size,coordinates,orientation,theme",
    [
        (1, 400, False, chess.WHITE, 0),
        (2, 520, True, chess.BLACK, 1),
        (3, 640, True, chess.WHITE, 2),
        (4, 300, False, chess.BLACK, 3),
    ],
)
def test_locate_board_on_cluttered_desktop(seed, size, coordinates, orientation, theme):
    rng = random.Random(seed)
    board, last = random_game_board(rng, 20)
    img, inner = render_board(board, size, orientation, coordinates, lastmove=last, colors=THEMES[theme])
    x, y = rng.randint(0, 1920 - size), rng.randint(0, 1080 - size)
    desktop = paste(cluttered_desktop(1920, 1080, seed), img, x, y)

    found = locate_boards(desktop)
    assert found, "board not found"
    _assert_rect_close(found[0].rect, inner.translated(x, y))

    refined = refine_board(desktop, found[0].rect.translated(3, -2))
    assert refined is not None
    _assert_rect_close(refined.rect, inner.translated(x, y))


def test_board_from_rough_selection():
    img, inner = render_board(chess.Board(), 480, coordinates=True, colors=THEMES[1])
    desktop = paste(cluttered_desktop(1280, 800, 7), img, 300, 150)
    selection = inner.translated(300, 150).expanded(25)
    found = board_from_selection(desktop, selection)
    assert found is not None
    _assert_rect_close(found.rect, inner.translated(300, 150))


@pytest.mark.parametrize("orientation", [chess.WHITE, chess.BLACK])
@pytest.mark.parametrize("coordinates", [False, True])
def test_calibration_orientation(orientation, coordinates):
    img, inner = render_board(chess.Board(), 480, orientation, coordinates, colors=THEMES[2])
    profile = calibrate(_crop(img, inner), "green")
    assert profile.white_bottom == (orientation == chess.WHITE)


def test_calibration_rejects_non_start_position():
    board, _ = random_game_board(random.Random(5), 12)
    img, inner = render_board(board, 480)
    with pytest.raises(CalibrationError):
        calibrate(_crop(img, inner), "bad")


@pytest.mark.parametrize("theme", range(len(THEMES)))
@pytest.mark.parametrize("orientation", [chess.WHITE, chess.BLACK])
def test_classify_random_positions(theme, orientation):
    calib_img, calib_inner = render_board(chess.Board(), 480, orientation, True, colors=THEMES[theme])
    profile = calibrate(_crop(calib_img, calib_inner), "t")
    classifier = SquareClassifier(profile)
    white_bottom = orientation == chess.WHITE

    rng = random.Random(theme * 10 + int(orientation))
    for i, scale in enumerate([0.8, 0.9, 1.0, 1.1, 1.25]):
        board, last = random_game_board(rng, rng.randint(10, 60))
        check = board.king(board.turn) if board.is_check() else None
        img, inner = render_board(board, int(480 * scale), orientation, True,
                                  lastmove=last, check=check, colors=THEMES[theme])
        rec = classifier.classify(_crop(img, inner))
        assert _wrong(rec, board, white_bottom) == 0, (i, scale, board.fen())


def test_highlights_detected():
    board = chess.Board()
    board.push_san("e4")
    img, inner = render_board(board, 480, lastmove=board.peek(), colors=THEMES[2])
    profile = calibrate(_crop(render_board(chess.Board(), 480, colors=THEMES[2])[0], inner), "g")
    rec = SquareClassifier(profile).classify(_crop(img, inner))
    assert _wrong(rec, board, True) == 0
    assert set(zip(*np.nonzero(rec.highlighted))) == {(6, 4), (4, 4)}


def test_overlay_outlines_do_not_change_recognition():
    """The hint overlay draws in each square's outer band, which must not affect recognition."""
    rng = random.Random(11)
    calib_img, inner = render_board(chess.Board(), 480, colors=THEMES[1])
    classifier = SquareClassifier(calibrate(_crop(calib_img, inner), "b"))
    for _ in range(5):
        board, last = random_game_board(rng, rng.randint(8, 40))
        img, inner = render_board(board, 480, lastmove=last, colors=THEMES[1])
        crop = _crop(img, inner).copy()
        sq = crop.shape[0] / 8
        pw = max(1, int(round(0.06 * sq)))
        for (row, col), color in (((rng.randrange(8), rng.randrange(8)), (0, 0, 255)),
                                  ((rng.randrange(8), rng.randrange(8)), (0, 200, 0))):
            x0, y0 = int(round(col * sq)), int(round(row * sq))
            x1, y1 = int(round((col + 1) * sq)) - 1, int(round((row + 1) * sq)) - 1
            for k in range(pw):
                cv2.rectangle(crop, (x0 + k, y0 + k), (x1 - k, y1 - k), color, 1)
        plain = classifier.classify(_crop(img, inner))
        drawn = classifier.classify(crop)
        assert _wrong(drawn, board, True) == 0
        assert (drawn.labels == plain.labels).all()


def _fixtures() -> list[dict]:
    manifest = FIXTURES / "manifest.json"
    return json.loads(manifest.read_text()) if manifest.exists() else []


@pytest.mark.parametrize("item", _fixtures(), ids=lambda f: f["file"])
def test_real_site_locate(item):
    img = cv2.imread(str(FIXTURES / item["file"]))
    found = locate_boards(img)
    assert found
    _assert_rect_close(found[0].rect, Rect(*item["board"]))


@pytest.mark.parametrize("item", _fixtures(), ids=lambda f: f["file"])
def test_builtin_profiles(item):
    profiles = load_profiles(BUILTIN_PROFILES)
    assert profiles
    img = cv2.imread(str(FIXTURES / item["file"]))
    board_img = _crop(img, Rect(*item["board"]))
    _, light, dark = checkerboard_score(square_backgrounds(split_squares(board_img)))
    profile = match_profile(profiles, light, dark)
    if item["site"] != "lichess":
        assert profile is None
        return
    assert profile is not None
    rec = SquareClassifier(profile).classify(board_img)
    assert _wrong(rec, chess.Board(item["fen"]), item["white_bottom"]) == 0


@pytest.mark.parametrize("site", sorted({f["site"] for f in _fixtures()}))
def test_real_site_recognition(site):
    items = [f for f in _fixtures() if f["site"] == site]
    start = next((f for f in items if f["fen"] == chess.STARTING_FEN), None)
    if start is None:
        pytest.skip(f"no starting-position fixture for {site}")
    img = cv2.imread(str(FIXTURES / start["file"]))
    classifier = SquareClassifier(calibrate(_crop(img, Rect(*start["board"])), site))
    for item in items:
        img = cv2.imread(str(FIXTURES / item["file"]))
        rec = classifier.classify(_crop(img, Rect(*item["board"])))
        assert rec.uncertain_count == 0, item["file"]
        assert _wrong(rec, chess.Board(item["fen"]), item["white_bottom"]) == 0, item["file"]
        assert (rec.labels != UNCERTAIN).all()
