import sys
from pathlib import Path
import unittest.mock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.services.command_service import CommandService
from gui.models.command_schema import CommandSchema

@pytest.fixture
def schema():
    return CommandSchema.load()

@pytest.fixture
def command_service():
    return CommandService()

def test_build_command_run_sources_only(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        values = {"sources": ["test_source.json"]}
        cmd = command_service.build_command("run", cmd_def, values)
        assert cmd == '"python" -m imagegen run "test_source.json"'

def test_build_command_run_multiple_sources(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        values = {"sources": ["source1.json", "source2.json"]}
        cmd = command_service.build_command("run", cmd_def, values)
        assert cmd == '"python" -m imagegen run "source1.json" "source2.json"'

def test_build_command_boolean_true(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        values = {"sources": ["src"], "dry_run": True}
        cmd = command_service.build_command("run", cmd_def, values)
        assert "--dry-run" in cmd
        
def test_build_command_boolean_false(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        values = {"sources": ["src"], "dry_run": False}
        cmd = command_service.build_command("run", cmd_def, values)
        assert "--dry-run" not in cmd

def test_build_command_path_quoting(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        values = {"sources": ["path with spaces"]}
        cmd = command_service.build_command("run", cmd_def, values)
        assert '"path with spaces"' in cmd

def test_build_command_repeatable_args(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        values = {"sources": ["src"], "only": ["id1", "id2"], "match": ["glob1"]}
        cmd = command_service.build_command("run", cmd_def, values)
        assert "--only id1 --only id2" in cmd
        assert "--match glob1" in cmd

def test_build_command_numeric_args(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["run"]
        # default max_attempts is 3
        values = {"sources": ["src"], "max_attempts": 5}
        cmd = command_service.build_command("run", cmd_def, values)
        assert "--max-attempts 5" in cmd

        # default limit is 0, so 0 shouldn't be included
        values2 = {"sources": ["src"], "limit": 0}
        cmd2 = command_service.build_command("run", cmd_def, values2)
        assert "--limit" not in cmd2

def test_validate_inputs_missing_required(schema, command_service):
    cmd_def = schema.commands["run"]
    errors = command_service.validate_inputs(cmd_def, {})
    assert "'Source(s)' is required." in errors

def test_validate_inputs_nonexistent_path(schema, command_service, tmp_path):
    cmd_def = schema.commands["run"]
    values = {"sources": [tmp_path / "nonexistent.json"]}
    errors = command_service.validate_inputs(cmd_def, values)
    assert any("Path not found" in e for e in errors)

def test_build_command_init(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["init"]
        values = {"prompt_dir": "my_folder"}
        cmd = command_service.build_command("init", cmd_def, values)
        assert cmd == '"python" -m imagegen init "my_folder"'

def test_build_command_spec(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["spec"]
        values = {"full": True}
        cmd = command_service.build_command("spec", cmd_def, values)
        assert cmd == '"python" -m imagegen spec --full'

def test_build_command_convert(schema, command_service):
    with unittest.mock.patch('gui.services.command_service.resolve_python', return_value="python"):
        cmd_def = schema.commands["convert"]
        values = {"manifest": "test.json", "folder": "out_dir"}
        cmd = command_service.build_command("convert", cmd_def, values)
        assert cmd == '"python" -m imagegen convert "test.json" "out_dir"'
