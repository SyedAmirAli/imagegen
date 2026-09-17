"""ImageGen Desktop GUI — entry point."""
from __future__ import annotations
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `imagegen` and `gui` are importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from gui.windows.main_window import MainWindow


def main() -> int:
    # Enable High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("ImageGen Desktop GUI")
    app.setOrganizationName("ImageGen")
    
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] == "imagegen":
        from imagegen.cli import main as cli_main
        sys.exit(cli_main(sys.argv[3:]))
    sys.exit(main())
