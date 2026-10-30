from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from chessmaster.config import APP_NAME, log_path


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def main() -> int:
    _setup_logging()
    from chessmaster.app import AppController

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    controller = AppController(app)
    controller.start()
    code = app.exec()
    controller.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
