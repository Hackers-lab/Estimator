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

from core import property_catalog
from core.database import DB_PATH

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget,
    QPushButton, QLabel,
)

from core.constants import (
    PROPERTY_DATA, 
     
    SIM_DEFAULTS,  
)


def _runtime_property_data() -> dict:
    return property_catalog.build_property_data(PROPERTY_DATA)


def _runtime_sim_defaults() -> dict:
    return property_catalog.build_sim_defaults(SIM_DEFAULTS)



class SearchDialog(QDialog):
    """
    Search the materials or labour database and pick an item to add
    to the live estimate as a custom (override) entry.
    """

    def __init__(self, db_type: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Search & Add {db_type}")
        self.setMinimumSize(600, 420)

        lay = QVBoxLayout(self)

        # Type badge
        badge_color = "#3498db" if db_type == "Material" else "#e67e22"
        badge = QLabel(f"  {db_type} Database  ")
        badge.setStyleSheet(
            f"background:{badge_color}; color:white; font-weight:bold;"
            "padding:4px 10px; border-radius:3px;"
        )
        badge.setFixedHeight(28)
        lay.addWidget(badge)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Type to search…")
        self._search.setStyleSheet("padding:6px; font-size:12px;")
        lay.addWidget(self._search)

        self._list = QListWidget()
        self._list.setStyleSheet("font-size:11px;")
        lay.addWidget(self._list)

        self._search.textChanged.connect(self._filter)
        self._list.itemDoubleClicked.connect(self.accept)

        add_btn = QPushButton(f"✔ Add Selected {db_type} to Estimate")
        add_btn.setStyleSheet(
            f"background:{badge_color}; color:white;"
            "font-weight:bold; padding:8px; font-size:12px;"
        )
        add_btn.clicked.connect(self.accept)
        lay.addWidget(add_btn)

        self._items_data: dict = {}
        self._load(db_type)

    def _load(self, db_type: str):
        conn   = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if db_type == "Material":
            cursor.execute(
                "SELECT item_code, item_name, unit, rate FROM materials "
                "ORDER BY item_name"
            )
        else:
            cursor.execute(
                "SELECT labor_code, task_name, unit, rate FROM labor "
                "ORDER BY task_name"
            )
        for row in cursor.fetchall():
            display = f"{row[1]}  ({row[2]})  —  Rs.{row[3]:.2f}"
            self._items_data[display] = {
                "code": row[0], "name": row[1],
                "unit": row[2], "rate": row[3],
                "type": db_type,
            }
            self._list.addItem(display)
        conn.close()

    def _filter(self, text: str):
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None:
                continue
            item.setHidden(text not in item.text().lower())

    def get_selected(self):
        sel = self._list.currentItem()
        return self._items_data.get(sel.text()) if sel else None


# ─────────────────────────────────────────────────────────────────────────────
#  SettingsDialog
# ─────────────────────────────────────────────────────────────────────────────

