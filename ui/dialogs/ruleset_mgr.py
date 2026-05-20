from core.property_registry import get_registry
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
                          Updated:   SIM_DEFAULTS
                          now imported from constants.py instead of being
                          hardcoded in the class body. SmartStructure and
                          SmartConsumer added throughout.
"""

import os
import sqlite3
import json
import re

from core.expression_engine import evaluate_condition, evaluate_formula, validate_expression

from core import defaults

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







from ui.dialogs._shared import ClickableCard
from ui.dialogs.search import SearchDialog

# ── Styling Constants ─────────────────────────────────────────────────────────

OBJ_STYLES = {
    "SmartPole":      {"icon": "\U0001f538", "fg": "#185FA5", "bg": "#ddeeff", "label": "POLE"},
    "SmartStructure": {"icon": "\U0001f537", "fg": "#6a1fb0", "bg": "#f3e8ff", "label": "STRUCTURE"},
    "SmartSpan":      {"icon": "\U0001f539", "fg": "#1a6b2a", "bg": "#e8f4ea", "label": "SPAN"},
    "SmartConsumer":  {"icon": "\U0001f536", "fg": "#a04000", "bg": "#fff3e0", "label": "CONSUMER"},
}

CONDITION_KEY_COLORS = {
    "is_existing":           ("#fdecea", "#b71c1c"),
    "is_new":                ("#e8f5e9", "#1b5e20"),
    "is_existing_span":      ("#fdecea", "#b71c1c"),
    "is_new_span":           ("#e8f5e9", "#1b5e20"),
    "is_distribution_span":  ("#ddeeff", "#185FA5"),
    "is_service_drop":       ("#fff3e0", "#a04000"),
    "is_lt_span":            ("#dff5ff", "#0a6080"),
    "is_ht_span":            ("#f3e8ff", "#6a1fb0"),
    "pole_type":             ("#ddeeff", "#185FA5"),
    "pole_type2":            ("#e0f7f7", "#176b6b"),
    "height":                ("#f3e8ff", "#6a1fb0"),
    "structure_type":        ("#eee8ff", "#4a20a0"),
    "conductor":             ("#ddeeff", "#0a3f80"),
    "conductor_size":        ("#e8f0ff", "#3058a0"),
    "aug_type":              ("#fff0e0", "#7a4000"),
    "wire_count":            ("#e8f0e8", "#2a5a2a"),
    "phase":                 ("#fce4ec", "#b71c4a"),
    "dtr_size":              ("#e8f4ea", "#1a5c2a"),
    "earth_count_gt":        ("#ffeef0", "#a01030"),
    "stay_count_gt":         ("#ffeef0", "#a01030"),
    "has_cg":                ("#fefce8", "#706000"),
    "has_extension":         ("#fefce8", "#706000"),
    "ab_cable_count_gt":     ("#e0f7f4", "#0a6b5a"),
    "ab_needs_dead_end":     ("#e0f7f4", "#0a6b5a"),
    "ab_needs_suspension":   ("#e0f7f4", "#0a6b5a"),
    "use_uh":                ("#fffde7", "#706000"),
    "agency_supply":         ("#f3e5f5", "#6a1b9a"),
    "consider_cable":        ("#e8f4ea", "#1a5c2a"),
    "project_type":          ("#e8eaf6", "#3949ab"),
}

CONDITION_LABEL_OVERRIDES = {
    ("is_existing",          "True"):  "EX. POLE",
    ("is_existing",          "False"): "NEW POLE",
    ("is_new",               "True"):  "NEW POLE",
    ("is_new",               "False"): "EX. POLE",
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
    ("has_cg",               "True"):  "WITH CG",
    ("has_cg",               "False"): "NO CG",
    ("has_extension",        "True"):  "WITH EXT.",
    ("has_extension",        "False"): "NO EXT.",
    ("ab_needs_dead_end",    "True"):  "DEAD END",
    ("ab_needs_suspension",  "True"):  "SUSPENSION",
    ("dist_box_required",    "True"):  "DIST BOX",
    ("use_uh",               "True"):  "UH MATS",
    ("use_uh",               "False"): "RAW MATS",
    ("agency_supply",        "True"):  "AGENCY SUPPLY",
    ("agency_supply",        "False"): "SELF SUPPLY",
    ("consider_cable",       "True"):  "WITH CABLE",
    ("consider_cable",       "False"): "NO CABLE",
}

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

    def __init__(self, parent=None, canvas_objects=None):
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
        self._canvas_objects       = canvas_objects or []
        self._view_mode            = "grouped"   # "flat" | "grouped"
        self._editor_mode          = "rule"      # "rule" | "group"
        self._group_edit_indices   = []          # rule indices for current group edit
        self._recipe_name_cache: dict[str, str] = {}  # recipe_key → display name

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
        self._tree_items = []

        # Overview dashboard node
        ov_item = QTreeWidgetItem(self._tree, ["\U0001f4ca  Overview"])
        ov_item.setData(0, Qt.ItemDataRole.UserRole, ("__dashboard__", {}))
        ov_item.setToolTip(0, "Rule count summary across all object types")
        self._tree_items.append((ov_item, "__dashboard__", {}))

        # Dynamically build categories
        obj_types = ["SmartPole", "SmartStructure", "SmartSpan", "SmartConsumer"]
        for r in self.rules:
            ot = r.get("object", "")
            if ot and ot not in obj_types:
                obj_types.append(ot)

        # Build dynamic folders per property dynamically to replace hardcoded TREE_DEF
        all_props = get_registry().get_all_property_data()
        for ot in obj_types:
            root_item = QTreeWidgetItem(self._tree, [ot])
            root_item.setData(0, Qt.ItemDataRole.UserRole, (ot, {}))
            self._tree_items.append((root_item, ot, {}))
            
            ot_props = all_props.get(ot, {})
            for prop_key, options in ot_props.items():
                if isinstance(options, list) and len(options) > 1:
                    prop_folder = QTreeWidgetItem(root_item, [f"By {prop_key}"])
                    prop_folder.setData(0, Qt.ItemDataRole.UserRole, (ot, {}))
                    self._tree_items.append((prop_folder, ot, {}))
                    
                    for opt in options:
                        opt_str = str(opt)
                        opt_item = QTreeWidgetItem(prop_folder, [opt_str])
                        opt_item.setData(0, Qt.ItemDataRole.UserRole, (ot, {prop_key: opt_str}))
                        self._tree_items.append((opt_item, ot, {prop_key: opt_str}))

        self._update_tree_counts()
        # Tree closed by default
        self._tree.collapseAll()

    def _update_tree_counts(self):
        for item, obj_type, fdict in self._tree_items:
            if obj_type == "__dashboard__":
                continue
            base  = item.text(0).split("  ")[0]
            count = len(self._get_matching_rules(obj_type, fdict, set()))
            item.setText(0, f"{base}  ({count})" if count else base)

    def _filter_tree(self, text: str):
        text = text.lower()
        
        # Reset visibility if search is cleared
        if not text:
            for i in range(self._tree.topLevelItemCount()):
                self._show_all_recursive(self._tree.topLevelItem(i))
            return

        # Hide all first, then selectively show based on matches
        for i in range(self._tree.topLevelItemCount()):
            self._filter_item_recursive(self._tree.topLevelItem(i), text)

    def _show_all_recursive(self, item: QTreeWidgetItem):
        item.setHidden(False)
        for i in range(item.childCount()):
            self._show_all_recursive(item.child(i))

    def _filter_item_recursive(self, item: QTreeWidgetItem, text: str) -> bool:
        """
        Recursively filters items. Returns True if the item or any descendant matches.
        """
        # Check if the current item matches
        item_text = item.text(0).lower()
        match = text in item_text
        
        # Recursively check children
        child_match = False
        for i in range(item.childCount()):
            if self._filter_item_recursive(item.child(i), text):
                child_match = True
        
        # This item should be visible if it matches OR if any child matches
        visible = match or child_match
        item.setHidden(not visible)
        
        # If a child matches, we must expand this item to show the path
        if child_match and text:
            item.setExpanded(True)
        elif not text:
            # Re-collapse everything when text is cleared (matching _populate_tree state)
            item.setExpanded(False)
            
        return visible

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

        template_btn = QPushButton("📋 Templates")
        template_btn.setStyleSheet(
            "background:#5DCAA5; color:white; border:none; "
            "padding:5px 12px; border-radius:4px; font-size:12px;"
        )
        template_btn.clicked.connect(self._open_templates)

        tl.addWidget(self._centre_title)
        tl.addStretch()
        tl.addWidget(self._card_search)
        tl.addWidget(self._type_filter)
        tl.addWidget(self._view_btn)
        tl.addWidget(self._logic_btn)
        tl.addWidget(new_btn)
        tl.addWidget(template_btn)
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

        chips = get_registry().get_filter_chips().get(self.active_obj_type, [])
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
        if getattr(self, "_is_global_search", False):
            self._centre_title.setText(f"Global Search Results  —  {len(visible)} rule(s)")
        else:
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
        search = self._card_search.text().strip().lower() if hasattr(self, "_card_search") else ""
        type_filter = self._type_filter.currentText() if hasattr(self, "_type_filter") else "All"
        
        # 1. Base set of rules
        if search:
            # GLOBAL SEARCH: Ignore tree filter and active_obj_type
            candidate_rules = [(i, r) for i, r in enumerate(self.rules)]
            self._is_global_search = True
        else:
            # LOCAL VIEW: Filter by Object Type, Tree Folder, and Chips
            candidate_rules = self._get_matching_rules(
                self.active_obj_type, self.active_tree_filter, self.active_chips
            )
            self._is_global_search = False
        
        # 2. Filter by Type (Material/Labor)
        if type_filter != "All":
            candidate_rules = [
                (i, r) for i, r in candidate_rules
                if any(itm.get("type", "Material") == type_filter for itm in r.get("items", []))
            ]
        
        # 3. Smart Search & Sorting
        if search:
            from core.ai_rule_parser import find_similar_rules, infer_properties_from_text
            
            # We score all candidate rules across ALL object types
            props = infer_properties_from_text(search)
            
            final_list = []
            
            # Group rules by object type to call scoring efficiently
            by_obj = {}
            for idx, rule in candidate_rules:
                ot = rule.get("object", "SmartPole")
                by_obj.setdefault(ot, []).append((idx, rule))
            
            all_scores = {}
            for ot, rules_in_ot in by_obj.items():
                from core.ai_rule_parser import search_existing_rules
                intent = {"object": ot, "properties": props, "item_name_hint": search}
                
                # Reconstruct a flat-like list for the parser by selecting the first item or descriptive text
                ot_rules_flat = []
                for idx, r in rules_in_ot:
                    items = r.get("items", [])
                    first_item_name = items[0].get("item_name", "") if items else "Group"
                    flat_r = {
                        "object": r.get("object"),
                        "condition": r.get("condition"),
                        "formula": items[0].get("formula", "1") if items else "1",
                        "type": items[0].get("type", "Material") if items else "Material",
                        "item_code": items[0].get("item_code", "") if items else "",
                        "item_name": first_item_name
                    }
                    ot_rules_flat.append(flat_r)
                
                matches = search_existing_rules(intent, ot_rules_flat, top_n=len(ot_rules_flat), threshold=0.0)
                for rel_idx, rule, score in matches:
                    orig_idx = rules_in_ot[rel_idx][0]
                    all_scores[orig_idx] = score

            for idx, rule in candidate_rules:
                has_name_hit = any(search in itm.get("item_name", "").lower() for itm in rule.get("items", []))
                condition = rule.get("condition", "").lower()
                string_hit = (has_name_hit or search in condition)
                sem_score = all_scores.get(idx, 0.0)
                
                final_score = sem_score
                if string_hit:
                    final_score = max(final_score, 0.5)
                
                if final_score > 0.05:
                    final_list.append((idx, rule, final_score))
            
            final_list.sort(key=lambda x: x[2], reverse=True)
            self._semantic_hits = {idx for idx, r, s in final_list if s >= 0.4}
            return [(idx, r) for idx, r, s in final_list]
            
        self._semantic_hits = set()
        return candidate_rules

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
        
        # Merge search hits into visual highlights
        if hasattr(self, "_semantic_hits"):
            sim_hits = sim_hits.union(self._semantic_hits)

        if self._view_mode == "grouped":
            self._render_grouped_cards(matched, sim_hits)
        else:
            for orig_idx, rule in matched:
                for item_idx, itm in enumerate(rule.get("items", [])):
                    flat_rule = {
                        "id": rule.get("id"),
                        "object": rule.get("object"),
                        "condition": rule.get("condition"),
                        "enabled": rule.get("enabled", 1),
                        "type": itm.get("type", "Material"),
                        "item_code": itm.get("item_code", ""),
                        "item_name": itm.get("item_name", ""),
                        "formula": itm.get("formula", "1")
                    }
                    card = self._make_card(orig_idx, flat_rule, orig_idx in sim_hits)
                    self._card_layout.insertWidget(
                        self._card_layout.count() - 1, card
                    )

        self._update_centre_title()
        self._update_tree_counts()

    # Regex matching recipe key identifiers (same pattern as rule_engine.py)
    _RECIPE_KEY_RE = re.compile(r'^[A-Z][A-Z0-9_]{1,}$')

    def _get_recipe_display(self, formula: str) -> str | None:
        """Return a friendly recipe name for recipe-key formulas, or None."""
        formula = (formula or "").strip()
        if formula == "recipe":
            return "Active structure recipe"
        if not self._RECIPE_KEY_RE.match(formula):
            return None
        if not self._recipe_name_cache:
            try:
                from core import db_gateway as _dbg
                self._recipe_name_cache = {r["recipe_key"]: r["name"] for r in _dbg.get_recipes()}
            except Exception:
                pass
        return self._recipe_name_cache.get(formula)

    def _make_rule_card_base(self, rule_index: int, rule: dict, sim_hit: bool, is_child: bool = False):
        card     = ClickableCard(lambda idx=rule_index: self._on_card(idx))
        selected = rule_index == self.selected_rule_index
        enabled  = bool(rule.get("enabled", 1))

        # Styling
        if not enabled:
            bc = "#378ADD" if selected else "#bbb"
            bw = "1.5px" if selected else "0.5px"
            bg = "#f5f5f5"
        else:
            bc = "#378ADD" if selected else ("#5DCAA5" if sim_hit else "#ddd")
            bw = "1.5px"   if (selected or sim_hit) else "0.5px"
            bg = "#eaf8f4" if sim_hit else "white"
        
        card.setStyleSheet(
            f"background:{bg}; border:{bw} solid {bc}; border-radius:{'0px' if is_child else '6px'};"
            + ("border-left: 2px solid " + bc if is_child else "")
        )
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(30 if is_child else 9, 5 if is_child else 7, 10, 5 if is_child else 7)
        lay.setSpacing(8)

        # 1. Object Type Badge (only in global search)
        if getattr(self, "_is_global_search", False):
            ot = rule.get("object", "SmartPole")
            style = self._get_obj_style(ot)
            obj_badge = QLabel(style["label"])
            obj_badge.setStyleSheet(
                f"background:{style['bg']}; color:{style['fg']}; border-radius:3px; "
                f"font-size:{'8px' if is_child else '9px'}; font-weight:bold; padding:1px 4px; border:0.5px solid #ccc;"
            )
            lay.addWidget(obj_badge)

        # 2. Material/Labor Badge
        r_type = rule.get("type", "Material")
        badge  = QLabel("M" if r_type == "Material" else "L")
        badge_size = 22 if is_child else 24
        badge.setFixedSize(badge_size, badge_size)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "border-radius:4px; font-size:10px; font-weight:bold; " + (
                "background:#ddeeff; color:#185FA5;" if r_type == "Material"
                else "background:#fff3e0; color:#854F0B;"
            )
        )
        lay.addWidget(badge)

        # 3. Content Row
        formula = rule.get("formula", "1")
        recipe_display = self._get_recipe_display(formula)

        # When a recipe key is used, show the recipe's name instead of the
        # generic "Structural Iron (from Recipe)" placeholder text.
        display_name = recipe_display if recipe_display else rule.get("item_name", "Unnamed")
        name_l = QLabel(display_name)
        name_style = f"font-size:12px; {'font-weight:bold;' if not is_child else ''}"
        if not enabled:
            name_style += " color:#aaa; text-decoration:line-through;"
        name_l.setStyleSheet(name_style)
        lay.addWidget(name_l, 1) # Item Name takes available space

        # Condition (only in flat view)
        if not is_child:
            cond_l = QLabel(rule.get("condition", "") or "(always)")
            cond_l.setStyleSheet(f"font-size:11px; color:{'#bbb' if not enabled else '#777'}; font-family:monospace;")
            lay.addWidget(cond_l)

        lay.addStretch() # Spacer to keep metadata on the right

        # Code
        code = rule.get("item_code", "")
        if code and code != "N/A":
            code_l = QLabel(code)
            code_l.setStyleSheet("font-size:10px; color:#999; background:#f0f0f0; padding:1px 4px; border-radius:2px;")
            lay.addWidget(code_l)

        # Formula / Quantity — recipe items show "recipe" badge instead of raw key
        if recipe_display:
            form_text = "recipe"
            form_color = "#27AE60" if enabled else "#ccc"
            form_bg    = "#e8f8f0"
        else:
            form_text  = f"{'×' if is_child else 'qty='}{formula}"
            form_color = "#185FA5" if enabled else "#ccc"
            form_bg    = "#eef4fb"
        form_l = QLabel(form_text)
        form_l.setStyleSheet(
            f"font-size:11px; font-weight:bold; color:{form_color}; "
            f"background:{form_bg}; padding:1px 6px; border-radius:3px;"
        )
        lay.addWidget(form_l)

        # 4. Toggle
        toggle_cb = QCheckBox()
        toggle_cb.setChecked(enabled)
        toggle_cb.stateChanged.connect(lambda state, idx=rule_index, r=rule: self._on_rule_toggle(idx, r, bool(state)))
        lay.addWidget(toggle_cb)

        return card

    def _make_card(self, rule_index, rule, sim_hit=False):
        return self._make_rule_card_base(rule_index, rule, sim_hit, is_child=False)

    # ── Condition tag pills ─────────────────────────────────────────────

    @staticmethod
    def _condition_to_pills(cond: str) -> list:
        """Parse a condition string into [(label, bg_color, fg_color)] pills."""
        if not cond or cond.strip() in ("True", ""):
            return [("always", "#e8e8e8", "#555")]

        pills = []
        default_style = ("#f0f0f0", "#444")
        
        # Split by logical operators but keep them or just use them as delimiters
        clauses = re.split(r'\s+(?:and|or)\s+', cond, flags=re.IGNORECASE)
        for clause in clauses:
            clause = clause.strip()
            if not clause: continue
            
            label, bg, fg = None, None, None
            
            # 1. NOT key
            m = re.match(r'^not\s+(\w+)$', clause)
            if m:
                key = m.group(1)
                label = CONDITION_LABEL_OVERRIDES.get((key, "False"), f"\u00ac{key}")
                bg, fg = CONDITION_KEY_COLORS.get(key, default_style)
            
            # 2. Key OP Value
            if not label:
                m = re.match(r"^(\w+)\s*(==|!=|>=|<=|>|<)\s*['\"]?(.+?)['\"]?$", clause)
                if m:
                    key, op, val = m.group(1), m.group(2), m.group(3).strip().strip("'\"")
                    label = CONDITION_LABEL_OVERRIDES.get((key, val))
                    if not label:
                        sym_map = {"==": "", "!=": "\u2260", ">=": "\u2265", "<=": "\u2264", ">": ">", "<": "<"}
                        label = f"{val}" if op == "==" else f"{key}{sym_map.get(op, op)}{val}"
                    bg, fg = CONDITION_KEY_COLORS.get(key, default_style)
            
            # 3. Bare Key
            if not label:
                m = re.match(r'^(\w+)$', clause)
                if m:
                    key = m.group(1)
                    label = CONDITION_LABEL_OVERRIDES.get((key, "True"), key)
                    bg, fg = CONDITION_KEY_COLORS.get(key, default_style)
            
            # Fallback
            if not label:
                label, (bg, fg) = clause[:14] + ("\u2026" if len(clause) > 14 else ""), default_style
                
            pills.append((label, bg, fg))

        return pills if pills else [("condition", "#f0f0f0", "#444")]

    def _normalize_condition(self, cond: str) -> str:
        """Normalize condition string for consistent grouping (quotes, spaces, operators)."""
        if not cond or cond.strip().lower() == "true": 
            return "True"
        # 1. Standardize quotes
        c = cond.replace('"', "'").strip()
        # 2. Normalize spaces around operators
        c = re.sub(r'\s*(==|!=|>=|<=|>|<|and|or|not)\s*', r' \1 ', c, flags=re.IGNORECASE)
        # 3. Collapse multiple spaces
        c = re.sub(r'\s+', ' ', c)
        return c.strip()

    # ── Grouped view ──────────────────────────────────────────────────────────

    def _render_grouped_cards(self, matched, sim_hits):
        """Render rules grouped by identical condition string (and object if global)."""
        is_global = getattr(self, "_is_global_search", False)

        for orig_idx, rule in matched:
            cond = rule.get("condition", "") or ""
            items = rule.get("items", [])
            
            mat_count = sum(1 for itm in items if itm.get("type") == "Material")
            lab_count = sum(1 for itm in items if itm.get("type") == "Labor")
            grp_hit   = orig_idx in sim_hits
            grp_sel   = (orig_idx == self.selected_rule_index)
            
            # Reconstruct items list for widget compatibility
            widget_items = []
            for itm in items:
                child_rule = {
                    "id": rule.get("id"),
                    "object": rule.get("object"),
                    "condition": cond,
                    "enabled": rule.get("enabled", 1),
                    "type": itm.get("type", "Material"),
                    "item_code": itm.get("item_code", ""),
                    "item_name": itm.get("item_name", ""),
                    "formula": itm.get("formula", "1")
                }
                widget_items.append((orig_idx, child_rule))

            group_w   = self._make_group_widget(
                cond, mat_count, lab_count, widget_items, sim_hits, grp_hit, grp_sel
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
            lambda _checked=False, idx=rule_indices[0]:
                self._on_card(idx)
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
        return self._make_rule_card_base(rule_index, rule, sim_hit, is_child=True)

    # ── Dashboard ─────────────────────────────────────────────────────────────────

    def _get_obj_style(self, obj_type: str) -> dict:
        return OBJ_STYLES.get(obj_type, {"icon": "▪", "fg": "#555", "bg": "#f0f0f0", "label": "ITEM"})

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

        top_types = [e[1] for e in get_registry().get_tree_def()]
        for obj_type in top_types:
            obj_rules = [(i, r) for i, r in enumerate(self.rules)
                         if r.get("object") == obj_type]
            n_conds = len(obj_rules)
            
            mat_n = 0
            lab_n = 0
            for _, r in obj_rules:
                for itm in r.get("items", []):
                    if itm.get("type") == "Material":
                        mat_n += 1
                    else:
                        lab_n += 1
            
            style = self._get_obj_style(obj_type)
            card = self._make_dashboard_card(
                obj_type, n_conds, mat_n, lab_n, 
                style["icon"], style["fg"], style["bg"]
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
        rule = self.rules[rule_index]
        new_obj = rule.get("object", "SmartPole")
        
        # If we selected a card from a different object type (global search), switch context
        if new_obj != self.active_obj_type:
            self.active_obj_type = new_obj
            self.active_tree_filter = {} # Clear tree filter when switching types via search
            self._select_tree_root(new_obj)
            
        self.selected_rule_index = rule_index
        self._refresh_cards()
        self._build_editor(rule)

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

        # --- "Pick from canvas" dropdown (Task 5) ---
        self._canvas_pick_w = QWidget()
        cpk_l = QHBoxLayout(self._canvas_pick_w)
        cpk_l.setContentsMargins(0, 0, 0, 4)
        cpk_l.setSpacing(6)
        cpk_lbl = QLabel("🎯 Pick from canvas:")
        cpk_lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
        self._canvas_pick_cb = QComboBox()
        self._canvas_pick_cb.setStyleSheet("font-size:11px; padding:3px;")
        self._canvas_pick_cb.addItem("— pick an object —")
        self._canvas_pick_cb.currentIndexChanged.connect(self._on_canvas_pick)
        cpk_l.addWidget(cpk_lbl)
        cpk_l.addWidget(self._canvas_pick_cb, 1)
        sb.addWidget(self._canvas_pick_w)
        # Only show if canvas objects were passed in
        self._canvas_pick_w.setVisible(bool(self._canvas_objects))

        # Horizontal Scroll Area for inputs
        sim_scroll = QScrollArea()
        sim_scroll.setWidgetResizable(True)
        sim_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        sim_scroll.setFixedHeight(50)
        sim_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sim_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._sim_inputs_w = QWidget()
        self._sim_inputs_l = QHBoxLayout(self._sim_inputs_w)
        self._sim_inputs_l.setContentsMargins(0, 0, 0, 0)
        self._sim_inputs_l.setSpacing(12)
        
        sim_scroll.setWidget(self._sim_inputs_w)
        sb.addWidget(sim_scroll)

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

        defaults = get_registry().get_sim_defaults(self.active_obj_type)
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

        # Rebuild canvas picker for current object type
        self._rebuild_canvas_picker()

    def _rebuild_canvas_picker(self):
        """Populate the 'Pick from canvas' dropdown with matching objects."""
        if not hasattr(self, "_canvas_pick_cb"):
            return
        self._canvas_pick_cb.blockSignals(True)
        self._canvas_pick_cb.clear()
        self._canvas_pick_cb.addItem("— pick an object —")

        # Map save-data "type" to internal object class names
        _TYPE_MAP = {"Pole": "SmartPole", "Structure": "SmartStructure", "Consumer": "SmartConsumer"}

        for nd in self._canvas_objects:
            nd_type = _TYPE_MAP.get(nd.get("type", ""), nd.get("type", ""))
            if nd_type != self.active_obj_type:
                continue
            label = nd.get("label_text", "") or nd.get("type", "?")
            seq   = nd.get("seq_id", "")
            summary = f"{label}"
            if seq:
                summary += f" (#{seq})"
            props = nd.get("dynamic_props", {})
            if nd.get("pole_type"):
                summary += f" {nd['pole_type']}"
            if nd.get("pole_type2"):
                summary += f" {nd['pole_type2']}"
            if nd.get("height"):
                summary += f" {nd['height']}m"
            self._canvas_pick_cb.addItem(summary, nd)

        self._canvas_pick_cb.blockSignals(False)
        self._canvas_pick_w.setVisible(
            bool(self._canvas_objects) and self._canvas_pick_cb.count() > 1
        )

    def _on_canvas_pick(self, index: int):
        """Handle selection from the 'Pick from canvas' dropdown."""
        if index <= 0:
            return
        nd = self._canvas_pick_cb.itemData(index)
        if nd and isinstance(nd, dict):
            self._prefill_sim_from_object(nd)

    def _prefill_sim_from_object(self, obj_dict: dict):
        """Pre-fill simulator widgets from a canvas object dict."""
        # Merge top-level props + dynamic_props as context
        ctx = {}
        ctx.update(obj_dict.get("dynamic_props", {}))
        # Overlay direct attributes
        for key in ("pole_type", "pole_type2", "height", "is_existing",
                     "has_extension", "extension_height", "earth_count",
                     "stay_count", "structure_type", "dtr_size",
                     "phase", "cable_size", "agency_supply",
                     "conductor", "conductor_size", "wire_count",
                     "length", "has_cg", "consider_cable",
                     "kiosk_required", "orientation",
                     "dist_box_required", "override_auto_stay"):
            if key in obj_dict:
                ctx[key] = obj_dict[key]

        for prop_name, widget in self.sim_widgets.items():
            if prop_name not in ctx:
                continue
            val = ctx[prop_name]
            if isinstance(widget, QSpinBox):
                try:
                    widget.setValue(int(float(val)))
                except (ValueError, TypeError):
                    pass
            elif isinstance(widget, QComboBox):
                text = str(val)
                idx = widget.findText(text)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                else:
                    # Try common conversions
                    if isinstance(val, bool):
                        widget.setCurrentText(str(val))
                    else:
                        widget.setCurrentText(text)
            else:
                widget.setText(str(val))

        # Update formula preview after pre-fill
        self._update_formula_preview()

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
        for i, rule in enumerate(self.rules):
            if rule.get("object") != self.active_obj_type:
                continue
            cond = rule.get("condition", "True") or "True"
            try:
                if evaluate_condition(cond, ctx):
                    hits.add(i)
            except Exception:
                pass
        return hits

    def _run_sim(self):
        ctx  = self._get_sim_ctx()
        hits = self._sim_hits()
        self._refresh_cards()

        self._sim_table.setRowCount(0)
        self._sim_table.setVisible(bool(hits))
        mat_n = lab_n = 0

        for i in sorted(hits):
            rule = self.rules[i]
            for itm in rule.get("items", []):
                r_type  = itm.get("type", "Material")
                formula = itm.get("formula", "1")
                try:
                    qty = evaluate_formula(formula, ctx)
                    qty_s = f"{qty:.3f}".rstrip("0").rstrip(".")
                except Exception:
                    qty_s = formula

                r = self._sim_table.rowCount()
                self._sim_table.insertRow(r)
                self._sim_table.setItem(r, 0, QTableWidgetItem(r_type))
                self._sim_table.setItem(r, 1, QTableWidgetItem(itm.get("item_name", "")))
                self._sim_table.setItem(r, 2, QTableWidgetItem(qty_s))
                self._sim_table.setItem(r, 3, QTableWidgetItem(formula))
                if r_type == "Material":
                    mat_n += 1
                else:
                    lab_n += 1

        total = len(hits)
        self._sim_count_lbl.setText(
            f"{total} condition group(s) fire  |  {mat_n} material, {lab_n} labour"
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
        self._save_btn.setText("\U0001f4be Save rule group")
        self._save_btn.setEnabled(True)
        self._del_btn.setEnabled(True)

        self._editor_hdr.setText(f"Editing Rule Group")

        # Condition section header row
        cond_hdr_row = QWidget()
        cond_hdr_l = QHBoxLayout(cond_hdr_row)
        cond_hdr_l.setContentsMargins(0, 0, 0, 0)
        cond_hdr_l.setSpacing(8)
        
        sec_label = self._sec_lbl("Condition Logic")
        cond_hdr_l.addWidget(sec_label, 1)
        
        ai_btn = QPushButton("✨ Describe in plain English")
        ai_btn.setStyleSheet(
            "background:#9b59b6; color:white; border:none; "
            "padding:3px 8px; border-radius:3px; font-size:10px; font-weight:bold;"
        )
        ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ai_btn.clicked.connect(self._open_ai_describe)
        cond_hdr_l.addWidget(ai_btn)
        
        self._editor_body_l.addWidget(cond_hdr_row)

        self._cond_container = QWidget()
        self._cond_rows_l    = QVBoxLayout(self._cond_container)
        self._cond_rows_l.setContentsMargins(0, 0, 0, 0)
        self._cond_rows_l.setSpacing(3)
        self._editor_body_l.addWidget(self._cond_container)

        self._add_cond_btn = QPushButton("+ add condition logic block")
        self._add_cond_btn.setStyleSheet(
            "color:#185FA5; background:none; border:none; "
            "font-size:11px; text-align:left;"
        )
        self._add_cond_btn.clicked.connect(self.add_condition_row)
        self._editor_body_l.addWidget(self._add_cond_btn)

        # Advanced Mode Checkbox
        from PyQt6.QtWidgets import QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView
        self._adv_cb = QCheckBox("Advanced Mode (Manually edit raw logic string)")
        self._adv_cb.setStyleSheet("font-size: 11px; color:#555;")
        self._adv_cb.toggled.connect(self._toggle_advanced_mode)
        self._editor_body_l.addWidget(self._adv_cb)

        self._raw_cond_input = QLineEdit(rule.get("condition", ""))
        self._raw_cond_input.setStyleSheet(
            "font-family:monospace; font-size:12px; background:#f5f5f5;"
        )
        self._raw_cond_input.setReadOnly(True)
        self._editor_body_l.addWidget(self._raw_cond_input)

        # Items Table
        self._editor_body_l.addWidget(self._sec_lbl("BOM & Labor Items"))

        self._items_table = QTableWidget(0, 4)
        self._items_table.setHorizontalHeaderLabels(["Type", "Code", "Name", "Formula"])
        self._items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._items_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._items_table.setStyleSheet("font-size:11px;")
        
        # Set column stretching
        hdr = self._items_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self._items_table.setColumnWidth(0, 70)
        self._items_table.setColumnWidth(1, 80)
        self._items_table.setColumnWidth(3, 70)
        self._items_table.setFixedHeight(150)

        # Populate Items
        items = rule.get("items", [])
        for itm in items:
            r = self._items_table.rowCount()
            self._items_table.insertRow(r)
            
            # Type (combobox in cell)
            type_cb = QComboBox()
            type_cb.addItems(["Material", "Labor"])
            type_cb.setCurrentText(itm.get("type", "Material"))
            type_cb.setStyleSheet("font-size:10px; padding:1px;")
            self._items_table.setCellWidget(r, 0, type_cb)

            # Code (read-only item)
            code_item = QTableWidgetItem(itm.get("item_code", "N/A"))
            code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._items_table.setItem(r, 1, code_item)

            # Name
            name_item = QTableWidgetItem(itm.get("item_name", "Unnamed"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._items_table.setItem(r, 2, name_item)

            # Formula
            self._setup_formula_column(r, itm.get("item_code", "N/A"), itm.get("formula", "1"))

        self._editor_body_l.addWidget(self._items_table)

        # Item actions row
        item_actions_w = QWidget()
        item_actions_l = QHBoxLayout(item_actions_w)
        item_actions_l.setContentsMargins(0, 0, 0, 0)
        item_actions_l.setSpacing(6)

        add_item_btn = QPushButton("+ Add Item")
        add_item_btn.setStyleSheet("font-size:11px; padding:3px 8px;")
        add_item_btn.clicked.connect(self._editor_add_item_row)

        del_item_btn = QPushButton("🗑 Remove")
        del_item_btn.setStyleSheet("font-size:11px; padding:3px 8px; color:#c0392b;")
        del_item_btn.clicked.connect(self._editor_del_item_row)

        lookup_item_btn = QPushButton("🔍 Look up DB...")
        lookup_item_btn.setStyleSheet("font-size:11px; padding:3px 8px;")
        lookup_item_btn.clicked.connect(self._editor_lookup_db_item)

        item_actions_l.addWidget(add_item_btn)
        item_actions_l.addWidget(del_item_btn)
        item_actions_l.addWidget(lookup_item_btn)
        item_actions_l.addStretch()
        self._editor_body_l.addWidget(item_actions_w)

        # Live formula preview & Validation
        self._formula_preview_lbl = QLabel("")
        self._formula_preview_lbl.setWordWrap(True)
        self._formula_preview_lbl.setStyleSheet(
            "font-size:11px; color:#1a6b2a; background:#eaf8f0; "
            "border-radius:3px; padding:5px 8px; font-family:monospace;"
        )
        self._editor_body_l.addWidget(self._formula_preview_lbl)

        self._validation_lbl = QLabel("")
        self._validation_lbl.setWordWrap(True)
        self._validation_lbl.setStyleSheet(
            "font-size:10px; color:#c0392b; background:#fff0f0; "
            "border-radius:3px; padding:4px 6px;"
        )
        self._validation_lbl.setVisible(False)
        self._editor_body_l.addWidget(self._validation_lbl)

        self._editor_body_l.addStretch()

        # Connect signals
        self._items_table.itemSelectionChanged.connect(self._update_formula_preview)
        self._items_table.itemChanged.connect(self._update_preview)

        # Parse condition logic blocks
        self._parse_conditions(rule)
        self._update_preview()

    def _editor_add_item_row(self):
        r = self._items_table.rowCount()
        self._items_table.insertRow(r)
        
        type_cb = QComboBox()
        type_cb.addItems(["Material", "Labor"])
        type_cb.setStyleSheet("font-size:10px; padding:1px;")
        self._items_table.setCellWidget(r, 0, type_cb)

        code_item = QTableWidgetItem("N/A")
        code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._items_table.setItem(r, 1, code_item)

        name_item = QTableWidgetItem("New Item - use DB lookup to search")
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._items_table.setItem(r, 2, name_item)

        formula_item = QTableWidgetItem("1")
        self._items_table.setItem(r, 3, formula_item)
        
        self._items_table.selectRow(r)
        self._update_preview()

    def _editor_del_item_row(self):
        row = self._items_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Warning", "Please select an item to remove.")
            return
        if self._items_table.rowCount() <= 1:
            QMessageBox.warning(self, "Warning", "A rule group must contain at least one item.")
            return
        self._items_table.removeRow(row)
        self._update_preview()

    def _setup_formula_column(self, row, item_code, current_formula):
        if item_code == "RECIPE_IRON":
            recipe_cb = QComboBox()
            recipe_cb.addItem("Active structure recipe", "recipe")
            try:
                from core import db_gateway as _dbg
                all_recipes = _dbg.get_recipes()
                for recipe in all_recipes:
                    recipe_cb.addItem(f"{recipe['name']} ({recipe['recipe_key']})", recipe["recipe_key"])
            except Exception as e:
                print(f"Error loading recipes into rules manager: {e}")
            
            idx = recipe_cb.findData(current_formula)
            if idx >= 0:
                recipe_cb.setCurrentIndex(idx)
            else:
                recipe_cb.addItem(current_formula, current_formula)
                recipe_cb.setCurrentIndex(recipe_cb.count() - 1)
            
            recipe_cb.setStyleSheet("font-size:10px; padding:1px;")
            self._items_table.setCellWidget(row, 3, recipe_cb)
            
            # Remove any standard text item to avoid double drawing
            self._items_table.setItem(row, 3, None)
        else:
            self._items_table.setCellWidget(row, 3, None)
            formula_item = QTableWidgetItem(current_formula)
            self._items_table.setItem(row, 3, formula_item)

    def _editor_lookup_db_item(self):
        row = self._items_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Warning", "Please select an item row to look up in the database.")
            return
        
        type_cb = self._items_table.cellWidget(row, 0)
        db_type = type_cb.currentText() if type_cb else "Material"
        
        dlg = SearchDialog(db_type, self)
        if dlg.exec():
            item = dlg.get_selected()
            if item:
                code_item = self._items_table.item(row, 1)
                if not code_item:
                    code_item = QTableWidgetItem()
                    code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._items_table.setItem(row, 1, code_item)
                code_item.setText(item.get("code") or item.get("labor_code", "N/A"))
                
                name_item = self._items_table.item(row, 2)
                if not name_item:
                    name_item = QTableWidgetItem()
                    name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._items_table.setItem(row, 2, name_item)
                name_item.setText(item.get("name") or item.get("task_name", "Unnamed"))
                
                if type_cb:
                    type_cb.setCurrentText(item.get("type", db_type))
                
                self._setup_formula_column(row, code_item.text(), "recipe")
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
        props = list(get_registry().get_all_property_data().get(obj, {}).keys())

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
        prop_info = get_registry().get_all_property_data().get(obj, {}).get(prop)
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

            # Numeric and boolean values should not be quoted in the rule condition string
            is_numeric = re.match(r"^-?\d+(\.\d+)?$", val)
            is_bool    = val.lower() in ("true", "false", "none")

            if is_numeric or is_bool:
                parts.append(f"{prop} {op} {val}")
            else:
                parts.append(f"{prop} {op} '{val}'")
        return parts

    def _toggle_advanced_mode(self, checked):
        self._raw_cond_input.setReadOnly(not checked)
        if hasattr(self, "_cond_container"):
            self._cond_container.setVisible(not checked)
            
        if checked:
            self._raw_cond_input.setStyleSheet("font-family:monospace; font-size:12px; background:#ffffff;")
        else:
            self._raw_cond_input.setStyleSheet("font-family:monospace; font-size:12px; background:#f5f5f5;")
            self._update_preview()

    def _update_preview(self):
        parts = self._build_condition_parts()
        builder = " ".join(parts).strip() if parts else "True"
        
        if hasattr(self, "_adv_cb") and not self._adv_cb.isChecked():
            if hasattr(self, "_raw_cond_input"):
                self._raw_cond_input.setText(builder)

        if hasattr(self, "_validation_lbl") and hasattr(self, "_items_table"):
            raw_cond = getattr(self, "_raw_cond_input", None)
            cond_text = raw_cond.text().strip() if raw_cond else ""
            
            props = list(get_registry().get_all_property_data().get(self.active_obj_type, {}).keys())
            ok, msg = validate_expression(cond_text, props)
            if not ok:
                self._validation_lbl.setVisible(True)
                self._validation_lbl.setText(f"\u26a0  Condition: {msg}")
            else:
                errors = []
                for row in range(self._items_table.rowCount()):
                    formula_widget = self._items_table.cellWidget(row, 3)
                    if isinstance(formula_widget, QComboBox):
                        formula_text = formula_widget.currentData() or "recipe"
                    else:
                        formula_item = self._items_table.item(row, 3)
                        formula_text = formula_item.text().strip() if formula_item else "1"
                    
                    is_recipe_formula = (formula_text == "recipe") or any(
                        formula_text.startswith(prefix) for prefix in ["DP_", "TP_", "4P_", "DTR_", "CUSTOM_", "POLE_"]
                    )
                    if is_recipe_formula:
                        ok_f, msg_f = True, ""
                    else:
                        ok_f, msg_f = validate_expression(formula_text, props)
                    
                    if not ok_f:
                        item_name_item = self._items_table.item(row, 2)
                        item_name = item_name_item.text() if item_name_item else f"Row {row+1}"
                        errors.append(f"Row {row+1} ({item_name}): {msg_f}")
                
                if errors:
                    self._validation_lbl.setVisible(True)
                    self._validation_lbl.setText("\u26a0  Formula: " + "; ".join(errors))
                else:
                    self._validation_lbl.setVisible(False)

        self._update_formula_preview()

    def _update_formula_preview(self):
        """Live-evaluate the formula against simulator context and display result."""
        if not hasattr(self, "_formula_preview_lbl"):
            return
        
        if not hasattr(self, "_items_table") or self._items_table.currentRow() < 0:
            self._formula_preview_lbl.setText("\u2192 select an item row to preview formula")
            self._formula_preview_lbl.setStyleSheet(
                "font-size:11px; color:#999; background:#f5f5f5; "
                "border-radius:3px; padding:5px 8px; font-family:monospace;"
            )
            return

        row = self._items_table.currentRow()
        formula_widget = self._items_table.cellWidget(row, 3)
        if isinstance(formula_widget, QComboBox):
            formula_text = formula_widget.currentData() or "recipe"
        else:
            formula_item = self._items_table.item(row, 3)
            formula_text = formula_item.text().strip() if formula_item else "1"

        if not formula_text:
            self._formula_preview_lbl.setVisible(False)
            return

        is_recipe_formula = (formula_text == "recipe") or any(
            formula_text.startswith(prefix) for prefix in ["DP_", "TP_", "4P_", "DTR_", "CUSTOM_", "POLE_"]
        )
        if is_recipe_formula:
            self._formula_preview_lbl.setVisible(True)
            self._formula_preview_lbl.setStyleSheet(
                "font-size:11px; color:#1a6b2a; background:#eaf8f0; "
                "border-radius:3px; padding:5px 8px; font-family:monospace;"
            )
            self._formula_preview_lbl.setText(f"\u2192 dynamic recipe: {formula_text}")
            return

        if not self.sim_widgets:
            self._formula_preview_lbl.setVisible(True)
            self._formula_preview_lbl.setStyleSheet(
                "font-size:11px; color:#999; background:#f5f5f5; "
                "border-radius:3px; padding:5px 8px; font-family:monospace;"
            )
            self._formula_preview_lbl.setText("\u2192 open simulator to preview")
            return

        try:
            ctx = self._get_sim_ctx()
            qty = evaluate_formula(formula_text, ctx)
            qty_s = f"{qty:.4f}".rstrip("0").rstrip(".")
            self._formula_preview_lbl.setVisible(True)
            self._formula_preview_lbl.setStyleSheet(
                "font-size:11px; color:#1a6b2a; background:#eaf8f0; "
                "border-radius:3px; padding:5px 8px; font-family:monospace;"
            )
            self._formula_preview_lbl.setText(
                f"\u2192 qty = {qty_s}  (simulator values)"
            )
        except Exception as exc:
            self._formula_preview_lbl.setVisible(True)
            self._formula_preview_lbl.setStyleSheet(
                "font-size:11px; color:#c0392b; background:#fff0f0; "
                "border-radius:3px; padding:5px 8px; font-family:monospace;"
            )
            self._formula_preview_lbl.setText(f"\u2192 error: {exc}")

    # ── Editor actions ────────────────────────────────────────────────────────

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
        if self.selected_rule_index == -1:
            return
        rule    = self.rules[self.selected_rule_index]
        cond    = self._raw_cond_input.text().strip()

        # Gather items from items table
        items = []
        for r in range(self._items_table.rowCount()):
            type_cb = self._items_table.cellWidget(r, 0)
            item_type = type_cb.currentText() if type_cb else "Material"
            
            code_item = self._items_table.item(r, 1)
            item_code = code_item.text() if code_item else "N/A"
            
            name_item = self._items_table.item(r, 2)
            item_name = name_item.text() if name_item else "Unnamed"
            
            formula_widget = self._items_table.cellWidget(r, 3)
            if isinstance(formula_widget, QComboBox):
                formula_text = formula_widget.currentData() or "recipe"
            else:
                formula_item = self._items_table.item(r, 3)
                formula_text = formula_item.text().strip() if formula_item else "1"
            
            items.append({
                "type": item_type,
                "item_code": item_code,
                "item_name": item_name,
                "formula": formula_text
            })

        # Validate condition and formulas before saving
        props = list(get_registry().get_all_property_data().get(rule.get("object", self.active_obj_type), {}).keys())
        ok_c, msg_c = validate_expression(cond, props)
        if not ok_c:
            QMessageBox.critical(self, "Validation Error", f"Condition syntax error:\n{msg_c}")
            return
            
        for idx, itm in enumerate(items):
            formula_text = itm["formula"]
            is_recipe_formula = (formula_text == "recipe") or any(
                formula_text.startswith(prefix) for prefix in ["DP_", "TP_", "4P_", "DTR_", "CUSTOM_", "POLE_"]
            )
            if is_recipe_formula:
                ok_f, msg_f = True, ""
            else:
                ok_f, msg_f = validate_expression(formula_text, props)
            if not ok_f:
                QMessageBox.critical(self, "Validation Error", f"Formula error in row {idx+1} ({itm['item_name']}):\n{msg_f}")
                return

        # Save to rule dict
        rule["condition"] = cond
        rule["items"] = items
        
        self.save_rules()
        self._update_tree_counts()
        self._refresh_cards()
        self._editor_hdr.setText("Editing Rule Group")
        QMessageBox.information(self, "Saved", "Rule group saved successfully.")

    def create_new_rule(self):
        new_rule = {
            "object":    self.active_obj_type,
            "condition": "True",
            "enabled":   1,
            "items": [
                {
                    "type":      "Material",
                    "item_code": "N/A",
                    "item_name": "New Item \u2014 edit me",
                    "formula":   "1",
                }
            ]
        }
        self.rules.append(new_rule)
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
        from core.property_registry import get_registry
        props = list(get_registry().get_all_property_data().get(obj_type, {}).keys())
        ok_c, msg_c = validate_expression(cond, props)
        if not ok_c:
            return False, f"Condition: {msg_c}"
        ok_f, msg_f = validate_expression(formula, props)
        if not ok_f:
            return False, f"Formula: {msg_f}"
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

    # ── Template dialog ───────────────────────────────────────────────────────

    def _open_templates(self):
        """Open the rule templates dialog and import selected template."""
        try:
            from core.rule_templates import get_templates_by_object
            grouped = get_templates_by_object()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not load templates:\n{exc}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Rule Templates")
        dlg.setMinimumSize(700, 500)
        root_l = QVBoxLayout(dlg)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)

        # Header
        hdr = QLabel("📋  Choose a template to create a pre-filled rule")
        hdr.setStyleSheet(
            "font-size:13px; font-weight:bold; padding:12px 16px; "
            "border-bottom:1px solid #ddd; background:white;"
        )
        root_l.addWidget(hdr)

        # Scroll area with template groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        container.setStyleSheet("background:#f8f8f8;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(12)

        _OBJ_ICONS = {
            "SmartPole": "🔸", "SmartStructure": "🔷",
            "SmartSpan": "🔹", "SmartConsumer": "🔶",
        }

        for obj_type in ["SmartPole", "SmartStructure", "SmartSpan", "SmartConsumer"]:
            templates = grouped.get(obj_type, [])
            if not templates:
                continue

            icon = _OBJ_ICONS.get(obj_type, "▪")
            grp = QGroupBox(f"{icon}  {obj_type.replace('Smart', 'Smart ')}")
            grp.setStyleSheet(
                "QGroupBox { font-size:12px; font-weight:bold; color:#333; "
                "border:1px solid #ddd; border-radius:6px; margin-top:8px; "
                "padding-top:18px; background:white; } "
                "QGroupBox::title { subcontrol-origin:margin; left:12px; "
                "padding:0 6px; }"
            )
            gl = QVBoxLayout(grp)
            gl.setSpacing(6)

            for tmpl in templates:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(8, 6, 8, 6)
                rl.setSpacing(8)

                # Info column
                info_w = QWidget()
                il = QVBoxLayout(info_w)
                il.setContentsMargins(0, 0, 0, 0)
                il.setSpacing(2)
                name_l = QLabel(tmpl["name"])
                name_l.setStyleSheet("font-size:12px; font-weight:bold;")
                desc_l = QLabel(tmpl.get("description", ""))
                desc_l.setStyleSheet("font-size:10px; color:#666;")
                desc_l.setWordWrap(True)

                # Pill row
                pills_w = QWidget()
                pills_l = QHBoxLayout(pills_w)
                pills_l.setContentsMargins(0, 0, 0, 0)
                pills_l.setSpacing(3)
                for p_label, p_bg, p_fg in self._condition_to_pills(tmpl["condition"]):
                    pill = QLabel(p_label)
                    pill.setStyleSheet(
                        f"background:{p_bg}; color:{p_fg}; border-radius:3px; "
                        "padding:1px 5px; font-size:9px; font-weight:bold;"
                    )
                    pills_l.addWidget(pill)
                pills_l.addStretch()

                formula_l = QLabel(f"qty = {tmpl['formula']}")
                formula_l.setStyleSheet("font-size:10px; color:#999; font-family:monospace;")

                il.addWidget(name_l)
                il.addWidget(desc_l)
                il.addWidget(pills_w)
                il.addWidget(formula_l)
                rl.addWidget(info_w, 1)

                # Badge
                r_type = tmpl.get("type", "Material")
                badge = QLabel("M" if r_type == "Material" else "L")
                badge.setFixedSize(22, 22)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setStyleSheet(
                    "border-radius:4px; font-size:10px; font-weight:bold; " + (
                        "background:#ddeeff; color:#185FA5;" if r_type == "Material"
                        else "background:#fff3e0; color:#854F0B;"
                    )
                )
                rl.addWidget(badge)

                # Import button
                imp_btn = QPushButton("Import")
                imp_btn.setStyleSheet(
                    "background:#185FA5; color:white; border:none; "
                    "padding:4px 10px; border-radius:3px; font-size:11px;"
                )
                imp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                imp_btn.clicked.connect(
                    lambda _checked=False, t=tmpl, d=dlg: self._import_template(t, d)
                )
                rl.addWidget(imp_btn)

                row.setStyleSheet(
                    "background:#fafafa; border:0.5px solid #eee; border-radius:4px;"
                )
                gl.addWidget(row)

            cl.addWidget(grp)

        cl.addStretch()
        scroll.setWidget(container)
        root_l.addWidget(scroll, 1)
        dlg.exec()

    def _import_template(self, tmpl: dict, parent_dlg: QDialog):
        """Create a new rule from a template and open it in the editor."""
        new_rule = {
            "object":    tmpl["object"],
            "condition": tmpl["condition"],
            "enabled":   1,
            "items": [
                {
                    "type":      tmpl.get("type", "Material"),
                    "item_code": tmpl.get("item_code", "N/A"),
                    "item_name": tmpl.get("item_name", "Template rule \u2014 edit me"),
                    "formula":   tmpl.get("formula", "1")
                }
            ]
        }
        self.rules.append(new_rule)
        self.selected_rule_index = len(self.rules) - 1
        parent_dlg.accept()  # Close template dialog
        self.active_obj_type = tmpl["object"]
        self._update_tree_counts()
        self._refresh_cards()
        self._build_editor(new_rule)
        QMessageBox.information(
            self, "Template Imported",
            f"Rule group created from template: {tmpl['name']}\n\n"
            "You can now edit the item list, condition, and formulas."
        )

    # ── AI describe ───────────────────────────────────────────────────────────

    def _open_ai_describe(self):
        """Use AI Assistant to parse requests and modify/create rules."""
        try:
            from ui.dialogs.ai_assistant import AIAssistantDialog
            dlg = AIAssistantDialog(self, obj_type=self.active_obj_type, current_rules=self.rules)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                ops = dlg.get_selected_operations()
                if not ops: return
                
                changed = False
                for op in ops:
                    action = str(op.get("action", "")).upper()
                    target_obj = op.get("object", self.active_obj_type)
                    if action == "CREATE":
                        new_r = {
                            "object": target_obj,
                            "condition": op.get("condition", "True"),
                            "enabled": 1,
                            "items": [
                                {
                                    "type": op.get("type", "Material"),
                                    "item_code": "",
                                    "item_name": op.get("item_name", "AI Suggested Item"),
                                    "formula": str(op.get("formula", "1"))
                                }
                            ]
                        }
                        self.rules.append(new_r)
                        changed = True
                    elif action == "UPDATE":
                        try:
                            real_id = int(op.get("rule_id", -1))
                            if 0 <= real_id < len(self.rules):
                                r = self.rules[real_id]
                                if "condition" in op: r["condition"] = op["condition"]
                                if r.get("items"):
                                    itm = r["items"][0]
                                    if "formula" in op: itm["formula"] = str(op["formula"])
                                    if "item_name" in op: itm["item_name"] = op["item_name"]
                                changed = True
                        except (ValueError, TypeError):
                            pass
                
                if changed:
                    self._update_tree_counts()
                    self._refresh_cards()
                    QMessageBox.information(self, "AI Update Applied", f"Changes applied to memory. Click 'Save' on individual rules to persist.")
                    
        except Exception as exc:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "AI Assistant Error", f"An error occurred:\n{exc}")

