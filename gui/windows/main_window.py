from __future__ import annotations
import time
from PySide6.QtWidgets import QMainWindow, QSplitter
from PySide6.QtCore import Qt
from ..widgets.command_builder import CommandBuilderWidget
from ..widgets.terminal_widget import TerminalWidget
from ..widgets.history_widget import HistoryWidget
from ..services.command_service import CommandService
from ..services.history_service import HistoryService
from ..services.execution_service import ExecutionService
from ..models.history_entry import HistoryEntry
from ..utils.formatting import now_iso

APP_STYLE = """
QMainWindow, QWidget { background-color: #2B2B2B; color: #D4D4D4; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { 
    background-color: #3C3F41; color: #D4D4D4; 
    border: 1px solid #555; padding: 4px; border-radius: 3px;
}
QPushButton { 
    background-color: #4C5052; color: #D4D4D4;
    border: 1px solid #666; padding: 5px 12px; border-radius: 3px;
}
QPushButton:hover { background-color: #5C6366; }
QPushButton#run_button { background-color: #2E7D32; color: white; }
QPushButton#run_button:hover { background-color: #388E3C; }
QPushButton#run_button:disabled { background-color: #1B5E20; color: #888; }
QPushButton#stop_button { background-color: #C62828; color: white; }
QPushButton#stop_button:hover { background-color: #D32F2F; }
QListWidget { background-color: #2B2B2B; border: 1px solid #444; }
QListWidget::item:selected { background-color: #0D47A1; }
QCheckBox { color: #D4D4D4; }
QScrollBar:vertical { background: #3C3F41; width: 12px; }
QGroupBox { border: 1px solid #555; margin-top: 8px; padding-top: 8px; color: #D4D4D4; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #9CDCFE; }
QSplitter::handle { background-color: #555; }
QLabel { color: #D4D4D4; }
"""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageGen Desktop GUI")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(APP_STYLE)

        self._history_service = HistoryService()
        self._command_service = CommandService()
        self._execution_service = ExecutionService(self)
        self._manual_execution_service = ExecutionService(self)
        
        self._current_entry_id: str | None = None
        self._output_buffer: list[str] = []
        self._start_time: float = 0.0

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.builder = CommandBuilderWidget()
        self.builder.setMinimumWidth(350)
        self.terminal = TerminalWidget()
        
        self.top_splitter.addWidget(self.builder)
        self.top_splitter.addWidget(self.terminal)
        self.top_splitter.setStretchFactor(0, 0)
        self.top_splitter.setStretchFactor(1, 1)
        
        self.history_widget = HistoryWidget(self._history_service)
        
        self.main_splitter.addWidget(self.top_splitter)
        self.main_splitter.addWidget(self.history_widget)
        self.main_splitter.setStretchFactor(0, 65)
        self.main_splitter.setStretchFactor(1, 35)
        
        self.setCentralWidget(self.main_splitter)

    def _connect_signals(self):
        self.builder.run_requested.connect(self._on_run_requested)
        self.builder.stop_requested.connect(self._execution_service.stop)
        
        self._execution_service.output_received.connect(self._on_output_received)
        self._execution_service.started.connect(self._on_execution_started)
        self._execution_service.finished.connect(self._on_execution_finished)
        
        self.terminal.manual_command_entered.connect(self._on_manual_command)
        
        self.history_widget.run_again_requested.connect(self._on_run_again_requested)
        self.history_widget.load_settings_requested.connect(self.builder.load_entry)
        
        self._manual_execution_service.output_received.connect(self.terminal.append_text)
        self._manual_execution_service.started.connect(lambda: self.terminal.set_input_enabled(False))
        self._manual_execution_service.finished.connect(lambda _, __: self.terminal.set_input_enabled(True))

    def _on_run_requested(self, program: str, args: list[str], cwd: str):
        cmd_str = self.builder.preview_widget.get_command()
        cmd_name = self.builder.command_combo.currentText()
        form_values = self.builder._collect_form_values()
        
        entry = HistoryEntry(
            id=HistoryEntry.new_id(),
            command=cmd_str,
            command_name=cmd_name,
            inputs=form_values,
            status="running",
            started_at=now_iso(),
            finished_at="",
            duration_seconds=0.0,
            exit_code=None,
            output=""
        )
        self._history_service.add_entry(entry)
        self._current_entry_id = entry.id
        self._output_buffer = []
        self._start_time = time.time()
        
        self.terminal.append_command(cmd_str)
        self._execution_service.run(program, args, cwd)

    def _on_output_received(self, text: str):
        self._output_buffer.append(text)
        self.terminal.append_text(text)

    def _on_execution_started(self):
        self.builder.set_running(True)
        self.terminal.set_input_enabled(False)

    def _on_execution_finished(self, exit_code: int, status: str):
        elapsed = time.time() - self._start_time
        if self._current_entry_id:
            self._history_service.update_entry(
                self._current_entry_id,
                status=status,
                exit_code=exit_code,
                finished_at=now_iso(),
                duration_seconds=elapsed,
                output="".join(self._output_buffer),
            )
            self._current_entry_id = None
            
        if status == "cancelled":
            self.terminal.append_text("\n[System] Program manually stopped.\n")
        elif exit_code != 0:
            self.terminal.append_text(f"\n[System] Program exited with code {exit_code}.\n")
        else:
            self.terminal.append_text("\n[System] Program finished successfully.\n")
            
        self.history_widget.refresh()
        self.builder.set_running(False)
        self.terminal.set_input_enabled(True)

    def _on_manual_command(self, cmd: str):
        self.terminal.append_command(cmd)
        cwd = self._command_service.get_cwd()
        self._manual_execution_service.run("powershell", ["-Command", cmd], cwd)

    def _on_run_again_requested(self, entry: "HistoryEntry") -> None:  # type: ignore[name-defined]
        """Re-run by restoring the history entry into the form, then triggering run."""
        self.builder.load_entry(entry)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.builder._on_run_clicked)
