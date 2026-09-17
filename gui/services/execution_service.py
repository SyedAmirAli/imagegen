"""Execution service using QProcess for non-blocking command execution."""
from __future__ import annotations
import os
from typing import Callable
from PySide6.QtCore import QObject, QProcess, Signal
from ..utils.paths import project_root


class ExecutionService(QObject):
    """Manages running an imagegen CLI command as a subprocess.
    
    Signals:
        output_received(str): Emitted for each chunk of stdout or stderr output.
        started(): Emitted when the process starts.
        finished(int, str): Emitted when process exits. Args: exit_code, status.
                            status is one of: 'success', 'failed', 'cancelled'.
    """
    output_received = Signal(str)
    started = Signal()
    finished = Signal(int, str)  # exit_code, status

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._cancelled: bool = False

    @property
    def is_running(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def run(self, program: str, arguments: list[str], cwd: str) -> None:
        """Start a command. program is the executable; arguments is the arg list."""
        if self.is_running:
            return
        self._cancelled = False
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        
        self._process = QProcess(self)
        self._process.setWorkingDirectory(cwd)
        proc_env = self._process.processEnvironment()
        
        from PySide6.QtCore import QProcessEnvironment
        q_env = QProcessEnvironment()
        for k, v in env.items():
            q_env.insert(k, v)
        self._process.setProcessEnvironment(q_env)
        
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.started.connect(self.started)
        
        self._process.start(program, arguments)

    def stop(self) -> None:
        """Terminate the running process."""
        if self._process and self.is_running:
            self._cancelled = True
            pid = self._process.processId()
            if pid and os.name == 'nt':
                import subprocess
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self._process.kill()

    def _on_stdout(self) -> None:
        if self._process:
            data = self._process.readAllStandardOutput().toStdString()
            self.output_received.emit(data)

    def _on_stderr(self) -> None:
        if self._process:
            data = self._process.readAllStandardError().toStdString()
            self.output_received.emit(data)

    def _on_finished(self, exit_code: int, exit_status) -> None:
        from PySide6.QtCore import QProcess as QP
        if self._cancelled:
            status = "cancelled"
        elif exit_code == 0:
            status = "success"
        else:
            status = "failed"
        self._process = None
        self.finished.emit(exit_code, status)
