"""Command Builder widget ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â dynamic form that generates imagegen CLI commands."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QComboBox,
    QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton,
    QFileDialog, QGroupBox, QLabel, QMessageBox, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from ..models.command_schema import CommandSchema, CommandDef, ArgumentDef, OptionDef
from ..models.history_entry import HistoryEntry
from ..services.command_service import CommandService
from .command_preview import CommandPreviewWidget


# ---------------------------------------------------------------------------
# Small helper widgets
# ---------------------------------------------------------------------------

class PathEntryWidget(QWidget):
    """A single path entry: text field + Browse button."""

    changed = Signal()

    def __init__(
        self,
        path_type: str = "file",
        file_filter: str = "All files (*)",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._path_type = path_type
        self._file_filter = file_filter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit = QLineEdit()
        self.line_edit.textChanged.connect(self.changed)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setFixedWidth(72)
        self.browse_btn.clicked.connect(self._browse)
        layout.addWidget(self.line_edit, stretch=1)
        layout.addWidget(self.browse_btn)

    def get_value(self) -> str:
        return self.line_edit.text().strip()

    def set_value(self, v: str) -> None:
        self.line_edit.setText(str(v))

    def _browse(self) -> None:
        if self._path_type == "folder":
            res = QFileDialog.getExistingDirectory(self, "Select Folder")
        elif self._path_type == "file_save":
            res, _ = QFileDialog.getSaveFileName(self, "Save File", "", self._file_filter)
        else:  # "file" or "file_or_folder"
            res, _ = QFileDialog.getOpenFileName(self, "Select File", "", self._file_filter)
        if res:
            self.line_edit.setText(res)


class MultiPathWidget(QWidget):
    """A vertically stacked list of PathEntryWidgets with Add/Remove."""

    changed = Signal()

    def __init__(
        self,
        path_type: str = "file_or_folder",
        file_filter: str = "All files (*)",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._path_type = path_type
        self._file_filter = file_filter
        self._entries: list[PathEntryWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._rows_widget = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addWidget(self._rows_widget)

        add_btn = QPushButton("+ Add Source")
        add_btn.clicked.connect(self._add_entry)
        outer.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Start with one empty row
        self._add_entry()

    def _add_entry(self, value: str = "") -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        entry = PathEntryWidget(self._path_type, self._file_filter)
        entry.changed.connect(self.changed)
        if value:
            entry.set_value(value)

        remove_btn = QPushButton("X")
        remove_btn.setFixedWidth(28)
        remove_btn.setToolTip("Remove this source")
        remove_btn.clicked.connect(lambda: self._remove_row(row, entry))

        row_layout.addWidget(entry, stretch=1)
        row_layout.addWidget(remove_btn)

        self._rows_layout.addWidget(row)
        self._entries.append(entry)
        self.changed.emit()

    def _remove_row(self, row: QWidget, entry: PathEntryWidget) -> None:
        if len(self._entries) <= 1:
            entry.set_value("")
            return
        self._entries.remove(entry)
        row.deleteLater()
        self.changed.emit()

    def get_values(self) -> list[str]:
        return [e.get_value() for e in self._entries if e.get_value()]

    def set_values(self, values: list[str]) -> None:
        # Clear existing beyond the first
        while len(self._entries) > 1:
            entry = self._entries.pop()
            entry.parent().deleteLater()  # type: ignore[union-attr]
        # Fill first entry
        if values:
            self._entries[0].set_value(values[0])
        else:
            self._entries[0].set_value("")
        # Add extras
        for v in values[1:]:
            self._add_entry(v)


class RepeatableStringWidget(QWidget):
    """A vertically stacked list of QLineEdit widgets with Add/Remove."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edits: list[QLineEdit] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._rows_widget = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addWidget(self._rows_widget)

        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(lambda: self._add_row())
        outer.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add_row(self, value: str = "") -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(value)
        edit.textChanged.connect(self.changed)

        remove_btn = QPushButton("X")
        remove_btn.setFixedWidth(28)
        remove_btn.clicked.connect(lambda: self._remove_row(row, edit))

        row_layout.addWidget(edit, stretch=1)
        row_layout.addWidget(remove_btn)

        self._rows_layout.addWidget(row)
        self._edits.append(edit)
        self.changed.emit()

    def _remove_row(self, row: QWidget, edit: QLineEdit) -> None:
        self._edits.remove(edit)
        row.deleteLater()
        self.changed.emit()

    def get_values(self) -> list[str]:
        return [e.text().strip() for e in self._edits if e.text().strip()]

    def set_values(self, values: list[str]) -> None:
        # Clear all rows
        for edit in list(self._edits):
            edit.parent().deleteLater()  # type: ignore[union-attr]
        self._edits.clear()
        for v in (values or []):
            self._add_row(v)


# ---------------------------------------------------------------------------
# Group labels for display
# ---------------------------------------------------------------------------

GROUP_LABELS: dict[str, str] = {
    "common": "Common Options",
    "run_control": "Run Control",
    "background": "Image Processing",
    "retry": "Retry & Timing",
    "ideogram_backend": "Ideogram Backend",
    "mock_backend": "Mock Backend (testing)",
}


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class CommandBuilderWidget(QWidget):
    """Left-panel widget: command selector + dynamic form + run/stop buttons."""

    run_requested = Signal(str, list, str)  # program, arg_list, cwd
    stop_requested = Signal()
    command_changed = Signal(str)           # updated command string

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        self._schema = CommandSchema.load()
        self._command_service = CommandService()
        self._run_animation_timer = QTimer(self)
        self._run_animation_timer.timeout.connect(self._animate_run_btn)
        self._run_animation_dots = 0
        # dest -> widget mapping (value extraction)
        self._field_widgets: dict[str, QWidget] = {}
        # group_name -> (group_box, backend_condition)
        self._group_boxes: dict[str, tuple[QGroupBox, str]] = {}

        self._setup_ui()

        if self._schema.commands:
            self.command_combo.addItems(list(self._schema.commands.keys()))
            # addItems triggers currentTextChanged ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ _update_command_form

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Title
        title = QLabel("Command Builder")
        title.setStyleSheet("color: #9CDCFE; font-weight: bold; font-size: 13px;")
        main_layout.addWidget(title)

        # Command selector row
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("Command:"))
        self.command_combo = QComboBox()
        self.command_combo.currentTextChanged.connect(self._on_command_changed)
        cmd_row.addWidget(self.command_combo, stretch=1)
        main_layout.addLayout(cmd_row)

        # Scroll area for dynamic form
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setSpacing(6)
        self.scroll_area.setWidget(self.form_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

        # Command preview
        self.preview_widget = CommandPreviewWidget()
        self.preview_widget.reset_requested.connect(self._reset_form)
        main_layout.addWidget(self.preview_widget)

        # Run / Stop buttons
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("run_button")
        self.run_btn.setMinimumHeight(32)
        self.run_btn.clicked.connect(self._on_run_clicked)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stop_button")
        self.stop_btn.setMinimumHeight(32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        btn_row.addWidget(self.run_btn, stretch=1)
        btn_row.addWidget(self.stop_btn, stretch=1)
        main_layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Form building
    # ------------------------------------------------------------------

    def _on_command_changed(self, _text: str) -> None:
        self._update_command_form()

    def _reset_form(self) -> None:
        """Rebuild the form (triggered by Preview's Reset button)."""
        self._update_command_form()

    def _clear_form_layout(self) -> None:
        """Remove all widgets from the dynamic form area."""
        self._field_widgets.clear()
        self._group_boxes.clear()
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _update_command_form(self) -> None:
        """Rebuild the form for the currently selected command."""
        self._clear_form_layout()

        cmd_name = self.command_combo.currentText()
        if not cmd_name or cmd_name not in self._schema.commands:
            return

        cmd_def = self._schema.commands[cmd_name]

        # --- Positional arguments section ---
        if cmd_def.arguments:
            arg_group = QGroupBox("Required Inputs")
            arg_layout = QVBoxLayout(arg_group)
            arg_layout.setSpacing(4)
            for arg in cmd_def.arguments:
                row = self._build_arg_row(arg)
                arg_layout.addLayout(row)
            self.form_layout.addWidget(arg_group)

        # --- Named options, grouped ---
        # Collect by group, preserving insertion order
        groups: dict[str, list[OptionDef]] = {}
        for opt in cmd_def.options:
            g = opt.group or "Options"
            groups.setdefault(g, []).append(opt)

        for grp_key, opts in groups.items():
            grp_label = GROUP_LABELS.get(grp_key, grp_key.replace("_", " ").title())
            # Determine backend condition (all opts in a backend group share it)
            backend_cond = opts[0].backend_condition if opts else ""

            grp_box = QGroupBox(grp_label)
            grp_layout = QVBoxLayout(grp_box)
            grp_layout.setSpacing(4)
            for opt in opts:
                row = self._build_option_row(opt)
                grp_layout.addLayout(row)
            self.form_layout.addWidget(grp_box)
            self._group_boxes[grp_key] = (grp_box, backend_cond)

        # JSON Defaults group
        self._json_group = QGroupBox("JSON Global Instructions (Defaults)")
        self._json_layout = QVBoxLayout(self._json_group)
        self._json_layout.setSpacing(4)
        
        self._json_prefix_edit = QLineEdit()
        self._json_prefix_edit.setPlaceholderText("Prompt Prefix")
        self._json_suffix_edit = QLineEdit()
        self._json_suffix_edit.setPlaceholderText("Prompt Suffix")
        self._json_negative_edit = QLineEdit()
        self._json_negative_edit.setPlaceholderText("Negative Prompt")
        
        self._json_layout.addWidget(QLabel("Prompt Prefix:"))
        self._json_layout.addWidget(self._json_prefix_edit)
        self._json_layout.addWidget(QLabel("Prompt Suffix:"))
        self._json_layout.addWidget(self._json_suffix_edit)
        self._json_layout.addWidget(QLabel("Negative Prompt:"))
        self._json_layout.addWidget(self._json_negative_edit)
        
        btn_save = QPushButton("Save Defaults to JSON")
        btn_save.clicked.connect(self._save_json_defaults)
        self._json_layout.addWidget(btn_save)
        
        self.form_layout.addWidget(self._json_group)
        self._json_group.hide()

        self.form_layout.addStretch()

        # Initial backend visibility + first preview
        self._update_backend_visibility()
        self._on_form_changed()

    def _build_arg_row(self, arg: ArgumentDef) -> QHBoxLayout:
        """Build the QHBoxLayout row for a positional argument."""
        layout = QVBoxLayout()
        label_text = arg.label + (" *" if arg.required else "")
        lbl = QLabel(label_text)
        lbl.setToolTip(arg.help)
        layout.addWidget(lbl)

        if arg.multi:
            w = MultiPathWidget(arg.path_type or "file_or_folder", arg.file_filter)
            w.changed.connect(self._on_form_changed)
            if arg.name == "sources":
                w.changed.connect(lambda: self._on_sources_changed(w))
            layout.addWidget(w)
            self._field_widgets[arg.name] = w
        elif arg.type == "path":
            w = PathEntryWidget(arg.path_type or "file", arg.file_filter)
            w.changed.connect(self._on_form_changed)
            layout.addWidget(w)
            self._field_widgets[arg.name] = w
        else:
            w = QLineEdit()
            if arg.type == "string" and hasattr(arg, "default") and arg.default:  # type: ignore[union-attr]
                w.setText(str(arg.default))  # type: ignore[attr-defined]
            w.textChanged.connect(self._on_form_changed)  # type: ignore[attr-defined]
            layout.addWidget(w)
            self._field_widgets[arg.name] = w

        # Wrap in a QHBoxLayout for consistent return type
        outer = QHBoxLayout()
        container = QWidget()
        container.setLayout(layout)
        outer.addWidget(container)
        return outer

    def _on_sources_changed(self, w: MultiPathWidget) -> None:
        paths = w.get_values()
        if not paths:
            if hasattr(self, '_json_group'): self._json_group.hide()
            return
            
        import json
        from pathlib import Path
        first_path = Path(paths[0])
        
        if first_path.suffix.lower() == '.json' and first_path.is_file():
            try:
                with open(first_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                out_dir_name = data.get('output_dir')
                if out_dir_name:
                    out_dir = first_path.parent / out_dir_name
                    out_w = self._field_widgets.get('out')
                    if hasattr(out_w, 'set_value'):
                        out_w.set_value(str(out_dir))
                        
                if hasattr(self, '_json_group'):
                    self._current_json_path = first_path
                    defaults = data.get('defaults', {})
                    self._json_prefix_edit.setText(defaults.get('prompt_prefix', ''))
                    self._json_suffix_edit.setText(defaults.get('prompt_suffix', ''))
                    self._json_negative_edit.setText(defaults.get('negative', ''))
                    self._json_group.show()
            except Exception:
                if hasattr(self, '_json_group'): self._json_group.hide()
        else:
            if hasattr(self, '_json_group'): self._json_group.hide()

    def _save_json_defaults(self) -> None:
        if not hasattr(self, '_current_json_path') or not self._current_json_path.is_file():
            return
        import json
        try:
            with open(self._current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'defaults' not in data:
                data['defaults'] = {}
                
            data['defaults']['prompt_prefix'] = self._json_prefix_edit.text()
            data['defaults']['prompt_suffix'] = self._json_suffix_edit.text()
            data['defaults']['negative'] = self._json_negative_edit.text()
            
            for k in ['prompt_prefix', 'prompt_suffix', 'negative']:
                if not data['defaults'][k]:
                    del data['defaults'][k]
                    
            with open(self._current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
            QMessageBox.information(self, "Success", "Defaults saved to JSON successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save JSON: {e}")

    def _build_option_row(self, opt: OptionDef) -> QHBoxLayout:
        """Build the QHBoxLayout row for a named option."""
        layout = QHBoxLayout()
        lbl = QLabel(opt.label)
        lbl.setToolTip(opt.help)
        lbl.setMinimumWidth(140)
        layout.addWidget(lbl)

        widget = self._create_option_widget(opt)
        if widget is None:
            return layout

        if isinstance(widget, (MultiPathWidget, RepeatableStringWidget)):
            # These need a vertical layout
            container = QWidget()
            vl = QVBoxLayout(container)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.addWidget(widget)
            layout.addWidget(container, stretch=1)
        else:
            layout.addWidget(widget, stretch=1)

        self._field_widgets[opt.dest] = widget
        return layout

    def _create_option_widget(self, opt: OptionDef) -> QWidget | None:
        """Instantiate the correct input widget for an OptionDef."""
        t = opt.type

        if t == "boolean":
            w = QCheckBox()
            if opt.default:
                w.setChecked(True)
            w.stateChanged.connect(lambda _: self._on_form_changed())
            return w

        if t == "choice":
            w = QComboBox()
            if opt.choices:
                w.addItems(opt.choices)
            if opt.default is not None:
                w.setCurrentText(str(opt.default))
            w.currentTextChanged.connect(lambda _: self._on_choice_changed(opt.dest))
            return w

        if t == "integer":
            w = QSpinBox()
            w.setRange(-1, 999_999)
            if opt.dest == "limit":
                w.setRange(0, 999_999)
                w.setSpecialValueText("All")
            if opt.default is not None:
                try:
                    w.setValue(int(opt.default))
                except (TypeError, ValueError):
                    pass
            w.valueChanged.connect(lambda _: self._on_form_changed())
            return w

        if t == "float":
            w = QDoubleSpinBox()
            w.setRange(0.0, 999_999.0)
            w.setDecimals(2)
            if opt.default is not None:
                try:
                    w.setValue(float(opt.default))
                except (TypeError, ValueError):
                    pass
            w.valueChanged.connect(lambda _: self._on_form_changed())
            return w

        if t in ("file", "folder", "file_save"):
            pt = "folder" if t == "folder" else ("file_save" if t == "file_save" else "file")
            w = PathEntryWidget(pt)
            if opt.default and str(opt.default).strip():
                w.set_value(str(opt.default))
            w.changed.connect(self._on_form_changed)
            return w

        if t == "repeatable_string":
            w = RepeatableStringWidget()
            w.changed.connect(self._on_form_changed)
            return w

        # Default: plain text
        w = QLineEdit()
        if opt.default is not None and str(opt.default).strip():
            w.setText(str(opt.default))
        w.textChanged.connect(lambda _: self._on_form_changed())
        return w

    # ------------------------------------------------------------------
    # Backend-conditional visibility
    # ------------------------------------------------------------------

    def _on_choice_changed(self, dest: str) -> None:
        if dest == "backend":
            self._update_backend_visibility()
        self._on_form_changed()

    def _update_backend_visibility(self) -> None:
        """Show/hide backend-specific option groups based on --backend value."""
        backend_widget = self._field_widgets.get("backend")
        current_backend = ""
        if isinstance(backend_widget, QComboBox):
            current_backend = backend_widget.currentText()

        for _grp_key, (grp_box, cond) in self._group_boxes.items():
            if cond:
                grp_box.setVisible(cond == current_backend)

    # ------------------------------------------------------------------
    # Form value collection
    # ------------------------------------------------------------------

    def _collect_form_values(self) -> dict[str, Any]:
        """Collect current widget values into a plain dict."""
        values: dict[str, Any] = {}
        for dest, widget in self._field_widgets.items():
            if isinstance(widget, MultiPathWidget):
                values[dest] = widget.get_values()
            elif isinstance(widget, RepeatableStringWidget):
                values[dest] = widget.get_values()
            elif isinstance(widget, PathEntryWidget):
                values[dest] = widget.get_value()
            elif isinstance(widget, QCheckBox):
                values[dest] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[dest] = widget.currentText()
            elif isinstance(widget, QSpinBox):
                values[dest] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                values[dest] = widget.value()
            elif isinstance(widget, QLineEdit):
                values[dest] = widget.text().strip()
        return values

    # ------------------------------------------------------------------
    # Preview update
    # ------------------------------------------------------------------

    def _on_form_changed(self) -> None:
        cmd_name = self.command_combo.currentText()
        if not cmd_name or cmd_name not in self._schema.commands:
            return
        cmd_def = self._schema.commands[cmd_name]
        values = self._collect_form_values()
        try:
            cmd_str = self._command_service.build_command(cmd_name, cmd_def, values)
        except Exception as exc:
            cmd_str = f"# Error building command: {exc}"
        self.preview_widget.set_command(cmd_str)
        self.command_changed.emit(cmd_str)

    # ------------------------------------------------------------------
    # Run / Stop
    # ------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        cmd_name = self.command_combo.currentText()
        if not cmd_name or cmd_name not in self._schema.commands:
            return
        cmd_def = self._schema.commands[cmd_name]
        values = self._collect_form_values()

        errors = self._command_service.validate_inputs(cmd_def, values)
        if errors:
            QMessageBox.warning(self, "Missing Inputs", "\n".join(errors))
            return

        # Build as a structured list to avoid shlex roundtrip issues with Windows paths
        program, arg_list = self._command_service.build_command_list(
            cmd_name, cmd_def, values
        )
        cwd = self._command_service.get_cwd()
        self.run_requested.emit(program, arg_list, cwd)

    def set_running(self, running: bool) -> None:
        """Update Run/Stop button states."""
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        if running:
            self._run_animation_dots = 0
            self._run_animation_timer.start(500)
            self._animate_run_btn()
        else:
            self._run_animation_timer.stop()
            self.run_btn.setText("Run")
            
    def _animate_run_btn(self) -> None:
        dots = "." * (self._run_animation_dots % 4)
        self.run_btn.setText(f"Running{dots}")
        self._run_animation_dots += 1

    # ------------------------------------------------------------------
    # Load from history
    # ------------------------------------------------------------------

    def load_entry(self, entry: HistoryEntry) -> None:
        """Restore the form from a HistoryEntry."""
        idx = self.command_combo.findText(entry.command_name)
        if idx >= 0:
            self.command_combo.setCurrentIndex(idx)
            self._update_command_form()

        for dest, value in entry.inputs.items():
            widget = self._field_widgets.get(dest)
            if widget is None:
                continue
            if isinstance(widget, MultiPathWidget):
                widget.set_values(value if isinstance(value, list) else [value])
            elif isinstance(widget, RepeatableStringWidget):
                widget.set_values(value if isinstance(value, list) else [value])
            elif isinstance(widget, PathEntryWidget):
                widget.set_value(str(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
            elif isinstance(widget, QSpinBox):
                try:
                    widget.setValue(int(value))
                except (TypeError, ValueError):
                    pass
            elif isinstance(widget, QDoubleSpinBox):
                try:
                    widget.setValue(float(value))
                except (TypeError, ValueError):
                    pass
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))

        self._on_form_changed()
