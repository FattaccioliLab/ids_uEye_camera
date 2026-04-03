"""
main.py — Entry point.
Usage: python main.py
"""

import sys
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("IDS Camera Acquisition")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
