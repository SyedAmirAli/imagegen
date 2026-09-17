"""Command string builder service."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from ..utils.paths import resolve_python, project_root
from ..utils.formatting import quote_path
from ..models.command_schema import CommandDef, ArgumentDef, OptionDef


class CommandService:
    """Builds CLI invocation command strings from form values."""

    def build_command(
        self,
        command_name: str,
        command_def: CommandDef,
        form_values: dict[str, Any],
    ) -> str:
        """
        Build the full imagegen CLI command string.

        Args:
            command_name: The subcommand name (e.g. "run").
            command_def: The CommandDef describing this command.
            form_values: Dict mapping argument/option dest → value.

        Returns:
            A shell-safe command string.
        """
        python_exe = resolve_python()
        parts = [quote_path(python_exe), "-m", "imagegen", command_name]

        # Positional arguments first
        for arg in command_def.arguments:
            value = form_values.get(arg.name)
            if not value:
                continue
            if arg.multi and isinstance(value, list):
                for v in value:
                    if v:
                        parts.append(quote_path(str(v)) if arg.type == "path" else str(v))
            else:
                parts.append(quote_path(str(value)) if arg.type == "path" else str(value))

        # Named options
        for opt in command_def.options:
            value = form_values.get(opt.dest)
            if value is None:
                continue
            self._add_option(parts, opt, value)

        return " ".join(parts)

    def _add_option(
        self,
        parts: list[str],
        opt: OptionDef,
        value: Any,
    ) -> None:
        """Append the CLI flag and value to parts in-place."""
        if opt.type == "boolean":
            if value and value != opt.default:
                parts.append(opt.flag)
        elif opt.type == "repeatable_string":
            if isinstance(value, list):
                for item in value:
                    if item:
                        parts.extend([opt.flag, str(item)])
        elif opt.type in ("file", "folder", "file_save"):
            if value and str(value).strip():
                parts.extend([opt.flag, quote_path(str(value))])
        elif opt.type in ("integer", "float"):
            default = opt.default
            try:
                if opt.type == "integer":
                    v = int(value)
                    d = int(default) if default is not None else None
                else:
                    v = float(value)
                    d = float(default) if default is not None else None
                if d is None or v != d:
                    parts.extend([opt.flag, str(v)])
            except (TypeError, ValueError):
                pass
        else:
            # string, choice
            default = opt.default
            if value and value != default:
                parts.extend([opt.flag, str(value)])

    def validate_inputs(
        self,
        command_def: CommandDef,
        form_values: dict[str, Any],
    ) -> list[str]:
        """
        Return a list of validation error messages.
        Empty list means all required fields are filled.
        """
        errors = []
        for arg in command_def.arguments:
            if not arg.required:
                continue
            value = form_values.get(arg.name)
            if not value or (isinstance(value, list) and not any(value)):
                errors.append(f"'{arg.label}' is required.")
                continue
            # Check paths exist
            if arg.type == "path":
                paths = value if isinstance(value, list) else [value]
                for p in paths:
                    if p and not Path(str(p)).exists():
                        errors.append(f"Path not found: {p}")
        return errors

    def get_cwd(self) -> str:
        """Return the working directory for subprocess execution."""
        return str(project_root())

    def build_command_list(
        self,
        command_name: str,
        command_def: CommandDef,
        form_values: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """
        Build the command as a (program, arguments_list) tuple.

        Unlike build_command(), this never shell-quotes paths, so Windows paths
        with backslashes and spaces are passed safely to QProcess/subprocess.

        Returns:
            (program, args_list) where program is the Python executable path
            and args_list is everything else.
        """
        python_exe = resolve_python()
        args: list[str] = ["-m", "imagegen", command_name]

        # Positional arguments
        for arg in command_def.arguments:
            value = form_values.get(arg.name)
            if not value:
                continue
            if arg.multi and isinstance(value, list):
                for v in value:
                    if v:
                        args.append(str(v))
            else:
                args.append(str(value))

        # Named options
        for opt in command_def.options:
            value = form_values.get(opt.dest)
            if value is None:
                continue
            self._add_option_list(args, opt, value)

        return python_exe, args

    def _add_option_list(
        self,
        args: list[str],
        opt: OptionDef,
        value: Any,
    ) -> None:
        """Append flag + value to args list (no quoting)."""
        if opt.type == "boolean":
            if value and value != opt.default:
                args.append(opt.flag)
        elif opt.type == "repeatable_string":
            if isinstance(value, list):
                for item in value:
                    if item:
                        args.extend([opt.flag, str(item)])
        elif opt.type in ("file", "folder", "file_save"):
            if value and str(value).strip():
                args.extend([opt.flag, str(value)])
        elif opt.type in ("integer", "float"):
            default = opt.default
            try:
                if opt.type == "integer":
                    v = int(value)
                    d = int(default) if default is not None else None
                else:
                    v = float(value)
                    d = float(default) if default is not None else None
                if d is None or v != d:
                    args.extend([opt.flag, str(v)])
            except (TypeError, ValueError):
                pass
        else:
            # string, choice
            default = opt.default
            if value and value != default:
                args.extend([opt.flag, str(value)])
