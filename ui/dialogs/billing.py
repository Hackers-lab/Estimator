"""
ui/dialogs/billing.py
=====================
Billing Module - select single or multiple projects, fill client/PO details,
adjust actual material consumption, and generate a consolidated Labor-only
Tax Invoice & Billing Packet PDF. Logs invoice records to local database.
"""

import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMessageBox, QLineEdit, QFormLayout, QCheckBox,
    QFileDialog, QHeaderView, QAbstractItemView, QWidget, QComboBox,
    QTextEdit, QScrollArea, QFrame, QTabWidget
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QImage
from PyQt6.QtPrintSupport import QPrinter

from core import db_gateway as _dbg

def amount_to_words(num):
    # Converts a number into Indian Rupees words
    # e.g., 12345.50 -> "Rupees Twelve Thousand Three Hundred Forty Five and Fifty Paise Only"
    if num is None:
        return ""
    
    import math
    num = round(num, 2)
    int_part = int(math.floor(num))
    frac_part = int(round((num - int_part) * 100))
    
    def num_to_words_int(n):
        units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                 "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        
        if n == 0:
            return "Zero"
            
        def convert_chunk(val):
            res = []
            if val >= 100:
                res.append(units[val // 100] + " Hundred")
                val %= 100
            if val >= 20:
                res.append(tens[val // 10])
                val %= 10
            if val > 0:
                res.append(units[val])
            return " ".join(res)
            
        words = []
        
        # Crores (1,00,00,000)
        if n >= 10000000:
            words.append(num_to_words_int(n // 10000000) + " Crore")
            n %= 10000000
            
        # Lakhs (1,00,000)
        if n >= 100000:
            words.append(convert_chunk(n // 100000) + " Lakh")
            n %= 100000
            
        # Thousands (1,000)
        if n >= 1000:
            words.append(convert_chunk(n // 1000) + " Thousand")
            n %= 1000
            
        # Hundreds and tens
        if n > 0:
            words.append(convert_chunk(n))
            
        return " ".join(words)
        
    int_words = num_to_words_int(int_part)
    words_str = f"Rupees {int_words}" if int_part > 0 else "Rupees Zero"
    
    if frac_part > 0:
        frac_words = num_to_words_int(frac_part)
        words_str += f" and {frac_words} Paise"
        
    words_str += " Only"
    return words_str

class BillingDialog(QDialog):
    """
    Billing & Invoice Generation Dialog.
    Presents a 3-column workspace to consolidate drawings and customize billing.
    """
    
    def __init__(self, main_app, parent=None):
        super().__init__(parent or main_app)
        self.setWindowTitle("Billing Packet & Invoice Generator")
        self.resize(1150, 620)
        self.setMinimumSize(1000, 500)
        self.setModal(True)
        
        self.main_app = main_app
        self.projects = []
        self.bom_items = []
        self.is_edit_mode = False
        self._init_ui()
        self._initialize_invoice_number()
        self._reload_projects()
        
        if self.client_destinations:
            self.client_dest_combo.setCurrentIndex(1)
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Check active profile
        self.profile = _dbg.get_active_profile()
        if not self.profile:
            banner_text = (
                "<b>Warning: No Active User Profile</b><br>"
                "Please configure a User Profile under Settings first to personalise invoice headers."
            )
            color = "#8a6d3b"
            bg = "#fcf8e3"
            border = "#faebcc"
        else:
            banner_text = (
                f"<b>Billing & Invoice Generator</b> (Active Profile: <b>{self.profile['firm_name']}</b>)<br>"
                "Consolidate project drawings, adjust material consumption, and generate a certified labor billing packet."
            )
            color = "#3c763d"
            bg = "#dff0d8"
            border = "#d6e9c6"
            
        banner = QLabel(banner_text)
        banner.setStyleSheet(
            f"background: {bg}; border: 1px solid {border}; border-radius: 6px; padding: 10px; color: {color};"
        )
        layout.addWidget(banner)
        
        # 3-Column workspace
        main_hbox = QHBoxLayout()
        layout.addLayout(main_hbox, 1)
        
        # Column 1: Project Selection
        col1_w = QWidget()
        col1_lay = QVBoxLayout(col1_w)
        col1_lay.setContentsMargins(0, 0, 0, 0)
        col1_lay.setSpacing(6)
        
        self.project_tabs = QTabWidget()
        self.project_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #e0e0e0; background: white; }"
            "QTabBar::tab { padding: 8px 12px; font-weight: bold; }"
        )
        
        # Tab 1: Active Projects
        self.tab_active = QWidget()
        tab_active_lay = QVBoxLayout(self.tab_active)
        tab_active_lay.setContentsMargins(4, 4, 4, 4)
        
        self.active_table = QTableWidget()
        self.active_table.setColumnCount(4)
        self.active_table.setHorizontalHeaderLabels(["", "Project Name", "Estimated Cost", "Last Modified"])
        self.active_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.active_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.active_table.setStyleSheet(
            "QTableWidget { border: none; background: white; }"
            "QHeaderView::section { background: #f5f5f5; font-weight: bold; border: 1px solid #e0e0e0; padding: 4px; }"
        )
        self.active_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.active_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.active_table.setColumnWidth(0, 30)
        self.active_table.setColumnWidth(2, 90)
        self.active_table.setColumnWidth(3, 100)
        self.active_table.cellClicked.connect(self._on_active_cell_clicked)
        tab_active_lay.addWidget(self.active_table)
        
        self.project_tabs.addTab(self.tab_active, "Active Projects")
        
        # Tab 2: Invoiced Projects
        self.tab_invoiced = QWidget()
        tab_invoiced_lay = QVBoxLayout(self.tab_invoiced)
        tab_invoiced_lay.setContentsMargins(4, 4, 4, 4)
        
        self.invoiced_table = QTableWidget()
        self.invoiced_table.setColumnCount(4)
        self.invoiced_table.setHorizontalHeaderLabels(["Project Name", "Invoice No", "Estimated Cost", "Last Modified"])
        self.invoiced_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.invoiced_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.invoiced_table.setStyleSheet(
            "QTableWidget { border: none; background: white; }"
            "QHeaderView::section { background: #f5f5f5; font-weight: bold; border: 1px solid #e0e0e0; padding: 4px; }"
        )
        self.invoiced_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.invoiced_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.invoiced_table.setColumnWidth(1, 100)
        self.invoiced_table.setColumnWidth(2, 90)
        self.invoiced_table.setColumnWidth(3, 100)
        self.invoiced_table.itemSelectionChanged.connect(self._on_invoiced_selection_changed)
        tab_invoiced_lay.addWidget(self.invoiced_table)
        
        self.project_tabs.addTab(self.tab_invoiced, "Invoiced Projects (Edit)")
        
        col1_lay.addWidget(self.project_tabs)
        main_hbox.addWidget(col1_w, 3)
        
        # Column 2: Material Consumption Adjustment
        col2_w = QWidget()
        col2_lay = QVBoxLayout(col2_w)
        col2_lay.setContentsMargins(0, 0, 0, 0)
        col2_lay.setSpacing(6)
        
        col2_lay.addWidget(QLabel("<b>2. Material Consumption (Edit Actuals):</b>"))
        self.consumption_table = QTableWidget()
        self.consumption_table.setColumnCount(4)
        self.consumption_table.setHorizontalHeaderLabels(["Material Name", "Unit", "Est. Qty", "Act. Consumed"])
        self.consumption_table.setStyleSheet(
            "QTableWidget { border: 1px solid #e0e0e0; background: white; }"
            "QHeaderView::section { background: #f5f5f5; font-weight: bold; border: 1px solid #e0e0e0; padding: 4px; }"
        )
        self.consumption_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.consumption_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.consumption_table.setColumnWidth(1, 45)
        self.consumption_table.setColumnWidth(2, 65)
        self.consumption_table.setColumnWidth(3, 85)
        
        col2_lay.addWidget(self.consumption_table)
        main_hbox.addWidget(col2_w, 4)
        
        # Column 3: Invoice & PO Details
        col3_w = QWidget()
        col3_lay = QVBoxLayout(col3_w)
        col3_lay.setContentsMargins(0, 0, 0, 0)
        col3_lay.setSpacing(6)
        
        col3_lay.addWidget(QLabel("<b>3. Invoice & PO Settings:</b>"))
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_content_layout = QVBoxLayout(scroll_content)
        scroll_content_layout.setContentsMargins(0, 0, 0, 0)
        
        form = QFormLayout()
        form.setSpacing(6)
        
        self.project_id_input = QLineEdit()
        self.project_id_input.setPlaceholderText("e.g. WBSEDCL/RURAL-42")
        form.addRow("Project ID:", self.project_id_input)
        
        self.po_no_input = QLineEdit()
        self.po_no_input.setPlaceholderText("e.g. PO/ENG/2026/89")
        form.addRow("PO Number:", self.po_no_input)
        
        self.po_date_input = QLineEdit(datetime.now().strftime("%d-%m-%Y"))
        form.addRow("PO Date:", self.po_date_input)
        
        self.vendor_id_input = QLineEdit()
        self.vendor_id_input.setPlaceholderText("e.g. 700099")
        form.addRow("Vendor ID:", self.vendor_id_input)

        self.comm_date_input = QLineEdit(datetime.now().strftime("%d-%m-%Y"))
        form.addRow("Commencement Date:", self.comm_date_input)

        self.comp_date_input = QLineEdit(datetime.now().strftime("%d-%m-%Y"))
        form.addRow("Completion Date:", self.comp_date_input)

        self.meas_date_input = QLineEdit(datetime.now().strftime("%d-%m-%Y"))
        form.addRow("Measurement Date:", self.meas_date_input)
        
        self.invoice_no_input = QLineEdit(f"INV-{datetime.now().strftime('%Y%m%d')}-01")
        form.addRow("Invoice No:", self.invoice_no_input)
        
        self.invoice_date_input = QLineEdit(datetime.now().strftime("%d-%m-%Y"))
        form.addRow("Invoice Date:", self.invoice_date_input)
        
        self.copy_type_combo = QComboBox()
        combo_style = "QComboBox { background-color: white; color: black; border: 1px solid #ccc; padding: 4px; border-radius: 4px; } QComboBox QAbstractItemView { background-color: white; color: black; selection-background-color: #2b82c9; }"
        self.copy_type_combo.setStyleSheet(combo_style)
        self.copy_type_combo.addItems([
            "Original for Recipient",
            "Duplicate for Provider",
            "Triplicate for Supplier",
            "All 3 Copies (Combined Packet)"
        ])
        form.addRow("Copy Stamp:", self.copy_type_combo)
        
        self.client_dest_combo = QComboBox()
        self.client_dest_combo.setStyleSheet(combo_style)
        self._load_client_destinations()
        self.client_dest_combo.currentIndexChanged.connect(self._on_client_dest_changed)
        form.addRow("Select Client Destination:", self.client_dest_combo)
        
        self.client_name_input = QLineEdit()
        self.client_name_input.setPlaceholderText("e.g. Divisional Manager, WBSEDCL")
        form.addRow("Client Name:", self.client_name_input)
        
        self.client_address_input = QLineEdit()
        self.client_address_input.setPlaceholderText("Client Address")
        form.addRow("Address:", self.client_address_input)
        
        self.client_gstin_input = QLineEdit()
        self.client_gstin_input.setPlaceholderText("Client GSTIN (optional)")
        form.addRow("Client GSTIN:", self.client_gstin_input)
        
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Scope of work description or project notes...")
        self.description_input.setMaximumHeight(70)
        form.addRow("Description:", self.description_input)

        self.meas_taken_by_input = QLineEdit()
        self.meas_taken_by_input.setPlaceholderText("e.g. Sub-Assistant Engineer")
        form.addRow("Meas. Taken By:", self.meas_taken_by_input)

        self.certified_by_input = QLineEdit()
        self.certified_by_input.setPlaceholderText("e.g. Assistant Engineer")
        form.addRow("Certified By:", self.certified_by_input)
        
        # Checkboxes for extra options
        self.exclude_header_invoice_cb = QCheckBox("Exclude Agency Header on Invoice (for Letterhead)")
        self.include_drawing_cb = QCheckBox("Include Project Drawing in Packet")
        self.include_estimate_cb = QCheckBox("Include Project Estimate & BOQ in Packet")
        self.include_meas_material_cb = QCheckBox("Include Measurement Sheet (Material)")
        self.include_meas_labor_cb = QCheckBox("Include Measurement Sheet (Labor)")
        
        form.addRow("", self.exclude_header_invoice_cb)
        form.addRow("", self.include_drawing_cb)
        form.addRow("", self.include_estimate_cb)
        form.addRow("", self.include_meas_material_cb)
        form.addRow("", self.include_meas_labor_cb)
        
        scroll_content_layout.addLayout(form)
        scroll.setWidget(scroll_content)
        col3_lay.addWidget(scroll)
        main_hbox.addWidget(col3_w, 4)
        
        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        self.btn_generate = QPushButton("🖨️  Generate Billing Packet")
        self.btn_generate.clicked.connect(self._generate_invoice)
        self.btn_generate.setStyleSheet("padding: 8px 18px; font-weight: bold; background: #27ae60; color: white;")

        self.btn_completion_cert = QPushButton("📜  Generate Completion Cert Only")
        self.btn_completion_cert.clicked.connect(self._generate_completion_certificate_only)
        self.btn_completion_cert.setStyleSheet("padding: 8px 16px; font-weight: bold; background: #2980b9; color: white;")
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setStyleSheet("padding: 8px 16px;")
        
        self.btn_report = QPushButton("📋  All Projects Report")
        self.btn_report.clicked.connect(self._generate_billing_report)
        self.btn_report.setStyleSheet("padding: 8px 16px; font-weight: bold; background: #8e44ad; color: white;")
        
        bottom_layout.addWidget(self.btn_generate)
        bottom_layout.addWidget(self.btn_completion_cert)
        bottom_layout.addWidget(self.btn_report)
        bottom_layout.addWidget(self.btn_cancel)
        layout.addLayout(bottom_layout)
        
        # Connect tab change signal only after full UI initialization to avoid AttributeErrors
        self.project_tabs.currentChanged.connect(self._on_tab_changed)
        
    def _initialize_invoice_number(self):
        if self.profile:
            seq, fy = _dbg.get_next_invoice_seq_and_fy(self.profile)
            fmt = self.profile.get("invoice_format", "SE/{FY}/KSD/{SEQ}")
            formatted_no = _dbg.format_invoice_number(fmt, seq)
            self.invoice_no_input.setText(formatted_no)
            
    def _load_client_destinations(self):
        self.client_dest_combo.clear()
        self.client_destinations = []
        if self.profile:
            import json
            try:
                self.client_destinations = json.loads(self.profile.get("billing_to_json", "[]"))
            except Exception:
                self.client_destinations = []
        
        self.client_dest_combo.addItem("Custom / Manual Input")
        for dest in self.client_destinations:
            self.client_dest_combo.addItem(dest.get("name", ""))
            
    def _on_client_dest_changed(self, index):
        if index <= 0:
            # Custom
            return
        dest = self.client_destinations[index - 1]
        self.client_name_input.setText(dest.get("name", ""))
        self.client_address_input.setText(dest.get("address", ""))
        self.client_gstin_input.setText(dest.get("gstin", ""))
        
    def _reload_projects(self):
        self.all_projects = _dbg.get_projects()
        
        self.active_projects = [p for p in self.all_projects if p.get("status") != "Invoiced"]
        self.invoiced_projects = [p for p in self.all_projects if p.get("status") == "Invoiced"]
        
        # Populate active projects
        self.active_table.setRowCount(0)
        self.active_table.blockSignals(True)
        for r, p in enumerate(self.active_projects):
            self.active_table.insertRow(r)
            
            chk = QCheckBox()
            chk.setChecked(False)
            chk.setProperty("row_idx", r)
            chk.stateChanged.connect(self._rebuild_consolidated_data)
            
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.active_table.setCellWidget(r, 0, chk_widget)
            
            self.active_table.setItem(r, 1, QTableWidgetItem(p["name"]))
            self.active_table.setItem(r, 2, QTableWidgetItem(f"Rs. {p['cost']:,.2f}"))
            self.active_table.setItem(r, 3, QTableWidgetItem(p["updated_at"]))
        self.active_table.blockSignals(False)
        
        # Populate invoiced projects
        self.invoiced_table.setRowCount(0)
        self.invoiced_table.blockSignals(True)
        for r, p in enumerate(self.invoiced_projects):
            self.invoiced_table.insertRow(r)
            self.invoiced_table.setItem(r, 0, QTableWidgetItem(p["name"]))
            self.invoiced_table.setItem(r, 1, QTableWidgetItem(p.get("invoice_no", "")))
            self.invoiced_table.setItem(r, 2, QTableWidgetItem(f"Rs. {p['cost']:,.2f}"))
            self.invoiced_table.setItem(r, 3, QTableWidgetItem(p["updated_at"]))
        self.invoiced_table.blockSignals(False)

    def _on_active_cell_clicked(self, row, col):
        chk_widget = self.active_table.cellWidget(row, 0)
        if chk_widget:
            chk = chk_widget.findChild(QCheckBox)
            if chk:
                chk.setChecked(not chk.isChecked())
                
    def _on_tab_changed(self, index):
        if not hasattr(self, "invoiced_table") or not hasattr(self, "active_table"):
            return
        if index == 0:
            self.invoiced_table.clearSelection()
            self.is_edit_mode = False
            self.invoice_no_input.setEnabled(True)
            self._initialize_invoice_number()
            self.btn_generate.setText("🖨️  Generate Billing Packet")
            self.btn_completion_cert.setText("📜  Generate Completion Cert Only")
            self._rebuild_consolidated_data()
        else:
            self.active_table.blockSignals(True)
            for r in range(self.active_table.rowCount()):
                chk_w = self.active_table.cellWidget(r, 0)
                if chk_w:
                    c = chk_w.findChild(QCheckBox)
                    if c:
                        c.setChecked(False)
            self.active_table.blockSignals(False)
            self._on_invoiced_selection_changed()
            
    def _on_invoiced_selection_changed(self):
        if not hasattr(self, "invoiced_table") or not hasattr(self, "active_table"):
            return
        selected_paths = self._get_selected_projects_paths()
        if not selected_paths or self.project_tabs.currentIndex() != 1:
            self.consumption_table.setRowCount(0)
            self.bom_items = []
            self.is_edit_mode = False
            self.invoice_no_input.setEnabled(True)
            self._initialize_invoice_number()
            self.btn_generate.setText("🖨️  Generate Billing Packet")
            self.btn_completion_cert.setText("📜  Generate Completion Cert Only")
            return
            
        self._rebuild_consolidated_data()

    def _get_selected_projects_paths(self) -> list[str]:
        if not hasattr(self, "invoiced_table") or not hasattr(self, "active_table"):
            return []
        if self.project_tabs.currentIndex() == 0:
            paths = []
            for r in range(self.active_table.rowCount()):
                chk_widget = self.active_table.cellWidget(r, 0)
                if chk_widget:
                    chk = chk_widget.findChild(QCheckBox)
                    if chk and chk.isChecked():
                        paths.append(self.active_projects[r]["path"])
            return paths
        else:
            selected_indexes = self.invoiced_table.selectionModel().selectedRows()
            if selected_indexes:
                row = selected_indexes[0].row()
                p = self.invoiced_projects[row]
                inv_no = p.get("invoice_no", "")
                
                # Retrieve all project paths associated with this invoice from the DB
                bills = _dbg.get_bills()
                for b in bills:
                    if b["invoice_no"] == inv_no:
                        return b.get("project_paths", [p["path"]])
                return [p["path"]]
            return []
        
    def _rebuild_consolidated_data(self):
        selected_paths = self._get_selected_projects_paths()
        if not selected_paths:
            self.consumption_table.setRowCount(0)
            self.bom_items = []
            self.supervision_rate = 0.10
            
            if self.is_edit_mode:
                self.is_edit_mode = False
                self.invoice_no_input.setEnabled(True)
                self._initialize_invoice_number()
                self.btn_generate.setText("🖨️  Generate Billing Packet")
                self.btn_completion_cert.setText("📜  Generate Completion Cert Only")
            return
            
        # Determine edit mode and edit invoice number first
        is_edit = (self.project_tabs.currentIndex() == 1)
        edit_inv_no = ""
        proj_info = None
        if is_edit and len(selected_paths) == 1:
            selected_indexes = self.invoiced_table.selectionModel().selectedRows()
            if selected_indexes:
                row = selected_indexes[0].row()
                proj_info = self.invoiced_projects[row]
                edit_inv_no = proj_info.get("invoice_no", "")
                
        # Re-consolidate BOM items from selected projects or load from database
        self.bom_items = []
        loaded_from_db = False
        target_bill = None
        
        if is_edit and edit_inv_no:
            bills = _dbg.get_bills()
            for b in bills:
                if b["invoice_no"] == edit_inv_no:
                    target_bill = b
                    break
            if target_bill:
                self.bom_items = target_bill.get("items", [])
                loaded_from_db = True
                
        if not loaded_from_db:
            try:
                self.bom_items = self._consolidate_boms(selected_paths)
            except Exception:
                return
                
        # Preserve user's actual edits already made
        existing_customs = {}
        for r in range(self.consumption_table.rowCount()):
            name_item = self.consumption_table.item(r, 0)
            act_item = self.consumption_table.item(r, 3)
            if name_item and act_item:
                try:
                    existing_customs[name_item.text()] = float(act_item.text())
                except ValueError:
                    pass
                    
        if is_edit:
            if not self.is_edit_mode:
                self.is_edit_mode = True
                self.invoice_no_input.setText(edit_inv_no)
                self.invoice_no_input.setEnabled(False)
                self.btn_generate.setText("✏️  Update Billing Packet")
                self.btn_completion_cert.setText("✏️  Update Completion Cert")
                
                if target_bill:
                    self.project_id_input.setText(target_bill.get("project_id", ""))
                    self.po_no_input.setText(target_bill.get("po_no", ""))
                    self.po_date_input.setText(target_bill.get("po_date", ""))
                    self.invoice_date_input.setText(target_bill.get("invoice_date", ""))
                    self.client_name_input.setText(target_bill.get("client_name", ""))
                    self.client_address_input.setText(target_bill.get("client_address", ""))
                    self.client_gstin_input.setText(target_bill.get("client_gstin", ""))
                    self.description_input.setText(target_bill.get("description", ""))
                    self.meas_taken_by_input.setText(target_bill.get("meas_taken_by", ""))
                    self.certified_by_input.setText(target_bill.get("certified_by", ""))
                    
                    if proj_info:
                        self.vendor_id_input.setText(proj_info.get("vendor_id", "") or (self.profile.get("vendor_no", "") if self.profile else ""))
                        self.comm_date_input.setText(proj_info.get("comm_date", ""))
                        self.comp_date_input.setText(proj_info.get("comp_date", ""))
                        self.meas_date_input.setText(proj_info.get("meas_date", ""))
            
            # Override/populate existing_customs with quantities from the saved bill
            if target_bill:
                for item in target_bill.get("items", []):
                    if "name" in item:
                        existing_customs[item["name"]] = item.get("act_qty", item.get("qty", 0.0))
        else:
            if self.is_edit_mode:
                self.is_edit_mode = False
                self.invoice_no_input.setEnabled(True)
                self._initialize_invoice_number()
                self.btn_generate.setText("🖨️  Generate Billing Packet")
                self.btn_completion_cert.setText("📜  Generate Completion Cert Only")
                
        # Update consumption table
        self.consumption_table.setRowCount(0)
        materials = [x for x in self.bom_items if x["type"] == "Material"]
        
        self.consumption_table.setUpdatesEnabled(False)
        for r, m in enumerate(materials):
            self.consumption_table.insertRow(r)
            
            # Name
            name_item = QTableWidgetItem(m["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.consumption_table.setItem(r, 0, name_item)
            
            # Unit
            unit_item = QTableWidgetItem(m["unit"])
            unit_item.setFlags(unit_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.consumption_table.setItem(r, 1, unit_item)
            
            # Est Qty
            est_item = QTableWidgetItem(f"{m['qty']:.3f}")
            est_item.setFlags(est_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            est_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.consumption_table.setItem(r, 2, est_item)
            
            # Act Qty (Editable)
            saved_act = existing_customs.get(m["name"], m["qty"])
            act_item = QTableWidgetItem(f"{saved_act:.3f}")
            act_item.setFlags(act_item.flags() | Qt.ItemFlag.ItemIsEditable)
            act_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            act_item.setBackground(QColor("#fff3cd"))
            self.consumption_table.setItem(r, 3, act_item)
            
        self.consumption_table.setUpdatesEnabled(True)
        
        # Prefill description from project subjects if empty
        if not self.description_input.toPlainText().strip() and len(selected_paths) == 1:
            proj_name = ""
            if not is_edit:
                for r in range(self.active_table.rowCount()):
                    chk_widget = self.active_table.cellWidget(r, 0)
                    if chk_widget:
                        chk = chk_widget.findChild(QCheckBox)
                        if chk and chk.isChecked():
                            proj_name = self.active_projects[r]["name"]
                            break
            else:
                selected_indexes = self.invoiced_table.selectionModel().selectedRows()
                if selected_indexes:
                    row = selected_indexes[0].row()
                    proj_name = self.invoiced_projects[row]["name"]
            if proj_name:
                self.description_input.setText(f"Labour / erection work executed according to approved drawing for {proj_name}.")
                        
        # Prefill project metadata fields from project details if single project
        if len(selected_paths) == 1 and not is_edit:
            checked_idx = -1
            for r in range(self.active_table.rowCount()):
                chk_widget = self.active_table.cellWidget(r, 0)
                if chk_widget:
                    chk = chk_widget.findChild(QCheckBox)
                    if chk and chk.isChecked():
                        checked_idx = r
                        break
            if checked_idx != -1:
                p = self.active_projects[checked_idx]
                self.project_id_input.setText(p.get("project_id", ""))
                self.po_no_input.setText(p.get("po_no", ""))
                self.po_date_input.setText(p.get("po_date", ""))
                self.vendor_id_input.setText(p.get("vendor_id", "") or (self.profile.get("vendor_no", "") if self.profile else p.get("vendor_id", "")))
                self.comm_date_input.setText(p.get("comm_date", ""))
                self.comp_date_input.setText(p.get("comp_date", ""))
                self.meas_date_input.setText(p.get("meas_date", ""))
                self.meas_taken_by_input.setText(p.get("meas_taken_by", ""))
                self.certified_by_input.setText(p.get("certified_by", ""))
        elif len(selected_paths) > 1:
            if self.profile and not self.vendor_id_input.text().strip():
                self.vendor_id_input.setText(self.profile.get("vendor_no", ""))
        
    def _consolidate_boms(self, paths: list[str]) -> list[dict]:
        """Loads each project JSON in background and runs a calculation pass to extract BOM."""
        from app import EstimateApp
        
        all_bom_items = []
        
        for path in paths:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            temp_app = EstimateApp(headless=True)
            temp_app.parse_load_data(data, fit_view=False)
            temp_app._do_refresh_live_estimate()
            
            all_bom_items.extend(temp_app.live_bom_data)
            temp_app.deleteLater()
            
        # Consolidate identical items by code, name, unit, rate, and type
        consolidated = {}
        for item in all_bom_items:
            key = (item["type"], item["code"], item["name"], item["unit"], item["rate"])
            consolidated[key] = consolidated.get(key, 0.0) + item["qty"]
            
        consolidated_list = []
        for (itype, code, name, unit, rate), qty in consolidated.items():
            consolidated_list.append({
                "type": itype,
                "code": code,
                "name": name,
                "unit": unit,
                "rate": rate,
                "qty": qty,
                "amt": qty * rate
            })
            
        return consolidated_list
        
    def _generate_invoice(self):
        selected_paths = self._get_selected_projects_paths()
        if not selected_paths:
            QMessageBox.warning(self, "No Selection", "Please select at least one project from the table.")
            return
            
        if not self.profile:
            QMessageBox.critical(self, "No Active Profile", "You must configure an active profile to generate invoices.")
            return
            
        project_id = self.project_id_input.text().strip()
        po_no = self.po_no_input.text().strip()
        po_date = self.po_date_input.text().strip()
        client_name = self.client_name_input.text().strip()
        client_addr = self.client_address_input.text().strip()
        client_gstin = self.client_gstin_input.text().strip()
        invoice_no = self.invoice_no_input.text().strip()
        invoice_date = self.invoice_date_input.text().strip()
        copy_type_selection = self.copy_type_combo.currentText()
        description = self.description_input.toPlainText().strip()
        
        comm_date = self.comm_date_input.text().strip()
        comp_date = self.comp_date_input.text().strip()
        meas_date = self.meas_date_input.text().strip()
        vendor_id = self.vendor_id_input.text().strip()
        
        if not project_id or not po_no or not po_date or not client_name or not client_addr or not invoice_no or not invoice_date or not comm_date or not comp_date or not meas_date:
            QMessageBox.warning(self, "Validation Error", "Please fill in Project ID, PO Number, PO Date, Client Name, Address, Invoice No, Date, Commencement Date, Completion Date, and Measurement Date.")
            return
            
        # Read actual consumed quantities from Middle panel
        actual_qtys = {}
        for r in range(self.consumption_table.rowCount()):
            name_item = self.consumption_table.item(r, 0)
            act_item = self.consumption_table.item(r, 3)
            if name_item and act_item:
                try:
                    actual_qtys[name_item.text()] = float(act_item.text())
                except ValueError:
                    pass
                    
        # Calculate proportional labor scaling
        materials = [x for x in self.bom_items if x["type"] == "Material"]
        est_material_val = sum(m["qty"] * m["rate"] for m in materials)
        act_material_val = sum(actual_qtys.get(m["name"], m["qty"]) * m["rate"] for m in materials)
        
        ratio = 1.0
        if est_material_val > 0.0:
            ratio = act_material_val / est_material_val
        if ratio > 1.0:
            ratio = 1.0
            
        # Update bom_items with actual quantities
        for item in self.bom_items:
            if item["type"] == "Material":
                item["act_qty"] = actual_qtys.get(item["name"], item["qty"])
                item["act_amt"] = item["act_qty"] * item["rate"]
            else:  # Labor
                item["act_qty"] = item["qty"] * ratio
                item["act_amt"] = item["act_qty"] * item["rate"]
                
        # File dialog to save Billing Packet PDF
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Billing Packet PDF", f"Billing_Packet_{invoice_no}.pdf", "PDF Files (*.pdf)"
        )
        if not filename:
            return
            
        # Write PDF using QPrinter
        try:
            self._write_invoice_pdf(
                filename, self.bom_items,
                client_name, client_addr, client_gstin,
                invoice_no, invoice_date, project_id, po_no, po_date,
                description, comm_date, comp_date, meas_date, vendor_id
            )
            
            # Log invoice details to DB
            lab_base = sum(x["act_amt"] for x in self.bom_items if x["type"] == "Labor")
            cgst_amt = lab_base * 0.09
            sgst_amt = lab_base * 0.09
            gst_amt = cgst_amt + sgst_amt
            grand_total = lab_base + gst_amt
            
            bill_data = {
                "invoice_no": invoice_no,
                "invoice_date": invoice_date,
                "project_id": project_id,
                "po_no": po_no,
                "po_date": po_date,
                "copy_type": copy_type_selection,
                "client_name": client_name,
                "client_address": client_addr,
                "client_gstin": client_gstin,
                "description": description,
                "labor_total": lab_base,
                "cgst": cgst_amt,
                "sgst": sgst_amt,
                "gst": gst_amt,
                "grand_total": grand_total,
                "project_paths": selected_paths,
                "items": self.bom_items,
                "meas_taken_by": self.meas_taken_by_input.text().strip(),
                "certified_by": self.certified_by_input.text().strip()
            }
            _dbg.save_bill(bill_data)
            
            # Mark projects invoiced and save updated metadata
            for path in selected_paths:
                _dbg.mark_project_invoiced(path, invoice_no)
                
                # Save updated project metadata
                proj_meta = {
                    "project_id": project_id,
                    "po_no": po_no,
                    "po_date": po_date,
                    "vendor_id": vendor_id,
                    "comm_date": comm_date,
                    "comp_date": comp_date,
                    "meas_date": meas_date,
                    "meas_taken_by": self.meas_taken_by_input.text().strip(),
                    "certified_by": self.certified_by_input.text().strip()
                }
                _dbg.update_project_billing_metadata(
                    path=path,
                    project_id=project_id,
                    po_no=po_no,
                    po_date=po_date,
                    vendor_id=vendor_id,
                    comm_date=comm_date,
                    comp_date=comp_date,
                    meas_date=meas_date,
                    meas_taken_by=self.meas_taken_by_input.text().strip(),
                    certified_by=self.certified_by_input.text().strip()
                )
                
                # Merge into the project's JSON file if exists
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f_json:
                            pdata = json.load(f_json)
                        if "metadata" not in pdata or not isinstance(pdata["metadata"], dict):
                            pdata["metadata"] = {}
                        pdata["metadata"].update(proj_meta)
                        with open(path, "w", encoding="utf-8") as f_json:
                            json.dump(pdata, f_json, indent=4, ensure_ascii=False)
                    except Exception as pe:
                        print(f"Error saving updated metadata to JSON file: {pe}")
                        
            # Increment next sequence in active profile if not in edit mode
            if not self.is_edit_mode:
                _dbg.increment_active_profile_seq()
                
            # Update main app if currently open project was invoiced
            if hasattr(self.main_app, "current_project_path") and self.main_app.current_project_path in selected_paths:
                if hasattr(self.main_app, "project_meta") and isinstance(self.main_app.project_meta, dict):
                    self.main_app.project_meta.update(proj_meta)
                self.main_app._refresh_proj_label()
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Billing Packet Generated")
            msg.setText(f"Billing packet successfully exported and saved to database:\n{filename}")
            open_btn = msg.addButton("Open Packet File", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Close)
            msg.exec()
            if msg.clickedButton() == open_btn:
                os.startfile(filename)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "PDF Export Failed", f"Could not generate billing packet PDF:\n{e}")

    def _generate_completion_certificate_only(self):
        selected_paths = self._get_selected_projects_paths()
        if not selected_paths:
            QMessageBox.warning(self, "No Selection", "Please select at least one project from the table.")
            return
            
        if not self.profile:
            QMessageBox.critical(self, "No Active Profile", "You must configure an active profile.")
            return
            
        project_id = self.project_id_input.text().strip()
        po_no = self.po_no_input.text().strip()
        po_date = self.po_date_input.text().strip()
        invoice_no = self.invoice_no_input.text().strip()
        invoice_date = self.invoice_date_input.text().strip()
        client_name = self.client_name_input.text().strip()
        client_addr = self.client_address_input.text().strip()
        comm_date = self.comm_date_input.text().strip()
        comp_date = self.comp_date_input.text().strip()
        meas_date = self.meas_date_input.text().strip()
        vendor_id = self.vendor_id_input.text().strip()
        
        if not project_id or not po_no or not po_date or not client_name or not client_addr or not comm_date or not comp_date:
            QMessageBox.warning(self, "Validation Error", "Please fill in Project ID, PO Number, PO Date, Client Name, Address, Commencement Date, and Completion Date.")
            return
            
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Completion Certificate", f"Completion_Certificate_{invoice_no}.pdf", "PDF Files (*.pdf)"
        )
        if not filename:
            return
            
        # Save updated metadata
        for path in selected_paths:
            proj_meta = {
                "project_id": project_id,
                "po_no": po_no,
                "po_date": po_date,
                "vendor_id": vendor_id,
                "comm_date": comm_date,
                "comp_date": comp_date,
                "meas_date": meas_date,
                "meas_taken_by": self.meas_taken_by_input.text().strip(),
                "certified_by": self.certified_by_input.text().strip()
            }
            _dbg.update_project_billing_metadata(
                path=path,
                project_id=project_id,
                po_no=po_no,
                po_date=po_date,
                vendor_id=vendor_id,
                comm_date=comm_date,
                comp_date=comp_date,
                meas_date=meas_date,
                meas_taken_by=self.meas_taken_by_input.text().strip(),
                certified_by=self.certified_by_input.text().strip()
            )
            
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f_json:
                        pdata = json.load(f_json)
                    if "metadata" not in pdata or not isinstance(pdata["metadata"], dict):
                        pdata["metadata"] = {}
                    pdata["metadata"].update(proj_meta)
                    with open(path, "w", encoding="utf-8") as f_json:
                        json.dump(pdata, f_json, indent=4, ensure_ascii=False)
                except Exception:
                    pass
            
        # Update main app if currently open project was updated
        if hasattr(self.main_app, "current_project_path") and self.main_app.current_project_path in selected_paths:
            if hasattr(self.main_app, "project_meta") and isinstance(self.main_app.project_meta, dict):
                self.main_app.project_meta.update(proj_meta)
            self.main_app._refresh_proj_label()
            
        try:
            printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(filename)
            
            from PyQt6.QtGui import QPageSize, QPageLayout
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageOrientation(QPageLayout.Orientation.Portrait)
            
            painter = QPainter(printer)
            paper = printer.paperRect(QPrinter.Unit.DevicePixel)
            
            margin = 40
            w = paper.width() - 2 * margin
            h = paper.height() - 2 * margin
            x0, y0 = margin, margin
            
            font_title = QFont("Arial", 15, QFont.Weight.Bold)
            font_h2 = QFont("Arial", 10, QFont.Weight.Bold)
            font_body = QFont("Arial", 8)
            font_body_bold = QFont("Arial", 8, QFont.Weight.Bold)
            font_small = QFont("Arial", 7)
            
            self._draw_completion_certificate_page(
                painter, client_name, client_addr,
                invoice_no, invoice_date, project_id, po_no, po_date,
                comm_date, comp_date,
                x0, y0, w, h, margin, font_title, font_h2,
                font_body, font_body_bold, font_small
            )
            
            painter.end()
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Certificate Generated")
            msg.setText(f"Completion Certificate successfully generated:\n{filename}")
            open_btn = msg.addButton("Open Certificate", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Close)
            msg.exec()
            if msg.clickedButton() == open_btn:
                os.startfile(filename)
            
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not generate completion certificate:\n{e}")
            
    def _generate_billing_report(self):
        """Generate a summary PDF report of all invoiced projects."""
        if not self.profile:
            QMessageBox.critical(self, "No Active Profile", "You must configure an active profile to generate reports.")
            return
            
        bills = _dbg.get_bills()
        if not bills:
            QMessageBox.information(self, "No Bills", "No invoiced projects found in the database.")
            return
            
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save All Projects Report PDF",
            f"Billing_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
            "PDF Files (*.pdf)"
        )
        if not filename:
            return
            
        try:
            printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(filename)
            
            from PyQt6.QtGui import QPageSize, QPageLayout
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)
            
            painter = QPainter(printer)
            paper = printer.paperRect(QPrinter.Unit.DevicePixel)
            
            margin = 35
            w = paper.width() - 2 * margin
            h = paper.height() - 2 * margin
            x0, y0 = margin, margin
            
            font_title = QFont("Arial", 14, QFont.Weight.Bold)
            font_h2 = QFont("Arial", 9, QFont.Weight.Bold)
            font_body = QFont("Arial", 7)
            font_body_bold = QFont("Arial", 7, QFont.Weight.Bold)
            font_small = QFont("Arial", 6)
            
            # Column definitions
            col_lbl = ["Sl", "Invoice No", "Invoice Date", "Project ID", "PO No", "PO Date",
                        "Client Name", "Description", "Labor Total", "GST", "Grand Total", "Created"]
            col_w = [25, 75, 60, 80, 70, 55, 100, w - 25 - 75 - 60 - 80 - 70 - 55 - 100 - 65 - 55 - 65 - 60, 65, 55, 65, 60]
            
            row_h = 16
            table_y = y0 + 55
            page_num = 1
            
            def draw_report_headers(p_num):
                painter.setFont(font_title)
                painter.setPen(Qt.GlobalColor.black)
                painter.drawText(QRectF(x0, y0, w, 22), Qt.AlignmentFlag.AlignCenter, "ALL PROJECTS BILLING REPORT")
                painter.setFont(font_body)
                painter.drawText(QRectF(x0, y0 + 24, w, 14), Qt.AlignmentFlag.AlignCenter,
                                 f"Agency: {self.profile['firm_name']} | Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
                
                painter.setPen(QPen(QColor("#333"), 1.0))
                painter.drawLine(QPointF(x0, y0 + 42), QPointF(x0 + w, y0 + 42))
                
                # Header row
                painter.setBrush(QBrush(QColor("#2c3e50")))
                painter.setPen(QPen(QColor("#2c3e50"), 0.8))
                painter.drawRect(QRectF(x0, table_y, w, row_h))
                
                painter.setFont(font_body_bold)
                painter.setPen(Qt.GlobalColor.white)
                cx = x0
                for i, lbl in enumerate(col_lbl):
                    painter.drawText(QRectF(cx + 2, table_y, col_w[i] - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter, lbl)
                    cx += col_w[i]
                    
                # Footer
                painter.setFont(font_small)
                painter.setPen(Qt.GlobalColor.black)
                painter.drawText(QRectF(x0, h + margin - 12, w, 10), Qt.AlignmentFlag.AlignCenter, f"Report Page {p_num}")
            
            draw_report_headers(page_num)
            cy = table_y + row_h
            
            grand_labor = 0.0
            grand_gst = 0.0
            grand_total_all = 0.0
            
            for idx, bill in enumerate(bills):
                if cy > h + margin - 40:
                    # Draw table border for current page
                    painter.setPen(QPen(QColor("#ccc"), 0.8))
                    painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
                    
                    printer.newPage()
                    page_num += 1
                    draw_report_headers(page_num)
                    cy = table_y + row_h
                
                # Alternating row background
                if idx % 2 == 0:
                    painter.setBrush(QBrush(QColor("#f8f9fa")))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(QRectF(x0, cy, w, row_h))
                
                # Row separator
                painter.setPen(QPen(QColor("#dee2e6"), 0.5))
                painter.drawLine(QPointF(x0, cy + row_h), QPointF(x0 + w, cy + row_h))
                
                painter.setPen(Qt.GlobalColor.black)
                painter.setFont(font_body)
                
                labor_total = bill.get("labor_total", 0) or 0
                gst = bill.get("gst", 0) or 0
                grand = bill.get("grand_total", 0) or 0
                
                grand_labor += labor_total
                grand_gst += gst
                grand_total_all += grand
                
                vals = [
                    str(idx + 1),
                    bill.get("invoice_no", ""),
                    bill.get("invoice_date", ""),
                    bill.get("project_id", ""),
                    bill.get("po_no", ""),
                    bill.get("po_date", ""),
                    bill.get("client_name", ""),
                    (bill.get("description", "") or "")[:60],
                    f"{labor_total:,.2f}",
                    f"{gst:,.2f}",
                    f"{grand:,.2f}",
                    (bill.get("created_at", "") or "")[:10]
                ]
                
                cx = x0
                for i, val in enumerate(vals):
                    metrics = painter.fontMetrics()
                    elided = metrics.elidedText(val, Qt.TextElideMode.ElideRight, int(col_w[i] - 6))
                    align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                    if i in (0, 8, 9, 10):  # right-align numbers
                        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                    painter.drawText(QRectF(cx + 3, cy, col_w[i] - 6, row_h), align, elided)
                    cx += col_w[i]
                    
                cy += row_h
            
            # Draw bottom border
            painter.setPen(QPen(QColor("#333"), 1.0))
            painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
            
            # Grand Total row
            if cy > h + margin - 40:
                printer.newPage()
                page_num += 1
                draw_report_headers(page_num)
                cy = table_y + row_h
                
            painter.setBrush(QBrush(QColor("#d4edda")))
            painter.setPen(QPen(QColor("#333"), 0.8))
            painter.drawRect(QRectF(x0, cy, w, row_h))
            
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body_bold)
            
            # Label
            painter.drawText(QRectF(x0 + 5, cy, 200, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             f"TOTALS ({len(bills)} Bills)")
            
            # Labor Total
            labor_x = x0 + sum(col_w[:8])
            painter.drawText(QRectF(labor_x + 3, cy, col_w[8] - 6, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{grand_labor:,.2f}")
            # GST
            gst_x = labor_x + col_w[8]
            painter.drawText(QRectF(gst_x + 3, cy, col_w[9] - 6, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{grand_gst:,.2f}")
            # Grand Total
            gt_x = gst_x + col_w[9]
            painter.drawText(QRectF(gt_x + 3, cy, col_w[10] - 6, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{grand_total_all:,.2f}")
            
            cy += row_h + 8
            
            # Amount in words
            from ui.dialogs.billing import amount_to_words
            words = amount_to_words(grand_total_all)
            painter.setFont(font_body_bold)
            painter.drawText(QRectF(x0 + 5, cy, w - 10, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             f"Grand Total in Words: {words}")
            
            painter.end()
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Report Generated")
            msg.setText(f"All Projects Billing Report exported successfully:\n{filename}")
            open_btn = msg.addButton("Open Report", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Close)
            msg.exec()
            if msg.clickedButton() == open_btn:
                os.startfile(filename)
                
        except Exception as e:
            QMessageBox.critical(self, "Report Export Failed", f"Could not generate billing report:\n{e}")

    def _write_invoice_pdf(
        self, filename, bom_items,
        client_name, client_addr, client_gstin,
        invoice_no, invoice_date, project_id, po_no, po_date,
        description, comm_date, comp_date, meas_date, vendor_id
    ):
        printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(filename)
        
        from PyQt6.QtGui import QPageSize, QPageLayout
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)
        
        painter = QPainter(printer)
        paper = printer.paperRect(QPrinter.Unit.DevicePixel)
        
        margin = 40
        w = paper.width() - 2 * margin
        h = paper.height() - 2 * margin
        x0, y0 = margin, margin
        
        # Set fonts
        font_title = QFont("Arial", 15, QFont.Weight.Bold)
        font_h2 = QFont("Arial", 10, QFont.Weight.Bold)
        font_body = QFont("Arial", 8)
        font_body_bold = QFont("Arial", 8, QFont.Weight.Bold)
        font_small = QFont("Arial", 7)
        
        # Determine copies to generate
        copy_type_selection = self.copy_type_combo.currentText()
        if copy_type_selection == "All 3 Copies (Combined Packet)":
            copies = [
                "Original for Recipient",
                "Duplicate for Provider",
                "Triplicate for Supplier"
            ]
        else:
            copies = [copy_type_selection]
            
        is_first = True
        for copy_title in copies:
            if not is_first:
                printer.newPage()
            is_first = False
            
            # Draw Page 1: Invoice Sheet
            self._draw_invoice_page(
                painter, copy_title, bom_items,
                client_name, client_addr, client_gstin,
                invoice_no, invoice_date, project_id, po_no, po_date,
                description, x0, y0, w, h, margin, font_title, font_h2,
                font_body, font_body_bold, font_small
            )
            
        # Draw Page 2: SMB Cover Page
        printer.newPage()
        self._draw_smb_cover_page(
            painter, client_name, client_addr,
            invoice_no, invoice_date, project_id, po_no, po_date,
            description, comm_date, comp_date, meas_date, vendor_id,
            x0, y0, w, h, margin, font_title, font_h2,
            font_body, font_body_bold, font_small
        )
        
        # Transition to Landscape for Page 3: Abstract of Quantities & Valuation
        from PyQt6.QtGui import QPageLayout
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        paper_l = printer.paperRect(QPrinter.Unit.DevicePixel)
        w_l = paper_l.width() - 2 * margin
        h_l = paper_l.height() - 2 * margin
        
        printer.newPage()
        self._draw_abstract_landscape_page(
            painter, bom_items,
            invoice_no, invoice_date, project_id, po_no, po_date,
            meas_date,
            x0, y0, w_l, h_l, margin, font_title, font_h2,
            font_body, font_body_bold, font_small
        )
        
        # Transition back to Portrait for remaining pages
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)
        
        # Draw Page 4: Completion & Undertaking Certificate (10 clauses)
        printer.newPage()
        self._draw_completion_certificate_page(
            painter, client_name, client_addr,
            invoice_no, invoice_date, project_id, po_no, po_date,
            comm_date, comp_date,
            x0, y0, w, h, margin, font_title, font_h2,
            font_body, font_body_bold, font_small
        )
        
        # Draw Page 6: Material Consumption & Completion Report (Reconciliation)
        printer.newPage()
        self._draw_consumption_report_page(
            painter, bom_items,
            invoice_no, invoice_date, project_id, po_no, po_date,
            x0, y0, w, h, margin, font_title, font_h2,
            font_body, font_body_bold, font_small
        )
        
        # Optional: Measurement Sheet (Material)
        if self.include_meas_material_cb.isChecked():
            printer.newPage()
            self._draw_measurement_sheet_page(
                printer, painter, bom_items, "Material",
                invoice_no, invoice_date, project_id, po_no, po_date,
                x0, y0, w, h, margin, font_title, font_h2,
                font_body, font_body_bold, font_small
            )
            
        # Optional: Measurement Sheet (Labor)
        if self.include_meas_labor_cb.isChecked():
            printer.newPage()
            self._draw_measurement_sheet_page(
                printer, painter, bom_items, "Labor",
                invoice_no, invoice_date, project_id, po_no, po_date,
                x0, y0, w, h, margin, font_title, font_h2,
                font_body, font_body_bold, font_small
            )
        
        # Check if project estimate should be included
        if self.include_estimate_cb.isChecked():
            printer.newPage()
            self._draw_estimate_page(
                printer, painter, bom_items,
                x0, y0, w, h, margin, font_title, font_h2,
                font_body, font_body_bold, font_small
            )
            
        # Check if project drawing should be included
        if self.include_drawing_cb.isChecked():
            from exporters.pdf import PDFExporter
            exporter = PDFExporter(self.main_app)
            exporter.export_to_painter(printer, painter)
            
        painter.end()

    def _draw_invoice_page(self, painter, copy_title, bom_items,
                            client_name, client_addr, client_gstin,
                            invoice_no, invoice_date, project_id, po_no, po_date,
                            description, x0, y0, w, h, margin, font_title, font_h2,
                            font_body, font_body_bold, font_small):
        # 1. HEADER (Firm Details)
        if not self.exclude_header_invoice_cb.isChecked():
            painter.setFont(font_body_bold)
            painter.setPen(QPen(QColor("#777")))
            painter.drawText(QRectF(x0, y0, w, 15), Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop, f"** {copy_title.upper()} **")
        
        if not self.exclude_header_invoice_cb.isChecked():
            # Check if logo exists and is valid
            logo_path = self.profile.get("logo_path")
            if logo_path and os.path.exists(logo_path):
                logo_img = QImage(logo_path)
                if not logo_img.isNull():
                    # Keep aspect ratio when scaling logo within a 55x55 region
                    logo_w = logo_img.width()
                    logo_h = logo_img.height()
                    if logo_w > 0 and logo_h > 0:
                        scale = min(55.0 / logo_w, 55.0 / logo_h)
                        fit_w = logo_w * scale
                        fit_h = logo_h * scale
                        # Center the logo in the 55x55 bounding box
                        logo_x = x0 + 10 + (55.0 - fit_w) / 2.0
                        logo_y = y0 + 15 + (55.0 - fit_h) / 2.0
                        painter.drawImage(QRectF(logo_x, logo_y, fit_w, fit_h), logo_img)

            # Center the agency heading and details
            painter.setFont(font_title)
            painter.setPen(Qt.GlobalColor.black)
            painter.drawText(QRectF(x0, y0 + 15, w, 24), Qt.AlignmentFlag.AlignCenter, self.profile["firm_name"])
            
            painter.setFont(font_body)
            painter.drawText(QRectF(x0, y0 + 40, w, 14), Qt.AlignmentFlag.AlignCenter, f"Address: {self.profile['address']}")
            painter.drawText(QRectF(x0, y0 + 54, w, 14), Qt.AlignmentFlag.AlignCenter, f"GSTIN: {self.profile['gstin']}")
            
            # Separator line
            painter.setPen(QPen(QColor("#333"), 1.2))
            painter.drawLine(QPointF(x0, y0 + 72), QPointF(x0 + w, y0 + 72))
        
        # Title "TAX INVOICE"
        painter.setFont(font_title)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0, y0 + 82, w, 24), Qt.AlignmentFlag.AlignCenter, "TAX INVOICE")
        
        if self.exclude_header_invoice_cb.isChecked():
            painter.setFont(font_small)
            painter.setPen(QPen(QColor("#555")))
            painter.drawText(QRectF(x0, y0 + 104, w, 12), Qt.AlignmentFlag.AlignCenter, f"({copy_title.upper()})")
        
        # 2. INVOICE META BLOCK (Left: Bill To, Right: Invoice Info & PO Info)
        # If exclude_header is checked, we add a middle "FROM" column with agency details
        meta_y = y0 + 115
        meta_h = 80
        
        # Draw table border for billing details
        painter.setPen(QPen(QColor("#000"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x0, meta_y, w, meta_h))
        
        if self.exclude_header_invoice_cb.isChecked():
            # 3-column layout: Bill To | From (Agency) | Invoice Info
            col_w = w / 3
            painter.drawLine(QPointF(x0 + col_w, meta_y), QPointF(x0 + col_w, meta_y + meta_h))
            painter.drawLine(QPointF(x0 + 2 * col_w, meta_y), QPointF(x0 + 2 * col_w, meta_y + meta_h))
            
            # Left: BILL TO
            painter.setFont(font_h2)
            painter.drawText(QRectF(x0 + 6, meta_y + 6, col_w - 12, 16), Qt.AlignmentFlag.AlignLeft, "BILL TO:")
            painter.setFont(font_body)
            painter.drawText(QRectF(x0 + 6, meta_y + 24, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, client_name)
            painter.drawText(QRectF(x0 + 6, meta_y + 38, col_w - 12, 30), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, client_addr)
            if client_gstin:
                painter.drawText(QRectF(x0 + 6, meta_y + 64, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"GSTIN: {client_gstin}")
                
            # Middle: FROM (Agency Details)
            painter.setFont(font_h2)
            painter.drawText(QRectF(x0 + col_w + 6, meta_y + 6, col_w - 12, 16), Qt.AlignmentFlag.AlignLeft, "FROM:")
            painter.setFont(font_body)
            painter.drawText(QRectF(x0 + col_w + 6, meta_y + 24, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, self.profile["firm_name"])
            painter.drawText(QRectF(x0 + col_w + 6, meta_y + 38, col_w - 12, 30), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.profile["address"])
            if self.profile.get("gstin"):
                painter.drawText(QRectF(x0 + col_w + 6, meta_y + 64, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"GSTIN: {self.profile['gstin']}")
                
            # Right: Invoice metadata
            painter.setFont(font_body_bold)
            painter.drawText(QRectF(x0 + 2 * col_w + 6, meta_y + 6, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"Inv No:   {invoice_no}")
            painter.drawText(QRectF(x0 + 2 * col_w + 6, meta_y + 20, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"Inv Date: {invoice_date}")
            painter.drawText(QRectF(x0 + 2 * col_w + 6, meta_y + 34, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"Proj ID:  {project_id}")
            painter.drawText(QRectF(x0 + 2 * col_w + 6, meta_y + 48, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"PO No:    {po_no}")
            painter.drawText(QRectF(x0 + 2 * col_w + 6, meta_y + 62, col_w - 12, 14), Qt.AlignmentFlag.AlignLeft, f"PO Date:  {po_date}")
        else:
            # 2-column layout: Bill To | Invoice Info
            painter.drawLine(QPointF(x0 + w / 2, meta_y), QPointF(x0 + w / 2, meta_y + meta_h))
            
            # Left: BILL TO
            painter.setFont(font_h2)
            painter.drawText(QRectF(x0 + 8, meta_y + 6, w / 2 - 16, 16), Qt.AlignmentFlag.AlignLeft, "BILL TO:")
            painter.setFont(font_body)
            painter.drawText(QRectF(x0 + 8, meta_y + 24, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, client_name)
            painter.drawText(QRectF(x0 + 8, meta_y + 38, w / 2 - 16, 30), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, client_addr)
            if client_gstin:
                painter.drawText(QRectF(x0 + 8, meta_y + 64, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, f"GSTIN: {client_gstin}")
                
            # Right: Invoice metadata
            painter.setFont(font_body_bold)
            painter.drawText(QRectF(x0 + w / 2 + 8, meta_y + 6, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, f"Invoice No:    {invoice_no}")
            painter.drawText(QRectF(x0 + w / 2 + 8, meta_y + 20, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, f"Invoice Date:  {invoice_date}")
            painter.drawText(QRectF(x0 + w / 2 + 8, meta_y + 34, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, f"Project ID:    {project_id}")
            painter.drawText(QRectF(x0 + w / 2 + 8, meta_y + 48, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, f"PO Number:     {po_no}")
            painter.drawText(QRectF(x0 + w / 2 + 8, meta_y + 62, w / 2 - 16, 14), Qt.AlignmentFlag.AlignLeft, f"PO Date:       {po_date}")
        
        # Project Subject table box with spacing
        subject_y = meta_y + meta_h + 10
        subject_h = 24
        painter.setPen(QPen(QColor("#000"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x0, subject_y, w, subject_h))
        
        painter.setFont(font_body_bold)
        painter.drawText(QRectF(x0 + 8, subject_y, 110, subject_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Project Subject:")
        
        painter.setFont(font_body)
        painter.drawText(QRectF(x0 + 120, subject_y, w - 128, subject_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, description or "")
        
        # 3. TABLE OF LABOUR ITEMS with spacing
        col_w = [30, w - 30 - 60 - 50 - 70 - 90, 60, 50, 70, 90]
        col_lbl = ["Sl", "Labour Erection Description", "Qty", "Unit", "Rate (Rs)", "Amount (Rs)"]
        
        table_y = subject_y + subject_h + 10
        row_h = 18
        
        # Table header background
        painter.setBrush(QBrush(QColor("#f2f2f2")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(x0, table_y, w, row_h))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        cx = x0
        for i, lbl in enumerate(col_lbl):
            painter.drawText(QRectF(cx, table_y, col_w[i], row_h), Qt.AlignmentFlag.AlignCenter, lbl)
            cx += col_w[i]
            
        cy = table_y + row_h
        sl = 1
        
        lab_items = [x for x in bom_items if x["type"] == "Labor"]
        lab_base = 0.0
        
        for item in lab_items:
            if cy > h + margin - 140:
                painter.setFont(font_body_bold)
                painter.drawText(QRectF(x0, cy, w, row_h), Qt.AlignmentFlag.AlignCenter, "... Continued on Measurement Sheet ...")
                cy += row_h
                break
                
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body)
            
            cx = x0
            # Sl
            painter.drawText(QRectF(cx, cy, col_w[0], row_h), Qt.AlignmentFlag.AlignCenter, str(sl))
            cx += col_w[0]
            
            # Desc
            desc_text = str(item["name"])
            metrics = painter.fontMetrics()
            elided_desc = metrics.elidedText(desc_text, Qt.TextElideMode.ElideRight, int(col_w[1] - 6))
            painter.drawText(QRectF(cx + 2, cy, col_w[1] - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_desc)
            cx += col_w[1]
            
            # Qty
            qty = item.get("act_qty", item["qty"])
            qty_str = f"{qty:,.3f}" if isinstance(qty, float) else str(qty)
            painter.drawText(QRectF(cx, cy, col_w[2], row_h), Qt.AlignmentFlag.AlignCenter, qty_str)
            cx += col_w[2]
            
            # Unit
            painter.drawText(QRectF(cx, cy, col_w[3], row_h), Qt.AlignmentFlag.AlignCenter, str(item["unit"]))
            cx += col_w[3]
            
            # Rate
            painter.drawText(QRectF(cx - 2, cy, col_w[4], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['rate']:,.2f}")
            cx += col_w[4]
            
            # Amt
            amt = item.get("act_amt", item["amt"])
            painter.drawText(QRectF(cx - 2, cy, col_w[5], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{amt:,.2f}")
            
            lab_base += amt
            cy += row_h
            sl += 1
            
        # Draw outer table border for items
        painter.setPen(QPen(QColor("#000"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x0, table_y, w, cy - table_y))
        
        # Draw horizontal lines for each row (including header separator)
        for r_y in range(table_y + row_h, cy + 1, row_h):
            painter.drawLine(QPointF(x0, r_y), QPointF(x0 + w, r_y))
            
        # Draw vertical lines for column separators
        vx = x0
        for width in col_w[:-1]:
            vx += width
            painter.drawLine(QPointF(vx, table_y), QPointF(vx, cy))
            
        # Draw summary rows
        def _draw_summary_row(label, val, bold=False, bg=None):
            nonlocal cy
            painter.save()
            if bg:
                painter.setBrush(QBrush(bg))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(x0, cy, w, row_h))
            painter.setPen(QPen(QColor("#000"), 1.0))
            painter.drawRect(QRectF(x0, cy, w, row_h))
            # Split summary row matching the Amount column
            painter.drawLine(QPointF(x0 + w - col_w[5], cy), QPointF(x0 + w - col_w[5], cy + row_h))
            
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body_bold if bold else font_body)
            painter.drawText(QRectF(x0 + 10, cy, w - col_w[5] - 20, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            val_str = f"Rs. {val:,.2f}"
            painter.drawText(QRectF(x0 + w - col_w[5] + 5, cy, col_w[5] - 10, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, val_str)
            painter.restore()
            cy += row_h
            
        _draw_summary_row("TOTAL LABOUR COST (A)", lab_base, bold=True, bg=QColor("#f0f7ff"))
        
        # GST split: CGST 9% + SGST 9%
        cgst_amt = lab_base * 0.09
        sgst_amt = lab_base * 0.09
        _draw_summary_row("Add: CGST @ 9% on Labour charges", cgst_amt)
        _draw_summary_row("Add: SGST @ 9% on Labour charges", sgst_amt)
        
        # Grand Total
        grand_total = lab_base + cgst_amt + sgst_amt
        _draw_summary_row("GRAND TOTAL (BILLED LABOR VALUE)", grand_total, bold=True, bg=QColor("#d4edda"))
        
        # Draw Amount in Words
        words_text = amount_to_words(grand_total)
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 10, cy + 5, w - 20, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"Amount in Words: {words_text}")
        cy += row_h + 10
            
        # Draw Declaration table/box below total amounts with spacing
        decl_w = w
        decl_h = 40
        decl_y = cy
        
        # Border
        painter.setPen(QPen(QColor("#000"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x0, decl_y, decl_w, decl_h))
        
        # Content
        painter.setFont(font_small)
        painter.setFont(QFont(font_small.family(), font_small.pointSize(), QFont.Weight.Bold))
        painter.drawText(QRectF(x0 + 6, decl_y + 4, decl_w - 12, 12), Qt.AlignmentFlag.AlignLeft, "Declaration:")
        
        painter.setFont(font_small)
        decl_text = "We declare that this invoice shows the actual price of the goods/services described and that all particulars are true and correct."
        painter.drawText(QRectF(x0 + 6, decl_y + 16, decl_w - 12, decl_h - 18), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, decl_text)
        
        cy += decl_h + 10
        
        # Signature block
        sig_y = max(cy + 15, h + margin - 70)
        sig_path = self.profile.get("signature_path")
        if sig_path and os.path.exists(sig_path):
            sig_img = QImage(sig_path)
            if not sig_img.isNull():
                painter.drawImage(QRectF(x0 + w - 120, sig_y - 45, 120, 45), sig_img)
                
        painter.setFont(font_body_bold)
        painter.drawText(QRectF(x0 + w - 200, sig_y, 200, 16), Qt.AlignmentFlag.AlignRight, "Authorized Signature")
        painter.setFont(font_small)
        painter.drawText(QRectF(x0, sig_y + 18, w, 15), Qt.AlignmentFlag.AlignCenter, "This is a computer-generated tax invoice and requires no physical seal.")

    def _draw_abstract_page(self, painter, bom_items,
                            client_name, client_addr, client_gstin,
                            invoice_no, invoice_date, project_id, po_no, po_date,
                            x0, y0, w, h, margin, font_title, font_h2,
                            font_body, font_body_bold, font_small):
        # 1. Title Banner
        painter.setFont(font_title)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0, y0, w, 24), Qt.AlignmentFlag.AlignCenter, "ABSTRACT OF LABOR ERECTION BILL")
        painter.setFont(font_body)
        painter.drawText(QRectF(x0, y0 + 26, w, 14), Qt.AlignmentFlag.AlignCenter, 
                         f"Invoice No: {invoice_no} | Date: {invoice_date} | Project ID: {project_id}")
        
        painter.setPen(QPen(QColor("#333"), 1.0))
        painter.drawLine(QPointF(x0, y0 + 44), QPointF(x0 + w, y0 + 44))
        
        # Columns: Sl (25), Description (Stretch), Unit (35), Rate (55), PO Qty (55), PO Amt (70), Act Qty (55), Act Amt (70)
        col_w = [25, w - 25 - 35 - 55 - 55 - 70 - 55 - 70, 35, 55, 55, 70, 55, 70]
        col_lbl = ["Sl", "Labour Work Description", "Unit", "Rate (Rs)", "PO Qty", "PO Amt (Rs)", "Act Qty", "Act Amt (Rs)"]
        
        table_y = y0 + 55
        row_h = 18
        
        # Header Box
        painter.setBrush(QBrush(QColor("#f2f2f2")))
        painter.setPen(QPen(QColor("#ccc"), 0.8))
        painter.drawRect(QRectF(x0, table_y, w, row_h))
        
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        cx = x0
        for i, lbl in enumerate(col_lbl):
            painter.drawText(QRectF(cx, table_y, col_w[i], row_h), Qt.AlignmentFlag.AlignCenter, lbl)
            cx += col_w[i]
            
        cy = table_y + row_h
        sl = 1
        
        lab_items = [x for x in bom_items if x["type"] == "Labor"]
        
        po_total = 0.0
        act_total = 0.0
        
        for item in lab_items:
            if cy > h + margin - 120:
                painter.drawText(QRectF(x0, cy, w, row_h), Qt.AlignmentFlag.AlignLeft, "... Continued on Next Page ...")
                break
                
            painter.setPen(QPen(QColor("#e0e0e0"), 0.5))
            painter.drawLine(QPointF(x0, cy + row_h), QPointF(x0 + w, cy + row_h))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body)
            
            cx = x0
            # Sl
            painter.drawText(QRectF(cx, cy, col_w[0], row_h), Qt.AlignmentFlag.AlignCenter, str(sl))
            cx += col_w[0]
            # Desc
            desc_text = str(item["name"])
            metrics = painter.fontMetrics()
            elided_desc = metrics.elidedText(desc_text, Qt.TextElideMode.ElideRight, int(col_w[1] - 6))
            painter.drawText(QRectF(cx + 2, cy, col_w[1] - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_desc)
            cx += col_w[1]
            # Unit
            painter.drawText(QRectF(cx, cy, col_w[2], row_h), Qt.AlignmentFlag.AlignCenter, str(item["unit"]))
            cx += col_w[2]
            # Rate
            painter.drawText(QRectF(cx - 2, cy, col_w[3], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['rate']:,.2f}")
            cx += col_w[3]
            # PO Qty
            painter.drawText(QRectF(cx - 2, cy, col_w[4], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['qty']:.3f}")
            cx += col_w[4]
            # PO Amt
            painter.drawText(QRectF(cx - 2, cy, col_w[5], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['amt']:,.2f}")
            cx += col_w[5]
            # Act Qty
            painter.drawText(QRectF(cx - 2, cy, col_w[6], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item.get('act_qty', item['qty']):.3f}")
            cx += col_w[6]
            # Act Amt
            painter.drawText(QRectF(cx - 2, cy, col_w[7], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item.get('act_amt', item['amt']):,.2f}")
            
            po_total += item["amt"]
            act_total += item.get("act_amt", item["amt"])
            cy += row_h
            sl += 1
            
        # Draw summary rows
        def _draw_sum_row(label, po_val, act_val, bold=False, bg=None):
            nonlocal cy
            painter.save()
            if bg:
                painter.setBrush(QBrush(bg))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(x0, cy, w, row_h))
            painter.setPen(QPen(QColor("#ccc"), 0.5))
            painter.drawLine(QPointF(x0, cy + row_h), QPointF(x0 + w, cy + row_h))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body_bold if bold else font_body)
            painter.drawText(QRectF(x0 + 10, cy, w - 240, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            
            po_str = f"Rs. {po_val:,.2f}"
            act_str = f"Rs. {act_val:,.2f}"
            painter.drawText(QRectF(x0 + w - 230, cy, 100, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, po_str)
            painter.drawText(QRectF(x0 + w - 110, cy, 100, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, act_str)
            painter.restore()
            cy += row_h

        _draw_sum_row("TOTAL LABOUR COST", po_total, act_total, bold=True, bg=QColor("#f0f7ff"))
        _draw_sum_row("Add: CGST @ 9% on Labour", po_total * 0.09, act_total * 0.09)
        _draw_sum_row("Add: SGST @ 9% on Labour", po_total * 0.09, act_total * 0.09)
        _draw_sum_row("GRAND TOTAL (BILLED LABOR VALUE)", po_total * 1.18, act_total * 1.18, bold=True, bg=QColor("#d4edda"))

        # Signatures
        sig_y = h + margin - 70
        painter.setPen(QPen(QColor("#ccc"), 0.5))
        painter.drawLine(QPointF(x0, sig_y - 10), QPointF(x0 + w, sig_y - 10))
        
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 10, sig_y, 250, 16), Qt.AlignmentFlag.AlignLeft, "Signature of Contractor")
        painter.drawText(QRectF(x0 + w - 260, sig_y, 250, 16), Qt.AlignmentFlag.AlignRight, "Signature of Assistant Engineer")
        
        painter.setFont(font_body)
        painter.drawText(QRectF(x0 + 10, sig_y + 18, 250, 16), Qt.AlignmentFlag.AlignLeft, f"M/S: {self.profile['firm_name']}")
        painter.drawText(QRectF(x0 + w - 260, sig_y + 18, 250, 16), Qt.AlignmentFlag.AlignRight, "WBSEDCL / Department Representative")

    def _draw_smb_cover_page(self, painter, client_name, client_addr,
                             invoice_no, invoice_date, project_id, po_no, po_date,
                             description, comm_date, comp_date, meas_date, vendor_id,
                             x0, y0, w, h, margin, font_title, font_h2,
                             font_body, font_body_bold, font_small):
        # Draw double border for cover page
        painter.save()
        painter.setPen(QPen(QColor("#000"), 1.8))
        painter.drawRect(QRectF(x0 - 15, y0 - 15, w + 30, h + 30))
        painter.setPen(QPen(QColor("#000"), 0.8))
        painter.drawRect(QRectF(x0 - 10, y0 - 10, w + 20, h + 20))
        painter.restore()

        # Title block
        font_main_hdr = QFont("Arial", 13, QFont.Weight.Bold)
        font_sub_hdr = QFont("Arial", 10, QFont.Weight.Bold)
        
        painter.setFont(font_main_hdr)
        painter.drawText(QRectF(x0, y0 + 30, w, 25), Qt.AlignmentFlag.AlignCenter, "WEST BENGAL STATE ELECTRICITY DISTRIBUTION CO. LTD.")
        
        painter.setFont(font_sub_hdr)
        painter.drawText(QRectF(x0, y0 + 55, w, 20), Qt.AlignmentFlag.AlignCenter, "(A Government of West Bengal Enterprise)")
        
        painter.setPen(QPen(QColor("#000"), 1.5))
        painter.drawLine(QPointF(x0 + 40, y0 + 85), QPointF(x0 + w - 40, y0 + 85))
        
        font_book_title = QFont("Arial", 16, QFont.Weight.Bold)
        painter.setFont(font_book_title)
        painter.drawText(QRectF(x0, y0 + 105, w, 30), Qt.AlignmentFlag.AlignCenter, "STANDARD MEASUREMENT BOOK")
        
        font_sub_title = QFont("Arial", 11, QFont.Weight.Bold)
        painter.setFont(font_sub_title)
        painter.drawText(QRectF(x0, y0 + 138, w, 20), Qt.AlignmentFlag.AlignCenter, f"PROJECT ID: {project_id}")
        
        painter.setPen(QPen(QColor("#000"), 1.0))
        painter.drawLine(QPointF(x0 + 80, y0 + 165), QPointF(x0 + w - 80, y0 + 165))

        # Form fields area
        field_y = y0 + 195
        row_h = 30
        
        # Name of project/work
        selected_paths = self._get_selected_projects_paths()
        proj_display_name = "Labor erection work"
        if selected_paths and len(selected_paths) == 1:
            for p in self.projects:
                if p["path"] == selected_paths[0]:
                    proj_display_name = p["name"]
                    break
        elif len(selected_paths) > 1:
            proj_display_name = f"Consolidated Labor Erection ({len(selected_paths)} Projects)"
            
        fields = [
            ("1. Name of Work / Project:", proj_display_name),
            ("2. Scope / Particulars of Work:", description or "Execution of electrical erection job"),
            ("3. Reference Award / Project ID:", project_id),
            ("4. Reference Purchase Order (PO):", f"PO No. {po_no}  Dated: {po_date}"),
            ("5. Working Site / Location:", client_addr),
            ("6. Name of Contractor / Agency:", self.profile["firm_name"] + (f"\n({self.profile.get('agency_details')})" if self.profile.get("agency_details") else "")),
            ("7. Contractor Vendor ID / Code:", vendor_id or "Not Specified"),
            ("8. Date of Commencement of Work:", comm_date),
            ("9. Date of Completion of Work:", comp_date),
            ("10. Date of Site Measurement:", meas_date),
            ("11. Measurement Recorded By:", self.meas_taken_by_input.text().strip() or "Sub-Assistant Engineer"),
        ]
        
        for i, (label, val) in enumerate(fields):
            # Restore pen to black for text
            painter.setPen(Qt.GlobalColor.black)
            
            # Label
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            painter.drawText(QRectF(x0 + 20, field_y, 220, row_h - 4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            
            # Value Box
            painter.setFont(QFont("Arial", 9, QFont.Weight.Normal))
            val_rect = QRectF(x0 + 240, field_y, w - 260, row_h - 4)
            painter.drawText(val_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, val)
            
            # Draw underline for visual separation
            painter.setPen(QPen(QColor("#ccc"), 0.6))
            painter.drawLine(QPointF(x0 + 20, field_y + row_h - 2), QPointF(x0 + w - 20, field_y + row_h - 2))
            field_y += row_h

        # Signature blocks at bottom
        sig_box_w = (w - 60) / 3
        sig_box_h = 75
        sig_y = h + margin - 90
        
        def _draw_sig_box(x, title, subtitle):
            painter.save()
            painter.setPen(QPen(QColor("#666"), 0.8))
            painter.drawRect(QRectF(x, sig_y, sig_box_w, sig_box_h))
            
            # Title
            painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
            painter.drawText(QRectF(x + 5, sig_y + 5, sig_box_w - 10, 15), Qt.AlignmentFlag.AlignCenter, title)
            
            # Line for signature
            painter.setPen(QPen(QColor("#888"), 0.6, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x + 15, sig_y + sig_box_h - 22), QPointF(x + sig_box_w - 15, sig_y + sig_box_h - 22))
            
            # Subtitle
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.setFont(QFont("Arial", 7))
            painter.drawText(QRectF(x + 5, sig_y + sig_box_h - 18, sig_box_w - 10, 15), Qt.AlignmentFlag.AlignCenter, subtitle)
            painter.restore()

        _draw_sig_box(x0 + 10, "AGENCY ACCEPTING MEASUREMENT", "Signature of Contractor / Agency")
        _draw_sig_box(x0 + 20 + sig_box_w, "RECORDED & MEASURED BY", "Sub-Assistant Engineer (SAE)")
        _draw_sig_box(x0 + 30 + 2 * sig_box_w, "CHECKED & CERTIFIED BY", "Assistant Engineer (AE) / SM")

    def _draw_abstract_landscape_page(self, painter, bom_items,
                                     invoice_no, invoice_date, project_id, po_no, po_date,
                                     meas_date,
                                     x0, y0, w, h, margin, font_title, font_h2,
                                     font_body, font_body_bold, font_small):
        # 1. Header (Centered)
        painter.setFont(font_h2)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0, y0, w, 18), Qt.AlignmentFlag.AlignCenter, "ABSTRACT OF LABOR ERECTION BILL (VALUATION & RECORD OF QUANTITIES)")
        
        painter.setFont(font_body)
        painter.drawText(QRectF(x0, y0 + 20, w, 14), Qt.AlignmentFlag.AlignCenter, 
                         f"PO No: {po_no} | Date: {po_date} | Project ID: {project_id} | Measurement Date: {meas_date}")
        
        # Separator line
        painter.setPen(QPen(QColor("#333"), 1.0))
        painter.drawLine(QPointF(x0, y0 + 38), QPointF(x0 + w, y0 + 38))
        
        # Get prior bills for this project_id to calculate cumulative quantities & amounts
        prior_bills = []
        try:
            all_bills = _dbg.get_bills()
            # Sort all bills chronologically by invoice_date or ID to establish sequence
            all_bills_sorted = sorted(all_bills, key=lambda b: (b.get("invoice_date", ""), b.get("id", 0)))
            
            # Find the position of the current bill
            current_index = -1
            for idx, b in enumerate(all_bills_sorted):
                if b["invoice_no"] == invoice_no:
                    current_index = idx
                    break
                    
            if current_index != -1:
                # Prior bills are all bills before the current index for this project
                prior_bills = [b for b in all_bills_sorted[:current_index] if str(b.get("project_id", "")).strip().lower() == str(project_id).strip().lower()]
            else:
                # If current bill is not yet saved, all bills for this project are prior bills
                prior_bills = [b for b in all_bills_sorted if str(b.get("project_id", "")).strip().lower() == str(project_id).strip().lower()]
        except Exception as e:
            print(f"[Billing] Error fetching prior bills: {e}")
            
        prior_qtys = {}
        prior_amts = {}
        for pb in prior_bills:
            for p_item in pb.get("items", []):
                name = p_item.get("name")
                if name:
                    qty = p_item.get("act_qty", p_item.get("qty", 0.0))
                    amt = p_item.get("act_amt", p_item.get("amt", 0.0))
                    prior_qtys[name] = prior_qtys.get(name, 0.0) + qty
                    prior_amts[name] = prior_amts.get(name, 0.0) + amt

        lab_items = [x for x in bom_items if x["type"] == "Labor"]

        # Dynamic description width calculation
        painter.setFont(font_body)
        metrics = painter.fontMetrics()
        max_desc_w = 120  # minimum description column width
        for item in lab_items:
            text_w = metrics.horizontalAdvance(str(item["name"]))
            if text_w > max_desc_w:
                max_desc_w = text_w
                
        desc_w = max_desc_w + 12
        # Ensure table fits on page
        desc_w = min(w - 510, desc_w)
        table_w = desc_w + 510
        
        # Center table horizontally
        t_x0 = x0 + (w - table_w) / 2
        
        table_y = y0 + 48
        header_h = 36
        row_h = 18
        
        # Table header background
        painter.setBrush(QBrush(QColor("#f2f2f2")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(t_x0, table_y, table_w, header_h))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        cx = t_x0
        
        # 1. Sl (spans 2 rows)
        painter.drawText(QRectF(cx, table_y, 30, header_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Sl")
        cx += 30
        
        # 2. Description (spans 2 rows)
        painter.drawText(QRectF(cx, table_y, desc_w, header_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Labour Erection Description")
        cx += desc_w
        
        # 3. Quantity Section (spans 1 row, covers 3 cols)
        qty_x = cx
        painter.drawText(QRectF(cx, table_y, 150, row_h), Qt.AlignmentFlag.AlignCenter, "Quantity")
        # Row 2 for Qty
        painter.setFont(font_small)
        painter.drawText(QRectF(cx, table_y + row_h, 50, row_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "This Bill\n(A)")
        painter.drawText(QRectF(cx + 50, table_y + row_h, 50, row_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Prior\n(b)")
        painter.drawText(QRectF(cx + 100, table_y + row_h, 50, row_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Upto\n(c=a+b)")
        cx += 150
        
        # 4. Unit (spans 2 rows)
        painter.setFont(font_body_bold)
        painter.drawText(QRectF(cx, table_y, 40, header_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Unit")
        cx += 40
        
        # 5. Rate (spans 2 rows)
        painter.drawText(QRectF(cx, table_y, 55, header_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Rate\n(Rs)")
        cx += 55
        
        # 6. Actual Rate (spans 2 rows)
        painter.drawText(QRectF(cx, table_y, 55, header_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Actual\nRate")
        cx += 55
        
        # 7. Amount Section (spans 1 row, covers 3 cols)
        amt_x = cx
        painter.drawText(QRectF(cx, table_y, 180, row_h), Qt.AlignmentFlag.AlignCenter, "Amount")
        # Row 2 for Amt
        painter.setFont(font_small)
        painter.drawText(QRectF(cx, table_y + row_h, 60, row_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "This Bill\n(d)")
        painter.drawText(QRectF(cx + 60, table_y + row_h, 60, row_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Prior\n(e)")
        painter.drawText(QRectF(cx + 120, table_y + row_h, 60, row_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Upto\n(f=d+e)")
        
        cy = table_y + header_h
        sl = 1
        
        for item in lab_items:
            # We need to leave space for summary rows (4 rows * 18px = 72px) and signatures (70px)
            if cy > h + margin - 150:
                painter.setFont(font_body_bold)
                painter.drawText(QRectF(t_x0, cy, table_w, row_h), Qt.AlignmentFlag.AlignCenter, "... Continued on Next Page ...")
                cy += row_h
                break
                
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body)
            
            cx = t_x0
            # Sl
            painter.drawText(QRectF(cx, cy, 30, row_h), Qt.AlignmentFlag.AlignCenter, str(sl))
            cx += 30
            
            # Desc
            desc_text = str(item["name"])
            metrics = painter.fontMetrics()
            elided_desc = metrics.elidedText(desc_text, Qt.TextElideMode.ElideRight, int(desc_w - 6))
            painter.drawText(QRectF(cx + 4, cy, desc_w - 8, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_desc)
            cx += desc_w
            
            # Qty: This Bill, Prior, Upto
            qty_this = item.get("act_qty", item.get("qty", 0.0))
            qty_prior = prior_qtys.get(item["name"], 0.0)
            qty_cum = qty_this + qty_prior
            
            painter.drawText(QRectF(cx + 2, cy, 46, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{qty_this:,.3f}")
            painter.drawText(QRectF(cx + 50 + 2, cy, 46, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{qty_prior:,.3f}")
            painter.drawText(QRectF(cx + 100 + 2, cy, 46, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{qty_cum:,.3f}")
            cx += 150
            
            # Unit
            painter.drawText(QRectF(cx, cy, 40, row_h), Qt.AlignmentFlag.AlignCenter, str(item["unit"]))
            cx += 40
            
            # Rate
            painter.drawText(QRectF(cx + 2, cy, 51, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['rate']:,.2f}")
            cx += 55
            
            # Actual Rate
            painter.drawText(QRectF(cx + 2, cy, 51, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['rate']:,.2f}")
            cx += 55
            
            # Amount: This Bill, Prior, Upto
            amt_this = item.get("act_amt", item.get("amt", 0.0))
            amt_prior = prior_amts.get(item["name"], 0.0)
            amt_cum = amt_this + amt_prior
            
            painter.drawText(QRectF(cx + 2, cy, 56, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{amt_this:,.2f}")
            painter.drawText(QRectF(cx + 60 + 2, cy, 56, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{amt_prior:,.2f}")
            painter.drawText(QRectF(cx + 120 + 2, cy, 56, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{amt_cum:,.2f}")
            
            cy += row_h
            sl += 1
            
        # Draw outer table border
        painter.setPen(QPen(QColor("#000"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(t_x0, table_y, table_w, cy - table_y))
        
        # Horizontal lines for rows
        painter.drawLine(QPointF(qty_x, table_y + row_h), QPointF(qty_x + 150, table_y + row_h))
        painter.drawLine(QPointF(amt_x, table_y + row_h), QPointF(amt_x + 180, table_y + row_h))
        for r_y in range(table_y + header_h, cy + 1, row_h):
            painter.drawLine(QPointF(t_x0, r_y), QPointF(t_x0 + table_w, r_y))
            
        # Draw vertical lines for column separators
        x_lines = [
            t_x0 + 30,
            t_x0 + 30 + desc_w,
            t_x0 + 30 + desc_w + 50,
            t_x0 + 30 + desc_w + 100,
            t_x0 + 30 + desc_w + 150,
            t_x0 + 30 + desc_w + 150 + 40,
            t_x0 + 30 + desc_w + 150 + 40 + 55,
            t_x0 + 30 + desc_w + 150 + 40 + 55 + 55,
            t_x0 + 30 + desc_w + 150 + 40 + 55 + 55 + 60,
            t_x0 + 30 + desc_w + 150 + 40 + 55 + 55 + 120
        ]
        for lx in x_lines:
            if lx in [t_x0 + 30 + desc_w + 50, t_x0 + 30 + desc_w + 100, t_x0 + 30 + desc_w + 150 + 40 + 55 + 55 + 60, t_x0 + 30 + desc_w + 150 + 40 + 55 + 55 + 120]:
                painter.drawLine(QPointF(lx, table_y + row_h), QPointF(lx, cy))
            else:
                painter.drawLine(QPointF(lx, table_y), QPointF(lx, cy))
                
        # Draw summary rows
        def _draw_summary_row_l(label, val_this, val_prior, val_cum, bold=False, bg=None):
            nonlocal cy
            painter.save()
            if bg:
                painter.setBrush(QBrush(bg))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(t_x0, cy, table_w, row_h))
            painter.setPen(QPen(QColor("#000"), 1.0))
            painter.drawRect(QRectF(t_x0, cy, table_w, row_h))
            
            # Split summary row matching the Amount columns
            painter.drawLine(QPointF(t_x0 + table_w - 180, cy), QPointF(t_x0 + table_w - 180, cy + row_h))
            painter.drawLine(QPointF(t_x0 + table_w - 120, cy), QPointF(t_x0 + table_w - 120, cy + row_h))
            painter.drawLine(QPointF(t_x0 + table_w - 60, cy), QPointF(t_x0 + table_w - 60, cy + row_h))
            
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body_bold if bold else font_body)
            painter.drawText(QRectF(t_x0 + 10, cy, table_w - 190, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            
            painter.drawText(QRectF(t_x0 + table_w - 180 + 2, cy, 56, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{val_this:,.2f}")
            painter.drawText(QRectF(t_x0 + table_w - 120 + 2, cy, 56, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{val_prior:,.2f}")
            painter.drawText(QRectF(t_x0 + table_w - 60 + 2, cy, 56, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{val_cum:,.2f}")
            painter.restore()
            cy += row_h
            
        tot_this = sum(x.get("act_amt", x.get("amt", 0.0)) for x in lab_items)
        tot_prior = sum(prior_amts.get(x["name"], 0.0) for x in lab_items)
        tot_cum = tot_this + tot_prior
        
        _draw_summary_row_l("TOTAL LABOR ERECTION COST (A)", tot_this, tot_prior, tot_cum, bold=True, bg=QColor("#f0f7ff"))
        
        cgst_this = tot_this * 0.09
        cgst_prior = tot_prior * 0.09
        cgst_cum = cgst_this + cgst_prior
        _draw_summary_row_l("Add: CGST @ 9% on Labor charges", cgst_this, cgst_prior, cgst_cum)
        
        sgst_this = tot_this * 0.09
        sgst_prior = tot_prior * 0.09
        sgst_cum = sgst_this + sgst_prior
        _draw_summary_row_l("Add: SGST @ 9% on Labor charges", sgst_this, sgst_prior, sgst_cum)
        
        grand_this = tot_this + cgst_this + sgst_this
        grand_prior = tot_prior + cgst_prior + sgst_prior
        grand_cum = tot_cum + cgst_cum + sgst_cum
        _draw_summary_row_l("GRAND TOTAL (BILLED LABOR VALUE)", grand_this, grand_prior, grand_cum, bold=True, bg=QColor("#d4edda"))
        
        # Signature boxes at the bottom of landscape sheet
        sig_box_w = (table_w - 60) / 3
        sig_box_h = 55
        sig_y = h + margin - 65
        
        def _draw_sig_box_landscape(x, title, subtitle):
            painter.save()
            painter.setPen(QPen(QColor("#666"), 0.8))
            painter.drawRect(QRectF(x, sig_y, sig_box_w, sig_box_h))
            
            # Title
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(x + 5, sig_y + 5, sig_box_w - 10, 15), Qt.AlignmentFlag.AlignCenter, title)
            
            # Line for signature
            painter.setPen(QPen(QColor("#888"), 0.6, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x + 15, sig_y + sig_box_h - 20), QPointF(x + sig_box_w - 15, sig_y + sig_box_h - 20))
            
            # Subtitle
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(QRectF(x + 5, sig_y + sig_box_h - 16, sig_box_w - 10, 15), Qt.AlignmentFlag.AlignCenter, subtitle)
            painter.restore()
            
        # Only Agency signature on abstract
        _draw_sig_box_landscape(t_x0 + (table_w - sig_box_w) / 2, "AGENCY ACCEPTING MEASUREMENT", "Signature of Contractor / Agency")

    def _draw_smb_billing_page(self, *args, **kwargs):
        return

    def _draw_completion_certificate_page(self, painter, client_name, client_addr,
                                          invoice_no, invoice_date, project_id, po_no, po_date,
                                          comm_date, comp_date,
                                          x0, y0, w, h, margin, font_title, font_h2,
                                          font_body, font_body_bold, font_small):
        # Draw border
        painter.save()
        painter.setPen(QPen(QColor("#000"), 1.5))
        painter.drawRect(QRectF(x0 - 10, y0 - 10, w + 20, h + 20))
        painter.restore()

        # Header (Firm Details)
        painter.setFont(font_title)
        painter.drawText(QRectF(x0, y0 + 10, w, 24), Qt.AlignmentFlag.AlignCenter, self.profile["firm_name"])
        painter.setFont(font_body)
        painter.drawText(QRectF(x0, y0 + 35, w, 14), Qt.AlignmentFlag.AlignCenter, f"Address: {self.profile['address']}")
        painter.drawText(QRectF(x0, y0 + 49, w, 14), Qt.AlignmentFlag.AlignCenter, f"GSTIN: {self.profile['gstin']}")

        painter.setPen(QPen(QColor("#333"), 1.2))
        painter.drawLine(QPointF(x0, y0 + 68), QPointF(x0 + w, y0 + 68))

        # Title
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(x0, y0 + 85, w, 22), Qt.AlignmentFlag.AlignCenter, "PROJECT COMPLETION & COMPLIANCE CERTIFICATE")

        # Project Info Block
        cy = y0 + 120
        painter.setFont(font_body_bold)
        painter.drawText(QRectF(x0, cy, w, 14), Qt.AlignmentFlag.AlignLeft, f"Project ID: {project_id}")
        painter.drawText(QRectF(x0 + w/2, cy, w/2, 14), Qt.AlignmentFlag.AlignLeft, f"Billing Date: {invoice_date}")
        cy += 16
        painter.drawText(QRectF(x0, cy, w, 14), Qt.AlignmentFlag.AlignLeft, f"PO Number: {po_no}")
        painter.drawText(QRectF(x0 + w/2, cy, w/2, 14), Qt.AlignmentFlag.AlignLeft, f"PO Date: {po_date}")
        cy += 16
        painter.drawText(QRectF(x0, cy, w, 14), Qt.AlignmentFlag.AlignLeft, f"Commencement: {comm_date}")
        painter.drawText(QRectF(x0 + w/2, cy, w/2, 14), Qt.AlignmentFlag.AlignLeft, f"Completion: {comp_date}")
        cy += 24

        # Intro text
        painter.setFont(font_body)
        proj_name = self.projects[0]['name'] if self.projects else 'Erection job'
        intro = (
            f"This is to certify that the contract work of '{proj_name}' awarded to us "
            f"vide the above-mentioned Purchase Order has been executed successfully. In connection "
            f"with the work completed and the billing thereof, we hereby declare and certify that:"
        )
        painter.drawText(QRectF(x0, cy, w, 40), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, intro)
        cy += 45

        # 10 Points
        points = [
            "1. The work has been executed in all respects as per the rules, department guidelines, approved drawings, and technical specifications.",
            "2. The execution of the work has been completed within the stipulated timeframe without delay.",
            "3. The bill claimed for this work has not been claimed/submitted before. This is the first and final bill for the executed work.",
            "4. The claimed quantities are accurate as per actual execution on site and have been verified and measured by the department.",
            f"5. The payment against the billed erection charges may kindly be released in favour of the agency (M/S {self.profile['firm_name']}).",
            "6. All materials issued by the division have been fully and properly utilised in the work as per the Material Reconciliation statement.",
            "7. All items and quantities claimed in the bill are strictly as per actual site installations and measurements.",
            "8. The work was executed under the direction and supervision of the department's Site Engineer.",
            "9. No departmental store materials have been wasted, lost, or unaccounted for during execution of the contract.",
            "10. We accept full responsibility for the stability, safety, and quality of work executed at the site."
        ]

        painter.setFont(font_body)
        for pt in points:
            rect = QRectF(x0 + 15, cy, w - 30, 28)
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, pt)
            cy += 28

        # Footer spacing
        cy += 5

        # Signatures
        sig_y = h + margin - 75
        painter.setPen(QPen(QColor("#ccc"), 0.5))
        painter.drawLine(QPointF(x0, sig_y - 15), QPointF(x0 + w, sig_y - 15))

        # Agency Sig
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 10, sig_y, 250, 16), Qt.AlignmentFlag.AlignLeft, "Signature of Contractor / Agency")
        painter.setFont(font_body)
        painter.drawText(QRectF(x0 + 10, sig_y + 18, 250, 16), Qt.AlignmentFlag.AlignLeft, f"M/S: {self.profile['firm_name']}")

    def _draw_consumption_report_page(self, painter, bom_items,
                                        invoice_no, invoice_date, project_id, po_no, po_date,
                                        x0, y0, w, h, margin, font_title, font_h2,
                                        font_body, font_body_bold, font_small):
        # Header
        painter.setFont(font_h2)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0, y0, w, 18), Qt.AlignmentFlag.AlignCenter, "MATERIAL CONSUMPTION & COMPLETION REPORT")
        
        painter.setFont(font_body)
        painter.drawText(QRectF(x0, y0 + 20, w, 14), Qt.AlignmentFlag.AlignCenter, f"PO No: {po_no} | Date: {po_date} | Project ID: {project_id}")
        
        # Columns: Sl (25), Code (80), Description (Stretch), Unit (40), Est Qty (70), Act Qty (70), Dev (65)
        col_w = [25, 80, w - 25 - 80 - 45 - 70 - 70 - 65, 45, 70, 70, 65]
        col_lbl = ["Sl", "Item Code", "Material Description", "Unit", "Est Qty", "Act Qty", "Deviation"]
        
        table_y = y0 + 45
        row_h = 18
        
        # Header Box
        painter.setBrush(QBrush(QColor("#f2f2f2")))
        painter.setPen(QPen(QColor("#ccc"), 0.8))
        painter.drawRect(QRectF(x0, table_y, w, row_h))
        
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        cx = x0
        for i, lbl in enumerate(col_lbl):
            painter.drawText(QRectF(cx, table_y, col_w[i], row_h), Qt.AlignmentFlag.AlignCenter, lbl)
            cx += col_w[i]
            
        cy = table_y + row_h
        sl = 1
        
        mat_items = [x for x in bom_items if x["type"] == "Material"]
        
        for item in mat_items:
            if cy > h + margin - 70:
                painter.drawText(QRectF(x0, cy, w, row_h), Qt.AlignmentFlag.AlignLeft, "... Continued on Next Page ...")
                break
                
            painter.setPen(QPen(QColor("#e0e0e0"), 0.5))
            painter.drawLine(QPointF(x0, cy + row_h), QPointF(x0 + w, cy + row_h))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body)
            
            cx = x0
            # Sl
            painter.drawText(QRectF(cx, cy, col_w[0], row_h), Qt.AlignmentFlag.AlignCenter, str(sl))
            cx += col_w[0]
            # Code
            painter.drawText(QRectF(cx + 2, cy, col_w[1] - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(item["code"]))
            cx += col_w[1]
            # Desc
            desc_text = str(item["name"])
            metrics = painter.fontMetrics()
            elided_desc = metrics.elidedText(desc_text, Qt.TextElideMode.ElideRight, int(col_w[2] - 6))
            painter.drawText(QRectF(cx + 2, cy, col_w[2] - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_desc)
            cx += col_w[2]
            # Unit
            painter.drawText(QRectF(cx, cy, col_w[3], row_h), Qt.AlignmentFlag.AlignCenter, str(item["unit"]))
            cx += col_w[3]
            # Est Qty
            est_str = f"{item['qty']:.3f}"
            painter.drawText(QRectF(cx - 2, cy, col_w[4], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, est_str)
            cx += col_w[4]
            # Act Qty
            act_str = f"{item['act_qty']:.3f}"
            painter.drawText(QRectF(cx - 2, cy, col_w[5], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, act_str)
            cx += col_w[5]
            # Dev
            dev = item["act_qty"] - item["qty"]
            dev_str = f"{dev:+.3f}" if dev != 0 else "0.000"
            painter.drawText(QRectF(cx - 2, cy, col_w[6], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, dev_str)
            
            cy += row_h
            sl += 1
            
        # Signature verification block
        sig_y = h + margin - 50
        painter.setFont(font_small)
        painter.drawText(QRectF(x0, sig_y - 20, w, 15), Qt.AlignmentFlag.AlignCenter, "Verified that materials issued by office have been consumed at site as per actuals.")
        
        painter.setFont(font_body_bold)
        painter.drawText(QRectF(x0 + 10, sig_y, 200, 16), Qt.AlignmentFlag.AlignLeft, "Contractor Signature")
        painter.drawText(QRectF(x0 + w - 210, sig_y, 200, 16), Qt.AlignmentFlag.AlignRight, "Site Engineer Signature")

    def _draw_measurement_sheet_page(self, printer, painter, bom_items, type_filter,
                                    invoice_no, invoice_date, project_id, po_no, po_date,
                                    x0, y0, w, h, margin, font_title, font_h2,
                                    font_body, font_body_bold, font_small):
        # Columns: Sl (25), Description (Stretch), No (30), L (40), B (40), D/H (40), PO Qty (60), Measured Qty (70), Unit (40)
        col_w = [25, w - 25 - 30 - 40 - 40 - 40 - 60 - 70 - 40, 30, 40, 40, 40, 60, 70, 40]
        
        desc_hdr = "Material Description" if type_filter == "Material" else "Labour Work Description"
        col_lbl = ["Sl", desc_hdr, "No", "L", "B", "D/H", "PO Qty", "Measured Qty", "Unit"]
        
        table_y = y0 + 45
        row_h = 18
        
        page_num = 1
        
        def draw_page_headers(p_num):
            painter.setFont(font_h2)
            painter.setPen(Qt.GlobalColor.black)
            title_text = "DETAILED MEASUREMENT SHEET (MATERIALS)" if type_filter == "Material" else "DETAILED MEASUREMENT & ERECTION SHEET (LABOR)"
            painter.drawText(QRectF(x0, y0, w, 18), Qt.AlignmentFlag.AlignLeft, title_text)
            
            painter.setFont(font_body)
            painter.drawText(QRectF(x0, y0 + 20, w, 14), Qt.AlignmentFlag.AlignLeft, f"PO No: {po_no} | Project ID: {project_id}")
            
            # Table header
            painter.setBrush(QBrush(QColor("#f2f2f2")))
            painter.setPen(QPen(QColor("#ccc"), 0.8))
            painter.drawRect(QRectF(x0, table_y, w, row_h))
            
            painter.setFont(font_body_bold)
            painter.setPen(Qt.GlobalColor.black)
            cx = x0
            for i, lbl in enumerate(col_lbl):
                painter.drawText(QRectF(cx, table_y, col_w[i], row_h), Qt.AlignmentFlag.AlignCenter, lbl)
                cx += col_w[i]
                
            # Draw page number in footer
            painter.setFont(font_small)
            footer_lbl = f"Material Measurement Page {p_num}" if type_filter == "Material" else f"Labor Measurement Page {p_num}"
            painter.drawText(QRectF(x0, h + margin - 15, w, 12), Qt.AlignmentFlag.AlignCenter, footer_lbl)
            
        draw_page_headers(page_num)
        
        cy = table_y + row_h
        sl = 1
        
        filtered_items = [x for x in bom_items if x["type"] == type_filter]
        
        for item in filtered_items:
            # Check for page overflow
            if cy > h + margin - 75:
                # Draw table border for current page
                painter.setPen(QPen(QColor("#ccc"), 0.8))
                painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
                
                printer.newPage()
                page_num += 1
                draw_page_headers(page_num)
                cy = table_y + row_h
                
            painter.setPen(QPen(QColor("#e0e0e0"), 0.5))
            painter.drawLine(QPointF(x0, cy + row_h), QPointF(x0 + w, cy + row_h))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body)
            
            cx = x0
            # Sl
            painter.drawText(QRectF(cx, cy, col_w[0], row_h), Qt.AlignmentFlag.AlignCenter, str(sl))
            cx += col_w[0]
            
            # Desc
            desc_text = str(item["name"])
            metrics = painter.fontMetrics()
            elided_desc = metrics.elidedText(desc_text, Qt.TextElideMode.ElideRight, int(col_w[1] - 6))
            painter.drawText(QRectF(cx + 2, cy, col_w[1] - 4, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_desc)
            cx += col_w[1]
            
            # PO (estimated) and measured (actual) quantities
            po_qty = item["qty"]
            act_qty = item.get("act_qty", item["qty"])
            
            # No
            painter.drawText(QRectF(cx, cy, col_w[2], row_h), Qt.AlignmentFlag.AlignCenter, "1")
            cx += col_w[2]
            
            # L, B, D/H
            if item["unit"] == "MTR":
                l_str = f"{act_qty:.2f}"
                b_str = "1.00"
                h_str = "1.00"
            else:
                l_str = "1.00"
                b_str = "1.00"
                h_str = "1.00"
                
            painter.drawText(QRectF(cx, cy, col_w[3], row_h), Qt.AlignmentFlag.AlignCenter, l_str)
            cx += col_w[3]
            painter.drawText(QRectF(cx, cy, col_w[4], row_h), Qt.AlignmentFlag.AlignCenter, b_str)
            cx += col_w[4]
            painter.drawText(QRectF(cx, cy, col_w[5], row_h), Qt.AlignmentFlag.AlignCenter, h_str)
            cx += col_w[5]
            
            # PO Qty
            painter.drawText(QRectF(cx - 2, cy, col_w[6], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{po_qty:.3f}")
            cx += col_w[6]
            
            # Measured Qty
            painter.drawText(QRectF(cx - 2, cy, col_w[7], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{act_qty:.3f}")
            cx += col_w[7]
            
            # Unit
            painter.drawText(QRectF(cx, cy, col_w[8], row_h), Qt.AlignmentFlag.AlignCenter, str(item["unit"]))
            
            cy += row_h
            sl += 1
            
        # Draw bottom border of table
        painter.setPen(QPen(QColor("#ccc"), 0.8))
        painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
        
        # Check if signature fits on this page, otherwise page break
        if cy > h + margin - 85:
            printer.newPage()
            page_num += 1
            draw_page_headers(page_num)
            cy = table_y + row_h
            
        # Signature block
        sig_y = h + margin - 75
        painter.setPen(QPen(QColor("#ccc"), 0.5))
        painter.drawLine(QPointF(x0, sig_y - 15), QPointF(x0 + w, sig_y - 15))
        
        # Agency Sig
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 10, sig_y, 250, 16), Qt.AlignmentFlag.AlignLeft, "Signature of Contractor / Agency")
        painter.setFont(font_body)
        painter.drawText(QRectF(x0 + 10, sig_y + 18, 250, 16), Qt.AlignmentFlag.AlignLeft, f"M/S: {self.profile['firm_name']}")
        
        # Meas Taken By & Certified By Sigs on right
        meas_by = self.meas_taken_by_input.text().strip() or "Sub-Assistant Engineer"
        cert_by = self.certified_by_input.text().strip() or "Assistant Engineer"
        
        painter.setFont(font_body_bold)
        painter.drawText(QRectF(x0 + w - 260, sig_y, 250, 16), Qt.AlignmentFlag.AlignRight, "Verified & Certified By:")
        painter.setFont(font_body)
        painter.drawText(QRectF(x0 + w - 260, sig_y + 18, 250, 16), Qt.AlignmentFlag.AlignRight, f"Measurement Taken By: {meas_by}")
        painter.drawText(QRectF(x0 + w - 260, sig_y + 32, 250, 16), Qt.AlignmentFlag.AlignRight, f"Certified By: {cert_by}")

    def _draw_estimate_page(self, printer, painter, bom_items,
                            x0, y0, w, h, margin, font_title, font_h2,
                            font_body, font_body_bold, font_small):
        # Table geometry
        # Columns: Sl (30), Description (Stretch), Type (70), Unit (40), Rate (70), Qty (70), Amount (80)
        col_w = [30, w - 30 - 70 - 40 - 70 - 70 - 80, 70, 40, 70, 70, 80]
        col_lbl = ["Sl", "Item Description", "Type", "Unit", "Rate (Rs)", "Quantity", "Amount (Rs)"]
        
        table_y = y0 + 55
        row_h = 20
        
        page_num = 1
        
        def draw_page_headers(p_num):
            painter.setFont(font_title)
            painter.setPen(Qt.GlobalColor.black)
            # Center header
            painter.drawText(QRectF(x0, y0, w, 24), Qt.AlignmentFlag.AlignCenter, "PROJECT ESTIMATE & BILL OF QUANTITIES")
            painter.setFont(font_body)
            painter.drawText(QRectF(x0, y0 + 26, w, 14), Qt.AlignmentFlag.AlignCenter, 
                             f"Project ID: {self.project_id_input.text().strip()} | PO No: {self.po_no_input.text().strip()}")
            
            painter.setPen(QPen(QColor("#333"), 1.0))
            painter.drawLine(QPointF(x0, y0 + 44), QPointF(x0 + w, y0 + 44))
            
            # Header Box
            painter.setBrush(QBrush(QColor("#f2f2f2")))
            painter.setPen(QPen(QColor("#ccc"), 0.8))
            painter.drawRect(QRectF(x0, table_y, w, row_h))
            
            painter.setFont(font_body_bold)
            painter.setPen(Qt.GlobalColor.black)
            cx = x0
            for i, lbl in enumerate(col_lbl):
                painter.drawText(QRectF(cx, table_y, col_w[i], row_h), Qt.AlignmentFlag.AlignCenter, lbl)
                cx += col_w[i]
                
            # Draw page number in footer
            painter.setFont(font_small)
            painter.drawText(QRectF(x0, h + margin - 15, w, 12), Qt.AlignmentFlag.AlignCenter, f"Estimate Page {p_num}")
            
        draw_page_headers(page_num)
        
        cy = table_y + row_h

        def check_overflow(height_needed=20):
            nonlocal cy, page_num
            if cy + height_needed > h + margin - 40:
                # Draw table border for current page
                painter.setPen(QPen(QColor("#ccc"), 0.8))
                painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
                
                printer.newPage()
                page_num += 1
                draw_page_headers(page_num)
                cy = table_y + row_h

        def draw_summary_row(label, val, bold=False, bg=None):
            nonlocal cy
            check_overflow(row_h)
            
            painter.save()
            if bg:
                painter.setBrush(QBrush(bg))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(x0, cy, w, row_h))
            painter.setPen(QPen(QColor("#ccc"), 0.8))
            painter.drawRect(QRectF(x0, cy, w, row_h))
            
            # Split summary row matching the Amount column
            painter.drawLine(QPointF(x0 + w - col_w[-1], cy), QPointF(x0 + w - col_w[-1], cy + row_h))
            
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body_bold if bold else font_body)
            painter.drawText(QRectF(x0 + 10, cy, w - col_w[-1] - 20, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            painter.drawText(QRectF(x0 + w - col_w[-1] - 4, cy, col_w[-1], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{val:,.2f}")
            painter.restore()
            cy += row_h

        # Calculate escalations just like app.py
        from core import defaults
        now = datetime.now()
        fy_start = now.year if now.month >= 4 else now.year - 1
        base_yr_str = defaults.current.get("rate_chart_base_year", "2026")
        try:
            base_yr = int(base_yr_str)
        except ValueError:
            base_yr = 2026

        # Calculate mat_base and lab_base
        mat_items = [x for x in bom_items if x["type"] == "Material"]
        lab_items = [x for x in bom_items if x["type"] == "Labor"]

        mat_base = sum(item.get("act_amt", item["amt"]) for item in mat_items)
        lab_base = sum(item.get("act_amt", item["amt"]) for item in lab_items)
        
        escalations = []
        cur = mat_base
        for yr in range(base_yr + 1, fy_start + 1):
            esc = cur * 0.05
            escalations.append((f"Add: Escalation @ 5% for FY {str(yr)[-2:]}-{str(yr+1)[-2:]}", esc))
            cur += esc

        # Sundries
        sun_amt = cur * 0.05
        
        # TOTAL MATERIAL COST (A)
        total_mat_cost = cur + sun_amt

        # TOTAL LABOR COST (B)
        total_lab_cost = lab_base

        # Supervision (C)
        sup_rate = getattr(self, "supervision_rate", 0.10)
        sup_pct = int(sup_rate * 100)
        sup_amt = (total_mat_cost + total_lab_cost) * sup_rate

        # GST on Labor only
        gst_amt = total_lab_cost * 0.18

        # Sub-total
        sub_total = total_mat_cost + total_lab_cost + sup_amt + gst_amt

        # Cess
        cess_amt = (total_mat_cost + total_lab_cost + sup_amt) * 0.01

        # GRAND TOTAL
        grand_total = sub_total + cess_amt

        # Helper to draw item row
        def draw_item_row(sl, item):
            nonlocal cy
            check_overflow(row_h)
            # Draw row separator
            painter.setPen(QPen(QColor("#e0e0e0"), 0.5))
            painter.drawLine(QPointF(x0, cy + row_h), QPointF(x0 + w, cy + row_h))
            
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(font_body)
            
            cx = x0
            # Sl
            painter.drawText(QRectF(cx, cy, col_w[0], row_h), Qt.AlignmentFlag.AlignCenter, str(sl))
            cx += col_w[0]
            
            # Desc
            desc_text = str(item["name"])
            metrics = painter.fontMetrics()
            elided_desc = metrics.elidedText(desc_text, Qt.TextElideMode.ElideRight, int(col_w[1] - 8))
            painter.drawText(QRectF(cx + 4, cy, col_w[1] - 8, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_desc)
            cx += col_w[1]
            
            # Type
            painter.drawText(QRectF(cx, cy, col_w[2], row_h), Qt.AlignmentFlag.AlignCenter, str(item["type"]))
            cx += col_w[2]
            
            # Unit
            painter.drawText(QRectF(cx, cy, col_w[3], row_h), Qt.AlignmentFlag.AlignCenter, str(item["unit"]))
            cx += col_w[3]
            
            # Rate
            painter.drawText(QRectF(cx - 4, cy, col_w[4], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{item['rate']:,.2f}")
            cx += col_w[4]
            
            # Qty
            qty = item.get("act_qty", item["qty"])
            painter.drawText(QRectF(cx - 4, cy, col_w[5], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{qty:,.3f}")
            cx += col_w[5]
            
            # Amt
            amt = item.get("act_amt", item["amt"])
            painter.drawText(QRectF(cx - 4, cy, col_w[6], row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{amt:,.2f}")
            
            cy += row_h

        # --- SECTION A: MATERIALS ---
        check_overflow(22)
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 5, cy, w - 10, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "A. MATERIALS")
        cy += 20
        
        sl = 1
        for item in mat_items:
            draw_item_row(sl, item)
            sl += 1
            
        # Draw bottom border of materials table
        painter.setPen(QPen(QColor("#ccc"), 0.8))
        painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
            
        # Write Materials summary rows
        draw_summary_row("Material Base Total", mat_base, bold=True)
        for label, esc_val in escalations:
            draw_summary_row(label, esc_val)
        draw_summary_row("Add: Sundries @ 5%", sun_amt)
        draw_summary_row("TOTAL MATERIAL COST (A)", total_mat_cost, bold=True, bg=QColor("#f0f7ff"))
        
        # Spacer
        check_overflow(15)
        cy += 10
        
        # --- SECTION B: ERECTION / LABOR ---
        check_overflow(22)
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 5, cy, w - 10, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "B. ERECTION / LABOR")
        cy += 20
        
        sl = 1
        for item in lab_items:
            draw_item_row(sl, item)
            sl += 1
            
        # Draw bottom border of labor table
        painter.setPen(QPen(QColor("#ccc"), 0.8))
        painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
            
        draw_summary_row("TOTAL LABOR COST (B)", total_lab_cost, bold=True, bg=QColor("#f0f7ff"))
        
        # Spacer
        check_overflow(15)
        cy += 10
        
        # --- SECTION C: OVERHEADS & TAXES ---
        check_overflow(22)
        painter.setFont(font_body_bold)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(QRectF(x0 + 5, cy, w - 10, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "C. OVERHEADS & TAXES")
        cy += 20
        
        draw_summary_row(f"Supervision @ {sup_pct}% on (A+B)", sup_amt)
        draw_summary_row("GST @ 18% on Labour only", gst_amt)
        draw_summary_row("Sub-Total", sub_total, bold=True)
        draw_summary_row("Add: Cess @ 1% on (Mat+Lab+Sup)", cess_amt)
        draw_summary_row("GRAND TOTAL", grand_total, bold=True, bg=QColor("#d4edda"))
