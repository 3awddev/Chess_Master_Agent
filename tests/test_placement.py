from chessmaster.common import Rect
from chessmaster.ui.placement import panel_position

SCREEN = Rect(0, 0, 1920, 1080)


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def test_no_move_when_clear():
    assert panel_position(Rect(1400, 20, 500, 500), Rect(300, 200, 640, 640), SCREEN) is None


def test_moves_right_of_board():
    pos = panel_position(Rect(400, 100, 560, 520), Rect(607, 233, 640, 640), SCREEN)
    assert pos == Rect(1259, 233, 560, 520)


def test_moves_left_when_board_is_on_the_right():
    board = Rect(1100, 200, 760, 760)
    pos = panel_position(Rect(1200, 300, 560, 520), board, SCREEN)
    assert pos is not None and not _overlaps(pos, board)
    assert pos.right <= board.x


def test_huge_board_picks_least_overlap_corner():
    board = Rect(100, 20, 1040, 1040)
    pos = panel_position(Rect(300, 300, 560, 520), board, SCREEN)
    assert pos is not None and not _overlaps(pos, board)
    assert pos.x >= SCREEN.x and pos.right <= SCREEN.right
