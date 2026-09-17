from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ArgumentDef:
    name: str
    label: str
    help: str
    type: str           # "path", "string", etc.
    path_type: str = ""  # "file", "folder", "file_or_folder", "file_save"
    file_filter: str = "All files (*)"
    required: bool = False
    multi: bool = False

@dataclass  
class OptionDef:
    flag: str
    dest: str
    label: str
    help: str
    type: str           # "boolean", "choice", "integer", "float", "string", "file", "folder", "file_save", "repeatable_string"
    choices: list[str] = field(default_factory=list)
    default: Any = None
    group: str = "common"
    backend_condition: str = ""  # if set, only show when --backend == this value

@dataclass
class CommandDef:
    name: str
    description: str
    arguments: list[ArgumentDef] = field(default_factory=list)
    options: list[OptionDef] = field(default_factory=list)

@dataclass
class CommandSchema:
    version: int
    commands: dict[str, CommandDef]
    
    @classmethod
    def load(cls) -> CommandSchema:
        """Load schema from command_schema.json next to this file's config/ dir."""
        import json
        from pathlib import Path
        schema_path = Path(__file__).parent.parent / "config" / "command_schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        commands = {}
        for cmd_name, cmd_data in data["commands"].items():
            args = [ArgumentDef(**a) for a in cmd_data.get("arguments", [])]
            opts = [OptionDef(**o) for o in cmd_data.get("options", [])]
            commands[cmd_name] = CommandDef(
                name=cmd_name,
                description=cmd_data["description"],
                arguments=args,
                options=opts,
            )
        return cls(version=data["version"], commands=commands)
