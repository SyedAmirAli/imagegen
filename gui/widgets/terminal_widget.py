from __future__ import annotations
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QLineEdit, QPushButton, QLabel, QApplication)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor, QColor, QPalette
from ..utils.formatting import strip_ansi

class TerminalWidget(QWidget):
    manual_command_entered = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        self.toolbar_layout = QHBoxLayout()
        self.title_label = QLabel("Terminal Output")
        self.title_label.setStyleSheet("color: #9CDCFE; font-weight: bold;")
        self.toolbar_layout.addWidget(self.title_label)
        self.toolbar_layout.addStretch()
        
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        self.toolbar_layout.addWidget(self.clear_btn)
        
        self.copy_btn = QPushButton("Copy All")
        self.copy_btn.clicked.connect(self._copy_all)
        self.toolbar_layout.addWidget(self.copy_btn)
        
        self.layout.addLayout(self.toolbar_layout)
        
        # Output Text Edit
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet("background-color: #1E1E1E; color: #D4D4D4;")
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.output_edit.setFont(font)
        self.layout.addWidget(self.output_edit, stretch=1)
        
        # Input Area
        self.input_layout = QHBoxLayout()
        self.prompt_label = QLabel("$")
        self.prompt_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.input_layout.addWidget(self.prompt_label)
        
        self.input_edit = QLineEdit()
        self.input_edit.setFont(font)
        self.input_edit.setStyleSheet("background-color: #1E1E1E; color: #D4D4D4; border: 1px solid #555;")
        self.input_edit.returnPressed.connect(self._on_return_pressed)
        self.input_layout.addWidget(self.input_edit)
        
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._on_return_pressed)
        self.input_layout.addWidget(self.run_btn)
        
        self.layout.addLayout(self.input_layout)

    def append_text(self, text: str) -> None:
        clean_text = strip_ansi(text)
        cursor = self.output_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(clean_text)
        self.output_edit.setTextCursor(cursor)
        self.output_edit.ensureCursorVisible()

    def append_command(self, cmd: str) -> None:
        html = f'<span style="color: #4CAF50;">&gt; {cmd}</span><br>'
        cursor = self.output_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html)
        self.output_edit.setTextCursor(cursor)
        self.output_edit.ensureCursorVisible()

    def clear(self) -> None:
        self.output_edit.clear()

    def set_input_enabled(self, enabled: bool) -> None:
        self.input_edit.setEnabled(enabled)
        self.run_btn.setEnabled(enabled)

    def _copy_all(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.output_edit.toPlainText())

    def _on_return_pressed(self) -> None:
        cmd = self.input_edit.text().strip()
        if cmd:
            self.input_edit.clear()
            self.manual_command_entered.emit(cmd)
