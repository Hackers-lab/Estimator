"""
ui/dialogs/user_profile.py
==========================
Dialog to manage and switch local User Profiles (Name, Firm Name, Address, GSTIN, Signature).
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QMessageBox, QFileDialog,
    QFormLayout, QDialogButtonBox, QListWidgetItem, QFrame, QSplitter,
    QTabWidget, QTextEdit, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap

from core import db_gateway as _dbg

class ClientEditDialog(QDialog):
    """Sub-dialog to create or edit a client billing destination."""
    
    def __init__(self, name="", address="", gstin="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Client Destination Details")
        self.setMinimumWidth(380)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        
        form = QFormLayout()
        form.setSpacing(8)
        
        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("e.g. WBSEDCL Kestopur Division")
        form.addRow("Client Name:", self.name_input)
        
        self.address_input = QLineEdit(address)
        self.address_input.setPlaceholderText("e.g. Salt Lake, Sector V")
        form.addRow("Address:", self.address_input)
        
        self.gstin_input = QLineEdit(gstin)
        self.gstin_input.setPlaceholderText("GSTIN (optional)")
        form.addRow("GSTIN:", self.gstin_input)
        
        layout.addLayout(form)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
    def _on_accept(self):
        if not self.name_input.text().strip() or not self.address_input.text().strip():
            QMessageBox.warning(self, "Required Fields", "Client Name and Address are required.")
            return
        self.accept()
        
    def get_details(self) -> tuple[str, str, str]:
        return (
            self.name_input.text().strip(),
            self.address_input.text().strip(),
            self.gstin_input.text().strip()
        )


class ProfileEditDialog(QDialog):
    """Sub-dialog to create or edit a single User Profile with Tabbed configuration."""
    
    def __init__(self, profile_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Profile" if profile_data else "Create Profile")
        self.setMinimumWidth(540)
        self.setMinimumHeight(640)
        self.resize(540, 680)
        self.setModal(True)
        
        self.profile_data = dict(profile_data) if profile_data else {}
        self.destinations = []
        if "billing_to_json" in self.profile_data:
            import json
            try:
                self.destinations = json.loads(self.profile_data["billing_to_json"])
            except Exception:
                self.destinations = []
                
        self._init_ui()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Tab 1: Organization Details
        tab_org = QWidget()
        org_lay = QVBoxLayout(tab_org)
        org_lay.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_content_lay = QVBoxLayout(scroll_content)
        scroll_content_lay.setContentsMargins(8, 8, 8, 8)
        
        form_org = QFormLayout()
        form_org.setSpacing(10)
        
        self.name_input = QLineEdit(self.profile_data.get("name", ""))
        self.name_input.setPlaceholderText("e.g. Standard, Executive, Project Site A")
        form_org.addRow("Profile Name:", self.name_input)
        
        self.firm_input = QLineEdit(self.profile_data.get("firm_name", ""))
        self.firm_input.setPlaceholderText("e.g. ABC Electricals Ltd.")
        form_org.addRow("Firm Name / Name:", self.firm_input)
        
        self.address_input = QLineEdit(self.profile_data.get("address", ""))
        self.address_input.setPlaceholderText("e.g. 123 Main St, New Delhi")
        form_org.addRow("Address:", self.address_input)
        
        self.gstin_input = QLineEdit(self.profile_data.get("gstin", ""))
        self.gstin_input.setPlaceholderText("e.g. 07AAAAA1111A1Z1")
        form_org.addRow("GSTIN:", self.gstin_input)
        
        self.vendor_input = QLineEdit(self.profile_data.get("vendor_no", ""))
        self.vendor_input.setPlaceholderText("e.g. 700099 (optional)")
        form_org.addRow("Vendor Number:", self.vendor_input)
        
        self.agency_input = QTextEdit(self.profile_data.get("agency_details", ""))
        self.agency_input.setPlaceholderText("Enter licensing, certification, or agency details (optional)...")
        self.agency_input.setMaximumHeight(60)
        form_org.addRow("Agency Details:", self.agency_input)
        
        sig_w = QWidget()
        sig_l = QHBoxLayout(sig_w)
        sig_l.setContentsMargins(0, 0, 0, 0)
        sig_l.setSpacing(6)
        
        self.sig_input = QLineEdit(self.profile_data.get("signature_path", ""))
        self.sig_input.setReadOnly(True)
        self.sig_input.setPlaceholderText("Select image path...")
        sig_l.addWidget(self.sig_input, 1)
        
        self.sig_btn = QPushButton("Browse...")
        self.sig_btn.clicked.connect(self._browse_signature)
        sig_l.addWidget(self.sig_btn)
        form_org.addRow("Signature Image:", sig_w)
        
        self.preview_lbl = QLabel()
        self.preview_lbl.setStyleSheet("border: 1px solid #ccc; background: #fafafa; border-radius: 4px;")
        self.preview_lbl.setFixedSize(150, 50)
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_org.addRow("Signature Preview:", self.preview_lbl)
        self._update_preview(self.sig_input.text())
        
        logo_w = QWidget()
        logo_l = QHBoxLayout(logo_w)
        logo_l.setContentsMargins(0, 0, 0, 0)
        logo_l.setSpacing(6)
        
        self.logo_input = QLineEdit(self.profile_data.get("logo_path", ""))
        self.logo_input.setReadOnly(True)
        self.logo_input.setPlaceholderText("Select image path...")
        logo_l.addWidget(self.logo_input, 1)
        
        self.logo_btn = QPushButton("Browse...")
        self.logo_btn.clicked.connect(self._browse_logo)
        logo_l.addWidget(self.logo_btn)
        form_org.addRow("Logo Image:", logo_w)
        
        self.logo_preview_lbl = QLabel()
        self.logo_preview_lbl.setStyleSheet("border: 1px solid #ccc; background: #fafafa; border-radius: 4px;")
        self.logo_preview_lbl.setFixedSize(80, 80)
        self.logo_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_org.addRow("Logo Preview:", self.logo_preview_lbl)
        self._update_logo_preview(self.logo_input.text())
        
        scroll_content_lay.addLayout(form_org)
        scroll.setWidget(scroll_content)
        org_lay.addWidget(scroll)
        self.tabs.addTab(tab_org, "Organization Info")
        
        # Tab 2: Invoice Format Settings
        tab_inv = QWidget()
        inv_lay = QVBoxLayout(tab_inv)
        inv_lay.setContentsMargins(8, 8, 8, 8)
        
        form_inv = QFormLayout()
        form_inv.setSpacing(10)
        
        self.format_input = QLineEdit(self.profile_data.get("invoice_format", "SE/{FY}/KSD/{SEQ}"))
        self.format_input.setPlaceholderText("e.g. SE/{FY}/KSD/{SEQ}")
        form_inv.addRow("Invoice Number Format:", self.format_input)
        
        format_help = QLabel(
            "<span style='color:#555; font-size:11px;'>"
            "Placeholders:<br>"
            "<b>{FY}</b>: Financial Year (e.g. 26-27)<br>"
            "<b>{FY_FULL}</b>: Full Financial Year (e.g. 2026-2027)<br>"
            "<b>{SEQ}</b>: Next sequence number (padded to 2 digits, e.g. 01)"
            "</span>"
        )
        form_inv.addRow("", format_help)
        
        self.seq_input = QSpinBox()
        self.seq_input.setRange(1, 999999)
        self.seq_input.setValue(self.profile_data.get("next_seq", 1))
        form_inv.addRow("Next Sequence Number:", self.seq_input)
        
        inv_lay.addLayout(form_inv)
        inv_lay.addStretch()
        self.tabs.addTab(tab_inv, "Invoice Settings")
        
        # Tab 3: Billing Destinations
        tab_dest = QWidget()
        dest_lay = QHBoxLayout(tab_dest)
        dest_lay.setContentsMargins(8, 8, 8, 8)
        
        self.dest_table = QTableWidget()
        self.dest_table.setColumnCount(3)
        self.dest_table.setHorizontalHeaderLabels(["Client Name", "Address", "GSTIN"])
        self.dest_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dest_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dest_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        dest_lay.addWidget(self.dest_table, 1)
        
        btn_panel = QVBoxLayout()
        self.btn_add_dest = QPushButton("➕ Add")
        self.btn_add_dest.clicked.connect(self._add_destination)
        self.btn_edit_dest = QPushButton("✏️ Edit")
        self.btn_edit_dest.clicked.connect(self._edit_destination)
        self.btn_del_dest = QPushButton("🗑️ Remove")
        self.btn_del_dest.clicked.connect(self._delete_destination)
        
        btn_panel.addWidget(self.btn_add_dest)
        btn_panel.addWidget(self.btn_edit_dest)
        btn_panel.addWidget(self.btn_del_dest)
        btn_panel.addStretch()
        dest_lay.addLayout(btn_panel)
        
        self.tabs.addTab(tab_dest, "Billing Destinations")
        self._reload_destinations_table()
        
        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
    def _browse_signature(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Signature Image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if filename:
            self.sig_input.setText(filename)
            self._update_preview(filename)
            
    def _update_preview(self, path):
        if path and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.preview_lbl.setPixmap(pix.scaled(
                    self.preview_lbl.width() - 4,
                    self.preview_lbl.height() - 4,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                return
        self.preview_lbl.setText("No image")
        self.preview_lbl.setPixmap(QPixmap())
        
    def _browse_logo(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Logo Image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if filename:
            self.logo_input.setText(filename)
            self._update_logo_preview(filename)
            
    def _update_logo_preview(self, path):
        if path and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.logo_preview_lbl.setPixmap(pix.scaled(
                    self.logo_preview_lbl.width() - 4,
                    self.logo_preview_lbl.height() - 4,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                return
        self.logo_preview_lbl.setText("No image")
        self.logo_preview_lbl.setPixmap(QPixmap())
        
    def _reload_destinations_table(self):
        self.dest_table.setRowCount(0)
        for r, dest in enumerate(self.destinations):
            self.dest_table.insertRow(r)
            self.dest_table.setItem(r, 0, QTableWidgetItem(dest.get("name", "")))
            self.dest_table.setItem(r, 1, QTableWidgetItem(dest.get("address", "")))
            self.dest_table.setItem(r, 2, QTableWidgetItem(dest.get("gstin", "")))
            
    def _add_destination(self):
        dlg = ClientEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, addr, gstin = dlg.get_details()
            self.destinations.append({"name": name, "address": addr, "gstin": gstin})
            self._reload_destinations_table()
            
    def _edit_destination(self):
        row = self.dest_table.currentRow()
        if row < 0 or row >= len(self.destinations):
            return
        dest = self.destinations[row]
        dlg = ClientEditDialog(dest.get("name", ""), dest.get("address", ""), dest.get("gstin", ""), parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, addr, gstin = dlg.get_details()
            self.destinations[row] = {"name": name, "address": addr, "gstin": gstin}
            self._reload_destinations_table()
            
    def _delete_destination(self):
        row = self.dest_table.currentRow()
        if row < 0 or row >= len(self.destinations):
            return
        self.destinations.pop(row)
        self._reload_destinations_table()
        
    def _on_accept(self):
        name = self.name_input.text().strip()
        firm = self.firm_input.text().strip()
        addr = self.address_input.text().strip()
        gstin = self.gstin_input.text().strip()
        sig = self.sig_input.text().strip()
        
        if not name or not firm or not addr or not gstin:
            QMessageBox.warning(self, "Validation Error", "Profile Name, Firm Name, Address, and GSTIN are required.")
            return
            
        self.profile_data["name"] = name
        self.profile_data["firm_name"] = firm
        self.profile_data["address"] = addr
        self.profile_data["gstin"] = gstin
        self.profile_data["signature_path"] = sig
        self.profile_data["logo_path"] = self.logo_input.text().strip()
        
        self.profile_data["vendor_no"] = self.vendor_input.text().strip()
        self.profile_data["agency_details"] = self.agency_input.toPlainText().strip()
        self.profile_data["invoice_format"] = self.format_input.text().strip()
        self.profile_data["next_seq"] = self.seq_input.value()
        
        import json
        self.profile_data["billing_to_json"] = json.dumps(self.destinations)
        
        self.accept()

    def get_data(self) -> dict:
        return self.profile_data


class UserProfileDialog(QDialog):
    """
    Premium PyQt6 dialog to manage and activate User/Firm Profiles.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("User Profiles Manager")
        self.resize(800, 450)
        self.setMinimumSize(750, 380)
        self.setModal(True)
        
        self.profiles = []
        self._init_ui()
        self._reload_profiles()
        
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # Header banner
        header = QLabel(
            "<b>User & Firm Profiles</b><br>"
            "Set up organization credentials, GST numbers, and signatures. "
            "The active profile will personalize PDF and Excel export headers/footers automatically."
        )
        header.setStyleSheet(
            "QLabel {"
            "  background: #f0f7ff;"
            "  border: 1px solid #cce2ff;"
            "  border-radius: 6px;"
            "  padding: 10px;"
            "  color: #1a365d;"
            "}"
        )
        main_layout.addWidget(header)
        
        # Splitter for left list and right preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1)
        
        # Left Panel: List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        left_layout.addWidget(QLabel("<b>Profiles List</b>"))
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.list_widget, 1)
        
        # Left actions
        left_btn_lay = QHBoxLayout()
        self.btn_new = QPushButton("➕  New Profile")
        self.btn_new.clicked.connect(self._create_profile)
        self.btn_new.setStyleSheet("padding: 5px;")
        
        self.btn_delete = QPushButton("🗑️  Delete")
        self.btn_delete.clicked.connect(self._delete_profile)
        self.btn_delete.setStyleSheet("padding: 5px;")
        
        left_btn_lay.addWidget(self.btn_new)
        left_btn_lay.addWidget(self.btn_delete)
        left_layout.addLayout(left_btn_lay)
        splitter.addWidget(left_widget)
        
        # Right Panel: Detail view
        self.detail_widget = QFrame()
        self.detail_widget.setFrameShape(QFrame.Shape.StyledPanel)
        self.detail_widget.setStyleSheet(
            "QFrame { background: #ffffff; border-radius: 6px; border: 1px solid #e0e0e0; }"
            "QLabel { border: none; }"
        )
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setSpacing(10)
        self.detail_layout.setContentsMargins(14, 14, 14, 14)
        
        self.lbl_profile_title = QLabel("<b>Profile Details</b>")
        self.lbl_profile_title.setStyleSheet("font-size: 13px; color: #333;")
        self.detail_layout.addWidget(self.lbl_profile_title)
        
        self.lbl_firm_name = QLabel()
        self.lbl_address = QLabel()
        self.lbl_gstin = QLabel()
        self.lbl_vendor = QLabel()
        self.lbl_format = QLabel()
        self.lbl_destinations = QLabel()
        
        for lbl in (self.lbl_firm_name, self.lbl_address, self.lbl_gstin, self.lbl_vendor, self.lbl_format, self.lbl_destinations):
            lbl.setWordWrap(True)
            self.detail_layout.addWidget(lbl)
            
        self.detail_layout.addWidget(QLabel("<b>Signature Preview:</b>"))
        self.preview_lbl = QLabel("No signature image path set.")
        self.preview_lbl.setStyleSheet("border: 1px solid #eee; background: #fafafa; border-radius: 4px;")
        self.preview_lbl.setFixedSize(180, 60)
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_layout.addWidget(self.preview_lbl)
        
        self.detail_layout.addWidget(QLabel("<b>Logo Preview:</b>"))
        self.logo_preview_lbl = QLabel("No logo image path set.")
        self.logo_preview_lbl.setStyleSheet("border: 1px solid #eee; background: #fafafa; border-radius: 4px;")
        self.logo_preview_lbl.setFixedSize(80, 80)
        self.logo_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_layout.addWidget(self.logo_preview_lbl)
        
        self.detail_layout.addStretch()
        
        # Right Actions
        right_btn_lay = QHBoxLayout()
        self.btn_edit = QPushButton("✏️  Edit Details")
        self.btn_edit.clicked.connect(self._edit_profile)
        self.btn_edit.setStyleSheet("padding: 6px 12px;")
        
        self.btn_set_active = QPushButton("⭐  Set Active")
        self.btn_set_active.clicked.connect(self._set_active_profile)
        self.btn_set_active.setStyleSheet("padding: 6px 12px; font-weight: bold; background: #2b82c9; color: white;")
        
        right_btn_lay.addWidget(self.btn_edit)
        right_btn_lay.addWidget(self.btn_set_active)
        self.detail_layout.addLayout(right_btn_lay)
        
        splitter.addWidget(self.detail_widget)
        splitter.setSizes([220, 480])
        
        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setStyleSheet("padding: 8px 20px; font-weight: bold;")
        bottom_layout.addWidget(self.btn_close)
        main_layout.addLayout(bottom_layout)
        
    def _reload_profiles(self):
        self.profiles = _dbg.get_user_profiles()
        self.list_widget.clear()
        
        for p in self.profiles:
            prefix = "⭐ " if p["is_active"] else "  "
            item = QListWidgetItem(f"{prefix}{p['name']}")
            self.list_widget.addItem(item)
            
        if self.profiles:
            self.list_widget.setCurrentRow(0)
        else:
            self.detail_widget.setEnabled(False)
            self._clear_detail_pane()
            
    def _clear_detail_pane(self):
        self.lbl_firm_name.setText("")
        self.lbl_address.setText("")
        self.lbl_gstin.setText("")
        self.lbl_vendor.setText("")
        self.lbl_format.setText("")
        self.lbl_destinations.setText("")
        self.preview_lbl.setText("No profile selected.")
        self.preview_lbl.setPixmap(QPixmap())
        self.logo_preview_lbl.setText("No profile selected.")
        self.logo_preview_lbl.setPixmap(QPixmap())
        
    def _on_profile_selected(self, index):
        if index < 0 or index >= len(self.profiles):
            self.detail_widget.setEnabled(False)
            self._clear_detail_pane()
            return
            
        self.detail_widget.setEnabled(True)
        p = self.profiles[index]
        
        import json
        try:
            dests = json.loads(p.get("billing_to_json", "[]"))
            dest_count = len(dests)
        except Exception:
            dest_count = 0
            
        self.lbl_profile_title.setText(f"<b>Profile: {p['name']}</b>" + (" (Active)" if p["is_active"] else ""))
        self.lbl_firm_name.setText(f"<b>Firm Name:</b> {p['firm_name']}")
        self.lbl_address.setText(f"<b>Address:</b> {p['address']}")
        self.lbl_gstin.setText(f"<b>GSTIN:</b> {p['gstin']}")
        self.lbl_vendor.setText(f"<b>Vendor Number:</b> {p.get('vendor_no', 'N/A')}")
        self.lbl_format.setText(f"<b>Invoice Format:</b> {p.get('invoice_format', '')} (Next Seq: {p.get('next_seq', 1)})")
        self.lbl_destinations.setText(f"<b>Clients Configured:</b> {dest_count} destination(s)")
        
        # Load signature preview
        sig = p.get("signature_path")
        if sig and os.path.exists(sig):
            pix = QPixmap(sig)
            if not pix.isNull():
                self.preview_lbl.setPixmap(pix.scaled(
                    self.preview_lbl.width() - 4,
                    self.preview_lbl.height() - 4,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
            else:
                self.preview_lbl.setText("No signature image")
                self.preview_lbl.setPixmap(QPixmap())
        else:
            self.preview_lbl.setText("No signature image")
            self.preview_lbl.setPixmap(QPixmap())
            
        # Load logo preview
        logo = p.get("logo_path")
        if logo and os.path.exists(logo):
            pix = QPixmap(logo)
            if not pix.isNull():
                self.logo_preview_lbl.setPixmap(pix.scaled(
                    self.logo_preview_lbl.width() - 4,
                    self.logo_preview_lbl.height() - 4,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
            else:
                self.logo_preview_lbl.setText("No logo image")
                self.logo_preview_lbl.setPixmap(QPixmap())
        else:
            self.logo_preview_lbl.setText("No logo image")
            self.logo_preview_lbl.setPixmap(QPixmap())
        
    def _create_profile(self):
        dlg = ProfileEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            success = _dbg.add_user_profile(data)
            if not success:
                QMessageBox.warning(self, "Duplicate Profile Name", "A profile with that name already exists.")
            self._reload_profiles()
            
    def _edit_profile(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.profiles):
            return
            
        p = self.profiles[row]
        dlg = ProfileEditDialog(p, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            _dbg.update_user_profile(p["id"], data)
            self._reload_profiles()
            # Select the same index
            self.list_widget.setCurrentRow(row)
            
    def _delete_profile(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.profiles):
            return
            
        p = self.profiles[row]
        ans = QMessageBox.question(
            self, "Delete Profile", f"Are you sure you want to delete profile '{p['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            _dbg.delete_user_profile(p["id"])
            self._reload_profiles()
            
    def _set_active_profile(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.profiles):
            return
            
        p = self.profiles[row]
        _dbg.set_active_profile(p["id"])
        self._reload_profiles()
        self.list_widget.setCurrentRow(row)
