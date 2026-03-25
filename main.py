#!/usr/bin/env python3
"""Entry point for qooop 3D File Viewer."""

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor

from viewer.ui.main_window import MainWindow


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> int:
    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("qooop 3D File Viewer")
    app.setOrganizationName("qooop")

    # Force dark palette as baseline
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(30, 30, 40))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(200, 200, 210))
    palette.setColor(QPalette.ColorRole.Base,            QColor(22, 22, 32))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(35, 35, 48))
    palette.setColor(QPalette.ColorRole.Text,            QColor(200, 200, 210))
    palette.setColor(QPalette.ColorRole.Button,          QColor(40, 40, 55))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(200, 200, 210))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(60, 100, 180))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    win = MainWindow()
    win.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
