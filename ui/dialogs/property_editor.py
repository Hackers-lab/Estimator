"""
ui_dialogs.py
=============
All QDialog subclasses for ERP Estimate Generator.

Dialogs
-------
ProjectSetupDialog      NEW — project wizard shown on launch and via
                             "Project Settings" button. Captures project
                             type, subject, lat/long, division, circle,
                             UH toggle. Returns project_meta dict.

SearchDialog            — search materials / labour DB and add to estimate.
                          Unchanged from v4 except minor style tweaks.

SettingsDialog          — gateway to DB manager and Ruleset Manager.
                          Unchanged from v4.

DatabaseManagerDialog   — view, import, export the SQLite master DB.
                          Unchanged from v4.

RulesetManagerDialog    — full rule builder / simulator / editor.
                          Updated: TREE_DEF, FILTER_CHIPS, SIM_DEFAULTS
                          now imported from constants.py instead of being
                          hardcoded in the class body. SmartStructure and
                          SmartConsumer added throughout.
"""

import sqlite3
import json
import re
import openpyxl

from core import defaults
from core import property_catalog
from app_config import APP_DISPLAY_NAME, APP_VERSION

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QListWidget, QPushButton, QCheckBox,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QGroupBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QHeaderView, QInputDialog,
    QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QLabel, QScrollArea, QDialogButtonBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from core.constants import (
    PROPERTY_DATA, FORMULA_VARS,
    PROJECT_TYPES, SUPERVISION_RATES,
    SIM_DEFAULTS, TREE_DEF, FILTER_CHIPS,
)


def _runtime_property_data() -> dict:
    return property_catalog.build_property_data(PROPERTY_DATA)


def _runtime_sim_defaults() -> dict:
    return property_catalog.build_sim_defaults(SIM_DEFAULTS)


from ui.dialogs._shared import ClickableCard

class PropertyEntryDialog(QDialog):
    def __init__(self, entry: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Property")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self._label = QLineEdit(str((entry or {}).get("label", "")))
        self._label.setPlaceholderText("Example: OLD_IRON")
        form.addRow("Name:", self._label)

        self._has_options = QCheckBox("This custom entry has option values")
        self._has_options.setChecked(bool((entry or {}).get("options", [])))
        form.addRow(self._has_options)

        self._options = QLineEdit(
            ", ".join((entry or {}).get("options", []))
        )
        self._options.setPlaceholderText("Example: Blue, Red")
        form.addRow("Options:", self._options)

        hint = QLabel(
            "Leave Options empty for a marker-style custom entry.\n"
            "Default object value will always remain None until a user selects it."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11px; color:#666;")

        root.addLayout(form)
        root.addWidget(hint)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._has_options.stateChanged.connect(self._sync_options_enabled)
        self._sync_options_enabled()
        self.result_entry: dict | None = None

    def _sync_options_enabled(self):
        self._options.setEnabled(self._has_options.isChecked())
        if not self._has_options.isChecked():
            self._options.clear()

    def _on_accept(self):
        label = self._label.text().strip()
        if not label:
            QMessageBox.warning(self, "Required", "Please enter a custom property name.")
            return
        if label.lower() == "none":
            QMessageBox.warning(self, "Invalid Name", "None is reserved and cannot be used.")
            return

        options = []
        if self._has_options.isChecked():
            seen = set()
            for raw in self._options.text().split(","):
                option = raw.strip()
                if not option or option.lower() == "none":
                    continue
                key = option.casefold()
                if key in seen:
                    continue
                seen.add(key)
                options.append(option)

        self.result_entry = {
            "label": label,
            "options": options,
        }
        self.accept()


class PropertyEditorDialog(QDialog):
    """
    Tree-based Property Editor.

    Shows all fixed properties of each canvas object type (read-only) and lets
    users:
      • Add new option values to any list-type fixed property.
      • Add, edit, and delete custom properties (per object type).

    Custom property values are stored in ``item.dynamic_props`` by label name
    and injected into the rule-engine context automatically.
    """

    _TYPE_LABELS: dict[str, str] = {
        "SmartPole":      "SmartPole  (LT Pole / HT Pole / Existing Pole)",
        "SmartStructure": "SmartStructure  (DP / TP / 4P / DTR)",
        "SmartSpan":      "SmartSpan  (AB Cable / ACSR / PVC / Service Drop)",
        "SmartConsumer":  "SmartConsumer",
    }
    _N_TYPE         = "type"
    _N_FIXED_GROUP  = "fixed_group"
    _N_CUSTOM_GROUP = "custom_group"
    _N_FIXED_PROP   = "fixed_prop"
    _N_CUSTOM_PROP  = "custom_prop"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Property Editor")
        self.resize(900, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Browse all object properties and manage custom properties per object type.\n"
            "Fixed properties are read-only — you can only add new option values to them. "
            "Custom properties appear as extra fields inside the object editor panel."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:11px; color:#555;")
        root.addWidget(intro)

        # ── Tree ──────────────────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Property", "Values / Description"])
        hdr = self._tree.header()
        if hdr is not None:
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        root.addWidget(self._tree, 1)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_add_custom  = QPushButton("+ Add Custom Property")
        self._btn_add_option  = QPushButton("+ Add Option to Property")
        self._btn_edit        = QPushButton("Edit Custom")
        self._btn_delete      = QPushButton("Delete Custom")
        for btn in (self._btn_add_custom, self._btn_add_option,
                    self._btn_edit, self._btn_delete):
            btn.setEnabled(False)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        self._btn_add_custom.clicked.connect(self._add_custom_property)
        self._btn_add_option.clicked.connect(self._add_option)
        self._btn_edit.clicked.connect(self._edit_custom_property)
        self._btn_delete.clicked.connect(self._delete_custom_property)
        root.addLayout(btn_row)

        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        root.addWidget(close_btns)

        self._build_tree()

    # ── Tree construction ─────────────────────────────────────────────────────

    def _node_data(self, item: QTreeWidgetItem) -> dict:
        return item.data(0, Qt.ItemDataRole.UserRole) or {}

    def _set_node(self, item: QTreeWidgetItem, data: dict) -> None:
        item.setData(0, Qt.ItemDataRole.UserRole, data)

    def _build_tree(self) -> None:
        self._tree.clear()
        rules   = self._load_rules()
        usage   = property_catalog.usage_details(rules)
        grey    = QColor("#777777")
        dim     = QColor("#999999")

        for obj_type in property_catalog.OBJECT_TYPES:
            # ── Object-type root ──────────────────────────────────────────────
            type_item = QTreeWidgetItem([
                self._TYPE_LABELS.get(obj_type, obj_type), ""
            ])
            bold = QFont()
            bold.setBold(True)
            type_item.setFont(0, bold)
            self._set_node(type_item, {"node": self._N_TYPE, "obj_type": obj_type})
            self._tree.addTopLevelItem(type_item)

            # ── Fixed Properties ──────────────────────────────────────────────
            fixed_grp = QTreeWidgetItem(["  \u25b8 Fixed Properties", ""])
            fixed_grp.setForeground(0, grey)
            self._set_node(fixed_grp, {"node": self._N_FIXED_GROUP, "obj_type": obj_type})
            type_item.addChild(fixed_grp)

            base_props = PROPERTY_DATA.get(obj_type, {})
            for prop_name, prop_val in base_props.items():
                if isinstance(prop_val, list):
                    ext       = property_catalog.get_extended_options(obj_type, prop_name)
                    base_txt  = ", ".join(str(o) for o in prop_val)
                    extra_txt = ("  |  +" + ", ".join(ext)) if ext else ""
                    prop_item = QTreeWidgetItem(
                        [f"    {prop_name}", base_txt + extra_txt]
                    )
                    self._set_node(prop_item, {
                        "node": self._N_FIXED_PROP,
                        "obj_type": obj_type,
                        "prop": prop_name,
                        "is_list": True,
                    })
                else:
                    type_str  = "numeric" if prop_val == "int" else "free text"
                    prop_item = QTreeWidgetItem([f"    {prop_name}", f"[{type_str}]"])
                    prop_item.setForeground(1, dim)
                    self._set_node(prop_item, {
                        "node": self._N_FIXED_PROP,
                        "obj_type": obj_type,
                        "prop": prop_name,
                        "is_list": False,
                    })
                fixed_grp.addChild(prop_item)

            # ── Custom Properties ─────────────────────────────────────────────
            custom_grp = QTreeWidgetItem(["  \u25b8 Custom Properties", ""])
            custom_grp.setForeground(0, grey)
            self._set_node(custom_grp, {"node": self._N_CUSTOM_GROUP, "obj_type": obj_type})
            type_item.addChild(custom_grp)

            for entry in property_catalog.get_custom_entries(obj_type):
                label   = entry["label"]
                options = entry.get("options", [])
                hits    = usage.get(label, [])
                opts_str  = ", ".join(options) if options else "(marker \u2013 no options)"
                usage_str = f"  [used in {len(hits)} rule(s)]" if hits else ""
                custom_item = QTreeWidgetItem(
                    [f"    {label}", opts_str + usage_str]
                )
                self._set_node(custom_item, {
                    "node": self._N_CUSTOM_PROP,
                    "obj_type": obj_type,
                    "label": label,
                })
                custom_grp.addChild(custom_item)

            type_item.setExpanded(True)
            custom_grp.setExpanded(True)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_selection_changed(
        self,
        current_item: QTreeWidgetItem | None,
        _previous,
    ) -> None:
        for btn in (self._btn_add_custom, self._btn_add_option,
                    self._btn_edit, self._btn_delete):
            btn.setEnabled(False)

        if current_item is None:
            return

        nd = self._node_data(current_item)
        node = nd.get("node", "")

        if node in (self._N_TYPE, self._N_CUSTOM_GROUP):
            self._btn_add_custom.setEnabled(True)

        elif node == self._N_FIXED_PROP:
            if nd.get("is_list"):
                self._btn_add_option.setEnabled(True)

        elif node == self._N_CUSTOM_PROP:
            self._btn_add_option.setEnabled(True)
            self._btn_edit.setEnabled(True)
            self._btn_delete.setEnabled(True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _load_rules(self) -> list[dict]:
        try:
            with open("rules.json", "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _selected_obj_type(self) -> str | None:
        item = self._tree.currentItem()
        return self._node_data(item).get("obj_type") if item else None

    def _add_custom_property(self) -> None:
        obj_type = self._selected_obj_type()
        if not obj_type:
            return

        dlg = PropertyEntryDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_entry is None:
            return

        label = dlg.result_entry["label"]
        existing = {e["label"].casefold() for e in property_catalog.get_custom_entries(obj_type)}
        if label.casefold() in existing:
            QMessageBox.warning(
                self, "Duplicate",
                f"A custom property '{label}' already exists for {obj_type}.",
            )
            return

        property_catalog.add_custom_entry(
            obj_type, label, dlg.result_entry.get("options", [])
        )
        self._build_tree()

    def _add_option(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        nd       = self._node_data(item)
        node     = nd.get("node", "")
        obj_type = nd.get("obj_type", "")

        if node == self._N_FIXED_PROP:
            prop_name = nd.get("prop", "")
            option, ok = QInputDialog.getText(
                self,
                f"Add Option \u2013 {prop_name} ({obj_type})",
                f"New option value to add to  {obj_type} \u203a {prop_name}:",
            )
            if not ok or not option.strip():
                return
            added = property_catalog.add_extended_option(obj_type, prop_name, option.strip())
            if not added:
                QMessageBox.information(
                    self, "Duplicate",
                    f"'{option.strip()}' already exists in {prop_name}.",
                )
            self._build_tree()

        elif node == self._N_CUSTOM_PROP:
            label  = nd.get("label", "")
            option, ok = QInputDialog.getText(
                self,
                f"Add Option \u2013 {label} ({obj_type})",
                f"New option value for custom property '{label}':",
            )
            if not ok or not option.strip():
                return
            option = option.strip()
            for entry in property_catalog.get_custom_entries(obj_type):
                if entry["label"].casefold() == label.casefold():
                    if option.casefold() in {o.casefold() for o in entry["options"]}:
                        QMessageBox.information(
                            self, "Duplicate",
                            f"'{option}' already exists.",
                        )
                        return
                    new_options = entry["options"] + [option]
                    property_catalog.update_custom_entry(
                        obj_type, label, label, new_options
                    )
                    break
            self._build_tree()

    def _edit_custom_property(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        nd = self._node_data(item)
        if nd.get("node") != self._N_CUSTOM_PROP:
            return

        obj_type = nd["obj_type"]
        label    = nd["label"]

        # Check usage
        rules = self._load_rules()
        usage = property_catalog.usage_details(rules, obj_type)
        hits  = usage.get(label, [])

        entry = next(
            (e for e in property_catalog.get_custom_entries(obj_type)
             if e["label"].casefold() == label.casefold()),
            None,
        )
        if entry is None:
            return

        dlg = PropertyEntryDialog(entry=entry, parent=self)
        if hits:
            dlg._label.setReadOnly(True)  # name locked while referenced in rules

        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_entry is None:
            return

        new_label   = dlg.result_entry["label"]
        new_options = dlg.result_entry.get("options", [])

        if new_label.casefold() != label.casefold():
            existing = {e["label"].casefold()
                        for e in property_catalog.get_custom_entries(obj_type)}
            if new_label.casefold() in existing:
                QMessageBox.warning(
                    self, "Duplicate",
                    f"A custom property '{new_label}' already exists for {obj_type}.",
                )
                return

        property_catalog.update_custom_entry(obj_type, label, new_label, new_options)
        self._build_tree()

    def _delete_custom_property(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        nd = self._node_data(item)
        if nd.get("node") != self._N_CUSTOM_PROP:
            return

        obj_type = nd["obj_type"]
        label    = nd["label"]

        rules = self._load_rules()
        usage = property_catalog.usage_details(rules, obj_type)
        hits  = usage.get(label, [])
        if hits:
            QMessageBox.warning(
                self, "In Use",
                f"'{label}' is referenced in {len(hits)} rule(s) and cannot be deleted.\n\n"
                + "\n".join(f"- {n}" for n in hits[:10]),
            )
            return

        answer = QMessageBox.question(
            self, "Delete Custom Property",
            f"Delete custom property '{label}' from {obj_type}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        property_catalog.delete_custom_entry(obj_type, label)
        self._build_tree()


# ─────────────────────────────────────────────────────────────────────────────
#  PlacementDefaultsDialog
# ─────────────────────────────────────────────────────────────────────────────

