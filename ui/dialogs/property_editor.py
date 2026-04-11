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

from core import defaults
from core import property_catalog
from app_config import APP_DISPLAY_NAME, APP_VERSION, get_data_path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QListWidget, QPushButton, QCheckBox,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QGroupBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QHeaderView, QInputDialog,
    QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QLabel, QScrollArea, QDialogButtonBox, QFrame,
    QColorDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from core.constants import (
    PROPERTY_DATA, FORMULA_VARS,
    PROJECT_TYPES, SUPERVISION_RATES,
    SIM_DEFAULTS, TREE_DEF, FILTER_CHIPS,
)
from core import defaults as _defaults_mod


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


class ConductorMetaDialog(QDialog):
    """
    Small dialog to create or edit a user-defined conductor type.

    Fields
    ------
    Conductor Name   — free text; read-only when editing an existing entry.
    Applicable to    — LT only / HT only / Both LT and HT.
    Initial Sizes    — comma-separated string (optional; more can be added later).
    """

    def __init__(
        self,
        conductor_name: str | None = None,
        existing_voltage: str = "Both",
        parent=None,
    ) -> None:
        super().__init__(parent)
        is_edit = conductor_name is not None
        self.setWindowTitle("Edit Conductor" if is_edit else "Add Conductor Type")
        self.setMinimumWidth(440)

        self.result_name:    str | None = None
        self.result_voltage: str        = existing_voltage
        self.result_sizes:   list[str]  = []

        root = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(conductor_name or "")
        self._name.setPlaceholderText("e.g. XLPE, HT-ACSR-Fox, UG-HT")
        if is_edit:
            self._name.setReadOnly(True)
            self._name.setStyleSheet("background:#f0f0f0; color:#555;")
        form.addRow("Conductor Name:", self._name)

        self._voltage = QComboBox()
        self._voltage.addItems(["LT only", "HT only", "Both LT and HT"])
        idx = {"LT": 0, "HT": 1, "Both": 2}.get(existing_voltage, 2)
        self._voltage.setCurrentIndex(idx)
        form.addRow("Applicable to:", self._voltage)

        self._sizes = QLineEdit()
        self._sizes.setPlaceholderText("e.g. 25SQMM, 50SQMM, 95SQMM")
        if is_edit:
            self._sizes.setPlaceholderText("Add more sizes via the conductor_size section in the tree")
            self._sizes.setEnabled(False)
        form.addRow("Initial Sizes:", self._sizes)

        root.addLayout(form)

        hint = QLabel(
            "\u2139 Sizes can always be added or removed later by selecting the conductor\u2019s\n"
            "  sub-group under  SmartSpan \u203a conductor_size  in the tree."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11px; color:#666; padding:4px 0;")
        root.addWidget(hint)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _on_accept(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Conductor name cannot be empty.")
            return
        if " " in name:
            QMessageBox.warning(self, "Invalid Name",
                                "Conductor name must not contain spaces.\n"
                                "Use underscores or hyphens instead (e.g. HT_ACSR).")
            return
        v_map = {0: "LT", 1: "HT", 2: "Both"}
        voltage = v_map.get(self._voltage.currentIndex(), "Both")
        sizes: list[str] = []
        seen: set = set()
        for raw in self._sizes.text().split(","):
            s = raw.strip()
            if s and s.casefold() not in seen:
                seen.add(s.casefold())
                sizes.append(s)
        self.result_name    = name
        self.result_voltage = voltage
        self.result_sizes   = sizes
        self.accept()


class PropertyEditorDialog(QDialog):
    """
    Tree-based Property Editor.

    Tree structure
    --------------
    ObjectType
      ▸ Fixed Properties
          propName  [variant]   — height, conductor_size have per-category sub-groups
            Sub-category        — e.g. "STP  (9 / 9.5 / 11 m)"
                9MTR            — grey/italic = built-in
                15MTR           — blue/bold   = user-added  → deletable
          propName  [list]      — all other list props; options shown as leaves
          propName  [int/text]  — single info row, no children
      ▸ Custom Properties
          customLabel           — user-defined, editable / deletable

    Buttons
    -------
    + Add Custom Property  — type / custom_group / custom_prop selected
    + Add Option Value     — fixed_prop(list), fixed_variant, or any option leaf
    ✕ Remove User Option   — only when a blue user-added option leaf is selected
    Edit Custom            — custom_prop selected
    Delete Custom          — custom_prop selected
    """

    _TYPE_LABELS: dict[str, str] = {
        "SmartPole":      "SmartPole  (LT / HT / Existing Pole)",
        "SmartStructure": "SmartStructure  (DP / TP / 4P / DTR)",
        "SmartSpan":      "SmartSpan  (AB Cable / ACSR / PVC Cable / Service Drop)",
        "SmartConsumer":  "SmartConsumer  (Service Point)",
    }

    # (obj_type, prop_name) → [(display_label, ext_key, [base_values])]
    # These properties get per-category sub-group children instead of a flat option list.
    # ext_key is the key used in property_catalog extended_options (compound: "prop__variant").
    _VARIANT_PROPS: dict[tuple, list] = {
        ("SmartPole",      "height"): [],  # dynamically built by _height_variants_for()
        ("SmartStructure", "height"): [],  # dynamically built by _height_variants_for()
        ("SmartSpan", "conductor_size"): [],  # dynamically extended via _conductor_size_variants()
    }

    _N_TYPE          = "type"
    _N_FIXED_GROUP   = "fixed_group"
    _N_CUSTOM_GROUP  = "custom_group"
    _N_FIXED_PROP    = "fixed_prop"
    _N_FIXED_VARIANT = "fixed_variant"
    _N_BASE_OPTION   = "base_opt"
    _N_EXT_OPTION    = "ext_opt"
    _N_CUSTOM_PROP   = "custom_prop"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Property Editor")
        self.resize(980, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Tab container ─────────────────────────────────────────────────────
        self._main_tabs = QTabWidget()
        self._main_tabs.addTab(self._build_properties_tab(),          "Properties")
        self._main_tabs.addTab(self._build_symbols_tab(),             "Canvas Symbols")
        self._main_tabs.addTab(self._build_heights_conductors_tab(),  "Heights & Sizes")
        root.addWidget(self._main_tabs, 1)

        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        root.addWidget(close_btns)

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _build_properties_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)

        intro = QLabel(
            "Each object type lists its fixed and custom properties.\n"
            "\u2022 Fixed property options shown in grey/italic are built-in and cannot be removed.\n"
            "\u2022 Options shown in blue/bold are user-added \u2014 select one and click  \u2715 Remove User Option  to delete it.\n"
            "\u2022 Height and conductor-size are split by sub-category so you can add values precisely "
            "(e.g. add 15MTR only under STP Heights, or a new cable size only under LT \u00b7 AB Cable).\n"
            "\u2022 Custom properties are entirely user-defined and appear as extra fields in the canvas object editor."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:11px; color:#555; padding:4px;")
        lay.addWidget(intro)

        # ── Tree ──────────────────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Property / Value", "Info"])
        hdr = self._tree.header()
        if hdr is not None:
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.setIndentation(18)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        lay.addWidget(self._tree, 1)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_add_custom  = QPushButton("+ Add Custom Property")
        self._btn_add_option  = QPushButton("+ Add Option Value")
        self._btn_remove_opt  = QPushButton("\u2715 Remove User Option")
        self._btn_edit        = QPushButton("Edit Custom")
        self._btn_delete      = QPushButton("Delete Custom")

        self._btn_remove_opt.setStyleSheet(
            "QPushButton { color:#c0392b; border:1px solid #c0392b; border-radius:3px; padding:2px 10px; }"
            "QPushButton:hover { background:#fdecea; }"
            "QPushButton:disabled { color:#ccc; border-color:#ccc; }"
        )
        for btn in (self._btn_add_custom, self._btn_add_option, self._btn_remove_opt,
                    self._btn_edit, self._btn_delete):
            btn.setEnabled(False)
            btn_row.addWidget(btn)
        btn_row.addStretch()

        self._btn_add_custom.clicked.connect(self._add_custom_property)
        self._btn_add_option.clicked.connect(self._add_option)
        self._btn_remove_opt.clicked.connect(self._remove_user_option)
        self._btn_edit.clicked.connect(self._edit_custom_property)
        self._btn_delete.clicked.connect(self._delete_custom_property)
        lay.addLayout(btn_row)

        self._build_tree()
        return w

    def _build_symbols_tab(self) -> QWidget:
        """Canvas symbol colour editor."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        lay   = QVBoxLayout(inner)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        intro = QLabel(
            "Customise the fill / pen colours for each canvas symbol type.\n"
            "Click a colour swatch to change it. Changes are saved immediately."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:11px; color:#555; padding-bottom:6px;")
        lay.addWidget(intro)

        SYMBOL_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
            ("Poles", [
                ("LT Pole fill",              "canvas_lt_pole"),
                ("HT Pole fill",              "canvas_ht_pole"),
                ("Existing Pole fill",         "canvas_ex_pole"),
                ("Existing Aug-DTR fill",      "canvas_ex_aug_dtr"),
            ]),
            ("Structures", [
                ("DP Structure fill",          "canvas_dp"),
                ("TP Structure fill",          "canvas_tp"),
                ("4P Structure fill",          "canvas_4p"),
                ("DTR Sub-Station fill",       "canvas_dtr"),
            ]),
            ("Consumers", [
                ("Consumer (WBSEDCL) fill",    "canvas_consumer"),
                ("Consumer (Agency) fill",     "canvas_consumer_agency"),
            ]),
            ("Span Lines", [
                ("ACSR span colour",           "canvas_acsr"),
                ("AB Cable span colour",       "canvas_ab_cable"),
                ("PVC Cable span colour",      "canvas_pvc_cable"),
                ("Service Drop span colour",   "canvas_svc_drop"),
            ]),
        ]

        for group_label, entries in SYMBOL_GROUPS:
            grp = QGroupBox(group_label)
            frm = QFormLayout(grp)
            frm.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for entry_label, key in entries:
                btn = self._make_color_btn(key)
                frm.addRow(entry_label + ":", btn)
            lay.addWidget(grp)

        reset_btn = QPushButton("\u21a9  Reset all canvas colours to factory defaults")
        reset_btn.clicked.connect(self._reset_symbol_colors)
        lay.addWidget(reset_btn)
        lay.addStretch()

        scroll.setWidget(inner)
        return scroll

    def _make_color_btn(self, default_key: str) -> QPushButton:
        """Return a colour-swatch button that opens QColorDialog on click."""
        hex_val = _defaults_mod.current.get(default_key, "#888888")
        btn     = QPushButton(hex_val)
        btn.setFixedHeight(28)
        btn.setMinimumWidth(120)
        self._apply_color_btn_style(btn, hex_val)
        btn.setProperty("color_key", default_key)
        btn.clicked.connect(lambda _, b=btn, k=default_key: self._pick_color(b, k))
        return btn

    @staticmethod
    def _apply_color_btn_style(btn: "QPushButton", hex_val: str) -> None:
        try:
            r = int(hex_val[1:3], 16)
            g = int(hex_val[3:5], 16)
            b = int(hex_val[5:7], 16)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
        except Exception:
            lum = 128
        text_col = "#000000" if lum > 150 else "#ffffff"
        btn.setStyleSheet(
            f"QPushButton {{ background:{hex_val}; color:{text_col}; "
            f"border:1px solid #999; border-radius:4px; font-weight:bold; }}"
            f"QPushButton:hover {{ border:2px solid #555; }}"
        )
        btn.setText(hex_val)

    def _pick_color(self, btn: "QPushButton", key: str) -> None:
        current_hex = _defaults_mod.current.get(key, "#888888")
        initial     = QColor(current_hex)
        chosen      = QColorDialog.getColor(initial, self, f"Choose colour \u2014 {key}")
        if not chosen.isValid():
            return
        new_hex = chosen.name()
        _defaults_mod.current[key] = new_hex
        _defaults_mod.save(_defaults_mod.current)
        self._apply_color_btn_style(btn, new_hex)

    def _reset_symbol_colors(self) -> None:
        ans = QMessageBox.question(
            self, "Reset Canvas Colours",
            "Reset all canvas symbol colours to factory defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        from core.defaults import _FACTORY
        color_keys = [
            "canvas_lt_pole", "canvas_ht_pole", "canvas_ex_pole", "canvas_ex_aug_dtr",
            "canvas_dp", "canvas_tp", "canvas_4p", "canvas_dtr",
            "canvas_consumer", "canvas_consumer_agency",
            "canvas_acsr", "canvas_ab_cable", "canvas_pvc_cable", "canvas_svc_drop",
        ]
        for k in color_keys:
            _defaults_mod.current[k] = _FACTORY.get(k, _defaults_mod.current.get(k, "#888888"))
        _defaults_mod.save(_defaults_mod.current)
        # Refresh the Canvas Symbols tab
        self._main_tabs.removeTab(1)
        self._main_tabs.addTab(self._build_symbols_tab(), "Canvas Symbols")

    # ── Heights & Sizes tab (C1 + C2) ────────────────────────────────────────

    def _build_heights_conductors_tab(self) -> QWidget:
        """Dedicated manager for pole heights and conductor sizes stored in DB."""
        outer = QWidget()
        lay   = QVBoxLayout(outer)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        intro = QLabel(
            "\u2022 Grey = built-in (cannot be removed)   \u2022 Blue = user-added (select to remove)\n"
            "\u2022 Changes apply immediately to the canvas object editors."
        )
        intro.setStyleSheet("font-size:11px; color:#555;")
        lay.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Heights section ─────────────────────────────────────────────────
        ht_grp = QGroupBox("Pole Heights  (per pole type)")
        ht_lay = QVBoxLayout(ht_grp)
        ht_lay.setContentsMargins(8, 8, 8, 8)
        ht_lay.setSpacing(6)

        self._heights_tree = QTreeWidget()
        self._heights_tree.setColumnCount(2)
        self._heights_tree.setHeaderLabels(["Pole Type / Height", "Info"])
        ht_hdr = self._heights_tree.header()
        if ht_hdr is not None:
            ht_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            ht_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._heights_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._heights_tree.currentItemChanged.connect(self._on_ht_selection)
        ht_lay.addWidget(self._heights_tree, 1)

        ht_btns = QHBoxLayout()
        self._ht_add_btn = QPushButton("+ Add Height")
        self._ht_add_btn.setEnabled(False)
        self._ht_rem_btn = QPushButton("\u2715 Remove")
        self._ht_rem_btn.setEnabled(False)
        self._ht_rem_btn.setStyleSheet(
            "QPushButton{color:#c0392b;border:1px solid #c0392b;border-radius:3px;padding:2px 10px;}"
            "QPushButton:hover{background:#fdecea;}"
            "QPushButton:disabled{color:#ccc;border-color:#ccc;}"
        )
        self._ht_add_btn.clicked.connect(self._on_add_height)
        self._ht_rem_btn.clicked.connect(self._on_remove_height)
        ht_btns.addWidget(self._ht_add_btn)
        ht_btns.addWidget(self._ht_rem_btn)
        ht_btns.addStretch()
        ht_lay.addLayout(ht_btns)
        self._refresh_heights_tree()
        splitter.addWidget(ht_grp)

        # ── Conductor Sizes section ──────────────────────────────────────────
        cd_grp = QGroupBox("Conductor Sizes  (per type and voltage class)")
        cd_lay = QVBoxLayout(cd_grp)
        cd_lay.setContentsMargins(8, 8, 8, 8)
        cd_lay.setSpacing(6)

        self._conductors_tree = QTreeWidget()
        self._conductors_tree.setColumnCount(2)
        self._conductors_tree.setHeaderLabels(["Conductor / Size", "Info"])
        cd_hdr = self._conductors_tree.header()
        if cd_hdr is not None:
            cd_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            cd_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._conductors_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._conductors_tree.currentItemChanged.connect(self._on_cd_selection)
        cd_lay.addWidget(self._conductors_tree, 1)

        cd_btns = QHBoxLayout()
        self._cd_add_btn = QPushButton("+ Add Size")
        self._cd_add_btn.setEnabled(False)
        self._cd_rem_btn = QPushButton("\u2715 Remove")
        self._cd_rem_btn.setEnabled(False)
        self._cd_rem_btn.setStyleSheet(
            "QPushButton{color:#c0392b;border:1px solid #c0392b;border-radius:3px;padding:2px 10px;}"
            "QPushButton:hover{background:#fdecea;}"
            "QPushButton:disabled{color:#ccc;border-color:#ccc;}"
        )
        self._cd_add_btn.clicked.connect(self._on_add_conductor_size)
        self._cd_rem_btn.clicked.connect(self._on_remove_conductor_size)
        cd_btns.addWidget(self._cd_add_btn)
        cd_btns.addWidget(self._cd_rem_btn)
        cd_btns.addStretch()
        cd_lay.addLayout(cd_btns)
        self._refresh_conductors_tree()
        splitter.addWidget(cd_grp)

        lay.addWidget(splitter, 1)
        return outer

    def _refresh_heights_tree(self) -> None:
        self._heights_tree.clear()
        from core import db_gateway as _dbg  # noqa: PLC0415
        detail = _dbg.get_all_height_options_detail()
        for pt2, heights in sorted(detail.items()):
            root = QTreeWidgetItem(self._heights_tree, [pt2, f"{len(heights)} value(s)"])
            root.setData(0, Qt.ItemDataRole.UserRole, {"scope": "ht_pt2", "pt2": pt2})
            root.setExpanded(True)
            _font_bold = QFont(); _font_bold.setBold(True)
            for h in heights:
                child = QTreeWidgetItem(root, [h["val"],
                                               "built-in" if h["builtin"] else "user-added"])
                child.setData(0, Qt.ItemDataRole.UserRole,
                              {"scope": "ht_val", "pt2": pt2,
                               "val": h["val"], "builtin": h["builtin"]})
                if h["builtin"]:
                    child.setForeground(0, QColor("#888888"))
                    child.setForeground(1, QColor("#888888"))
                else:
                    child.setForeground(0, QColor("#185FA5"))
                    child.setFont(0, _font_bold)

    def _on_ht_selection(self, current, _prev) -> None:
        if current is None:
            self._ht_add_btn.setEnabled(False)
            self._ht_rem_btn.setEnabled(False)
            return
        nd = current.data(0, Qt.ItemDataRole.UserRole) or {}
        scope = nd.get("scope", "")
        self._ht_add_btn.setEnabled(scope in ("ht_pt2", "ht_val"))
        self._ht_rem_btn.setEnabled(scope == "ht_val" and not nd.get("builtin", True))

    def _on_add_height(self) -> None:
        from core import db_gateway as _dbg  # noqa: PLC0415
        item = self._heights_tree.currentItem()
        nd   = item.data(0, Qt.ItemDataRole.UserRole) if item else {}
        pt2  = nd.get("pt2", "")

        pole_types = list(_dbg.get_all_height_options_detail().keys())
        if not pole_types:
            pole_types = ["PCC", "STP", "H-BEAM"]

        pole_type, ok1 = QInputDialog.getItem(
            self, "Add Height — Step 1", "Pole type:", pole_types,
            pole_types.index(pt2) if pt2 in pole_types else 0, False,
        )
        if not ok1:
            return

        val, ok2 = QInputDialog.getText(
            self, "Add Height — Step 2",
            f"Height value for  {pole_type}  (e.g. 15MTR, 20MTR):",
        )
        if not ok2 or not val.strip():
            return
        val = val.strip().upper()
        if not val.endswith("MTR"):
            val += "MTR"

        added = _dbg.add_height_option(pole_type, val)
        if not added:
            QMessageBox.information(self, "Duplicate",
                                    f"'{val}' already exists for {pole_type}.")
        self._refresh_heights_tree()

    def _on_remove_height(self) -> None:
        item = self._heights_tree.currentItem()
        if not item:
            return
        nd = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if nd.get("scope") != "ht_val" or nd.get("builtin"):
            return
        pt2 = nd["pt2"]
        val = nd["val"]
        reply = QMessageBox.question(
            self, "Remove Height",
            f"Remove  '{val}'  from  {pt2}?\n\n"
            "Canvas objects already using this value keep it until manually changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.remove_height_option(pt2, val)
        self._refresh_heights_tree()

    def _refresh_conductors_tree(self) -> None:
        self._conductors_tree.clear()
        from core import db_gateway as _dbg  # noqa: PLC0415
        detail = _dbg.get_all_conductor_options_detail()
        _font_bold = QFont(); _font_bold.setBold(True)
        for (ct, vc), sizes in sorted(detail.items()):
            label = f"{ct}  \u00b7  {vc}"
            root  = QTreeWidgetItem(self._conductors_tree,
                                    [label, f"{len(sizes)} size(s)"])
            root.setData(0, Qt.ItemDataRole.UserRole,
                         {"scope": "cd_group", "ct": ct, "vc": vc})
            root.setExpanded(True)
            for s in sizes:
                child = QTreeWidgetItem(root, [s["val"],
                                               "built-in" if s["builtin"] else "user-added"])
                child.setData(0, Qt.ItemDataRole.UserRole,
                              {"scope": "cd_val", "ct": ct, "vc": vc,
                               "val": s["val"], "builtin": s["builtin"]})
                if s["builtin"]:
                    child.setForeground(0, QColor("#888888"))
                    child.setForeground(1, QColor("#888888"))
                else:
                    child.setForeground(0, QColor("#185FA5"))
                    child.setFont(0, _font_bold)

    def _on_cd_selection(self, current, _prev) -> None:
        if current is None:
            self._cd_add_btn.setEnabled(False)
            self._cd_rem_btn.setEnabled(False)
            return
        nd    = current.data(0, Qt.ItemDataRole.UserRole) or {}
        scope = nd.get("scope", "")
        self._cd_add_btn.setEnabled(scope in ("cd_group", "cd_val"))
        self._cd_rem_btn.setEnabled(scope == "cd_val" and not nd.get("builtin", True))

    def _on_add_conductor_size(self) -> None:
        from core import db_gateway as _dbg  # noqa: PLC0415
        item = self._conductors_tree.currentItem()
        nd   = item.data(0, Qt.ItemDataRole.UserRole) if item else {}

        detail = _dbg.get_all_conductor_options_detail()
        cond_types  = sorted({ct for ct, _vc in detail})
        volt_classes = ["LT", "HT"]

        default_ct = nd.get("ct", cond_types[0] if cond_types else "")
        default_vc = nd.get("vc", "LT")

        ct, ok1 = QInputDialog.getItem(
            self, "Add Size — Step 1", "Conductor type:", cond_types,
            cond_types.index(default_ct) if default_ct in cond_types else 0, False,
        )
        if not ok1:
            return

        vc, ok2 = QInputDialog.getItem(
            self, "Add Size — Step 2", "Voltage class:", volt_classes,
            volt_classes.index(default_vc) if default_vc in volt_classes else 0, False,
        )
        if not ok2:
            return

        val, ok3 = QInputDialog.getText(
            self, "Add Size — Step 3",
            f"Size value for  {ct} ({vc})  (e.g. 70SQMM, 3CX120+1CX70):",
        )
        if not ok3 or not val.strip():
            return

        added = _dbg.add_conductor_option(ct, vc, val.strip())
        if not added:
            QMessageBox.information(self, "Duplicate",
                                    f"'{val.strip()}' already exists for {ct} ({vc}).")
        self._refresh_conductors_tree()

    def _on_remove_conductor_size(self) -> None:
        item = self._conductors_tree.currentItem()
        if not item:
            return
        nd = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if nd.get("scope") != "cd_val" or nd.get("builtin"):
            return
        ct  = nd["ct"]
        vc  = nd["vc"]
        val = nd["val"]
        reply = QMessageBox.question(
            self, "Remove Size",
            f"Remove  '{val}'  from  {ct} ({vc})?\n\n"
            "Canvas objects already using this value keep it until manually changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.remove_conductor_option(ct, vc, val)
        self._refresh_conductors_tree()

    # ── Tree helpers ──────────────────────────────────────────────────────────

    def _node_data(self, item: QTreeWidgetItem) -> dict:
        return item.data(0, Qt.ItemDataRole.UserRole) or {}

    def _set_node(self, item: QTreeWidgetItem, data: dict) -> None:
        item.setData(0, Qt.ItemDataRole.UserRole, data)

    def _make_base_leaf(self, value: str) -> QTreeWidgetItem:
        leaf = QTreeWidgetItem([f"          {value}", "built-in"])
        dim = QColor("#999999")
        leaf.setForeground(0, dim)
        leaf.setForeground(1, dim)
        f = QFont()
        f.setItalic(True)
        leaf.setFont(0, f)
        self._set_node(leaf, {"node": self._N_BASE_OPTION})
        return leaf

    def _make_ext_leaf(
        self,
        value: str,
        obj_type: str,
        ext_key: str,
        label_override: str | None = None,
        info_override:  str | None = None,
        extra:          dict | None = None,
    ) -> QTreeWidgetItem:
        lbl  = label_override or f"          {value}"
        info = info_override  or "\u270e user-added  \u2014  select + \u2715 Remove to delete"
        leaf = QTreeWidgetItem([lbl, info])
        leaf.setForeground(0, QColor("#1a5276"))
        leaf.setForeground(1, QColor("#7f8c8d"))
        f = QFont()
        f.setBold(True)
        leaf.setFont(0, f)
        data: dict = {
            "node":     self._N_EXT_OPTION,
            "obj_type": obj_type,
            "ext_key":  ext_key,
            "value":    value,
        }
        if extra:
            data.update(extra)
        self._set_node(leaf, data)
        return leaf

    # ── Tree construction ─────────────────────────────────────────────────────

    def _build_tree(self) -> None:
        self._tree.clear()
        rules  = self._load_rules()
        usage  = property_catalog.usage_details(rules)
        grey   = QColor("#555555")
        dim    = QColor("#999999")
        blue   = QColor("#1a5276")

        for obj_type in property_catalog.OBJECT_TYPES:
            # ── Object-type root ──────────────────────────────────────────────
            type_item = QTreeWidgetItem([self._TYPE_LABELS.get(obj_type, obj_type), ""])
            f = QFont()
            f.setBold(True)
            f.setPointSize(10)
            type_item.setFont(0, f)
            self._set_node(type_item, {"node": self._N_TYPE, "obj_type": obj_type})
            self._tree.addTopLevelItem(type_item)

            # ── Fixed Properties group ────────────────────────────────────────
            fixed_grp = QTreeWidgetItem(["  \u25b8 Fixed Properties", "built-in, cannot rename or delete"])
            fixed_grp.setForeground(0, grey)
            fixed_grp.setForeground(1, dim)
            self._set_node(fixed_grp, {"node": self._N_FIXED_GROUP, "obj_type": obj_type})
            type_item.addChild(fixed_grp)

            base_props = PROPERTY_DATA.get(obj_type, {})
            for prop_name, prop_val in base_props.items():
                vkey = (obj_type, prop_name)

                if vkey in self._VARIANT_PROPS:
                    # ── Variant prop (height / conductor_size) ────────────────
                    if vkey == ("SmartSpan", "conductor_size"):
                        variants = self._conductor_size_variants()
                    elif prop_name == "height":
                        variants = self._height_variants_for(obj_type)
                    else:
                        variants = self._VARIANT_PROPS[vkey]
                    total_ext   = sum(
                        len(property_catalog.get_extended_options(obj_type, vd[1]))
                        for vd in variants
                    )
                    summary = f"{len(variants)} sub-categories"
                    if total_ext:
                        summary += f"  \u2022  {total_ext} user-added option(s)"
                    prop_item = QTreeWidgetItem([f"    {prop_name}", summary])
                    pf = QFont()
                    pf.setBold(True)
                    prop_item.setFont(0, pf)
                    self._set_node(prop_item, {
                        "node": self._N_FIXED_PROP,
                        "obj_type": obj_type,
                        "prop": prop_name,
                        "is_list": True,
                        "is_variant": True,
                    })
                    fixed_grp.addChild(prop_item)

                    for disp, ext_key, base_vals in variants:
                        ext_vals  = property_catalog.get_extended_options(obj_type, ext_key)
                        total     = len(base_vals) + len(ext_vals)
                        var_desc  = f"{total} option(s)"
                        if ext_vals:
                            var_desc += f"  \u2022  {len(ext_vals)} user-added"
                        var_item = QTreeWidgetItem([f"      {disp}", var_desc])
                        vf = QFont()
                        vf.setBold(True)
                        var_item.setFont(0, vf)
                        var_item.setForeground(0, QColor("#2c3e50"))
                        self._set_node(var_item, {
                            "node": self._N_FIXED_VARIANT,
                            "obj_type": obj_type,
                            "prop": prop_name,
                            "ext_key": ext_key,
                        })
                        prop_item.addChild(var_item)
                        for bv in base_vals:
                            var_item.addChild(self._make_base_leaf(str(bv)))
                        for ev in ext_vals:
                            var_item.addChild(self._make_ext_leaf(ev, obj_type, ext_key))
                        var_item.setExpanded(bool(ext_vals))

                    prop_item.setExpanded(True)

                elif isinstance(prop_val, list):
                    # ── Regular list prop (flat option leaves) ────────────────
                    ext     = property_catalog.get_extended_options(obj_type, prop_name)
                    is_cond = (obj_type == "SmartSpan" and prop_name == "conductor")
                    summary = f"{len(prop_val)} option(s)"
                    if ext:
                        summary += f"  \u2022  {len(ext)} user-added"
                    prop_item = QTreeWidgetItem([f"    {prop_name}", summary])
                    self._set_node(prop_item, {
                        "node": self._N_FIXED_PROP,
                        "obj_type": obj_type,
                        "prop": prop_name,
                        "is_list": True,
                        "is_variant": False,
                    })
                    fixed_grp.addChild(prop_item)
                    for bv in prop_val:
                        prop_item.addChild(self._make_base_leaf(str(bv)))
                    for ev in ext:
                        if is_cond:
                            meta    = property_catalog.get_conductor_meta(ev)
                            voltage = meta.get("voltage", "Both")
                            vtag    = {"LT": " [LT only]", "HT": " [HT only]", "Both": " [LT + HT]"}.get(voltage, "")
                            prop_item.addChild(self._make_ext_leaf(
                                ev, obj_type, prop_name,
                                label_override=f"          {ev}{vtag}",
                                info_override="\u270e user conductor \u2014 \u2715 Remove | Edit to change voltage",
                                extra={"is_conductor": True},
                            ))
                        else:
                            prop_item.addChild(self._make_ext_leaf(ev, obj_type, prop_name))
                    if ext:
                        prop_item.setExpanded(True)

                else:
                    # ── Non-list prop (int / text) ────────────────────────────
                    type_str  = "numeric (integer)" if prop_val == "int" else "free text"
                    prop_item = QTreeWidgetItem([f"    {prop_name}", f"[{type_str}]"])
                    prop_item.setForeground(1, dim)
                    self._set_node(prop_item, {
                        "node": self._N_FIXED_PROP,
                        "obj_type": obj_type,
                        "prop": prop_name,
                        "is_list": False,
                        "is_variant": False,
                    })
                    fixed_grp.addChild(prop_item)

            # ── Custom Properties group ───────────────────────────────────────
            custom_grp = QTreeWidgetItem([
                "  \u25b8 Custom Properties",
                "user-defined \u2014 appear in the object editor on the canvas",
            ])
            custom_grp.setForeground(0, grey)
            custom_grp.setForeground(1, dim)
            self._set_node(custom_grp, {"node": self._N_CUSTOM_GROUP, "obj_type": obj_type})
            type_item.addChild(custom_grp)

            for entry in property_catalog.get_custom_entries(obj_type):
                label   = entry["label"]
                options = entry.get("options", [])
                hits    = usage.get(label, [])
                opts_str  = ", ".join(options) if options else "(marker \u2013 no options)"
                usage_str = (
                    f"  [used in {len(hits)} rule(s)]" if hits
                    else "  [not referenced in any rule]"
                )
                custom_item = QTreeWidgetItem([f"    {label}", opts_str + usage_str])
                cf = QFont()
                cf.setBold(True)
                custom_item.setFont(0, cf)
                custom_item.setForeground(0, QColor("#6c3483"))
                self._set_node(custom_item, {
                    "node": self._N_CUSTOM_PROP,
                    "obj_type": obj_type,
                    "label": label,
                })
                custom_grp.addChild(custom_item)

            type_item.setExpanded(True)
            fixed_grp.setExpanded(True)
            custom_grp.setExpanded(True)

    # ── Selection handler ─────────────────────────────────────────────────────

    def _on_selection_changed(
        self,
        current_item: QTreeWidgetItem | None,
        _previous,
    ) -> None:
        for btn in (self._btn_add_custom, self._btn_add_option, self._btn_remove_opt,
                    self._btn_edit, self._btn_delete):
            btn.setEnabled(False)

        if current_item is None:
            return

        nd   = self._node_data(current_item)
        node = nd.get("node", "")

        # Add Custom Property
        if node in (self._N_TYPE, self._N_CUSTOM_GROUP, self._N_CUSTOM_PROP):
            self._btn_add_custom.setEnabled(True)

        # Add Option Value
        if node == self._N_FIXED_VARIANT:
            self._btn_add_option.setEnabled(True)
        elif node == self._N_FIXED_PROP and nd.get("is_list"):
            self._btn_add_option.setEnabled(True)
        elif node in (self._N_BASE_OPTION, self._N_EXT_OPTION):
            self._btn_add_option.setEnabled(True)
        elif node == self._N_CUSTOM_PROP:
            self._btn_add_option.setEnabled(True)

        # Remove User Option — only for user-added leaves
        if node == self._N_EXT_OPTION:
            self._btn_remove_opt.setEnabled(True)
            if nd.get("is_conductor"):
                # Conductor leaf: disable “add option” (use conductor_size section);
                # enable “edit” to let the user change its voltage affinity.
                self._btn_add_option.setEnabled(False)
                self._btn_edit.setEnabled(True)

        # Edit / Delete Custom
        if node == self._N_CUSTOM_PROP:
            self._btn_edit.setEnabled(True)
            self._btn_delete.setEnabled(True)

    # ── Resolve add-target from current selection ─────────────────────────────

    def _resolve_add_target(self) -> "tuple[str, str] | None":
        """Return (obj_type, ext_key) that 'Add Option Value' should write to."""
        item = self._tree.currentItem()
        if item is None:
            return None
        nd   = self._node_data(item)
        node = nd.get("node", "")

        if node == self._N_FIXED_VARIANT:
            return nd.get("obj_type"), nd.get("ext_key")

        if node in (self._N_BASE_OPTION, self._N_EXT_OPTION):
            parent = item.parent()
            if parent is None:
                return None
            pnd   = self._node_data(parent)
            pnode = pnd.get("node", "")
            if pnode == self._N_FIXED_VARIANT:
                return pnd.get("obj_type"), pnd.get("ext_key")
            if pnode == self._N_FIXED_PROP and not pnd.get("is_variant"):
                return pnd.get("obj_type"), pnd.get("prop")

        if node == self._N_FIXED_PROP and nd.get("is_list") and not nd.get("is_variant"):
            return nd.get("obj_type"), nd.get("prop")

        return None

    # ── Actions ───────────────────────────────────────────────────────────────

    def _load_rules(self) -> list[dict]:
        try:
            from core import db_gateway as _dbg  # noqa: PLC0415
            return _dbg.get_rules(enabled_only=False)
        except Exception:
            try:
                with open(get_data_path("rules.json"), "r", encoding="utf-8") as handle:
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

        label    = dlg.result_entry["label"]
        existing = {e["label"].casefold() for e in property_catalog.get_custom_entries(obj_type)}
        if label.casefold() in existing:
            QMessageBox.warning(
                self, "Duplicate",
                f"A custom property '{label}' already exists for {obj_type}.",
            )
            return

        property_catalog.add_custom_entry(obj_type, label, dlg.result_entry.get("options", []))
        self._build_tree()

    def _add_option(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        nd   = self._node_data(item)
        node = nd.get("node", "")

        # ── Custom property — add an option value ─────────────────────────────
        if node == self._N_CUSTOM_PROP:
            obj_type = nd["obj_type"]
            label    = nd["label"]
            option, ok = QInputDialog.getText(
                self,
                f"Add Option \u2013 {label}",
                f"New option value for custom property  '{label}'  ({obj_type}):",
            )
            if not ok or not option.strip():
                return
            option = option.strip()
            for entry in property_catalog.get_custom_entries(obj_type):
                if entry["label"].casefold() == label.casefold():
                    if option.casefold() in {o.casefold() for o in entry["options"]}:
                        QMessageBox.information(self, "Duplicate", f"'{option}' already exists.")
                        return
                    property_catalog.update_custom_entry(
                        obj_type, label, label, entry["options"] + [option]
                    )
                    break
            self._build_tree()
            return

        # ── Fixed property or variant — add via extended_options ──────────────
        target = self._resolve_add_target()
        if target is None:
            return
        obj_type, ext_key = target

        # Special case: adding a new conductor type to SmartSpan
        if obj_type == "SmartSpan" and ext_key == "conductor":
            self._add_user_conductor()
            return

        # Build human-readable context label for the prompt
        if "__" in ext_key:
            prop, variant = ext_key.split("__", 1)
            ctx = f"{obj_type}  \u203a  {prop}  \u203a  {variant.replace('_', ' ')}"
        else:
            ctx = f"{obj_type}  \u203a  {ext_key}"

        option, ok = QInputDialog.getText(
            self,
            "Add Option Value",
            f"New value to add to:\n{ctx}",
        )
        if not ok or not option.strip():
            return

        added = property_catalog.add_extended_option(obj_type, ext_key, option.strip())
        if not added:
            QMessageBox.information(
                self, "Duplicate",
                f"'{option.strip()}' already exists in this property.",
            )
        else:
            self._build_tree()

    def _remove_user_option(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        nd = self._node_data(item)
        if nd.get("node") != self._N_EXT_OPTION:
            return

        obj_type = nd["obj_type"]
        ext_key  = nd["ext_key"]
        value    = nd["value"]

        if "__" in ext_key:
            prop, variant = ext_key.split("__", 1)
            ctx = f"{prop}  \u203a  {variant.replace('_', ' ')}"
        else:
            ctx = ext_key

        is_cond = nd.get("is_conductor", False)
        if is_cond:
            confirm_msg = (
                f"Delete conductor '{value}' from {obj_type}?\n\n"
                f"This will also remove its voltage setting and ALL its size options\n"
                f"from the catalog. Spans already using '{value}' keep it until you\n"
                f"manually change them."
            )
            dlg_title = "Delete User Conductor"
        else:
            confirm_msg = (
                f"Remove  '{value}'  from  {obj_type}  \u203a  {ctx}?\n\n"
                f"Canvas objects that currently use this value will keep it until you change them manually."
            )
            dlg_title = "Remove User-Added Option"

        answer = QMessageBox.question(
            self, dlg_title, confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if is_cond:
            property_catalog.delete_user_conductor(value)
        else:
            property_catalog.remove_extended_option(obj_type, ext_key, value)
        self._build_tree()

    def _edit_custom_property(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        nd = self._node_data(item)

        # User-conductor leaf: edit voltage affinity via ConductorMetaDialog
        if nd.get("node") == self._N_EXT_OPTION and nd.get("is_conductor"):
            self._edit_user_conductor(nd["value"])
            return

        if nd.get("node") != self._N_CUSTOM_PROP:
            return

        obj_type = nd["obj_type"]
        label    = nd["label"]

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
            dlg._label.setReadOnly(True)

        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_entry is None:
            return

        new_label   = dlg.result_entry["label"]
        new_options = dlg.result_entry.get("options", [])

        if new_label.casefold() != label.casefold():
            existing = {e["label"].casefold() for e in property_catalog.get_custom_entries(obj_type)}
            if new_label.casefold() in existing:
                QMessageBox.warning(
                    self, "Duplicate",
                    f"A custom property '{new_label}' already exists for {obj_type}.",
                )
                return

        property_catalog.update_custom_entry(obj_type, label, new_label, new_options)
        self._build_tree()

    def _height_variants_for(self, obj_type: str) -> list:
        """Return height sub-group list, including user-added pole_type2 entries."""
        variants: list = [
            ("PCC  (8 / 9 m)",        "height__PCC",    ["8MTR", "9MTR"]),
            ("STP  (9 / 9.5 / 11 m)", "height__STP",    ["9MTR", "9.5MTR", "11MTR"]),
            ("H-BEAM  (13 m)",         "height__H-BEAM", ["13MTR"]),
        ]
        for user_pt2 in property_catalog.get_extended_options(obj_type, "pole_type2"):
            variants.append((
                f"{user_pt2}  \u2460 user",
                f"height__{user_pt2}",
                [],
            ))
        return variants

    def _conductor_size_variants(self) -> list:
        """Return the full conductor_size sub-group list, including user-added conductors."""
        variants: list = [
            ("LT  \u00b7  AB Cable",  "conductor_size__lt_AB Cable",
             ["3CX50+1CX35", "3CX50+1CX16+1CX35", "3CX70+1CX16+1CX50"]),
            ("LT  \u00b7  ACSR",      "conductor_size__lt_ACSR",      ["30SQMM", "50SQMM"]),
            ("LT  \u00b7  PVC Cable", "conductor_size__lt_PVC Cable",
             ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM", "95 SQMM", "120 SQMM"]),
            ("HT  \u00b7  AB Cable",  "conductor_size__ht_AB Cable",  ["3CX50+1CX150", "3CX95+1CX70"]),
            ("HT  \u00b7  ACSR",      "conductor_size__ht_ACSR",      ["30SQMM", "50SQMM"]),
            ("HT  \u00b7  PVC Cable", "conductor_size__ht_PVC Cable",
             ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM", "95 SQMM", "120 SQMM"]),
        ]
        for uc in property_catalog.get_user_conductors():
            name    = uc["name"]
            voltage = uc["voltage"]
            if voltage in ("LT", "Both"):
                variants.append((
                    f"LT  \u00b7  {name}  \u2460 user",
                    f"conductor_size__lt_{name}",
                    [],
                ))
            if voltage in ("HT", "Both"):
                variants.append((
                    f"HT  \u00b7  {name}  \u2460 user",
                    f"conductor_size__ht_{name}",
                    [],
                ))
        return variants

    def _add_user_conductor(self) -> None:
        """Open ConductorMetaDialog to create a new user-defined conductor type."""
        dlg = ConductorMetaDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_name:
            return
        name    = dlg.result_name
        voltage = dlg.result_voltage
        sizes   = dlg.result_sizes
        built_in = {"ACSR", "AB Cable", "PVC Cable", "Service Drop"}
        existing = set(property_catalog.get_extended_options("SmartSpan", "conductor"))
        if name in built_in or name in existing:
            QMessageBox.warning(self, "Duplicate",
                                f"A conductor named '{name}' already exists.")
            return
        property_catalog.add_extended_option("SmartSpan", "conductor", name)
        property_catalog.set_conductor_meta(name, voltage)
        for sz in sizes:
            if voltage in ("LT", "Both"):
                property_catalog.add_extended_option("SmartSpan", f"conductor_size__lt_{name}", sz)
            if voltage in ("HT", "Both"):
                property_catalog.add_extended_option("SmartSpan", f"conductor_size__ht_{name}", sz)
        self._build_tree()

    def _edit_user_conductor(self, conductor_name: str) -> None:
        """Open ConductorMetaDialog to change the voltage affinity of an existing user conductor."""
        meta = property_catalog.get_conductor_meta(conductor_name)
        dlg  = ConductorMetaDialog(
            conductor_name=conductor_name,
            existing_voltage=meta.get("voltage", "Both"),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_voltage = dlg.result_voltage
        old_voltage = meta.get("voltage", "Both")
        if new_voltage == old_voltage:
            return
        property_catalog.set_conductor_meta(conductor_name, new_voltage)
        if old_voltage == "Both":
            lost = "LT" if new_voltage == "HT" else "HT"
            QMessageBox.information(
                self, "Voltage Changed",
                f"'{conductor_name}' is now {new_voltage} only.\n"
                f"Existing {lost} size options are still stored and will be shown again\n"
                f"if you change the voltage back to 'Both'.",
            )
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

