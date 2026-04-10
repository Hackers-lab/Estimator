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

class PlacementDefaultsDialog(QDialog):
    """
    Lets the user configure what values are applied when a new canvas
    object is placed (pole heights, conductor types, span lengths, etc.).
    Changes are persisted to ``defaults.json`` immediately on Save.
    """

    _HEIGHT_OPTIONS = {
        "PCC":    ["8MTR", "9MTR"],
        "STP":    ["9MTR", "9.5MTR", "11MTR"],
        "H-BEAM": ["13MTR"],
    }
    _LT_CONDUCTORS = ["AB Cable", "ACSR", "PVC Cable"]
    _HT_CONDUCTORS = ["ACSR", "AB Cable"]
    _CONDUCTOR_SIZES = {
        ("AB Cable",  "LT"): ["3CX50+1CX35", "3CX50+1CX16+1CX35", "3CX70+1CX16+1CX50"],
        ("AB Cable",  "HT"): ["3CX50+1CX150", "3CX95+1CX70"],
        ("ACSR",      "LT"): ["30SQMM", "50SQMM"],
        ("ACSR",      "HT"): ["30SQMM", "50SQMM"],
        ("PVC Cable", "LT"): ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM", "95 SQMM", "120 SQMM"],
        ("PVC Cable", "HT"): ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM", "95 SQMM", "120 SQMM"],
    }
    _SD_SIZES = ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Placement Defaults")
        self.setMinimumWidth(480)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        tabs = QTabWidget()

        poles_page = self._build_poles_tab()
        poles_scroll = QScrollArea()
        poles_scroll.setWidgetResizable(True)
        poles_scroll.setFrameShape(QFrame.Shape.NoFrame)
        poles_scroll.setWidget(poles_page)
        tabs.addTab(poles_scroll, "⚡ Poles & Structures")

        spans_page = self._build_spans_tab()
        spans_scroll = QScrollArea()
        spans_scroll.setWidgetResizable(True)
        spans_scroll.setFrameShape(QFrame.Shape.NoFrame)
        spans_scroll.setWidget(spans_page)
        tabs.addTab(spans_scroll, "📏 Spans & Service Drop")

        labels_page = self._build_labels_tab()
        labels_scroll = QScrollArea()
        labels_scroll.setWidgetResizable(True)
        labels_scroll.setFrameShape(QFrame.Shape.NoFrame)
        labels_scroll.setWidget(labels_page)
        tabs.addTab(labels_scroll, "🏷 Labels")

        self._tabs = tabs   # keep reference for tab-aware reset
        root.addWidget(tabs)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("↩  Reset this tab")
        reset_btn.setToolTip("Reset only the currently visible tab to factory values")
        reset_btn.clicked.connect(self._reset_current_tab)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        btn_row.addWidget(btns)
        root.addLayout(btn_row)

    def _wrap_collapsible(self, title: str, content: QWidget, expanded: bool = False) -> QWidget:
        """Return a simple collapsible block with a header button."""
        block = QWidget()
        lay = QVBoxLayout(block)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        btn = QPushButton()
        btn.setCheckable(True)
        btn.setChecked(expanded)
        btn.setStyleSheet(
            "text-align:left; padding:6px 8px; font-weight:600;"
            "background:#f3f4f6; border:1px solid #d8dbe0; border-radius:6px;"
        )

        def _sync(checked: bool) -> None:
            btn.setText(("▼ " if checked else "▶ ") + title)
            content.setVisible(checked)

        btn.toggled.connect(_sync)
        _sync(expanded)

        lay.addWidget(btn)
        lay.addWidget(content)
        return block

    # ── Tab builders ──────────────────────────────────────────────────────

    def _build_poles_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        d = defaults.current

        # ── LT Pole ───────────────────────────────────────────────────────
        lt_grp = QGroupBox("LT Pole")
        lt_frm = QFormLayout(lt_grp)

        self.lt_type2 = QComboBox()
        self.lt_type2.addItems(["PCC", "STP", "H-BEAM"])
        self.lt_type2.setCurrentText(d["lt_pole_type2"])
        lt_frm.addRow("Material:", self.lt_type2)

        self.lt_height = QComboBox()
        self._refresh_heights(self.lt_type2, self.lt_height, d["lt_height"])
        self.lt_type2.currentTextChanged.connect(
            lambda: self._refresh_heights(self.lt_type2, self.lt_height)
        )
        lt_frm.addRow("Height:", self.lt_height)

        self.lt_earth = QSpinBox()
        self.lt_earth.setRange(0, 20)
        self.lt_earth.setValue(d["lt_earth_count"])
        lt_frm.addRow("Earth Sets:", self.lt_earth)

        self.lt_stay = QSpinBox()
        self.lt_stay.setRange(0, 20)
        self.lt_stay.setValue(d["lt_stay_count"])
        lt_frm.addRow("Stay Sets:", self.lt_stay)

        self.lt_dist_box = QCheckBox("Distribution Box required by default")
        self.lt_dist_box.setChecked(bool(d.get("lt_dist_box_required", True)))
        lt_frm.addRow(self.lt_dist_box)

        lay.addWidget(self._wrap_collapsible("LT Pole", lt_grp, expanded=True))

        # ── HT Pole ───────────────────────────────────────────────────────
        ht_grp = QGroupBox("HT Pole")
        ht_frm = QFormLayout(ht_grp)

        self.ht_type2 = QComboBox()
        self.ht_type2.addItems(["PCC", "STP", "H-BEAM"])
        self.ht_type2.setCurrentText(d["ht_pole_type2"])
        ht_frm.addRow("Material:", self.ht_type2)

        self.ht_height = QComboBox()
        self._refresh_heights(self.ht_type2, self.ht_height, d["ht_height"])
        self.ht_type2.currentTextChanged.connect(
            lambda: self._refresh_heights(self.ht_type2, self.ht_height)
        )
        ht_frm.addRow("Height:", self.ht_height)

        self.ht_earth = QSpinBox()
        self.ht_earth.setRange(0, 20)
        self.ht_earth.setValue(d["ht_earth_count"])
        ht_frm.addRow("Earth Sets:", self.ht_earth)

        self.ht_stay = QSpinBox()
        self.ht_stay.setRange(0, 20)
        self.ht_stay.setValue(d["ht_stay_count"])
        ht_frm.addRow("Stay Sets:", self.ht_stay)

        lay.addWidget(self._wrap_collapsible("HT Pole", ht_grp, expanded=False))

        # ── Structure ─────────────────────────────────────────────────────
        st_grp = QGroupBox("Structure (DP / TP / 4P / DTR)")
        st_frm = QFormLayout(st_grp)

        self.st_type2 = QComboBox()
        self.st_type2.addItems(["PCC", "STP", "H-BEAM"])
        self.st_type2.setCurrentText(d["struct_pole_type2"])
        st_frm.addRow("Material:", self.st_type2)

        self.st_height = QComboBox()
        self._refresh_heights(self.st_type2, self.st_height, d["struct_height"])
        self.st_type2.currentTextChanged.connect(
            lambda: self._refresh_heights(self.st_type2, self.st_height)
        )
        st_frm.addRow("Height:", self.st_height)

        self.st_stay = QSpinBox()
        self.st_stay.setRange(0, 20)
        self.st_stay.setValue(d["struct_stay_count"])
        st_frm.addRow("Stay Sets:", self.st_stay)

        self.st_orient = QComboBox()
        self.st_orient.addItems(["Horizontal", "Vertical"])
        self.st_orient.setCurrentText(d.get("struct_orientation", "Horizontal"))
        st_frm.addRow("Orientation:", self.st_orient)

        self.st_kiosk = QCheckBox("DTR kiosk required by default")
        self.st_kiosk.setChecked(bool(d.get("dtr_kiosk_required", True)))
        st_frm.addRow(self.st_kiosk)

        lay.addWidget(self._wrap_collapsible("Structure (DP / TP / 4P / DTR)", st_grp, expanded=False))

        # ── Shared ────────────────────────────────────────────────────────
        ext_grp = QGroupBox("Extension")
        ext_frm = QFormLayout(ext_grp)
        self.ext_ht = QDoubleSpinBox()
        self.ext_ht.setRange(1.0, 10.0)
        self.ext_ht.setSingleStep(0.5)
        self.ext_ht.setSuffix(" m")
        self.ext_ht.setValue(d["extension_height"])
        ext_frm.addRow("Default Ext. Height:", self.ext_ht)
        lay.addWidget(self._wrap_collapsible("Extension", ext_grp, expanded=False))

        # ── Placement rules ──────────────────────────────────────────────
        pr_grp = QGroupBox("Placement Rules")
        pr_frm = QFormLayout(pr_grp)

        self.node_min_gap = QSpinBox()
        self.node_min_gap.setRange(5, 500)
        self.node_min_gap.setSuffix(" units")
        self.node_min_gap.setValue(int(d.get("node_min_gap", 36)))
        pr_frm.addRow("Min node spacing:", self.node_min_gap)

        self.ex_stay_tol = QSpinBox()
        self.ex_stay_tol.setRange(0, 90)
        self.ex_stay_tol.setSuffix(" deg")
        self.ex_stay_tol.setValue(int(d.get("existing_stay_angle_tolerance_deg", 20)))
        pr_frm.addRow("Existing stay angle tol:", self.ex_stay_tol)
        lay.addWidget(self._wrap_collapsible("Placement Rules", pr_grp, expanded=False))

        lay.addStretch()
        return w

    def _build_spans_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        d = defaults.current

        # ── LT Span ───────────────────────────────────────────────────────
        lt_grp = QGroupBox("LT Span")
        lt_frm = QFormLayout(lt_grp)

        self.lt_cond = QComboBox()
        self.lt_cond.addItems(self._LT_CONDUCTORS)
        self.lt_cond.setCurrentText(d["lt_conductor"])
        lt_frm.addRow("Conductor:", self.lt_cond)

        self.lt_size = QComboBox()
        self.lt_size.setEditable(True)
        self._refresh_sizes(self.lt_cond, self.lt_size, "LT", d["lt_conductor_size"])
        self.lt_cond.currentTextChanged.connect(
            lambda: self._refresh_sizes(self.lt_cond, self.lt_size, "LT")
        )
        lt_frm.addRow("Conductor Size:", self.lt_size)

        self.lt_len = QSpinBox()
        self.lt_len.setRange(1, 5000)
        self.lt_len.setSuffix(" m")
        self.lt_len.setValue(d["lt_span_length"])
        lt_frm.addRow("Default Length:", self.lt_len)

        self.lt_wires = QComboBox()
        self.lt_wires.addItems(["1", "2", "3", "4"])
        self.lt_wires.setCurrentText(str(d["lt_wire_count"]))
        lt_frm.addRow("Wire Count:", self.lt_wires)

        lay.addWidget(self._wrap_collapsible("LT Span", lt_grp, expanded=True))

        # ── HT Span ───────────────────────────────────────────────────────
        ht_grp = QGroupBox("HT Span")
        ht_frm = QFormLayout(ht_grp)

        self.ht_cond = QComboBox()
        self.ht_cond.addItems(self._HT_CONDUCTORS)
        self.ht_cond.setCurrentText(d["ht_conductor"])
        ht_frm.addRow("Conductor:", self.ht_cond)

        self.ht_size = QComboBox()
        self.ht_size.setEditable(True)
        self._refresh_sizes(self.ht_cond, self.ht_size, "HT", d["ht_conductor_size"])
        self.ht_cond.currentTextChanged.connect(
            lambda: self._refresh_sizes(self.ht_cond, self.ht_size, "HT")
        )
        ht_frm.addRow("Conductor Size:", self.ht_size)

        self.ht_len = QSpinBox()
        self.ht_len.setRange(1, 5000)
        self.ht_len.setSuffix(" m")
        self.ht_len.setValue(d["ht_span_length"])
        ht_frm.addRow("Default Length:", self.ht_len)

        self.ht_wires = QComboBox()
        self.ht_wires.addItems(["1", "2", "3", "4"])
        self.ht_wires.setCurrentText(str(d["ht_wire_count"]))
        ht_frm.addRow("Wire Count:", self.ht_wires)

        self.ht_cg = QCheckBox("Cradle Guard (CG) required by default")
        self.ht_cg.setChecked(bool(d.get("ht_cg_required", True)))
        ht_frm.addRow(self.ht_cg)

        lay.addWidget(self._wrap_collapsible("HT Span", ht_grp, expanded=False))

        # ── Service Drop ──────────────────────────────────────────────────
        sd_grp = QGroupBox("Service Drop")
        sd_frm = QFormLayout(sd_grp)

        self.sd_size = QComboBox()
        self.sd_size.addItems(self._SD_SIZES)
        self.sd_size.setCurrentText(d["sd_conductor_size"])
        sd_frm.addRow("Cable Size:", self.sd_size)

        self.sd_len = QSpinBox()
        self.sd_len.setRange(1, 500)
        self.sd_len.setSuffix(" m")
        self.sd_len.setValue(d["sd_length"])
        sd_frm.addRow("Default Length:", self.sd_len)

        self.sd_phase = QComboBox()
        self.sd_phase.addItems(["1 Phase", "3 Phase"])
        self.sd_phase.setCurrentText(d["sd_phase"])
        sd_frm.addRow("Phase:", self.sd_phase)

        lay.addWidget(self._wrap_collapsible("Service Drop", sd_grp, expanded=False))

        lay.addStretch()
        return w

    # ── Cascade helpers ───────────────────────────────────────────────────

    def _build_labels_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        d = defaults.current

        grp = QGroupBox("Canvas Label Prefixes")
        frm = QFormLayout(grp)
        frm.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        note = QLabel(
            "Each object on canvas is labelled with the prefix below\n"
            "followed by a sequential number (e.g. PP1, PP2 …).\n"
            "Changes take effect the next time a label is refreshed."
        )
        note.setStyleSheet("color: #555; font-size: 11px;")
        frm.addRow(note)

        self.lbl_new_lt = QLineEdit(d.get("label_new_lt", "PP"))
        self.lbl_new_lt.setMaxLength(8)
        frm.addRow("New LT Pole prefix:", self.lbl_new_lt)

        self.lbl_new_ht = QLineEdit(d.get("label_new_ht", "HP"))
        self.lbl_new_ht.setMaxLength(8)
        frm.addRow("New HT Pole prefix:", self.lbl_new_ht)

        self.lbl_ex_pole = QLineEdit(d.get("label_ex_pole", "EP"))
        self.lbl_ex_pole.setMaxLength(8)
        frm.addRow("Existing Pole prefix:", self.lbl_ex_pole)

        self.lbl_dp = QLineEdit(d.get("label_dp", "DP"))
        self.lbl_dp.setMaxLength(8)
        frm.addRow("DP Structure prefix:", self.lbl_dp)

        self.lbl_tp = QLineEdit(d.get("label_tp", "TP"))
        self.lbl_tp.setMaxLength(8)
        frm.addRow("TP Structure prefix:", self.lbl_tp)

        self.lbl_4p = QLineEdit(d.get("label_4p", "4P"))
        self.lbl_4p.setMaxLength(8)
        frm.addRow("4P Structure prefix:", self.lbl_4p)

        self.lbl_dtr = QLineEdit(d.get("label_dtr", "DTR"))
        self.lbl_dtr.setMaxLength(8)
        frm.addRow("DTR Sub-station prefix:", self.lbl_dtr)

        self.lbl_consumer = QLineEdit(d.get("label_consumer", "SC"))
        self.lbl_consumer.setMaxLength(8)
        frm.addRow("Consumer prefix:", self.lbl_consumer)

        lay.addWidget(grp)
        lay.addStretch()
        return w

    def _refresh_heights(self, type2_cb: QComboBox, height_cb: QComboBox,
                         current_val: str = "") -> None:
        opts = self._HEIGHT_OPTIONS.get(type2_cb.currentText(), ["8MTR", "9MTR"])
        height_cb.blockSignals(True)
        height_cb.clear()
        height_cb.addItems(opts)
        if current_val in opts:
            height_cb.setCurrentText(current_val)
        height_cb.blockSignals(False)

    def _refresh_sizes(self, cond_cb: QComboBox, size_cb: QComboBox,
                       voltage: str, current_val: str = "") -> None:
        key  = (cond_cb.currentText(), voltage)
        opts = self._CONDUCTOR_SIZES.get(key, ["10 SQMM"])
        size_cb.blockSignals(True)
        size_cb.clear()
        size_cb.addItems(opts)
        if current_val and current_val not in opts:
            size_cb.addItem(current_val)   # preserve user-typed custom size
        if current_val:
            size_cb.setCurrentText(current_val)
        size_cb.blockSignals(False)

    # ── Actions ───────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        return {
            "lt_pole_type2":     self.lt_type2.currentText(),
            "lt_height":         self.lt_height.currentText(),
            "lt_earth_count":    self.lt_earth.value(),
            "lt_stay_count":       self.lt_stay.value(),
            "lt_dist_box_required": self.lt_dist_box.isChecked(),
            "ht_pole_type2":     self.ht_type2.currentText(),
            "ht_height":         self.ht_height.currentText(),
            "ht_earth_count":    self.ht_earth.value(),
            "ht_stay_count":     self.ht_stay.value(),
            "struct_pole_type2": self.st_type2.currentText(),
            "struct_height":     self.st_height.currentText(),
            "struct_stay_count": self.st_stay.value(),
            "struct_orientation": self.st_orient.currentText(),
            "dtr_kiosk_required": self.st_kiosk.isChecked(),
            "extension_height":  self.ext_ht.value(),
            "node_min_gap":      self.node_min_gap.value(),
            "existing_stay_angle_tolerance_deg": self.ex_stay_tol.value(),
            "lt_conductor":      self.lt_cond.currentText(),
            "lt_conductor_size": self.lt_size.currentText(),
            "lt_span_length":    self.lt_len.value(),
            "lt_wire_count":     self.lt_wires.currentText(),
            "ht_conductor":      self.ht_cond.currentText(),
            "ht_conductor_size": self.ht_size.currentText(),
            "ht_span_length":    self.ht_len.value(),
            "ht_wire_count":     self.ht_wires.currentText(),
            "ht_cg_required":    self.ht_cg.isChecked(),
            "sd_conductor_size": self.sd_size.currentText(),
            "sd_length":         self.sd_len.value(),
            "sd_phase":          self.sd_phase.currentText(),
            # Label prefixes
            "label_new_lt":   self.lbl_new_lt.text().strip() or "PP",
            "label_new_ht":   self.lbl_new_ht.text().strip() or "HP",
            "label_ex_pole":  self.lbl_ex_pole.text().strip() or "EP",
            "label_dp":       self.lbl_dp.text().strip() or "DP",
            "label_tp":       self.lbl_tp.text().strip() or "TP",
            "label_4p":       self.lbl_4p.text().strip() or "4P",
            "label_dtr":      self.lbl_dtr.text().strip() or "DTR",
            "label_consumer": self.lbl_consumer.text().strip() or "SC",
        }

    def _save(self) -> None:
        defaults.save(self._collect())
        self.accept()

    def _reset_current_tab(self) -> None:
        """Reset only the widgets on the currently visible tab to factory values."""
        from PyQt6.QtWidgets import QMessageBox
        from core.defaults import _FACTORY
        tab_names = [
            self._tabs.tabText(i) for i in range(self._tabs.count())
        ]
        idx  = self._tabs.currentIndex()
        name = tab_names[idx]
        # Strip emoji characters before Python 3.12 (no backslashes in f-string expressions)
        plain_name = name.encode("ascii", errors="ignore").decode("ascii").strip()
        if QMessageBox.question(
            self, "Reset Tab",
            f'Reset "{plain_name}" defaults to factory values?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        f = _FACTORY
        if idx == 0:   # Poles & Structures
            self.lt_type2.setCurrentText(f["lt_pole_type2"])
            self._refresh_heights(self.lt_type2, self.lt_height, f["lt_height"])
            self.lt_earth.setValue(f["lt_earth_count"])
            self.lt_stay.setValue(f["lt_stay_count"])
            self.lt_dist_box.setChecked(bool(f["lt_dist_box_required"]))
            self.ht_type2.setCurrentText(f["ht_pole_type2"])
            self._refresh_heights(self.ht_type2, self.ht_height, f["ht_height"])
            self.ht_earth.setValue(f["ht_earth_count"])
            self.ht_stay.setValue(f["ht_stay_count"])
            self.st_type2.setCurrentText(f["struct_pole_type2"])
            self._refresh_heights(self.st_type2, self.st_height, f["struct_height"])
            self.st_stay.setValue(f["struct_stay_count"])
            self.st_orient.setCurrentText(f["struct_orientation"])
            self.st_kiosk.setChecked(bool(f["dtr_kiosk_required"]))
            self.ext_ht.setValue(f["extension_height"])
            self.node_min_gap.setValue(int(f["node_min_gap"]))
            self.ex_stay_tol.setValue(int(f["existing_stay_angle_tolerance_deg"]))
        elif idx == 1:   # Spans & Service Drop
            self.lt_cond.setCurrentText(f["lt_conductor"])
            self._refresh_sizes(self.lt_cond, self.lt_size, "LT", f["lt_conductor_size"])
            self.lt_len.setValue(f["lt_span_length"])
            self.lt_wires.setCurrentText(str(f["lt_wire_count"]))
            self.ht_cond.setCurrentText(f["ht_conductor"])
            self._refresh_sizes(self.ht_cond, self.ht_size, "HT", f["ht_conductor_size"])
            self.ht_len.setValue(f["ht_span_length"])
            self.ht_wires.setCurrentText(str(f["ht_wire_count"]))
            self.ht_cg.setChecked(bool(f["ht_cg_required"]))
            self.sd_size.setCurrentText(f["sd_conductor_size"])
            self.sd_len.setValue(f["sd_length"])
            self.sd_phase.setCurrentText(f["sd_phase"])
        elif idx == 2:   # Labels
            self.lbl_new_lt.setText(f["label_new_lt"])
            self.lbl_new_ht.setText(f["label_new_ht"])
            self.lbl_ex_pole.setText(f["label_ex_pole"])
            self.lbl_dp.setText(f["label_dp"])
            self.lbl_tp.setText(f["label_tp"])
            self.lbl_4p.setText(f["label_4p"])
            self.lbl_dtr.setText(f["label_dtr"])
            self.lbl_consumer.setText(f["label_consumer"])

    def _reset(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(
            self, "Reset Defaults",
            "Reset ALL placement defaults to factory values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            defaults.reset_to_factory()
            self.reject()   # close; user can reopen to see factory values


# ─────────────────────────────────────────────────────────────────────────────
#  DatabaseManagerDialog
# ─────────────────────────────────────────────────────────────────────────────

