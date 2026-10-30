"""Smoke tests for the widgets, run on Qt's offscreen platform."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from chessmaster.common import Rect
from chessmaster.config import Settings
from chessmaster.ui.overlay import HintOverlay, OverlayHint
from chessmaster.ui.region_selector import RegionSelector
from chessmaster.ui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_settings_dialog_round_trip(app):
    dialog = SettingsDialog(Settings(think_time=2.5, hint_side="black", thickness=0.05))
    assert dialog.result_settings().hint_side == "black"
    dialog.think_time.setValue(0.5)
    dialog.hint_side.setCurrentIndex(dialog.hint_side.findData("both"))
    result = dialog.result_settings()
    assert result.think_time == pytest.approx(0.5)
    assert result.hint_side == "both"
    assert result.thickness == pytest.approx(0.05)


def test_overlay_paints_only_in_square_edge_band(app):
    overlay = HintOverlay(thickness=0.06)
    overlay.resize(480, 480)
    overlay.show_hint(OverlayHint(from_cell=(6, 4), to_cell=(4, 4)))
    image = overlay.grab().toImage()
    sq = 60

    def pixel(x: int, y: int) -> QColor:
        return image.pixelColor(x, y)

    edge_from = pixel(4 * sq + 1, 6 * sq + sq // 2)
    edge_to = pixel(4 * sq + sq // 2, 4 * sq + 1)
    assert edge_from.red() > 200 and edge_from.green() < 80
    assert edge_to.green() > 150 and edge_to.red() < 80
    band = 4 * sq // 48
    for cx, cy in ((4 * sq + band + 1, 6 * sq + band + 1), (4 * sq + sq // 2, 4 * sq + sq // 2)):
        c = pixel(cx, cy)
        assert not (c.red() > 200 and c.green() < 80) and not (c.green() > 150 and c.red() < 80)
    overlay.deleteLater()


def test_region_selector_constructs(app):
    selector = RegionSelector([Rect(0, 0, 1920, 1080)])
    assert selector is not None
