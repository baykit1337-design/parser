"""
Точка входа для запуска GUI приложения
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow


def run_gui():
    """Запуск графического интерфейса"""
    app = QApplication(sys.argv)
    app.setApplicationName("RanobeLIB Downloader")
    app.setOrganizationName("RanobeLIB")

    app.setStyle("Fusion")

    dark_palette = QPalette()

    bg_color = QColor(0, 0, 0)
    disabled_color = QColor(64, 64, 64)
    text_color = QColor(224, 224, 224)
    blue_color = QColor(0, 112, 255)

    dark_palette.setColor(QPalette.ColorRole.Window, bg_color)
    dark_palette.setColor(QPalette.ColorRole.WindowText, text_color)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(10, 10, 10))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(15, 15, 15))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(10, 10, 10))
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, text_color)
    dark_palette.setColor(QPalette.ColorRole.Text, text_color)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(17, 17, 17))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, blue_color)
    dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 64))
    dark_palette.setColor(QPalette.ColorRole.Link, blue_color)
    dark_palette.setColor(QPalette.ColorRole.Highlight, blue_color)
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)

    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_color)
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_color)
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_color)

    app.setPalette(dark_palette)

    main_window = MainWindow()
    main_window.show()

    return app.exec() 