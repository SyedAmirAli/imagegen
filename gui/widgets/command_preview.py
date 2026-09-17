from __future__ import annotations
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QApplication
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from ..utils.formatting import strip_ansi

class CommandPreviewWidget(QWidget):
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.header_layout = QHBoxLayout()
        self.label = QLabel("Generated Command:")
        self.label.setStyleSheet("color: #9CDCFE; font-weight: bold;")
        self.header_layout.addWidget(self.label)
        self.header_layout.addStretch()
        
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        self.header_layout.addWidget(self.reset_btn)
        
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self._copy_command)
        self.header_layout.addWidget(self.copy_btn)
        
        self.layout.addLayout(self.header_layout)
        
        self.command_edit = QLineEdit()
        self.command_edit.setReadOnly(True)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.command_edit.setFont(font)
        self.command_edit.setStyleSheet("background-color: #1E1E1E; color: #D4D4D4; border: 1px solid #555; padding: 4px;")
        self.layout.addWidget(self.command_edit)

    def set_command(self, cmd: str) -> None:
        self.command_edit.setText(cmd)
        self.command_edit.setCursorPosition(0)

    def get_command(self) -> str:
        return self.command_edit.text()

    def _copy_command(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.get_command())
            self.copy_btn.setText("Copied!")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy"))
