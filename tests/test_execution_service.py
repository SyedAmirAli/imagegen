from __future__ import annotations
import os
from gui.services.execution_service import ExecutionService
from PySide6.QtCore import QCoreApplication

def test_is_running_initially_false(qtbot):
    svc = ExecutionService()
    assert not svc.is_running

def test_execution_service_success(qtbot):
    svc = ExecutionService()
    with qtbot.waitSignal(svc.finished, timeout=5000) as blocker:
        svc.run("powershell", ["-Command", "echo", "hello"], os.getcwd())
    
    assert blocker.args[0] == 0
    assert blocker.args[1] == "success"

def test_execution_service_failure(qtbot):
    svc = ExecutionService()
    with qtbot.waitSignal(svc.finished, timeout=5000) as blocker:
        svc.run("powershell", ["-Command", "exit 1"], os.getcwd())
    
    assert blocker.args[0] == 1
    assert blocker.args[1] == "failed"

def test_execution_service_stop(qtbot):
    svc = ExecutionService()
    svc.run("powershell", ["-Command", "Start-Sleep -Seconds 10"], os.getcwd())
    assert svc.is_running
    
    with qtbot.waitSignal(svc.finished, timeout=5000) as blocker:
        svc.stop()
        
    assert blocker.args[1] == "cancelled"
