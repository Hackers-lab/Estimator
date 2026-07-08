"""
ui/dialogs/project_manager.py
==============================
Premium dialog to manage projects (list, open, rename, delete, duplicate, compare side-by-side).
"""

import os
import json
import shutil
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMessageBox, QInputDialog, QHeaderView,
    QAbstractItemView, QLineEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from core import db_gateway as _dbg

class ProjectCompareDialog(QDialog):
    """
    Dialog to show a detailed side-by-side comparison of two projects.
    """
    
    def __init__(self, proj1: dict, proj2: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Comparison")
        self.resize(600, 480)
        self.setModal(True)
        
        self.proj1 = proj1
        self.proj2 = proj2
        self._init_ui()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        header = QLabel("<b>Side-by-Side Comparison</b>")
        header.setStyleSheet("font-size: 14px; color: #1a365d;")
        layout.addWidget(header)
        
        table = QTableWidget()
        table.setColumnCount(3)
        table.setRowCount(11)
        table.setHorizontalHeaderLabels(["Metric", self.proj1["name"], self.proj2["name"]])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setStyleSheet(
            "QTableWidget { border: 1px solid #e0e0e0; background: white; }"
            "QHeaderView::section { background: #f5f5f5; font-weight: bold; border: 1px solid #e0e0e0; padding: 4px; }"
        )
        
        # Load JSON file data for counts
        data1 = self._load_json(self.proj1["path"])
        data2 = self._load_json(self.proj2["path"])
        
        metrics = [
            ("Project Name", self.proj1["name"], self.proj2["name"]),
            ("Project Type", self.proj1["type"], self.proj2["type"]),
            ("Estimated Cost", f"Rs. {self.proj1['cost']:,.2f}", f"Rs. {self.proj2['cost']:,.2f}"),
            ("GPS Coordinates", f"{self.proj1['lat']}, {self.proj1['long']}", f"{self.proj2['lat']}, {self.proj2['long']}"),
            ("Last Modified", self.proj1["updated_at"], self.proj2["updated_at"]),
            ("JSON Path", self.proj1["path"], self.proj2["path"]),
            ("Total Nodes/Poles", str(self._count_nodes(data1)), str(self._count_nodes(data2))),
            ("Total Spans", str(self._count_spans(data1)), str(self._count_spans(data2))),
            ("Total Consumers", str(self._count_consumers(data1)), str(self._count_consumers(data2))),
            ("Uses Readymade Steel", "Yes" if self._uses_uh(data1) else "No", "Yes" if self._uses_uh(data2) else "No"),
            ("File Size", self._file_size(self.proj1["path"]), self._file_size(self.proj2["path"])),
        ]
        
        for r, (metric, val1, val2) in enumerate(metrics):
            table.setItem(r, 0, QTableWidgetItem(metric))
            table.setItem(r, 1, QTableWidgetItem(val1))
            table.setItem(r, 2, QTableWidgetItem(val2))
            
            # Make the metric name bold
            table.item(r, 0).setFont(QFont("Arial", 9, QFont.Weight.Bold))
            
            # Highlight cost difference
            if metric == "Estimated Cost":
                table.item(r, 1).setFont(QFont("Arial", 9, QFont.Weight.Bold))
                table.item(r, 2).setFont(QFont("Arial", 9, QFont.Weight.Bold))
                if self.proj1["cost"] < self.proj2["cost"]:
                    table.item(r, 1).setBackground(QColor("#d4edda"))
                    table.item(r, 2).setBackground(QColor("#f8d7da"))
                elif self.proj1["cost"] > self.proj2["cost"]:
                    table.item(r, 1).setBackground(QColor("#f8d7da"))
                    table.item(r, 2).setBackground(QColor("#d4edda"))
                    
        layout.addWidget(table)
        
        # Close Button
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_close.setStyleSheet("padding: 6px 20px;")
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)
        
    def _load_json(self, path) -> dict:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
        
    def _count_nodes(self, data) -> int:
        return len(data.get("nodes", []))
        
    def _count_spans(self, data) -> int:
        return len(data.get("spans", []))
        
    def _count_consumers(self, data) -> int:
        return sum(1 for n in data.get("nodes", []) if n.get("type") == "consumer")
        
    def _uses_uh(self, data) -> bool:
        return bool(data.get("project_meta", {}).get("use_uh", False))
        
    def _file_size(self, path) -> str:
        if path and os.path.exists(path):
            size = os.path.getsize(path)
            return f"{size / 1024:.1f} KB"
        return "N/A"


class ProjectManagerDialog(QDialog):
    """
    Premium Dialog to list, open, rename, delete, duplicate, and compare projects.
    """
    
    def __init__(self, main_app, parent=None):
        super().__init__(parent or main_app)
        self.setWindowTitle("My Projects Explorer")
        self.resize(900, 480)
        self.setMinimumSize(850, 400)
        self.setModal(True)
        
        self.main_app = main_app
        self.projects = []
        self._init_ui()
        self._reload_projects()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Header banner
        header = QLabel(
            "<b>Projects Manager</b><br>"
            "Manage your saved estimates database. Open, rename, duplicate, compare, or clean up projects."
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
        layout.addWidget(header)
        
        # Table of projects
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Project Subject / Name", "Estimated Cost", "Type", "Lat / Long", "Last Modified", "JSON File Path"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget { border: 1px solid #e0e0e0; background: white; }"
            "QHeaderView::section { background: #f5f5f5; font-weight: bold; border: 1px solid #e0e0e0; padding: 4px; }"
        )
        # Resize column dimensions nicely
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 140)
        self.table.setColumnWidth(5, 200)
        
        layout.addWidget(self.table, 1)
        
        # Button bar
        btn_layout = QHBoxLayout()
        
        self.btn_open = QPushButton("📂  Open Project")
        self.btn_open.clicked.connect(self._open_project)
        self.btn_open.setStyleSheet("padding: 7px 14px; font-weight: bold; background: #27ae60; color: white;")
        btn_layout.addWidget(self.btn_open)
        
        self.btn_rename = QPushButton("✏️  Rename")
        self.btn_rename.clicked.connect(self._rename_project)
        self.btn_rename.setStyleSheet("padding: 7px 12px;")
        btn_layout.addWidget(self.btn_rename)
        
        self.btn_duplicate = QPushButton("👯  Duplicate")
        self.btn_duplicate.clicked.connect(self._duplicate_project)
        self.btn_duplicate.setStyleSheet("padding: 7px 12px;")
        btn_layout.addWidget(self.btn_duplicate)
        
        self.btn_compare = QPushButton("📊  Compare Two")
        self.btn_compare.clicked.connect(self._compare_projects)
        self.btn_compare.setStyleSheet("padding: 7px 12px;")
        btn_layout.addWidget(self.btn_compare)
        
        self.btn_delete = QPushButton("🗑️  Delete")
        self.btn_delete.clicked.connect(self._delete_project)
        self.btn_delete.setStyleSheet("padding: 7px 12px;")
        btn_layout.addWidget(self.btn_delete)
        
        btn_layout.addStretch()
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        self.btn_close.setStyleSheet("padding: 7px 16px;")
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)
        
    def _reload_projects(self):
        self.projects = _dbg.get_projects()
        self.table.setRowCount(0)
        
        for r, p in enumerate(self.projects):
            self.table.insertRow(r)
            
            # Col 0: Name
            self.table.setItem(r, 0, QTableWidgetItem(p["name"]))
            
            # Col 1: Cost
            cost_item = QTableWidgetItem(f"Rs. {p['cost']:,.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 1, cost_item)
            
            # Col 2: Type
            self.table.setItem(r, 2, QTableWidgetItem(p["type"]))
            
            # Col 3: Coordinates
            coord_str = f"{p['lat']}, {p['long']}" if p["lat"] else ""
            self.table.setItem(r, 3, QTableWidgetItem(coord_str))
            
            # Col 4: Last Modified
            self.table.setItem(r, 4, QTableWidgetItem(p["updated_at"]))
            
            # Col 5: Path
            self.table.setItem(r, 5, QTableWidgetItem(p["path"]))
            
        # Select first row by default
        if self.projects:
            self.table.selectRow(0)
            
    def _get_selected_project(self) -> dict | None:
        row = self.table.currentRow()
        if row >= 0 and row < len(self.projects):
            return self.projects[row]
        return None
        
    def _open_project(self):
        p = self._get_selected_project()
        if not p:
            return
            
        if not os.path.exists(p["path"]):
            QMessageBox.critical(self, "File Not Found", f"Project file not found on disk at:\n{p['path']}")
            return
            
        # Ask to save current if dirty
        self.main_app._save_unsaved_drawing()
        
        try:
            with open(p["path"], "r", encoding="utf-8") as f:
                data = json.load(f)
            self.main_app.parse_load_data(data)
            self.main_app.current_project_path = p["path"]
            self.main_app._drawing_dirty = False
            self.main_app._refresh_proj_label()
            self.main_app.refresh_live_estimate()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load project: {e}")
            
    def _rename_project(self):
        p = self._get_selected_project()
        if not p:
            return
            
        new_name, ok = QInputDialog.getText(
            self, "Rename Project", "Enter new project name:", QLineEdit.EchoMode.Normal, p["name"]
        )
        if ok and new_name.strip():
            new_name = new_name.strip()
            # Calculate new file path in same directory
            dir_name = os.path.dirname(p["path"])
            safe_stem = "".join(c for c in new_name if c not in r'\/*?:"<>|').strip()
            new_path = os.path.join(dir_name, f"{safe_stem}.json")
            
            if os.path.exists(new_path) and new_path != p["path"]:
                QMessageBox.warning(self, "File Collision", "A file with that name already exists in the same folder.")
                return
                
            # Rename file on disk if exists
            if os.path.exists(p["path"]):
                try:
                    os.rename(p["path"], new_path)
                    
                    # Update file contents with new name inside the JSON metadata as well!
                    try:
                        with open(new_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if "project_meta" in data:
                            data["project_meta"]["subject"] = new_name
                        with open(new_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2)
                    except Exception:
                        pass
                except Exception as e:
                    QMessageBox.critical(self, "File Rename Failed", f"Could not rename file on disk: {e}")
                    return
            
            # Update DB metadata
            _dbg.rename_project_metadata(p["path"], new_path, new_name)
            
            # If the renamed project is currently open in the app, update its active path
            if getattr(self.main_app, "current_project_path", None) == p["path"]:
                self.main_app.current_project_path = new_path
                self.main_app.project_meta["subject"] = new_name
                self.main_app._refresh_proj_label()
                
            self._reload_projects()
            
    def _duplicate_project(self):
        p = self._get_selected_project()
        if not p:
            return
            
        if not os.path.exists(p["path"]):
            QMessageBox.critical(self, "File Not Found", "Original JSON file does not exist on disk.")
            return
            
        dir_name = os.path.dirname(p["path"])
        file_name = os.path.basename(p["path"])
        stem, ext = os.path.splitext(file_name)
        
        # Determine unique copy path
        copy_idx = 1
        copy_path = os.path.join(dir_name, f"{stem}_copy{copy_idx}{ext}")
        while os.path.exists(copy_path):
            copy_idx += 1
            copy_path = os.path.join(dir_name, f"{stem}_copy{copy_idx}{ext}")
            
        new_name = f"{p['name']} (Copy {copy_idx})"
        
        try:
            shutil.copy2(p["path"], copy_path)
            
            # Update internal JSON metadata subject
            with open(copy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "project_meta" in data:
                data["project_meta"]["subject"] = new_name
            with open(copy_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                
            # Insert into DB
            _dbg.save_project_metadata(
                new_name, copy_path, p["type"], p["lat"], p["long"], p["cost"]
            )
            self._reload_projects()
        except Exception as e:
            QMessageBox.critical(self, "Duplication Failed", f"Failed to duplicate: {e}")
            
    def _delete_project(self):
        p = self._get_selected_project()
        if not p:
            return
            
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Delete Project")
        msg.setText(f"Are you sure you want to delete the project:\n'{p['name']}' from the database?")
        msg.setInformativeText("This will remove it from 'My Projects' list.")
        
        btn_only_db = msg.addButton("Remove from List Only", QMessageBox.ButtonRole.DestructiveRole)
        btn_with_file = msg.addButton("Delete JSON File Too", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()
        
        selected_btn = msg.clickedButton()
        if selected_btn == btn_only_db or selected_btn == btn_with_file:
            # Delete from DB
            _dbg.delete_project_metadata(p["path"])
            
            # Delete file on disk if requested
            if selected_btn == btn_with_file and os.path.exists(p["path"]):
                try:
                    os.remove(p["path"])
                except Exception as e:
                    QMessageBox.warning(self, "Delete Failed", f"Could not delete the file on disk:\n{e}")
            
            # Reset active project path in main app if it was open
            if getattr(self.main_app, "current_project_path", None) == p["path"]:
                self.main_app.current_project_path = None
                
            self._reload_projects()
            
    def _compare_projects(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            QMessageBox.warning(self, "Select Projects", "Please select two projects in the list first.")
            return
            
        # Get selected rows
        rows = set()
        for r in selected_ranges:
            for row in range(r.topRow(), r.bottomRow() + 1):
                rows.add(row)
                
        if len(rows) != 2:
            QMessageBox.warning(
                self, "Select Exactly Two",
                f"You have selected {len(rows)} projects. Please hold Ctrl and select EXACTLY 2 rows to compare."
            )
            return
            
        rows_list = sorted(list(rows))
        p1 = self.projects[rows_list[0]]
        p2 = self.projects[rows_list[1]]
        
        dlg = ProjectCompareDialog(p1, p2, parent=self)
        dlg.exec()
