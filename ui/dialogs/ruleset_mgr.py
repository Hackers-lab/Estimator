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

import os
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
from ui.dialogs.search import SearchDialog

class RulesetManagerDialog(QDialog):
    """
    Full rule builder with three panels:

    Left   — hierarchical tree (SmartPole / SmartStructure / SmartSpan /
             SmartConsumer → sub-types) with search and rule counts.

    Centre — filtered card list with:
             • search box + AND/OR logic toggle
             • context-aware filter chips
             • collapsible Simulator strip

    Right  — rule editor:
             • item type / name / code picker
             • condition row builder with dropdowns
             • live condition preview
             • quantity formula input
             • Delete / Save footer

    All tree/chip/simulator data imported from constants.py — no
    hardcoded class-level dicts here.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ruleset Manager")
        self.setGeometry(60, 60, 1440, 880)

        # State
        self.rules               = []
        self.selected_rule_index = -1
        self.selected_result_item = None
        self.condition_widgets   = []
        self.active_tree_filter  = {}
        self.active_obj_type     = "SmartPole"
        self.filter_logic        = "AND"
        self.active_chips        = set()
        self.sim_visible           = False
        self.sim_widgets           = {}
        self._view_mode            = "grouped"   # "flat" | "grouped"
        self._editor_mode          = "rule"      # "rule" | "group"
        self._group_edit_indices   = []          # rule indices for current group edit

        self._build_ui()
        self.load_rules()
        self._select_tree_root("SmartPole")

    # ═════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ═════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._build_left())
        root.addWidget(self._build_centre())
        root.addWidget(self._build_right())

    @staticmethod
    def _combo_box_stylesheet() -> str:
        return (
            "QComboBox { color:#222; background:white; border:0.5px solid #ccc; "
            "border-radius:4px; padding:3px 6px; font-size:12px; }"
            "QComboBox QAbstractItemView { color:#222; background:white; "
            "selection-color:#222; selection-background-color:#ddeeff; }"
        )

    # ── LEFT ──────────────────────────────────────────────────────────────────

    def _build_left(self):
        panel = QWidget()
        panel.setFixedWidth(230)
        panel.setStyleSheet("background:#f5f5f5; border-right:1px solid #ddd;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tree_search = QLineEdit()
        self._tree_search.setPlaceholderText("Search tree…")
        self._tree_search.setStyleSheet(
            "margin:6px; padding:4px 8px; border:0.5px solid #ccc;"
            "border-radius:4px; font-size:12px;"
        )
        self._tree_search.textChanged.connect(self._filter_tree)
        lay.addWidget(self._tree_search)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet("""
            QTreeWidget { border:none; background:#f5f5f5; font-size:12px; }
            QTreeWidget::item { padding:4px 6px; }
            QTreeWidget::item:selected { background:#ddeeff; color:#0C447C; }
            QTreeWidget::item:hover:!selected { background:#ebebeb; }
        """)
        self._tree.itemClicked.connect(self._on_tree_click)
        lay.addWidget(self._tree)

        self._populate_tree()
        return panel

    def _populate_tree(self):
        self._tree.clear()
        self._tree_items = []   # (QTreeWidgetItem, obj_type, filter_dict)

        # Overview dashboard node — always at the top of the tree
        ov_item = QTreeWidgetItem(self._tree, ["\U0001f4ca  Overview"])
        ov_item.setData(0, Qt.ItemDataRole.UserRole, ("__dashboard__", {}))
        ov_item.setToolTip(0, "Rule count summary across all object types")
        self._tree_items.append((ov_item, "__dashboard__", {}))

        def add_node(parent, label, obj_type, fdict, children):
            item = QTreeWidgetItem(
                parent if parent else self._tree, [label]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, (obj_type, fdict))
            self._tree_items.append((item, obj_type, fdict))
            for ch in children:
                add_node(item, ch[0], ch[1], ch[2], ch[3])
            return item

        for entry in TREE_DEF:
            add_node(None, entry[0], entry[1], entry[2], entry[3])

        self._update_tree_counts()
        self._tree.expandToDepth(1)

    def _update_tree_counts(self):
        for item, obj_type, fdict in self._tree_items:
            if obj_type == "__dashboard__":
                continue
            base  = item.text(0).split("  ")[0]
            count = len(self._get_matching_rules(obj_type, fdict, set()))
            item.setText(0, f"{base}  ({count})" if count else base)

    def _filter_tree(self, text: str):
        text = text.lower()
        for item, *_ in self._tree_items:
            item.setHidden(bool(text) and text not in item.text(0).lower())

    def _select_tree_root(self, obj_type: str):
        for item, ot, fd in self._tree_items:
            if ot == obj_type and not fd:
                self._tree.setCurrentItem(item)
                self._on_tree_click(item, 0)
                return

    def _on_tree_click(self, item, _col):
        obj_type, fdict = item.data(0, Qt.ItemDataRole.UserRole)
        if obj_type == "__dashboard__":
            self.active_chips.clear()
            self.selected_rule_index = -1
            self._chip_bar.setVisible(False)
            self._clear_editor()
            self._show_dashboard()
            return
        self.active_obj_type    = obj_type
        self.active_tree_filter = fdict
        self.active_chips.clear()
        self.selected_rule_index = -1
        self._rebuild_chips()
        self._refresh_cards()
        self._clear_editor()
        self._update_centre_title()

    # ── CENTRE ────────────────────────────────────────────────────────────────

    def _build_centre(self):
        self._centre = QWidget()
        lay = QVBoxLayout(self._centre)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Top bar
        topbar = QWidget()
        topbar.setStyleSheet("background:white; border-bottom:1px solid #ddd;")
        tl = QHBoxLayout(topbar)
        tl.setContentsMargins(10, 7, 10, 7)
        tl.setSpacing(8)

        self._centre_title = QLabel("")
        self._centre_title.setStyleSheet("font-weight:bold; font-size:13px;")

        self._card_search = QLineEdit()
        self._card_search.setPlaceholderText("Search rules…")
        self._card_search.setStyleSheet(
            "padding:4px 8px; border:0.5px solid #ccc; "
            "border-radius:4px; font-size:12px; max-width:200px;"
        )
        self._card_search.textChanged.connect(self._refresh_cards)

        self._type_filter = QComboBox()
        self._type_filter.addItems(["All", "Material", "Labor"])
        self._type_filter.setFixedWidth(86)
        self._type_filter.setStyleSheet(self._combo_box_stylesheet())
        self._type_filter.currentTextChanged.connect(self._refresh_cards)

        self._logic_btn = QPushButton("AND")
        self._logic_btn.setCheckable(True)
        self._logic_btn.setChecked(True)
        self._logic_btn.setFixedWidth(46)
        self._logic_btn.setStyleSheet(
            "QPushButton{padding:4px; border:1px solid #ccc;"
            "border-radius:4px; font-size:11px; font-weight:bold;}"
            "QPushButton:checked{background:#185FA5; color:white; border-color:#185FA5;}"
        )
        self._logic_btn.clicked.connect(self._toggle_logic)

        self._view_btn = QPushButton("☰ Flat")
        self._view_btn.setCheckable(True)
        self._view_btn.setChecked(True)
        self._view_btn.setFixedWidth(74)
        self._view_btn.setStyleSheet(
            "QPushButton{padding:4px; border:1px solid #ccc;"
            "border-radius:4px; font-size:11px;}"
            "QPushButton:checked{background:#5DCAA5; color:white; border-color:#3aab85;}"
        )
        self._view_btn.clicked.connect(self._toggle_view_mode)

        new_btn = QPushButton("+ New rule")
        new_btn.setStyleSheet(
            "background:#185FA5; color:white; border:none; "
            "padding:5px 12px; border-radius:4px; font-size:12px;"
        )
        new_btn.clicked.connect(self.create_new_rule)

        tl.addWidget(self._centre_title)
        tl.addStretch()
        tl.addWidget(self._card_search)
        tl.addWidget(self._type_filter)
        tl.addWidget(self._view_btn)
        tl.addWidget(self._logic_btn)
        tl.addWidget(new_btn)
        lay.addWidget(topbar)

        # Chip bar
        self._chip_bar = QWidget()
        self._chip_bar.setStyleSheet(
            "background:#fafafa; border-bottom:1px solid #eee;"
        )
        self._chip_layout = QHBoxLayout(self._chip_bar)
        self._chip_layout.setContentsMargins(10, 5, 10, 5)
        self._chip_layout.setSpacing(6)
        lay.addWidget(self._chip_bar)

        # Card scroll area
        self._card_container = QWidget()
        self._card_container.setStyleSheet("background:#f8f8f8;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(8, 8, 8, 8)
        self._card_layout.setSpacing(5)
        self._card_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._card_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(scroll, 1)

        # Simulator (collapsed by default)
        lay.addWidget(self._build_sim_panel())
        return self._centre

    def _toggle_logic(self):
        self.filter_logic = "AND" if self._logic_btn.isChecked() else "OR"
        self._logic_btn.setText(self.filter_logic)
        self._refresh_cards()

    def _toggle_view_mode(self):
        self._view_mode = "grouped" if self._view_btn.isChecked() else "flat"
        self._view_btn.setText("☰ Flat" if self._view_mode == "grouped" else "⊞ Group")
        self._refresh_cards()

    def _rebuild_chips(self):
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

        chips = FILTER_CHIPS.get(self.active_obj_type, [])
        self._chip_bar.setVisible(bool(chips))
        if not chips:
            return

        lbl = QLabel("Filter:")
        lbl.setStyleSheet("font-size:11px; color:#888;")
        self._chip_layout.addWidget(lbl)

        self._chip_checks = {}
        for label, key, val in chips:
            cb = QCheckBox(label)
            cb.setStyleSheet(
                "QCheckBox{font-size:11px; padding:2px 6px;"
                "border:0.5px solid #ccc; border-radius:10px; background:white;}"
                "QCheckBox:checked{background:#ddeeff;"
                "border-color:#378ADD; color:#0C447C;}"
            )
            chip_key = (key, str(val))
            cb.stateChanged.connect(
                lambda state, k=chip_key: self._on_chip(k, state)
            )
            self._chip_layout.addWidget(cb)
            self._chip_checks[chip_key] = cb

        self._chip_layout.addStretch()

    def _on_chip(self, chip_key, state):
        if state:
            self.active_chips.add(chip_key)
        else:
            self.active_chips.discard(chip_key)
        self._refresh_cards()

    def _update_centre_title(self):
        visible = self._visible_indices()
        self._centre_title.setText(
            f"{self.active_obj_type.replace('Smart','')}  —  "
            f"{len(visible)} rule(s)"
        )

    # ── Card list ─────────────────────────────────────────────────────────────

    @staticmethod
    def _cond_has(cond: str, key: str, val_str: str) -> bool:
        """Return True when a condition string contains a key/value test."""
        if key == "condition_true":
            return cond.strip() in ("", "True")

        if key.endswith("_gt"):
            base = key[:-3]
            return (f"{base} >" in cond) or (f"{base}>" in cond)
        if key.endswith("_ne"):
            base = key[:-3]
            return (
                f"{base} != '{val_str}'" in cond or
                f"{base} != \"{val_str}\"" in cond or
                f"{base} != {val_str}" in cond
            )

        if val_str.lower() == "false":
            return (
                f"not {key}" in cond or
                f"{key} == False" in cond
            )
        if val_str.lower() == "true":
            return (
                (key in cond and f"not {key}" not in cond)
                or f"{key} == True" in cond
            )

        return (
            f"{key} == '{val_str}'" in cond or
            f"{key} == \"{val_str}\"" in cond or
            f"{key} == {val_str}" in cond
        )

    def _get_matching_rules(self, obj_type, fdict, chips):
        result = []
        for i, rule in enumerate(self.rules):
            if rule.get("object") != obj_type:
                continue
            cond = rule.get("condition", "")

            if fdict:
                ok = True
                for prop, val in fdict.items():
                    vs = str(val)
                    if not self._cond_has(cond, prop, vs):
                        ok = False
                        break
                if not ok:
                    continue

            if chips:
                chip_results = []
                for (key, val_str) in chips:
                    match = self._cond_has(cond, key, val_str)
                    chip_results.append(match)

                if self.filter_logic == "AND" and not all(chip_results):
                    continue
                if self.filter_logic == "OR" and not any(chip_results):
                    continue

            result.append((i, rule))
        return result

    def _visible_indices(self):
        search = (
            self._card_search.text().lower()
            if hasattr(self, "_card_search") else ""
        )
        type_filter = (
            self._type_filter.currentText()
            if hasattr(self, "_type_filter") else "All"
        )
        matched = self._get_matching_rules(
            self.active_obj_type, self.active_tree_filter, self.active_chips
        )
        if type_filter != "All":
            matched = [
                (i, r) for i, r in matched
                if r.get("type", "Material") == type_filter
            ]
        if search:
            matched = [
                (i, r) for i, r in matched
                if search in r.get("item_name", "").lower()
                or search in r.get("condition", "").lower()
            ]
        return matched

    def _refresh_cards(self):
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

        matched   = self._visible_indices()
        sim_hits  = self._sim_hits() if self.sim_visible else set()

        if self._view_mode == "grouped":
            self._render_grouped_cards(matched, sim_hits)
        else:
            for orig_idx, rule in matched:
                card = self._make_card(orig_idx, rule, orig_idx in sim_hits)
                self._card_layout.insertWidget(
                    self._card_layout.count() - 1, card
                )

        self._update_centre_title()
        self._update_tree_counts()

    def _make_card(self, rule_index, rule, sim_hit=False):
        card     = ClickableCard(lambda idx=rule_index: self._on_card(idx))
        selected = rule_index == self.selected_rule_index
        enabled  = bool(rule.get("enabled", 1))

        if not enabled:
            bc = "#378ADD" if selected else "#bbb"
            bw = "1.5px" if selected else "0.5px"
            bg = "#f5f5f5"
        else:
            bc = "#378ADD" if selected else ("#5DCAA5" if sim_hit else "#ddd")
            bw = "1.5px"   if (selected or sim_hit) else "0.5px"
            bg = "#eaf8f4" if sim_hit else "white"
        card.setStyleSheet(
            f"background:{bg}; border:{bw} solid {bc}; border-radius:6px;"
        )
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(9, 7, 9, 7)
        lay.setSpacing(8)

        r_type = rule.get("type", "Material")
        badge  = QLabel("M" if r_type == "Material" else "L")
        badge.setFixedSize(24, 24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "border-radius:4px; font-size:10px; font-weight:bold; " + (
                "background:#ddeeff; color:#185FA5;" if r_type == "Material"
                else "background:#fff3e0; color:#854F0B;"
            )
        )
        lay.addWidget(badge)

        body = QWidget()
        bl   = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(1)

        name_l = QLabel(rule.get("item_name", "Unnamed"))
        name_style = "font-size:12px; font-weight:bold;"
        if not enabled:
            name_style += " color:#aaa; text-decoration:line-through;"
        name_l.setStyleSheet(name_style)

        cond_l = QLabel(rule.get("condition", "") or "(no condition)")
        cond_l.setStyleSheet(
            f"font-size:11px; color:{'#bbb' if not enabled else '#555'};"
            " font-family:monospace;"
        )
        form_l = QLabel(f"qty = {rule.get('formula','1')}")
        form_l.setStyleSheet(
            f"font-size:10px; color:{'#ccc' if not enabled else '#999'};"
        )
        bl.addWidget(name_l)
        bl.addWidget(cond_l)
        bl.addWidget(form_l)
        lay.addWidget(body, 1)

        toggle_cb = QCheckBox()
        toggle_cb.setToolTip("Enable / disable this rule")
        toggle_cb.setChecked(enabled)
        toggle_cb.setStyleSheet("margin-left:4px;")
        toggle_cb.stateChanged.connect(
            lambda state, idx=rule_index, r=rule:
                self._on_rule_toggle(idx, r, bool(state))
        )
        lay.addWidget(toggle_cb)

        return card

    # ── Condition tag pills ─────────────────────────────────────────────

    @staticmethod
    def _condition_to_pills(cond: str) -> list:
        """Parse a condition string into [(label, bg_color, fg_color)] pills."""
        if not cond or cond.strip() in ("True", ""):
            return [("always", "#e8e8e8", "#555")]

        _KEY_COLORS = {
            # ── pole/structure status ─────────────────────────────────────
            "is_existing":           ("#fdecea", "#b71c1c"),
            "is_new":                ("#e8f5e9", "#1b5e20"),
            # ── span status ───────────────────────────────────────────────
            "is_existing_span":      ("#fdecea", "#b71c1c"),
            "is_new_span":           ("#e8f5e9", "#1b5e20"),
            "is_distribution_span":  ("#ddeeff", "#185FA5"),
            "is_service_drop":       ("#fff3e0", "#a04000"),
            "is_lt_span":            ("#dff5ff", "#0a6080"),
            "is_ht_span":            ("#f3e8ff", "#6a1fb0"),
            # ── pole identity ─────────────────────────────────────────────
            "pole_type":             ("#ddeeff", "#185FA5"),
            "pole_type2":            ("#e0f7f7", "#176b6b"),
            "height":                ("#f3e8ff", "#6a1fb0"),
            "structure_type":        ("#eee8ff", "#4a20a0"),
            # ── span identity ─────────────────────────────────────────────
            "conductor":             ("#ddeeff", "#0a3f80"),
            "conductor_size":        ("#e8f0ff", "#3058a0"),
            "aug_type":              ("#fff0e0", "#7a4000"),
            "wire_count":            ("#e8f0e8", "#2a5a2a"),
            "phase":                 ("#fce4ec", "#b71c4a"),
            # ── hardware ──────────────────────────────────────────────────
            "dtr_size":              ("#e8f4ea", "#1a5c2a"),
            "earth_count_gt":        ("#ffeef0", "#a01030"),
            "stay_count_gt":         ("#ffeef0", "#a01030"),
            "has_cg":                ("#fefce8", "#706000"),
            "has_extension":         ("#fefce8", "#706000"),
            "ab_cable_count_gt":     ("#e0f7f4", "#0a6b5a"),
            "ab_needs_dead_end":     ("#e0f7f4", "#0a6b5a"),
            "ab_needs_suspension":   ("#e0f7f4", "#0a6b5a"),
            # ── supply / project ──────────────────────────────────────────
            "use_uh":                ("#fffde7", "#706000"),
            "agency_supply":         ("#f3e5f5", "#6a1b9a"),
            "consider_cable":        ("#e8f4ea", "#1a5c2a"),
            "project_type":          ("#e8eaf6", "#3949ab"),
        }
        _default = ("#f0f0f0", "#444")
        # (key, str_value) -> human label
        _LABEL_OVERRIDES = {
            # ── pole / structure status ───────────────────────────────────
            ("is_existing",          "True"):  "EX. POLE",
            ("is_existing",          "False"): "NEW POLE",
            ("is_new",               "True"):  "NEW POLE",
            ("is_new",               "False"): "EX. POLE",
            # ── span status ───────────────────────────────────────────────
            ("is_existing_span",     "True"):  "EX. SPAN",
            ("is_existing_span",     "False"): "NEW SPAN",
            ("is_new_span",          "True"):  "NEW SPAN",
            ("is_new_span",          "False"): "EX. SPAN",
            ("is_distribution_span", "True"):  "DIST. SPAN",
            ("is_distribution_span", "False"): "SVC DROP",
            ("is_service_drop",      "True"):  "SVC DROP",
            ("is_service_drop",      "False"): "DIST. SPAN",
            ("is_lt_span",           "True"):  "LT SPAN",
            ("is_lt_span",           "False"): "HT SPAN",
            ("is_ht_span",           "True"):  "HT SPAN",
            ("is_ht_span",           "False"): "LT SPAN",
            # ── hardware booleans ─────────────────────────────────────────
            ("has_cg",               "True"):  "WITH CG",
            ("has_cg",               "False"): "NO CG",
            ("has_extension",        "True"):  "WITH EXT.",
            ("has_extension",        "False"): "NO EXT.",
            ("ab_needs_dead_end",    "True"):  "DEAD END",
            ("ab_needs_suspension",  "True"):  "SUSPENSION",
            ("dist_box_required",    "True"):  "DIST BOX",
            # ── supply ───────────────────────────────────────────────────
            ("use_uh",               "True"):  "UH MATS",
            ("use_uh",               "False"): "RAW MATS",
            ("agency_supply",        "True"):  "AGENCY SUPPLY",
            ("agency_supply",        "False"): "SELF SUPPLY",
            ("consider_cable",       "True"):  "WITH CABLE",
            ("consider_cable",       "False"): "NO CABLE",
        }

        pills = []
        clauses = re.split(r'\s+(?:and|or)\s+', cond, flags=re.IGNORECASE)
        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            # not key
            m = re.match(r'^not\s+(\w+)$', clause)
            if m:
                key = m.group(1)
                label = _LABEL_OVERRIDES.get((key, "False"), f"\u00ac{key}")
                bg, fg = _KEY_COLORS.get(key, _default)
                pills.append((label, bg, fg))
                continue
            # bare key (truthy)
            m = re.match(r'^(\w+)$', clause)
            if m:
                key = m.group(1)
                label = _LABEL_OVERRIDES.get((key, "True"), key)
                bg, fg = _KEY_COLORS.get(key, _default)
                pills.append((label, bg, fg))
                continue
            # key op 'value' or key op value
            m = re.match(
                r"^(\w+)\s*(==|!=|>=|<=|>|<)\s*['\"]?(.+?)['\"]?$", clause
            )
            if m:
                key  = m.group(1)
                op   = m.group(2)
                val  = m.group(3).strip().strip("'\"")
                label = _LABEL_OVERRIDES.get((key, val))
                if label is None:
                    if op == "==":
                        label = val
                    elif op == "!=":
                        label = f"\u2260{val}"
                    elif op in (">", ">="):
                        _sym = "\u2265" if op == ">=" else ">"
                        label = f"{key}{_sym}{val}"
                    elif op in ("<", "<="):
                        _sym = "\u2264" if op == "<=" else "<"
                        label = f"{key}{_sym}{val}"
                    else:
                        label = f"{key}{op}{val}"
                bg, fg = _KEY_COLORS.get(key, _default)
                pills.append((label, bg, fg))
                continue
            # fallback: truncated clause
            pills.append((
                clause[:14] + ("\u2026" if len(clause) > 14 else ""),
                "#f0f0f0", "#444"
            ))

        return pills if pills else [("condition", "#f0f0f0", "#444")]

    # ── Grouped view ──────────────────────────────────────────────────────────

    def _render_grouped_cards(self, matched, sim_hits):
        """Render rules grouped by identical condition string."""
        from collections import OrderedDict
        groups = OrderedDict()
        for orig_idx, rule in matched:
            key = rule.get("condition", "") or ""
            groups.setdefault(key, []).append((orig_idx, rule))

        for cond, items in groups.items():
            mat_count = sum(1 for _, r in items if r.get("type") == "Material")
            lab_count = sum(1 for _, r in items if r.get("type") == "Labor")
            grp_hit   = any(i in sim_hits for i, _ in items)
            grp_sel   = any(i == self.selected_rule_index for i, _ in items)
            group_w   = self._make_group_widget(
                cond, mat_count, lab_count, items, sim_hits, grp_hit, grp_sel
            )
            self._card_layout.insertWidget(self._card_layout.count() - 1, group_w)

    def _make_group_widget(self, cond, mat_count, lab_count, items,
                           sim_hits, grp_hit, grp_sel):
        """Build a collapsible group card for rules sharing the same condition."""
        outer = QWidget()
        bc_outer = "#378ADD" if grp_sel else ("#3aab85" if grp_hit else "#ccc")
        outer.setStyleSheet(
            f"background:white; border:1px solid {bc_outer}; "
            "border-radius:6px; margin-bottom:4px;"
        )
        outer_l = QVBoxLayout(outer)
        outer_l.setContentsMargins(0, 0, 0, 0)
        outer_l.setSpacing(0)

        # Header
        hdr_bg = "#eaf8f4" if grp_hit else ("#eef4fb" if grp_sel else "#f0f4f8")
        header = QWidget()
        header.setStyleSheet(
            f"background:{hdr_bg}; border-radius:5px 5px 0px 0px;"
        )
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 7, 10, 7)
        hl.setSpacing(6)

        toggle_lbl = QLabel("▼")
        toggle_lbl.setStyleSheet("font-size:10px; color:#888; min-width:12px;")
        hl.addWidget(toggle_lbl)

        # Pill row (replaces raw condition label)
        pills_w = QWidget()
        pills_w.setToolTip(cond or "(no condition)")
        pills_l = QHBoxLayout(pills_w)
        pills_l.setContentsMargins(0, 0, 0, 0)
        pills_l.setSpacing(3)
        for p_label, p_bg, p_fg in self._condition_to_pills(cond):
            pill = QLabel(p_label)
            pill.setStyleSheet(
                f"background:{p_bg}; color:{p_fg}; border-radius:3px; "
                "padding:1px 6px; font-size:10px; font-weight:bold;"
            )
            pills_l.addWidget(pill)
        pills_l.addStretch()
        hl.addWidget(pills_w, 1)

        if mat_count:
            mb = QLabel(f"{mat_count}M")
            mb.setFixedSize(26, 18)
            mb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mb.setStyleSheet(
                "background:#ddeeff; color:#185FA5; border-radius:3px; "
                "font-size:10px; font-weight:bold;"
            )
            hl.addWidget(mb)
        if lab_count:
            lb = QLabel(f"{lab_count}L")
            lb.setFixedSize(26, 18)
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet(
                "background:#fff3e0; color:#854F0B; border-radius:3px; "
                "font-size:10px; font-weight:bold;"
            )
            hl.addWidget(lb)

        rule_indices = [i for i, _ in items]

        add_btn = QPushButton("+ Add")
        add_btn.setFixedHeight(22)
        add_btn.setStyleSheet(
            "background:#185FA5; color:white; border:none; "
            "border-radius:3px; font-size:10px; padding:0px 6px;"
        )
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(
            lambda _checked=False, c=cond: self._add_to_group_rule(c)
        )
        hl.addWidget(add_btn)

        edit_btn = QPushButton("\u270f Edit")
        edit_btn.setFixedHeight(22)
        edit_btn.setStyleSheet(
            "background:#f0f4f8; color:#185FA5; border:1px solid #aac; "
            "border-radius:3px; font-size:10px; padding:0px 6px;"
        )
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(
            lambda _checked=False, c=cond, idx=rule_indices:
                self._build_group_editor(c, idx)
        )
        hl.addWidget(edit_btn)

        outer_l.addWidget(header)

        # Child rows container
        children_w = QWidget()
        children_w.setStyleSheet(
            "background:transparent; border-top:0.5px solid #e0e0e0;"
        )
        cl = QVBoxLayout(children_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        for orig_idx, rule in items:
            child = self._make_child_row(orig_idx, rule, orig_idx in sim_hits)
            cl.addWidget(child)

        outer_l.addWidget(children_w)

        # Collapse toggle
        def _toggle():
            vis = not children_w.isVisible()
            children_w.setVisible(vis)
            toggle_lbl.setText("▼" if vis else "▶")

        def _header_mouse_press(a0=None):
            _toggle()

        header.mousePressEvent = _header_mouse_press
        return outer

    def _make_child_row(self, rule_index, rule, sim_hit=False):
        """Build one item row inside a condition group."""
        card     = ClickableCard(lambda idx=rule_index: self._on_card(idx))
        selected = rule_index == self.selected_rule_index
        enabled  = bool(rule.get("enabled", 1))

        bc = "#378ADD" if selected else ("#5DCAA5" if sim_hit else "#e8e8e8")
        bg = "#eaf8f4" if sim_hit else (
            "#eef4fb" if selected else ("#f5f5f5" if not enabled else "#fafafa")
        )
        card.setStyleSheet(
            f"background:{bg}; border-left:2px solid {bc}; "
            "border-radius:0px;"
        )
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(30, 5, 10, 5)
        lay.setSpacing(8)

        r_type = rule.get("type", "Material")
        badge  = QLabel("M" if r_type == "Material" else "L")
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "border-radius:4px; font-size:10px; font-weight:bold; " + (
                "background:#ddeeff; color:#185FA5;" if r_type == "Material"
                else "background:#fff3e0; color:#854F0B;"
            )
        )
        lay.addWidget(badge)

        name_lbl = QLabel(rule.get("item_name", "Unnamed"))
        name_style = "font-size:12px;"
        if not enabled:
            name_style += " color:#aaa; text-decoration:line-through;"
        name_lbl.setStyleSheet(name_style)
        lay.addWidget(name_lbl, 1)

        code_lbl = QLabel(rule.get("item_code", ""))
        code_lbl.setStyleSheet("font-size:10px; color:#999;")
        lay.addWidget(code_lbl)

        form_lbl = QLabel(f"\u00d7{rule.get('formula', '1')}")
        form_lbl.setStyleSheet("font-size:10px; color:#bbb;")
        lay.addWidget(form_lbl)

        toggle_cb = QCheckBox()
        toggle_cb.setToolTip("Enable / disable this rule")
        toggle_cb.setChecked(enabled)
        toggle_cb.setStyleSheet("margin-left:4px;")
        toggle_cb.stateChanged.connect(
            lambda state, idx=rule_index, r=rule:
                self._on_rule_toggle(idx, r, bool(state))
        )
        lay.addWidget(toggle_cb)

        return card

    # ── Dashboard ─────────────────────────────────────────────────────────────────

    def _show_dashboard(self):
        """Render object-type summary cards in the centre panel."""
        while self._card_layout.count() > 1:
            itm = self._card_layout.takeAt(0)
            if itm is None:
                continue
            w = itm.widget()
            if w is not None:
                w.deleteLater()

        self._centre_title.setText("Overview  \u2014  All Object Types")

        _OBJ_STYLES = {
            "SmartPole":      ("\U0001f538", "#185FA5", "#ddeeff"),
            "SmartStructure": ("\U0001f537", "#6a1fb0", "#f3e8ff"),
            "SmartSpan":      ("\U0001f539", "#1a6b2a", "#e8f4ea"),
            "SmartConsumer":  ("\U0001f536", "#a04000", "#fff3e0"),
        }
        top_types = [e[1] for e in TREE_DEF]
        for obj_type in top_types:
            obj_rules = [(i, r) for i, r in enumerate(self.rules)
                         if r.get("object") == obj_type]
            n_conds = len(set(r.get("condition", "") for _, r in obj_rules))
            mat_n   = sum(1 for _, r in obj_rules if r.get("type") == "Material")
            lab_n   = sum(1 for _, r in obj_rules if r.get("type") == "Labor")
            icon, fg, bg = _OBJ_STYLES.get(obj_type, ("\u25aa", "#555", "#f0f0f0"))
            card = self._make_dashboard_card(
                obj_type, n_conds, mat_n, lab_n, icon, fg, bg
            )
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

    def _make_dashboard_card(self, obj_type, n_conds, mat_n, lab_n, icon, fg, bg):
        card = ClickableCard(lambda ot=obj_type: self._select_tree_root(ot))
        card.setStyleSheet(
            f"background:{bg}; border:1px solid {fg}55; "
            "border-radius:10px; margin:6px 8px;"
        )
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        title_row = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size:24px;")
        name_lbl = QLabel(obj_type.replace("Smart", "Smart "))
        name_lbl.setStyleSheet(
            f"font-size:15px; font-weight:bold; color:{fg};"
        )
        go_lbl = QLabel("Click to explore \u2192")
        go_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        title_row.addWidget(icon_lbl)
        title_row.addWidget(name_lbl)
        title_row.addStretch()
        title_row.addWidget(go_lbl)
        lay.addLayout(title_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        for label, val, s_bg, s_fg in [
            ("Conditions",  str(n_conds),       "#f0f0f0", "#555"),
            ("Material",    str(mat_n),          "#ddeeff", "#185FA5"),
            ("Labour",      str(lab_n),          "#fff3e0", "#854F0B"),
            ("Total rules", str(mat_n + lab_n),  "#f0f0ff", "#444"),
        ]:
            stat_w = QWidget()
            stat_w.setStyleSheet(f"background:{s_bg}; border-radius:6px;")
            sl = QVBoxLayout(stat_w)
            sl.setContentsMargins(12, 6, 12, 6)
            sl.setSpacing(1)
            n_lbl = QLabel(val)
            n_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n_lbl.setStyleSheet(
                f"font-size:20px; font-weight:bold; color:{s_fg};"
            )
            t_lbl = QLabel(label)
            t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t_lbl.setStyleSheet(f"font-size:10px; color:{s_fg};")
            sl.addWidget(n_lbl)
            sl.addWidget(t_lbl)
            stats_row.addWidget(stat_w)
        stats_row.addStretch()
        lay.addLayout(stats_row)
        return card

    # ── Card click ────────────────────────────────────────────────────────────

    def _on_card(self, rule_index):
        self.selected_rule_index = rule_index
        self._refresh_cards()
        self._build_editor(self.rules[rule_index])

    # ── SIMULATOR ─────────────────────────────────────────────────────────────

    def _build_sim_panel(self):
        self._sim_outer = QWidget()
        self._sim_outer.setStyleSheet(
            "border-top:1px solid #ddd; background:#f5f5f5;"
        )
        ol = QVBoxLayout(self._sim_outer)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)

        self._sim_toggle_btn = QPushButton(
            "▲  Simulator — set values and see which rules fire"
        )
        self._sim_toggle_btn.setStyleSheet(
            "text-align:left; padding:6px 12px; border:none; "
            "background:#f0f0f0; font-size:12px; font-weight:bold; color:#333;"
        )
        self._sim_toggle_btn.clicked.connect(self._toggle_sim)
        ol.addWidget(self._sim_toggle_btn)

        self._sim_body = QWidget()
        self._sim_body.setVisible(False)
        sb = QVBoxLayout(self._sim_body)
        sb.setContentsMargins(10, 8, 10, 8)
        sb.setSpacing(6)

        self._sim_inputs_w = QWidget()
        self._sim_inputs_l = QHBoxLayout(self._sim_inputs_w)
        self._sim_inputs_l.setContentsMargins(0, 0, 0, 0)
        self._sim_inputs_l.setSpacing(8)
        sb.addWidget(self._sim_inputs_w)

        run_row = QHBoxLayout()
        run_btn = QPushButton("▶  Run")
        run_btn.setStyleSheet(
            "background:#185FA5; color:white; border:none; "
            "padding:5px 16px; border-radius:4px; font-size:12px;"
        )
        run_btn.clicked.connect(self._run_sim)
        self._sim_count_lbl = QLabel("")
        self._sim_count_lbl.setStyleSheet(
            "font-size:12px; color:#0F6E56; font-weight:bold;"
        )
        run_row.addWidget(run_btn)
        run_row.addWidget(self._sim_count_lbl)
        run_row.addStretch()
        sb.addLayout(run_row)

        self._sim_table = QTableWidget(0, 4)
        self._sim_table.setHorizontalHeaderLabels(
            ["Type", "Item", "Qty", "Formula"]
        )
        sim_hdr = self._sim_table.horizontalHeader()
        if sim_hdr is not None:
            sim_hdr.setSectionResizeMode(
                1, QHeaderView.ResizeMode.Stretch
            )
        self._sim_table.setMaximumHeight(160)
        self._sim_table.setStyleSheet("font-size:11px;")
        self._sim_table.setVisible(False)
        sb.addWidget(self._sim_table)

        ol.addWidget(self._sim_body)
        return self._sim_outer

    def _toggle_sim(self):
        self.sim_visible = not self.sim_visible
        self._sim_body.setVisible(self.sim_visible)
        arrow = "▼" if self.sim_visible else "▲"
        self._sim_toggle_btn.setText(
            f"{arrow}  Simulator — set values and see which rules fire"
        )
        if self.sim_visible:
            self._rebuild_sim_inputs()

    def _rebuild_sim_inputs(self):
        while self._sim_inputs_l.count():
            item = self._sim_inputs_l.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.sim_widgets = {}

        defaults = _runtime_sim_defaults().get(self.active_obj_type, {})
        for prop, (wtype, options, default) in defaults.items():
            col = QWidget()
            cl  = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            lbl = QLabel(prop)
            lbl.setStyleSheet("font-size:10px; color:#666;")
            cl.addWidget(lbl)

            if wtype == "combo":
                w = QComboBox()
                w.addItems([str(o) for o in options])
                w.setCurrentText(str(default))
                w.setStyleSheet("font-size:11px; padding:3px;")
            else:  # spin
                w = QSpinBox()
                w.setRange(options[0], options[1])
                w.setValue(default)
                w.setStyleSheet("font-size:11px; padding:3px;")
                w.setFixedWidth(64)

            cl.addWidget(w)
            self.sim_widgets[prop] = w
            self._sim_inputs_l.addWidget(col)
        self._sim_inputs_l.addStretch()

    def _get_sim_ctx(self) -> dict:
        ctx = {
            "use_uh":       False,
            "object_type":  self.active_obj_type,
            "project_type": "NSC",
        }
        for prop, w in self.sim_widgets.items():
            if isinstance(w, QSpinBox):
                ctx[prop] = w.value()
            else:
                val = w.currentText()
                if val == "True":
                    ctx[prop] = True
                elif val == "False":
                    ctx[prop] = False
                else:
                    try:
                        ctx[prop] = int(val)
                    except ValueError:
                        ctx[prop] = val
        return ctx

    def _sim_hits(self) -> set:
        if not self.sim_widgets:
            return set()
        ctx  = self._get_sim_ctx()
        hits = set()
        import math as _math
        for i, rule in enumerate(self.rules):
            if rule.get("object") != self.active_obj_type:
                continue
            cond = rule.get("condition", "True") or "True"
            try:
                if eval(
                    cond,
                    {"__builtins__": {}, "math": _math},
                    ctx
                ):
                    hits.add(i)
            except Exception:
                pass
        return hits

    def _run_sim(self):
        import math as _math
        ctx  = self._get_sim_ctx()
        hits = self._sim_hits()
        self._refresh_cards()

        self._sim_table.setRowCount(0)
        self._sim_table.setVisible(bool(hits))
        mat_n = lab_n = 0

        for i in sorted(hits):
            rule    = self.rules[i]
            r_type  = rule.get("type", "")
            formula = rule.get("formula", "1")
            try:
                qty = eval(
                    formula,
                    {"__builtins__": {"int": int, "round": round},
                     "math": _math},
                    ctx
                )
                qty_s = f"{qty:.3f}".rstrip("0").rstrip(".")
            except Exception:
                qty_s = formula

            r = self._sim_table.rowCount()
            self._sim_table.insertRow(r)
            self._sim_table.setItem(r, 0, QTableWidgetItem(r_type))
            self._sim_table.setItem(r, 1, QTableWidgetItem(rule.get("item_name", "")))
            self._sim_table.setItem(r, 2, QTableWidgetItem(qty_s))
            self._sim_table.setItem(r, 3, QTableWidgetItem(formula))
            if r_type == "Material":
                mat_n += 1
            else:
                lab_n += 1

        total = len(hits)
        self._sim_count_lbl.setText(
            f"{total} rule(s) fire  |  {mat_n} material, {lab_n} labour"
            if total else "No rules matched."
        )

    # ── RIGHT — editor ────────────────────────────────────────────────────────

    def _build_right(self):
        self._editor_outer = QWidget()
        self._editor_outer.setFixedWidth(400)
        self._editor_outer.setStyleSheet(
            "border-left:1px solid #ddd; background:white;"
        )
        lay = QVBoxLayout(self._editor_outer)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._editor_hdr = QLabel("Select a rule to edit")
        self._editor_hdr.setStyleSheet(
            "font-weight:bold; font-size:13px; padding:10px 14px;"
            "border-bottom:1px solid #ddd;"
        )
        lay.addWidget(self._editor_hdr)

        self._editor_body   = QWidget()
        self._editor_body_l = QVBoxLayout(self._editor_body)
        self._editor_body_l.setContentsMargins(14, 12, 14, 12)
        self._editor_body_l.setSpacing(10)
        self._editor_body_l.addStretch()

        scr = QScrollArea()
        scr.setWidget(self._editor_body)
        scr.setWidgetResizable(True)
        scr.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(scr, 1)

        # Footer
        footer = QWidget()
        footer.setStyleSheet("border-top:1px solid #ddd; background:white;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 8, 12, 8)

        self._del_btn = QPushButton("🗑 Delete")
        self._del_btn.setStyleSheet(
            "color:#c0392b; border:1px solid #c0392b; padding:5px 10px;"
            "border-radius:4px; background:white; font-size:12px;"
        )
        self._del_btn.clicked.connect(self.delete_selected_rule)
        self._del_btn.setEnabled(False)

        self._save_btn = QPushButton("💾 Save rule")
        self._save_btn.setStyleSheet(
            "background:#27ae60; color:white; border:none; padding:5px 14px;"
            "border-radius:4px; font-weight:bold; font-size:12px;"
        )
        self._save_btn.clicked.connect(self.save_rule_changes)
        self._save_btn.setEnabled(False)

        fl.addWidget(self._del_btn)
        fl.addStretch()
        fl.addWidget(self._save_btn)
        lay.addWidget(footer)
        return self._editor_outer

    # ── Editor helpers ────────────────────────────────────────────────────────

    def _sec_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size:10px; font-weight:bold; color:#888; "
            "text-transform:uppercase; padding-bottom:4px; "
            "border-bottom:1px solid #eee; letter-spacing:.05em;"
        )
        return lbl

    def _field_row(self, label_text: str, widget: QWidget) -> QWidget:
        row = QWidget()
        rl  = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size:11px; color:#666;")
        lbl.setFixedWidth(54)
        rl.addWidget(lbl)
        rl.addWidget(widget, 1)
        return row

    def _clear_editor(self):
        self._clear_layout(self._editor_body_l)
        self._editor_body_l.addStretch()
        self._editor_hdr.setText("Select a rule to edit")
        self._save_btn.setEnabled(False)
        self._save_btn.setText("\U0001f4be Save rule")
        self._del_btn.setEnabled(False)
        self.condition_widgets    = []
        self.selected_result_item = None
        self._editor_mode         = "rule"

    def _build_group_editor(self, cond: str, rule_indices: list):
        """Right-panel editor for updating the shared condition on all group rules."""
        self._group_edit_indices = rule_indices
        self._editor_mode        = "group"
        self._clear_layout(self._editor_body_l)
        self.condition_widgets    = []
        self.selected_result_item = None
        self.selected_rule_index  = -1

        self._editor_hdr.setText(f"Group condition  ({len(rule_indices)} rules)")
        self._save_btn.setText("\U0001f4be Save group condition")
        self._save_btn.setEnabled(True)
        self._del_btn.setEnabled(False)

        self._editor_body_l.addWidget(self._sec_lbl("Shared Condition"))

        warn = QLabel(
            f"\u26a0  This will overwrite the condition on all "
            f"{len(rule_indices)} rule(s) in this group."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "font-size:11px; color:#a15c00; background:#fff8e1; "
            "border-radius:4px; padding:6px 8px;"
        )
        self._editor_body_l.addWidget(warn)

        self._raw_cond_input = QLineEdit(cond)
        self._raw_cond_input.setStyleSheet(
            "font-family:monospace; font-size:12px;"
        )
        self._editor_body_l.addWidget(self._raw_cond_input)

        self._editor_body_l.addWidget(self._sec_lbl("Rules in this group"))
        for idx in rule_indices:
            rule   = self.rules[idx]
            r_type = rule.get("type", "Material")
            lbl    = QLabel(
                f"[{'M' if r_type == 'Material' else 'L'}]  "
                f"{rule.get('item_name', 'Unnamed')}  "
                f"\u2014  {rule.get('item_code', '')}"
            )
            lbl.setStyleSheet(
                "font-size:11px; color:#444; padding:2px 0px;"
            )
            self._editor_body_l.addWidget(lbl)

        self._editor_body_l.addStretch()

    def _save_group_condition(self):
        """Apply the edited condition to every rule in the current group."""
        new_cond = self._raw_cond_input.text().strip()
        for idx in self._group_edit_indices:
            self.rules[idx]["condition"] = new_cond
        self.save_rules()
        self._update_tree_counts()
        self._refresh_cards()
        n = len(self._group_edit_indices)
        QMessageBox.information(
            self, "Saved", f"Condition updated on {n} rule(s)."
        )

    def _add_to_group_rule(self, cond: str):
        """Create a new rule pre-seeded with the given group condition."""
        new_rule = {
            "object":    self.active_obj_type,
            "item_name": "New item \u2014 edit me",
            "condition": cond,
            "type":      "Material",
            "item_code": "N/A",
            "formula":   "1",
        }
        self.rules.append(new_rule)
        self.save_rules()
        self.selected_rule_index = len(self.rules) - 1
        self._editor_mode        = "rule"
        self._save_btn.setText("\U0001f4be Save rule")
        self._update_tree_counts()
        self._refresh_cards()
        self._build_editor(new_rule)

    def _build_editor(self, rule: dict):
        self._clear_layout(self._editor_body_l)
        self.condition_widgets    = []
        self.selected_result_item = None
        self._editor_mode         = "rule"
        self._save_btn.setText("\U0001f4be Save rule")

        self._editor_hdr.setText(f"Editing: {rule.get('item_name','')}")
        self._save_btn.setEnabled(True)
        self._del_btn.setEnabled(True)

        # Item section
        self._editor_body_l.addWidget(self._sec_lbl("Item"))

        self._type_combo = QComboBox()
        self._type_combo.addItems(["Material", "Labor"])
        self._type_combo.setCurrentText(rule.get("type", "Material"))
        self._type_combo.setStyleSheet(self._combo_box_stylesheet())
        self._editor_body_l.addWidget(self._field_row("Type", self._type_combo))

        self._item_display = QLineEdit(rule.get("item_name", ""))
        self._item_display.setReadOnly(True)
        self._item_display.setStyleSheet("background:#f5f5f5; font-size:12px;")
        change_btn = QPushButton("Change…")
        change_btn.setStyleSheet("font-size:11px; padding:3px 8px;")
        change_btn.clicked.connect(self.search_database_for_item)

        item_row = QWidget()
        ir = QHBoxLayout(item_row)
        ir.setContentsMargins(0, 0, 0, 0)
        ir.setSpacing(4)
        lbl = QLabel("Item")
        lbl.setStyleSheet("font-size:11px; color:#666;")
        lbl.setFixedWidth(54)
        ir.addWidget(lbl)
        ir.addWidget(self._item_display, 1)
        ir.addWidget(change_btn)
        self._editor_body_l.addWidget(item_row)

        self._code_display = QLineEdit(rule.get("item_code", ""))
        self._code_display.setReadOnly(True)
        self._code_display.setStyleSheet(
            "background:#f5f5f5; font-size:11px; color:#888;"
        )
        self._editor_body_l.addWidget(
            self._field_row("Code", self._code_display)
        )

        # Condition section
        self._editor_body_l.addWidget(self._sec_lbl("Conditions"))

        self._cond_container = QWidget()
        self._cond_rows_l    = QVBoxLayout(self._cond_container)
        self._cond_rows_l.setContentsMargins(0, 0, 0, 0)
        self._cond_rows_l.setSpacing(3)
        self._editor_body_l.addWidget(self._cond_container)

        add_cond_btn = QPushButton("+ add condition row")
        add_cond_btn.setStyleSheet(
            "color:#185FA5; background:none; border:none; "
            "font-size:11px; text-align:left;"
        )
        add_cond_btn.clicked.connect(self.add_condition_row)
        self._editor_body_l.addWidget(add_cond_btn)

        # Preview
        self._editor_body_l.addWidget(self._sec_lbl("Condition preview"))
        self._preview_lbl = QLabel("")
        self._preview_lbl.setWordWrap(True)
        self._preview_lbl.setStyleSheet(
            "background:#f0f0f0; border-radius:4px; padding:5px 8px;"
            "font-family:monospace; font-size:11px; color:#333;"
        )
        self._editor_body_l.addWidget(self._preview_lbl)

        # Exact raw condition string (authoritative on save)
        self._editor_body_l.addWidget(self._sec_lbl("Raw condition (exact)"))
        self._raw_cond_input = QLineEdit(rule.get("condition", ""))
        self._raw_cond_input.setStyleSheet(
            "font-family:monospace; font-size:12px;"
        )
        self._editor_body_l.addWidget(self._raw_cond_input)
        self._raw_cond_input.textChanged.connect(self._update_preview)

        apply_builder_btn = QPushButton("Use builder preview as raw condition")
        apply_builder_btn.setStyleSheet(
            "font-size:11px; color:#185FA5; background:none; border:none; text-align:left;"
        )
        apply_builder_btn.clicked.connect(
            lambda: self._raw_cond_input.setText(" ".join(self._build_condition_parts()))
        )
        self._editor_body_l.addWidget(apply_builder_btn)

        self._cond_sync_hint = QLabel("")
        self._cond_sync_hint.setWordWrap(True)
        self._cond_sync_hint.setStyleSheet("font-size:10px; color:#a15c00;")
        self._editor_body_l.addWidget(self._cond_sync_hint)

        # Guided raw-condition composer
        self._editor_body_l.addWidget(self._sec_lbl("Guided condition composer"))

        helper_row = QWidget()
        hr = QHBoxLayout(helper_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(4)

        obj_props = list(_runtime_property_data().get(rule.get("object", self.active_obj_type), {}).keys())
        self._expr_prop_cb = QComboBox()
        self._expr_prop_cb.addItems(obj_props)
        self._expr_prop_cb.setToolTip("Available condition keys for this object")
        self._expr_prop_cb.setStyleSheet(self._combo_box_stylesheet())

        self._expr_op_cb = QComboBox()
        self._expr_op_cb.addItems(["==", "!=", ">", "<", ">=", "<=", "in", "not in"])
        self._expr_op_cb.setFixedWidth(70)
        self._expr_op_cb.setStyleSheet(self._combo_box_stylesheet())

        self._expr_val_w = QLineEdit()
        self._expr_val_w.setPlaceholderText("value")

        ins_clause_btn = QPushButton("Insert clause")
        ins_clause_btn.setStyleSheet("font-size:11px; padding:3px 8px;")
        ins_clause_btn.clicked.connect(self._insert_clause_from_helper)

        hr.addWidget(self._expr_prop_cb, 2)
        hr.addWidget(self._expr_op_cb)
        hr.addWidget(self._expr_val_w, 2)
        hr.addWidget(ins_clause_btn)
        self._editor_body_l.addWidget(helper_row)

        token_row = QWidget()
        tr = QHBoxLayout(token_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(4)

        for lbl, token in [
            ("AND", " and "),
            ("OR", " or "),
            ("NOT", "not "),
            ("(", "("),
            (")", ")"),
        ]:
            b = QPushButton(lbl)
            b.setStyleSheet("font-size:10px; padding:2px 6px;")
            b.clicked.connect(lambda _, t=token: self._insert_raw_text(t))
            tr.addWidget(b)

        clear_btn = QPushButton("Clear raw")
        clear_btn.setStyleSheet("font-size:10px; padding:2px 6px; color:#a00;")
        clear_btn.clicked.connect(lambda: self._raw_cond_input.setText(""))
        tr.addWidget(clear_btn)
        tr.addStretch()
        self._editor_body_l.addWidget(token_row)

        self._expr_prop_cb.currentTextChanged.connect(self._sync_expr_value_widget)
        self._sync_expr_value_widget(self._expr_prop_cb.currentText())

        # Formula
        self._editor_body_l.addWidget(self._sec_lbl("Quantity formula"))
        avail = FORMULA_VARS.get(rule.get("object", ""), [])
        hint  = QLabel(
            f"vars: {', '.join(avail)}" if avail else "no numeric vars"
        )
        hint.setStyleSheet("font-size:10px; color:#aaa;")
        self._editor_body_l.addWidget(hint)
        self._formula_input = QLineEdit(rule.get("formula", "1"))
        self._formula_input.setStyleSheet(
            "font-family:monospace; font-size:12px;"
        )
        self._editor_body_l.addWidget(self._formula_input)
        self._formula_input.textChanged.connect(self._update_preview)

        # C4: real-time validation label (hidden unless there is an error)
        self._validation_lbl = QLabel("")
        self._validation_lbl.setWordWrap(True)
        self._validation_lbl.setStyleSheet(
            "font-size:10px; color:#c0392b; background:#fff0f0; "
            "border-radius:3px; padding:4px 6px;"
        )
        self._validation_lbl.setVisible(False)
        self._editor_body_l.addWidget(self._validation_lbl)

        self._editor_body_l.addStretch()
        self._parse_conditions(rule)
        self._update_preview()

    # ── Condition rows ────────────────────────────────────────────────────────

    def _parse_conditions(self, rule: dict):
        cond = rule.get("condition", "")
        if not cond or cond.strip() == "True":
            self.add_condition_row()
            return
        tokens = re.split(r"\s+(and|or)\s+", cond, flags=re.IGNORECASE)
        self.add_condition_row(expression=tokens[0])
        for i in range(1, len(tokens), 2):
            logic = tokens[i].upper()
            expr  = tokens[i + 1] if i + 1 < len(tokens) else ""
            self.add_condition_row(logical_op=logic, expression=expr)

    def add_condition_row(self, logical_op=None, expression=None):
        obj   = self.active_obj_type
        props = list(_runtime_property_data().get(obj, {}).keys())

        row_w = QWidget()
        rl    = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(3)

        logic_cb = QComboBox()
        logic_cb.addItems(["AND", "OR"])
        logic_cb.setFixedWidth(52)
        logic_cb.setVisible(len(self.condition_widgets) > 0)
        if logical_op:
            logic_cb.setCurrentText(logical_op)
        logic_cb.setStyleSheet(self._combo_box_stylesheet())
        logic_cb.currentTextChanged.connect(self._update_preview)

        prop_cb = QComboBox()
        prop_cb.addItems(props)
        prop_cb.setStyleSheet(self._combo_box_stylesheet())

        op_cb = QComboBox()
        op_cb.addItems(["==", "!=", ">", "<", ">=", "<="])
        op_cb.setFixedWidth(50)
        op_cb.setStyleSheet(self._combo_box_stylesheet())
        op_cb.currentTextChanged.connect(self._update_preview)

        val_w = QLineEdit()
        val_w.textChanged.connect(self._update_preview)

        rem_btn = QPushButton("✕")
        rem_btn.setFixedWidth(22)
        rem_btn.setStyleSheet(
            "color:#aaa; border:none; background:none; font-size:11px;"
        )

        rl.addWidget(logic_cb)
        rl.addWidget(prop_cb, 2)
        rl.addWidget(op_cb)
        rl.addWidget(val_w, 2)
        rl.addWidget(rem_btn)

        wm = {
            "widget": row_w, "logic": logic_cb,
            "prop": prop_cb, "op": op_cb, "value": val_w,
        }
        self.condition_widgets.append(wm)
        self._cond_rows_l.addWidget(row_w)

        prop_cb.currentTextChanged.connect(
            lambda t, w=wm: self._on_prop_change(t, w)
        )
        rem_btn.clicked.connect(
            lambda _, w=row_w: self._remove_cond_row(w)
        )

        self._on_prop_change(prop_cb.currentText(), wm)

        if expression:
            self._restore_expr(expression.strip(), wm, op_cb)

        self._update_preview()

    def _on_prop_change(self, prop: str, wm: dict):
        obj       = self.active_obj_type
        prop_info = _runtime_property_data().get(obj, {}).get(prop)
        cur       = wm["value"]

        if isinstance(prop_info, list):
            cls = QComboBox
        elif prop_info == "int":
            cls = QSpinBox
        else:
            cls = QLineEdit

        if not isinstance(cur, cls):
            new_w = cls()
            if isinstance(new_w, QSpinBox):
                new_w.setRange(-100000, 100000)
                new_w.valueChanged.connect(self._update_preview)
            elif isinstance(new_w, QComboBox):
                new_w.setStyleSheet(self._combo_box_stylesheet())
                new_w.currentTextChanged.connect(self._update_preview)
            else:
                new_w.textChanged.connect(self._update_preview)
            wm["widget"].layout().replaceWidget(cur, new_w)
            cur.deleteLater()
            wm["value"] = new_w
            cur = new_w

        if isinstance(cur, QComboBox) and isinstance(prop_info, list):
            cur.blockSignals(True)
            cur.clear()
            cur.addItems([str(p) for p in prop_info])
            cur.blockSignals(False)

        self._update_preview()

    def _restore_expr(self, expr: str, wm: dict, op_cb: QComboBox):
        not_m = re.match(r"^not\s+(\w+)$", expr)
        if not_m:
            wm["prop"].setCurrentText(not_m.group(1))
            self._on_prop_change(not_m.group(1), wm)
            op_cb.setCurrentText("==")
            v = wm["value"]
            (v.setCurrentText if isinstance(v, QComboBox) else v.setText)("False")
            return

        plain_m = re.match(r"^(\w+)$", expr)
        if plain_m:
            wm["prop"].setCurrentText(plain_m.group(1))
            self._on_prop_change(plain_m.group(1), wm)
            op_cb.setCurrentText("==")
            v = wm["value"]
            (v.setCurrentText if isinstance(v, QComboBox) else v.setText)("True")
            return

        m = re.match(r"(\w+)\s*([<>=!]+)\s*(.*)", expr)
        if not m:
            return
        prop = m.group(1).strip()
        op   = m.group(2).strip()
        val  = m.group(3).strip().strip("'\"")
        wm["prop"].setCurrentText(prop)
        self._on_prop_change(prop, wm)
        op_cb.setCurrentText(op)
        v = wm["value"]
        if isinstance(v, QComboBox):
            v.setCurrentText(val)
        elif isinstance(v, QSpinBox):
            try:
                v.setValue(int(float(val)))
            except ValueError:
                pass
        else:
            v.setText(val)

    def _remove_cond_row(self, widget: QWidget):
        if len(self.condition_widgets) <= 1:
            return
        self.condition_widgets = [
            w for w in self.condition_widgets if w["widget"] is not widget
        ]
        widget.deleteLater()
        if self.condition_widgets:
            self.condition_widgets[0]["logic"].setVisible(False)
        self._update_preview()

    def _build_condition_parts(self) -> list:
        parts = []
        for i, wm in enumerate(self.condition_widgets):
            prop = wm["prop"].currentText()
            op   = wm["op"].currentText()
            v    = wm["value"]
            if isinstance(v, QSpinBox):
                val = str(v.value())
            elif isinstance(v, QComboBox):
                val = v.currentText()
            else:
                val = v.text().strip()

            if not prop:
                continue
            if i > 0:
                parts.append(wm["logic"].currentText().lower())

            is_numeric = re.match(r"^-?\d+(\.\d+)?$", val)
            is_bool    = val.lower() in ("true", "false")
            if is_numeric or is_bool:
                parts.append(f"{prop} {op} {val}")
            else:
                parts.append(f"{prop} {op} '{val}'")
        return parts

    def _update_preview(self):
        parts = self._build_condition_parts()
        text  = " ".join(parts) if parts else "(no conditions)"
        if hasattr(self, "_preview_lbl"):
            self._preview_lbl.setText(text)
        if hasattr(self, "_cond_sync_hint") and hasattr(self, "_raw_cond_input"):
            raw = self._raw_cond_input.text().strip()
            builder = " ".join(parts).strip()
            # Normalise empty/no-condition variants for comparison
            if raw in ("", "True") and builder in ("", "(no conditions)"):
                self._cond_sync_hint.setText("")
            elif raw == builder:
                self._cond_sync_hint.setText("")
            else:
                self._cond_sync_hint.setText(
                    "Builder preview differs from raw condition. "
                    "For complex rules (groups/in/not), edit Raw condition directly."
                )
        # C4: real-time syntax validation
        if hasattr(self, "_validation_lbl") and hasattr(self, "_formula_input"):
            raw_cond = getattr(self, "_raw_cond_input", None)
            cond_text    = raw_cond.text().strip() if raw_cond else ""
            formula_text = self._formula_input.text().strip() or "1"
            ok, msg = self._validate_rule(cond_text, formula_text, self.active_obj_type)
            self._validation_lbl.setVisible(not ok)
            if not ok:
                self._validation_lbl.setText(f"\u26a0  {msg}")

    def _insert_raw_text(self, token: str):
        if not hasattr(self, "_raw_cond_input"):
            return
        old = self._raw_cond_input.text()
        pos = self._raw_cond_input.cursorPosition()
        new = old[:pos] + token + old[pos:]
        self._raw_cond_input.setText(new)
        self._raw_cond_input.setCursorPosition(pos + len(token))

    def _sync_expr_value_widget(self, prop: str):
        obj = self.active_obj_type
        pinfo = _runtime_property_data().get(obj, {}).get(prop)

        new_w = None
        if isinstance(pinfo, list):
            cb = QComboBox()
            cb.addItems([str(v) for v in pinfo])
            cb.setEditable(False)
            new_w = cb
        elif pinfo == "int":
            sp = QSpinBox()
            sp.setRange(-100000, 100000)
            new_w = sp
        else:
            le = QLineEdit()
            le.setPlaceholderText("value")
            new_w = le

        row = self._expr_val_w.parentWidget()
        lay = row.layout() if row else None
        if lay is not None:
            lay.replaceWidget(self._expr_val_w, new_w)
        self._expr_val_w.deleteLater()
        self._expr_val_w = new_w

    def _insert_clause_from_helper(self):
        if not hasattr(self, "_expr_prop_cb"):
            return
        prop = self._expr_prop_cb.currentText().strip()
        op = self._expr_op_cb.currentText().strip()
        if not prop:
            return

        v = self._expr_val_w
        if isinstance(v, QSpinBox):
            raw_val = str(v.value())
        elif isinstance(v, QComboBox):
            raw_val = v.currentText().strip()
        else:
            raw_val = v.text().strip()

        def _fmt_token(t: str) -> str:
            is_num = re.match(r"^-?\d+(\.\d+)?$", t)
            is_bool = t.lower() in ("true", "false")
            if is_num or is_bool:
                return t
            return f"'{t}'"

        if op in ("in", "not in"):
            vals = [x.strip() for x in raw_val.split(",") if x.strip()]
            if not vals:
                vals = ["value"]
            seq = ", ".join(_fmt_token(x) for x in vals)
            clause = f"{prop} {op} ({seq})"
        else:
            if raw_val == "":
                raw_val = "value"
            clause = f"{prop} {op} {_fmt_token(raw_val)}"

        if self._raw_cond_input.text().strip():
            self._insert_raw_text(" and " + clause)
        else:
            self._insert_raw_text(clause)

    # ── Editor actions ────────────────────────────────────────────────────────

    def search_database_for_item(self):
        db_type, ok = QInputDialog.getItem(
            self, "Select type", "Which database?",
            ["Material", "Labor"], 0, False
        )
        if not (ok and db_type):
            return
        dlg = SearchDialog(db_type, self)
        if dlg.exec():
            item = dlg.get_selected()
            if item:
                self.selected_result_item = item
                self._item_display.setText(item["name"])
                self._code_display.setText(item.get("code", ""))
                self._type_combo.setCurrentText(item["type"])

    def save_rule_changes(self):
        if self._editor_mode == "group":
            self._save_group_condition()
            return
        if self.selected_rule_index == -1:
            return
        rule    = self.rules[self.selected_rule_index]
        cond    = self._raw_cond_input.text().strip()
        formula = self._formula_input.text().strip() or "1"

        # C4: validate syntax before committing
        ok, msg = self._validate_rule(cond, formula, rule.get("object", self.active_obj_type))
        if not ok:
            reply = QMessageBox.question(
                self, "Validation Warning",
                f"{msg}\n\nSave anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Save the exact condition text so complex JSON conditions are preserved.
        rule["condition"] = cond
        if self.selected_result_item:
            rule["type"]      = self.selected_result_item["type"]
            rule["item_code"] = self.selected_result_item.get("code", "")
            rule["item_name"] = (
                self.selected_result_item.get("name")
                or self.selected_result_item.get("item_name", "")
            )
        else:
            rule["type"] = self._type_combo.currentText()
        rule["formula"] = formula
        self.save_rules()
        self._update_tree_counts()
        self._refresh_cards()
        self._editor_hdr.setText(f"Editing: {rule.get('item_name','')}")
        QMessageBox.information(self, "Saved", "Rule saved successfully.")

    def create_new_rule(self):
        new_rule = {
            "object":    self.active_obj_type,
            "item_name": "New Rule — edit me",
            "condition": "",
            "type":      "Material",
            "item_code": "N/A",
            "formula":   "1",
        }
        self.rules.append(new_rule)
        self.save_rules()
        self.selected_rule_index = len(self.rules) - 1
        self._update_tree_counts()
        self._refresh_cards()
        self._build_editor(new_rule)

    def delete_selected_rule(self):
        if self.selected_rule_index == -1:
            return
        rule  = self.rules[self.selected_rule_index]
        reply = QMessageBox.question(
            self, "Delete rule",
            f"Delete:\n'{rule.get('item_name')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.rules[self.selected_rule_index]
            self.selected_rule_index = -1
            self.save_rules()
            self._update_tree_counts()
            self._refresh_cards()
            self._clear_editor()

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_rules(self):
        try:
            from core import db_gateway as _dbg  # noqa: PLC0415
            self.rules = _dbg.get_rules(enabled_only=False)
        except Exception:
            self.rules = []

    def save_rules(self):
        try:
            from core import db_gateway as _dbg  # noqa: PLC0415
            _dbg.save_rules(self.rules)
            # Reload to get fresh IDs from DB after the full replace
            self.rules = _dbg.get_rules(enabled_only=False)
            # Also keep a JSON backup alongside the DB
            path = get_data_path("rules.json")
            import os as _os
            _os.makedirs(_os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save rules:\n{exc}")

    # ── Rule toggle (C3) ─────────────────────────────────────────────────────

    def _on_rule_toggle(self, rule_index: int, rule: dict, enabled: bool):
        """Immediately enable/disable a rule via DB toggle, refresh cards."""
        rule["enabled"] = 1 if enabled else 0
        rule_id = rule.get("id")
        if rule_id:
            try:
                from core import db_gateway as _dbg  # noqa: PLC0415
                _dbg.toggle_rule(rule_id, enabled)
            except Exception:
                pass
        self._refresh_cards()

    # ── Rule validation (C4) ──────────────────────────────────────────────────

    @staticmethod
    def _validate_rule(cond: str, formula: str, obj_type: str) -> tuple[bool, str]:
        """Syntax-check condition and formula. Returns (ok, error_message)."""
        cond_text    = cond.strip() or "True"
        formula_text = formula.strip() or "1"
        try:
            compile(cond_text, "<condition>", "eval")
        except SyntaxError as e:
            col = f", col {e.offset}" if e.offset else ""
            return False, f"Condition syntax error: {e.msg}{col}"
        try:
            compile(formula_text, "<formula>", "eval")
        except SyntaxError as e:
            col = f", col {e.offset}" if e.offset else ""
            return False, f"Formula syntax error: {e.msg}{col}"
        return True, ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _clear_layout(self, layout):
        if not layout:
            return
        while layout.count():
            child = layout.takeAt(0)
            if child is None:
                continue
            w = child.widget()
            if w is not None:
                w.deleteLater()
                continue
            l = child.layout()
            if l is not None:
                self._clear_layout(l)
