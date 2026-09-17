import sys
from pathlib import Path
import unittest.mock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.services.history_service import HistoryService
from gui.models.history_entry import HistoryEntry

@pytest.fixture
def mock_history_file(tmp_path):
    file_path = tmp_path / "history.json"
    with unittest.mock.patch('gui.services.history_service.history_file', return_value=file_path):
        yield file_path

def test_add_and_get_entry(mock_history_file):
    service = HistoryService()
    entry = HistoryEntry(id="1", command="test", command_name="run", inputs={}, status="running", started_at="now")
    service.add_entry(entry)
    
    entries = service.get_entries()
    assert len(entries) == 1
    assert entries[0].id == "1"
    
    retrieved = service.get_entry("1")
    assert retrieved is not None
    assert retrieved.id == "1"

def test_entries_returned_newest_first(mock_history_file):
    service = HistoryService()
    service.add_entry(HistoryEntry(id="1", command="c1", command_name="run", inputs={}, status="running", started_at="t1"))
    service.add_entry(HistoryEntry(id="2", command="c2", command_name="run", inputs={}, status="running", started_at="t2"))
    
    entries = service.get_entries()
    assert entries[0].id == "2"
    assert entries[1].id == "1"

def test_update_entry(mock_history_file):
    service = HistoryService()
    service.add_entry(HistoryEntry(id="1", command="c1", command_name="run", inputs={}, status="running", started_at="t1"))
    
    service.update_entry("1", status="success", duration_seconds=5.0)
    
    entry = service.get_entry("1")
    assert entry.status == "success"
    assert entry.duration_seconds == 5.0

def test_delete_entry(mock_history_file):
    service = HistoryService()
    service.add_entry(HistoryEntry(id="1", command="c1", command_name="run", inputs={}, status="running", started_at="t1"))
    
    service.delete_entry("1")
    assert service.get_entry("1") is None
    assert len(service.get_entries()) == 0

def test_clear_all(mock_history_file):
    service = HistoryService()
    service.add_entry(HistoryEntry(id="1", command="c1", command_name="run", inputs={}, status="running", started_at="t1"))
    service.add_entry(HistoryEntry(id="2", command="c2", command_name="run", inputs={}, status="running", started_at="t2"))
    
    service.clear_all()
    assert len(service.get_entries()) == 0

def test_persistence(mock_history_file):
    service1 = HistoryService()
    service1.add_entry(HistoryEntry(id="1", command="c1", command_name="run", inputs={}, status="running", started_at="t1"))
    
    # New instance should load from file
    service2 = HistoryService()
    entries = service2.get_entries()
    assert len(entries) == 1
    assert entries[0].id == "1"

def test_max_history_entries(mock_history_file):
    with unittest.mock.patch('gui.services.history_service.MAX_HISTORY_ENTRIES', 2):
        service = HistoryService()
        service.add_entry(HistoryEntry(id="1", command="c1", command_name="run", inputs={}, status="running", started_at="t1"))
        service.add_entry(HistoryEntry(id="2", command="c2", command_name="run", inputs={}, status="running", started_at="t2"))
        service.add_entry(HistoryEntry(id="3", command="c3", command_name="run", inputs={}, status="running", started_at="t3"))
        
        entries = service.get_entries()
        assert len(entries) == 2
        # Newest first: 3, 2
        assert entries[0].id == "3"
        assert entries[1].id == "2"

def test_corrupt_file_graceful_handling(mock_history_file):
    mock_history_file.write_text("{corrupt json", encoding="utf-8")
    service = HistoryService()
    assert len(service.get_entries()) == 0
