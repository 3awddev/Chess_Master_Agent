from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QPushButton, QSpinBox, QWidget,
)

from chessmaster.config import Settings

HINT_SIDE_LABELS = [
    ("Side at the bottom of the board", "auto"),
    ("White", "white"),
    ("Black", "black"),
    ("Both sides", "both"),
]


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ChessMaster settings")
        self._settings = settings
        form = QFormLayout(self)

        self.engine_path = QLineEdit(settings.engine_path)
        self.engine_path.setPlaceholderText("Bundled Stockfish")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.engine_path)
        row.addWidget(browse)
        form.addRow("Engine", row)

        self.think_time = QDoubleSpinBox()
        self.think_time.setRange(0.1, 30.0)
        self.think_time.setSingleStep(0.1)
        self.think_time.setSuffix(" s")
        self.think_time.setValue(settings.think_time)
        form.addRow("Think time per move", self.think_time)

        self.threads = QSpinBox()
        self.threads.setRange(1, os.cpu_count() or 1)
        self.threads.setValue(settings.threads)
        form.addRow("Engine threads", self.threads)

        self.hash_mb = QSpinBox()
        self.hash_mb.setRange(16, 8192)
        self.hash_mb.setSingleStep(64)
        self.hash_mb.setSuffix(" MB")
        self.hash_mb.setValue(settings.hash_mb)
        form.addRow("Engine hash", self.hash_mb)

        self.fps = QDoubleSpinBox()
        self.fps.setRange(2.0, 30.0)
        self.fps.setSuffix(" per second")
        self.fps.setValue(settings.capture_fps)
        form.addRow("Screen checks", self.fps)

        self.hint_side = QComboBox()
        for label, value in HINT_SIDE_LABELS:
            self.hint_side.addItem(label, value)
        self.hint_side.setCurrentIndex(max(0, self.hint_side.findData(settings.hint_side)))
        form.addRow("Show hints for", self.hint_side)

        self.thickness = QSpinBox()
        self.thickness.setRange(2, 8)
        self.thickness.setSuffix(" % of square")
        self.thickness.setValue(round(settings.thickness * 100))
        form.addRow("Rectangle thickness", self.thickness)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a UCI engine", "", "Executables (*.exe)")
        if path:
            self.engine_path.setText(path)

    def result_settings(self) -> Settings:
        return replace(
            self._settings,
            engine_path=self.engine_path.text().strip(),
            think_time=self.think_time.value(),
            threads=self.threads.value(),
            hash_mb=self.hash_mb.value(),
            capture_fps=self.fps.value(),
            hint_side=self.hint_side.currentData(),
            thickness=self.thickness.value() / 100,
        )
