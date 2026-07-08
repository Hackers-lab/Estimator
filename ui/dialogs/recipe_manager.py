"""
ui/dialogs/recipe_manager.py
============================
Premium editor for structural MS Iron Recipe Templates.
Allows users to edit the standard factory recipes and create custom profiles.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QWidget,
    QLabel, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QMessageBox, QDoubleSpinBox, QSpinBox,
    QHeaderView, QFrame, QSplitter
)
from PyQt6.QtCore import Qt

import os
import json
from app_config import get_data_path
from core import db_gateway as _dbg

# Dynamic loading of default/factory recipe keys from recipes.json
def _get_factory_recipe_keys() -> set[str]:
    try:
        path = get_data_path("recipes.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.keys())
    except Exception as e:
        print(f"[RecipeManager] Error loading factory recipes from file: {e}")
    # Fallback to standard built-in keys if file not found or corrupted
    return {
        "DP_IRON", "TP_IRON", "4P_IRON", "DTR_IRON",
        "POLE_LT_IRON", "POLE_LT_TOP_ADAPTOR", "POLE_HT_IRON",
        "POLE_LT_EXT", "POLE_HT_EXT", "CG_BRACKET",
        "LT_ACSR_BRACKET", "AB_CABLE_CLAMP", "HT_JUNCTION"
    }

_FACTORY_RECIPE_KEYS = _get_factory_recipe_keys()

class RecipeManagerDialog(QDialog):
    """
    Premium PyQt6 dialog to manage and edit Iron Recipes and Section Profiles. [ignoring loop detection]
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iron Recipes & Steel Profiles Manager")
        self.resize(850, 520)
        self.setMinimumSize(800, 450)

        # Load dynamic sections and recipes from DB
        self.sections_dict = _dbg.get_sections()
        self.recipes_list = _dbg.get_recipes()
        self.current_recipe = None

        self._init_ui()
        self._load_recipes_into_list()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Header Info Banner
        header = QLabel(
            "<b>Iron Recipe Templates Manager</b><br>"
            "Customize the structural steel sections, lengths, and quantities "
            "for DP, TP, 4-Pole, and DTR structures. Values are computed dynamically by the Rule Engine."
        )
        header.setStyleSheet(
            "QLabel {"
            "  background: #f7fbff;"
            "  border: 1px solid #d7e8f6;"
            "  border-radius: 6px;"
            "  padding: 10px;"
            "  color: #2b3d4f;"
            "}"
        )
        main_layout.addWidget(header)

        # Splitter for left list and right editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1)

        # Left panel: Recipe List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        left_layout.addWidget(QLabel("<b>Templates List</b>"))
        self.recipe_list_widget = QListWidget()
        self.recipe_list_widget.currentRowChanged.connect(self._on_recipe_selected)
        left_layout.addWidget(self.recipe_list_widget, 1)

        # Add/Delete Recipe buttons
        left_btn_layout = QHBoxLayout()
        self.btn_new_recipe = QPushButton("➕  New Recipe")
        self.btn_new_recipe.clicked.connect(self._create_new_recipe)
        self.btn_new_recipe.setStyleSheet("padding: 5px;")
        
        self.btn_delete_recipe = QPushButton("🗑️  Delete")
        self.btn_delete_recipe.clicked.connect(self._delete_selected_recipe)
        self.btn_delete_recipe.setStyleSheet("padding: 5px;")
        
        left_btn_layout.addWidget(self.btn_new_recipe)
        left_btn_layout.addWidget(self.btn_delete_recipe)
        left_layout.addLayout(left_btn_layout)

        splitter.addWidget(left_widget)

        # Right panel: Detailed Editor
        self.right_widget = QFrame()
        self.right_widget.setFrameShape(QFrame.Shape.StyledPanel)
        self.right_widget.setStyleSheet(
            "QFrame { background: #ffffff; border-radius: 6px; border: 1px solid #e0e0e0; }"
            "QLabel { border: none; }"
        )
        
        self.right_layout = QVBoxLayout(self.right_widget)
        self.right_layout.setSpacing(10)
        self.right_layout.setContentsMargins(14, 14, 14, 14)

        # Form info
        form_layout = QHBoxLayout()
        
        key_widget = QWidget()
        key_lay = QVBoxLayout(key_widget)
        key_lay.setContentsMargins(0, 0, 0, 0)
        key_lay.setSpacing(4)
        key_lay.addWidget(QLabel("<b>Recipe ID (Unique Key):</b>"))
        self.recipe_key_input = QLineEdit()
        key_lay.addWidget(self.recipe_key_input)
        form_layout.addWidget(key_widget, 1)

        name_widget = QWidget()
        name_lay = QVBoxLayout(name_widget)
        name_lay.setContentsMargins(0, 0, 0, 0)
        name_lay.setSpacing(4)
        name_lay.addWidget(QLabel("<b>Display Name:</b>"))
        self.recipe_name_input = QLineEdit()
        name_lay.addWidget(self.recipe_name_input)
        form_layout.addWidget(name_widget, 2)

        type_widget = QWidget()
        type_lay = QVBoxLayout(type_widget)
        type_lay.setContentsMargins(0, 0, 0, 0)
        type_lay.setSpacing(4)
        type_lay.addWidget(QLabel("<b>Object Type:</b>"))
        self.recipe_type_cb = QComboBox()
        self.recipe_type_cb.addItems(["SmartStructure", "SmartPole"])
        type_lay.addWidget(self.recipe_type_cb)
        form_layout.addWidget(type_widget, 1)

        self.right_layout.addLayout(form_layout)

        # Sections Table Widget
        self.right_layout.addWidget(QLabel("<b>Steel Sections & Profiles Breakup:</b>"))
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(4)
        self.table_widget.setHorizontalHeaderLabels([
            "Section Profile / Code", "Description Label", "Length (metres)", "Quantity (Nos)"
        ])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_widget.setStyleSheet(
            "QTableWidget { border: 1px solid #e0e0e0; background: white; }"
            "QHeaderView::section { background: #f5f5f5; font-weight: bold; border: 1px solid #e0e0e0; padding: 4px; }"
        )
        self.right_layout.addWidget(self.table_widget, 1)

        # Row controls
        row_btn_layout = QHBoxLayout()
        self.btn_add_row = QPushButton("➕  Add Profile Row")
        self.btn_add_row.clicked.connect(self._add_table_row)
        self.btn_add_row.setStyleSheet("padding: 4px;")
        
        self.btn_remove_row = QPushButton("❌  Remove Selected")
        self.btn_remove_row.clicked.connect(self._remove_table_row)
        self.btn_remove_row.setStyleSheet("padding: 4px;")
        
        row_btn_layout.addWidget(self.btn_add_row)
        row_btn_layout.addWidget(self.btn_remove_row)
        row_btn_layout.addStretch()
        self.right_layout.addLayout(row_btn_layout)

        splitter.addWidget(self.right_widget)
        splitter.setSizes([200, 600])

        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        self.btn_save = QPushButton("💾  Save Changes")
        self.btn_save.clicked.connect(self._save_and_close)
        self.btn_save.setStyleSheet("padding: 8px 16px; font-weight: bold; background: #27ae60; color: white;")
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setStyleSheet("padding: 8px 16px;")
        
        bottom_layout.addWidget(self.btn_save)
        bottom_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(bottom_layout)

    def _load_recipes_into_list(self):
        self.recipe_list_widget.clear()
        for r in self.recipes_list:
            display_name = f"🔧 {r['name']} ({r['recipe_key']})"
            self.recipe_list_widget.addItem(display_name)
        
        if self.recipes_list:
            self.recipe_list_widget.setCurrentRow(0)

    def _on_recipe_selected(self, index):
        if index < 0 or index >= len(self.recipes_list):
            self.current_recipe = None
            self.right_widget.setEnabled(False)
            return

        self.right_widget.setEnabled(True)
        self.current_recipe = self.recipes_list[index]

        # Populate fields
        self.recipe_key_input.setText(self.current_recipe["recipe_key"])
        self.recipe_name_input.setText(self.current_recipe["name"])
        self.recipe_type_cb.setCurrentText(self.current_recipe.get("object_type", "SmartStructure"))

        # Disable recipe_key editing for built-in factory templates, but allow deletion
        is_factory = self.current_recipe["recipe_key"] in _FACTORY_RECIPE_KEYS
        self.recipe_key_input.setEnabled(not is_factory)
        self.btn_delete_recipe.setEnabled(True)

        # Populate Table
        self._populate_table(self.current_recipe.get("items", []))

    def _populate_table(self, items):
        self.table_widget.setRowCount(0)
        for item in items:
            self._add_table_row_data(item)

    def _add_table_row_data(self, item_data=None):
        row = self.table_widget.rowCount()
        self.table_widget.insertRow(row)

        # Col 0: Steel Section Selector
        section_cb = QComboBox()
        for code, data in self.sections_dict.items():
            section_cb.addItem(f"{code} ({data['kg_per_metre']} kg/m)", code)
            
        initial_section = item_data.get("section", "CH_75X40") if item_data else "CH_75X40"
        idx = section_cb.findData(initial_section)
        if idx >= 0:
            section_cb.setCurrentIndex(idx)
        self.table_widget.setCellWidget(row, 0, section_cb)

        # Col 1: Description (Label)
        desc = item_data.get("description", "") if item_data else ""
        desc_item = QTableWidgetItem(desc)
        self.table_widget.setItem(row, 1, desc_item)

        # Automatically fill description on section change
        def _on_section_selected(index, r=row, cb=section_cb):
            code = cb.currentData()
            label = self.sections_dict.get(code, {}).get("label", code)
            item = self.table_widget.item(r, 1)
            if item:
                item.setText(label)
            else:
                self.table_widget.setItem(r, 1, QTableWidgetItem(label))

        section_cb.currentIndexChanged.connect(_on_section_selected)
        if not desc:
            _on_section_selected(section_cb.currentIndex())

        # Col 2: Length (DoubleSpinBox) — reads length_per_piece (falls back to legacy "length")
        len_box = QDoubleSpinBox()
        len_box.setRange(0.01, 100.0)
        len_box.setSingleStep(0.1)
        len_box.setDecimals(3)
        lpp = item_data.get("length_per_piece", item_data.get("length", 1.0)) if item_data else 1.0
        len_box.setValue(float(lpp))
        self.table_widget.setCellWidget(row, 2, len_box)

        # Col 3: Qty (SpinBox) — reads qty_per_object (falls back to legacy "qty")
        qty_box = QSpinBox()
        qty_box.setRange(1, 1000)
        qpo = item_data.get("qty_per_object", item_data.get("qty", 1)) if item_data else 1
        qty_box.setValue(int(qpo))
        self.table_widget.setCellWidget(row, 3, qty_box)

    def _add_table_row(self):
        self._add_table_row_data()

    def _remove_table_row(self):
        row = self.table_widget.currentRow()
        if row >= 0:
            self.table_widget.removeRow(row)

    def _create_new_recipe(self):
        # Generate generic new key
        new_idx = 1
        new_key = f"CUSTOM_RECIPE_{new_idx}"
        while any(r["recipe_key"] == new_key for r in self.recipes_list):
            new_idx += 1
            new_key = f"CUSTOM_RECIPE_{new_idx}"

        new_recipe = {
            "recipe_key": new_key,
            "name": f"New Custom Recipe {new_idx}",
            "object_type": "SmartStructure",
            "items": []
        }
        self.recipes_list.append(new_recipe)
        self._load_recipes_into_list()
        
        # Select the newly created recipe
        for idx in range(self.recipe_list_widget.count()):
            if new_key in self.recipe_list_widget.item(idx).text():
                self.recipe_list_widget.setCurrentRow(idx)
                break

    def _delete_selected_recipe(self):
        row = self.recipe_list_widget.currentRow()
        if row < 0 or row >= len(self.recipes_list):
            return

        recipe = self.recipes_list[row]
        
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete the recipe '{recipe['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # If it's a factory recipe, record it as deleted in user settings
            if recipe["recipe_key"] in _FACTORY_RECIPE_KEYS:
                try:
                    deleted_json = _dbg.get_setting("deleted_factory_recipes", "[]")
                    deleted_list = json.loads(deleted_json)
                except Exception:
                    deleted_list = []
                if recipe["recipe_key"] not in deleted_list:
                    deleted_list.append(recipe["recipe_key"])
                    _dbg.save_setting("deleted_factory_recipes", json.dumps(deleted_list))

            # Delete from DB immediately
            _dbg.delete_recipe(recipe["recipe_key"])
            self.recipes_list.pop(row)
            self._load_recipes_into_list()

    def _save_and_close(self):
        # 1. First, save the currently selected recipe details from inputs
        if self.current_recipe:
            key = self.recipe_key_input.text().strip()
            name = self.recipe_name_input.text().strip()
            obj_type = self.recipe_type_cb.currentText()

            if not key or not name:
                QMessageBox.warning(self, "Invalid Inputs", "Recipe Key and Display Name cannot be blank.")
                return

            self.current_recipe["recipe_key"] = key
            self.current_recipe["name"] = name
            self.current_recipe["object_type"] = obj_type

            # Parse Table Items
            items = []
            for row in range(self.table_widget.rowCount()):
                cb = self.table_widget.cellWidget(row, 0)
                desc_item = self.table_widget.item(row, 1)
                len_box = self.table_widget.cellWidget(row, 2)
                qty_box = self.table_widget.cellWidget(row, 3)

                if cb and len_box and qty_box:
                    lpp = len_box.value()
                    qpo = qty_box.value()
                    lf = f"={qpo}*{lpp}" if qpo > 1 else str(lpp)
                    items.append({
                        "section": cb.currentData(),
                        "description": desc_item.text() if desc_item else cb.currentText(),
                        "length_per_piece": lpp,
                        "qty_per_object": qpo,
                        "length_formula": lf,
                    })
            self.current_recipe["items"] = items

        # 2. Write all recipes back to SQLite database using gateway save_recipe()
        try:
            for r in self.recipes_list:
                _dbg.save_recipe(r)
            QMessageBox.information(self, "Success", "All recipes saved successfully to database!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Failed to save recipes to database: {e}")
