from core import db_gateway
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
    QLabel, QScrollArea, QDialogButtonBox, QFrame, QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from core.constants import (
    PROPERTY_DATA, 
     
    SIM_DEFAULTS,  
)


def _runtime_property_data() -> dict:
    return property_catalog.build_property_data(PROPERTY_DATA)


def _runtime_sim_defaults() -> dict:
    return property_catalog.build_sim_defaults(SIM_DEFAULTS)


from ui.dialogs._shared import ClickableCard

class ProjectSetupDialog(QDialog):
    """
    Project Setup Wizard — shown on first launch and via 'Project Settings'.

    Captures
    --------
    subject       : project name / description
    lat, long     : GPS coordinates
    division      : utility division name
    circle        : utility circle name
    project_type  : one of db_gateway.get_project_types() (drives supervision rate)
    use_uh        : bool — use UH (readymade) materials instead of raw steel
    supervision_rate : float — auto-derived from project_type

    Parameters
    ----------
    current_meta : dict  — pre-populate fields from existing project_meta
    parent       : QWidget
    first_run    : bool  — if True, shows a welcome banner; if False,
                           shows an "Edit Settings" heading instead
    """

    def __init__(self, current_meta: dict, parent=None, first_run: bool = True):
        super().__init__(parent)
        self._meta = dict(current_meta)
        self.setWindowTitle(
            "New Project Setup" if first_run else "Project Settings"
        )
        self.setMinimumWidth(480)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Banner ────────────────────────────────────────────────────────
        if first_run:
            banner = QLabel(
                f"<b style='font-size:14px;'>{APP_DISPLAY_NAME} v{APP_VERSION}</b><br>"
                "<span style='color:#555;'>Set up your project before drawing.</span>"
            )
            banner.setStyleSheet(
                "background:#ddeeff; padding:10px; border-radius:5px;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)
        else:
            lbl = QLabel("<b>Edit Project Settings</b>")
            lbl.setStyleSheet("font-size:13px;")
            root.addWidget(lbl)

        # ── Tabbed Layout ─────────────────────────────────────────────────
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        # ── Tab 1: General Settings ───────────────────────────────────────
        tab_general = QWidget()
        tab_general_layout = QVBoxLayout(tab_general)
        tab_general_layout.setContentsMargins(8, 8, 8, 8)
        
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Subject — max ~5 lines (300 chars) with live counter
        _SUBJECT_MAX = 300
        self._subject = QTextEdit(self._meta.get("subject", ""))
        self._subject.setPlaceholderText("e.g. GOCHIYA II LT Line Extension")
        self._subject.setFixedHeight(80)
        self._subject.setStyleSheet("font-size: 13px; padding: 4px; border: 1px solid #ccc; border-radius: 4px;")
        _subj_counter = QLabel()
        _subj_counter.setStyleSheet("color:#888; font-size:11px;")

        def _update_counter() -> None:
            text = self._subject.toPlainText()
            if len(text) > _SUBJECT_MAX:
                text = text[:_SUBJECT_MAX]
                cursor = self._subject.textCursor()
                pos = cursor.position()
                self._subject.setPlainText(text)
                cursor.setPosition(min(pos, len(text)))
                self._subject.setTextCursor(cursor)
            remaining = _SUBJECT_MAX - len(text)
            _subj_counter.setText(f"{len(text)}/{_SUBJECT_MAX} chars")
            _subj_counter.setStyleSheet(
                "color:#c0392b; font-size:11px;" if remaining < 30
                else "color:#888; font-size:11px;"
            )

        self._subject.textChanged.connect(_update_counter)
        _update_counter()

        _subj_w = QWidget()
        _subj_l = QVBoxLayout(_subj_w)
        _subj_l.setContentsMargins(0, 0, 0, 0)
        _subj_l.setSpacing(2)
        _subj_l.addWidget(self._subject)
        _subj_l.addWidget(_subj_counter)
        form.addRow("Project Name:", _subj_w)

        # Lat / Long side by side
        ll_w = QWidget()
        ll_l = QHBoxLayout(ll_w)
        ll_l.setContentsMargins(0, 0, 0, 0)
        ll_l.setSpacing(6)
        self._lat  = QLineEdit(self._meta.get("lat", ""))
        self._long = QLineEdit(self._meta.get("long", ""))
        self._lat.setPlaceholderText("Latitude")
        self._long.setPlaceholderText("Longitude")
        ll_l.addWidget(self._lat)
        ll_l.addWidget(self._long)
        form.addRow("Lat / Long:", ll_w)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#ccc;")
        form.addRow(sep)

        # Project type
        self._proj_type = QComboBox()
        self._proj_type.addItems(db_gateway.get_project_types())
        current_type = self._meta.get("project_type", "NSC")
        if current_type in db_gateway.get_project_types():
            self._proj_type.setCurrentText(current_type)
        else:
            self._proj_type.setCurrentText("NSC")
        form.addRow("Project Type:", self._proj_type)

        # Supervision rate display (read-only)
        self._sup_lbl = QLabel()
        self._sup_lbl.setStyleSheet("color:#27ae60; font-weight:bold;")
        form.addRow("Supervision Rate:", self._sup_lbl)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#ccc;")
        form.addRow(sep2)

        # UH toggle (NSC projects only)
        self._uh = QCheckBox(
            "Use UH (Readymade) Materials instead of Raw Steel"
        )
        self._uh.setStyleSheet("font-weight:bold; color:#107C41;")
        self._uh.setChecked(self._meta.get("use_uh", False))
        form.addRow(self._uh)

        # Now connect signal & trigger initial sync (after _uh exists)
        self._proj_type.currentTextChanged.connect(self._on_type_changed)
        self._on_type_changed(self._proj_type.currentText())

        tab_general_layout.addLayout(form)
        self.tabs.addTab(tab_general, "General Settings")

        # ── Tab 2: Billing & PO Details ───────────────────────────────────
        tab_billing = QWidget()
        tab_billing_layout = QVBoxLayout(tab_billing)
        tab_billing_layout.setContentsMargins(8, 8, 8, 8)

        form_billing = QFormLayout()
        form_billing.setSpacing(8)
        form_billing.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._project_id = QLineEdit(self._meta.get("project_id", ""))
        self._project_id.setPlaceholderText("e.g. WBSEDCL/RURAL-42")
        form_billing.addRow("Project ID:", self._project_id)

        self._po_no = QLineEdit(self._meta.get("po_no", ""))
        self._po_no.setPlaceholderText("e.g. PO/ENG/2026/89")
        form_billing.addRow("PO Number:", self._po_no)

        self._po_date = QLineEdit(self._meta.get("po_date", ""))
        self._po_date.setPlaceholderText("e.g. DD-MM-YYYY")
        form_billing.addRow("PO Date:", self._po_date)

        self._vendor_id = QLineEdit(self._meta.get("vendor_id", ""))
        self._vendor_id.setPlaceholderText("e.g. 700099")
        form_billing.addRow("Vendor ID:", self._vendor_id)

        self._comm_date = QLineEdit(self._meta.get("comm_date", ""))
        self._comm_date.setPlaceholderText("e.g. DD-MM-YYYY")
        form_billing.addRow("Commencement Date:", self._comm_date)

        self._comp_date = QLineEdit(self._meta.get("comp_date", ""))
        self._comp_date.setPlaceholderText("e.g. DD-MM-YYYY")
        form_billing.addRow("Completion Date:", self._comp_date)

        self._meas_date = QLineEdit(self._meta.get("meas_date", ""))
        self._meas_date.setPlaceholderText("e.g. DD-MM-YYYY")
        form_billing.addRow("Measurement Date:", self._meas_date)

        self._meas_taken_by = QLineEdit(self._meta.get("meas_taken_by", ""))
        self._meas_taken_by.setPlaceholderText("e.g. Sub-Assistant Engineer")
        form_billing.addRow("Meas. Taken By:", self._meas_taken_by)

        self._certified_by = QLineEdit(self._meta.get("certified_by", ""))
        self._certified_by.setPlaceholderText("e.g. Assistant Engineer")
        form_billing.addRow("Certified By:", self._certified_by)

        tab_billing_layout.addLayout(form_billing)
        self.tabs.addTab(tab_billing, "Billing & PO Details")

        # ── Buttons ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("✔ Continue" if first_run else "✔ Save")
            ok_btn.setStyleSheet(
                "background:#2980b9; color:white; font-weight:bold; padding:6px 16px;"
            )
        root.addWidget(btns)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_type_changed(self, proj_type: str):
        rate = db_gateway.get_supervision_rates().get(proj_type, 0.10)
        self._sup_lbl.setText(f"{int(rate * 100)}%")
        self._meta["project_type"]     = proj_type
        self._meta["supervision_rate"] = rate
        self._sync_uh_visibility(proj_type)

    def _sync_uh_visibility(self, proj_type: str):
        is_nsc = proj_type == "NSC"
        self._uh.setEnabled(is_nsc)
        if not is_nsc:
            self._uh.setChecked(False)

    def _on_accept(self):
        subj = self._subject.toPlainText().strip()
        if not subj:
            QMessageBox.warning(
                self, "Required", "Please enter a Project Name."
            )
            return
        self._meta["subject"]  = subj
        self._meta["lat"]      = self._lat.text().strip()
        self._meta["long"]     = self._long.text().strip()
        self._meta["use_uh"]   = self._uh.isChecked()
        proj_type = self._proj_type.currentText()
        self._meta["project_type"]     = proj_type
        self._meta["supervision_rate"] = db_gateway.get_supervision_rates().get(proj_type, 0.10)
        
        # Save billing details
        self._meta["project_id"]    = self._project_id.text().strip()
        self._meta["po_no"]         = self._po_no.text().strip()
        self._meta["po_date"]       = self._po_date.text().strip()
        self._meta["vendor_id"]     = self._vendor_id.text().strip()
        self._meta["comm_date"]     = self._comm_date.text().strip()
        self._meta["comp_date"]     = self._comp_date.text().strip()
        self._meta["meas_date"]     = self._meas_date.text().strip()
        self._meta["meas_taken_by"] = self._meas_taken_by.text().strip()
        self._meta["certified_by"]  = self._certified_by.text().strip()
        
        self.accept()

    def get_meta(self) -> dict:
        """Call after exec() == Accepted to retrieve the filled project_meta."""
        return dict(self._meta)


# ─────────────────────────────────────────────────────────────────────────────
#  SearchDialog
# ─────────────────────────────────────────────────────────────────────────────

