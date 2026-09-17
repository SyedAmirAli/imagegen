from __future__ import annotations
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, 
    QListWidgetItem, QPushButton, QLabel, QMenu, QDialog, QPlainTextEdit, QApplication)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
from ..models.history_entry import HistoryEntry
from ..services.history_service import HistoryService
from ..utils.formatting import duration_str, timestamp_str

class HistoryWidget(QWidget):
    run_again_requested = Signal(object)  # emits HistoryEntry
    load_settings_requested = Signal(HistoryEntry)

    def __init__(self, history_service: HistoryService, parent: QWidget | None = None):
        super().__init__(parent)
        self._history_service = history_service
        self._history_service.on_change(self.refresh)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        self.header_layout = QHBoxLayout()
        self.title_label = QLabel("Command History")
        self.title_label.setStyleSheet("color: #9CDCFE; font-weight: bold;")
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()
        
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._history_service.clear_all)
        self.header_layout.addWidget(self.clear_btn)
        
        self.layout.addLayout(self.header_layout)
        
        # List Widget
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.layout.addWidget(self.list_widget, stretch=1)
        
        # Toolbar actions
        self.toolbar_layout = QHBoxLayout()
        self.run_btn = QPushButton("Run Again")
        self.run_btn.clicked.connect(self._run_selected)
        
        self.load_btn = QPushButton("Load Settings")
        self.load_btn.clicked.connect(self._load_selected)
        
        self.copy_btn = QPushButton("Copy Command")
        self.copy_btn.clicked.connect(self._copy_selected)
        
        self.details_btn = QPushButton("View Details")
        self.details_btn.clicked.connect(self._view_selected_details)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_selected)
        
        for btn in [self.run_btn, self.load_btn, self.copy_btn, self.details_btn, self.delete_btn]:
            self.toolbar_layout.addWidget(btn)
            
        self.layout.addLayout(self.toolbar_layout)
        
        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        entries = self._history_service.get_entries()
        for entry in reversed(entries):  # newest first
            status_map = {
                "success": "✔",
                "failed": "✘",
                "cancelled": "⧮",
                "running": "↻"
            }
            icon = status_map.get(entry.status, "?")
            
            # format the text
            short_cmd = entry.command[:50] + "..." if len(entry.command) > 50 else entry.command
            time_str = timestamp_str(entry.started_at)
            dur_str = duration_str(entry.duration_seconds) if entry.duration_seconds > 0 else ""
            
            text = f"{icon} {short_cmd}  |  {time_str} {dur_str}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list_widget.addItem(item)

    def _get_selected_entry(self) -> HistoryEntry | None:
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        entry = item.data(Qt.ItemDataRole.UserRole)
        self._show_details_dialog(entry)

    def _on_context_menu(self, pos):
        entry = self._get_selected_entry()
        if not entry:
            return
            
        menu = QMenu(self)
        
        run_act = QAction("Run Again", self)
        run_act.triggered.connect(self._run_selected)
        menu.addAction(run_act)
        
        load_act = QAction("Load Settings", self)
        load_act.triggered.connect(self._load_selected)
        menu.addAction(load_act)
        
        copy_act = QAction("Copy Command", self)
        copy_act.triggered.connect(self._copy_selected)
        menu.addAction(copy_act)
        
        details_act = QAction("View Details", self)
        details_act.triggered.connect(self._view_selected_details)
        menu.addAction(details_act)
        
        menu.addSeparator()
        
        del_act = QAction("Delete", self)
        del_act.triggered.connect(self._delete_selected)
        menu.addAction(del_act)
        
        menu.exec(self.list_widget.mapToGlobal(pos))

    def _run_selected(self):
        entry = self._get_selected_entry()
        if entry:
            self.run_again_requested.emit(entry)

    def _load_selected(self):
        entry = self._get_selected_entry()
        if entry:
            self.load_settings_requested.emit(entry)

    def _copy_selected(self):
        entry = self._get_selected_entry()
        if entry:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(entry.command)

    def _view_selected_details(self):
        entry = self._get_selected_entry()
        if entry:
            self._show_details_dialog(entry)

    def _delete_selected(self):
        entry = self._get_selected_entry()
        if entry:
            self._history_service.delete_entry(entry.id)

    def _show_details_dialog(self, entry: HistoryEntry):
        dlg = QDialog(self)
        dlg.setWindowTitle("Command Details")
        dlg.resize(600, 400)
        
        layout = QVBoxLayout(dlg)
        
        info = f"""Command: {entry.command}
Started: {timestamp_str(entry.started_at)}
Finished: {timestamp_str(entry.finished_at) if entry.finished_at else 'N/A'}
Duration: {duration_str(entry.duration_seconds)}
Exit Code: {entry.exit_code}
Status: {entry.status}"""

        info_label = QLabel(info)
        info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(info_label)
        
        layout.addWidget(QLabel("--- Output ---"))
        
        out_edit = QPlainTextEdit()
        out_edit.setReadOnly(True)
        out_edit.setPlainText(entry.output)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        out_edit.setFont(font)
        
        layout.addWidget(out_edit, stretch=1)
        
        dlg.exec()
