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

class SettingsDialog(QDialog):
    """Gateway dialog for advanced settings."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Advanced Settings")
        self.setFixedSize(320, 140)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(12, 12, 12, 12)

        db_btn = QPushButton("🗃️  Master Database (Excel Sync)")
        db_btn.clicked.connect(self.parent_app.open_db_manager)
        db_btn.setStyleSheet("padding:8px; font-size:12px;")
        lay.addWidget(db_btn)

        rule_btn = QPushButton("🧠  Ruleset Manager")
        rule_btn.clicked.connect(self.parent_app.open_rule_manager)
        rule_btn.setStyleSheet("padding:8px; font-size:12px;")
        lay.addWidget(rule_btn)

        prop_btn = QPushButton("🧩  Property Editor")
        prop_btn.clicked.connect(self.parent_app.open_property_editor)
        prop_btn.setStyleSheet("padding:8px; font-size:12px;")
        lay.addWidget(prop_btn)

        lay.addStretch()


