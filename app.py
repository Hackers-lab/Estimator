"""
Main application module for the ERP Estimate Generator.
Application version is defined in app_config.py.
  - Project Setup Wizard (project type, UH toggle, supervision rate)
  - SmartPole with pole_type2 (PCC/STP/H-BEAM) + cascading heights
  - SmartStructure as separate canvas object (DP/TP/4P/DTR)
  - SmartSpan with unified conductor_size + voltage auto-detection
  - SmartConsumer (replaces SmartHome) with phase + agency supply
  - Iron Breakup sheet in Excel export
  - Detail View toggle for canvas symbols
  - Full backward compatibility with v4 saved JSON files
"""

import sys
import math
import json
import os
import re
import sqlite3
from datetime import datetime

# pyrefly: ignore [missing-import]
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QGraphicsScene, QGraphicsItem,
    QFormLayout, QGroupBox, QSpinBox, QLineEdit,
    QFileDialog, QMessageBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QGraphicsView,
    QDialog, QDoubleSpinBox, QScrollArea, QFrame,
    QMenu, QTextBrowser, QInputDialog, QSizePolicy, QSlider, QStackedWidget, QProgressDialog,
    QToolButton
)
# pyrefly: ignore [missing-import]
from PyQt6.QtGui import (
    QPen, QColor, QAction, QKeySequence, QIcon,
    QPixmap, QFont, QPainter, QFontMetrics
)
# pyrefly: ignore [missing-import]
from PyQt6.QtCore import Qt, QTimer, QPointF, QEvent, QSize, pyqtSignal, QThread, QObject

from core.constants import (
    TOOLS, SAG_ITEMS
)
from core import defaults
from core.expiry import check_expiry
from app_config import (
    APP_DISPLAY_NAME, APP_VERSION, APP_AUTHOR, APP_EXPIRY, get_user_data_path
)
from core.database import setup_database, DB_PATH
from core.rule_engine import DynamicRuleEngine
from ui.components import InteractiveView, DraggableLabel
from canvas import (
    SmartPole, SmartStructure, SmartSpan, SmartConsumer, 
    CanvasSymbol, CanvasTextBox, GridManager
)
from canvas.map_overlay import GPSBackgroundItem
from ui.dialogs import (
    SearchDialog, SettingsDialog, DatabaseManagerDialog,
    RulesetManagerDialog, ProjectSetupDialog, PlacementDefaultsDialog,
    PropertyEditorDialog, RecipeManagerDialog,
)


# ─────────────────────────────────────────────────────────────────────────────
#  RESOURCE PATH HELPER (PyInstaller-compatible)
# ─────────────────────────────────────────────────────────────────────────────
def resource_path(relative_path):
    """Return absolute path to a bundled resource, works for dev and PyInstaller."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


# ─────────────────────────────────────────────────────────────────────────────
#  PROJECT META DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PROJECT_META = {
    "subject":          "",
    "lat":              "",
    "long":             "",
    "project_type":     "NSC",
    "use_uh":           False,
    "supervision_rate": 0.10,
    "project_id":       "",
    "po_no":            "",
    "po_date":          "",
    "vendor_id":        "",
    "comm_date":        "",
    "comp_date":        "",
    "meas_date":        "",
    "meas_taken_by":    "",
    "certified_by":     "",
}


# Mutex handle to enforce single instance of the application on Windows
_single_instance_mutex = None





# ─────────────────────────────────────────────────────────────────────────────
#  Wheel-event blocker for combo/spin boxes inside scroll areas
# ─────────────────────────────────────────────────────────────────────────────

class _WheelBlockFilter(QObject):
    """Ignores wheel events on QComboBox / QSpinBox when they don't have focus."""
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return super().eventFilter(obj, event)


class _ElidedLabel(QLabel):
    """A QLabel that cleanly elides text to fit whatever width its parent gives it,
    never pushing or expanding its container horizontally."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        self._full_text = text
        super().setText(text)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(10, self.width() - 8))
        opt_rect = self.rect().adjusted(4, 0, -4, 0)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(opt_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN APPLICATION CLASS
# ─────────────────────────────────────────────────────────────────────────────
from ui.editors import EditorMixin
class EstimateApp(QMainWindow, EditorMixin):
    refresh_signal = pyqtSignal()
    _MIN_NODE_GAP = 36.0  # fallback scene units
    # Debounce window for the full recalc/BOM pass. Small enough to feel instant
    # after a placement, large enough to collapse every pixel of a drag into one
    # pass. Canvas geometry still follows nodes live (see _on_position_changed).
    _REFRESH_DEBOUNCE_MS = 30

    def __init__(self, headless=False):
        super().__init__()
        self.headless = headless
        self._combo_wheel_filter = _WheelBlockFilter(self)

        setup_database()
        defaults.load()

        # ── Project-level state ────────────────────────────────────────────
        self.project_meta   = dict(DEFAULT_PROJECT_META)
        self.bom_overrides  = {}
        self.live_bom_data  = []
        self.live_bom_provenance = {}
        self.escalations    = []
        self.current_project_path = None
        self.detail_view    = True          # show stay/earth/CG symbols
        self.span_start_pole = None
        self.last_placed_node = None        # for auto-span chain when placing nodes
        self.autosave_file  = "autosave_erp.json"
        self._drawing_dirty = False            # True when canvas has unsaved changes
        self._resetting     = False            # True during a factory reset (skips close autosave)
        self.current_tool   = "SELECT"
        self._pending_symbol_shape = "circle"   # last chosen symbol shape
        self.active_structure_type  = "DP"       # default active structure subtype
        self.active_existing_subtype = "LT"      # default active existing subtype

        # ── Page grid state ────────────────────────────────────────────────
        # 17.5 scene units ≈ 1 real-world metre  (calibrated: 40m span = ~700 units)
        self.pdf_scale  = 200   # default print scale
        self.pdf_show_project_name = True
        self.pdf_show_legend = True
        self.pdf_orientation_mode = "Auto + Overrides"
        self.pdf_auto_gain_threshold = 1.08
        self.pdf_page_overrides: dict[int, str] = {}
        self.show_page_grid  = True
        self.show_crosshatch = True

        # Rule engine (lazy-init on first refresh)
        self.rule_engine = DynamicRuleEngine()

        # ── History state (Undo/Redo) ──────────────────────────────────────
        from canvas.history_manager import CanvasHistoryManager
        self.history_mgr = CanvasHistoryManager(
            get_state_fn=self.compile_save_data,
            apply_state_fn=self.parse_load_data,
        )
        self._refreshing_live = False
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.timeout.connect(self.push_history)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh_live_estimate)

        if not self.headless:
            self.grid_manager = GridManager(self)

            # ── Build UI ───────────────────────────────────────────────────────
            self.setWindowTitle(f"{APP_DISPLAY_NAME} — v{APP_VERSION}")
            self.setGeometry(30, 30, 1380, 840)
            logo_path = resource_path("assets/logo.svg")
            if os.path.exists(logo_path):
                self.setWindowIcon(QIcon(logo_path))

            self._build_menu_bar()
            self._build_ui()

            app_inst = QApplication.instance()
            if app_inst is not None:
                app_inst.installEventFilter(self)

            # ── Wire signals ───────────────────────────────────────────────────
            self.refresh_signal.connect(self.refresh_live_estimate)
            self.scene.selectionChanged.connect(self.on_selection_changed)

            # ── Load autosave ──────────────────────────────────────────────────
            self.set_tool("SELECT")
            self.load_autosave()
            self.on_selection_changed()

            # ── Background update check (packaged builds only) ──────────────────
            QTimer.singleShot(3000, self.maybe_check_for_updates_on_startup)
            QTimer.singleShot(1000, self._check_profile_on_startup)
        else:
            self.scene = QGraphicsScene()


    # =========================================================================
    #  MENU BAR
    # =========================================================================

    def _build_menu_bar(self):
        from ui.menu_bar import build_menu_bar
        build_menu_bar(self)

    # =========================================================================
    #  UI CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(central)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self.splitter)

        # Left: canvas area
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        self.lock_banner = QLabel("🔒 PROJECT INVOICED: Drawing and estimate are locked from further editing.")
        self.lock_banner.setStyleSheet("background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; border-radius: 4px; padding: 6px; font-weight: bold; font-size: 11px;")
        self.lock_banner.setVisible(False)
        left_layout.addWidget(self.lock_banner)

        left_layout.addLayout(self._build_icon_ribbon())
        left_layout.addLayout(self._build_draw_toolbar())

        self.scene = QGraphicsScene()
        self.view  = InteractiveView(self.scene, self)
        left_layout.addWidget(self.view)

        # ── Bottom canvas control bar ──────────────────────────────────────
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(5)
        bottom_bar.setContentsMargins(2, 0, 2, 0)

        # Show Symbols checkbox
        self.detail_chk = QCheckBox("Symbol")
        self.detail_chk.setChecked(True)
        self.detail_chk.setStyleSheet(
            "font-size:10px; font-weight:bold; color:#555; spacing:3px;"
        )
        self.detail_chk.toggled.connect(self._toggle_detail_view)
        bottom_bar.addWidget(self.detail_chk)

        # Separator
        sep1 = QLabel("|")
        sep1.setStyleSheet("color:#ccc; font-size:12px;")
        bottom_bar.addWidget(sep1)

        # Hide existing-span length labels (declutter busy drawings)
        self.ex_len_chk = QCheckBox("Ex Len")
        self.ex_len_chk.setChecked(True)
        self.ex_len_chk.setToolTip("Show the length label on existing spans")
        self.ex_len_chk.setStyleSheet(
            "font-size:10px; color:#555; spacing:3px;"
        )
        self.ex_len_chk.toggled.connect(self._toggle_existing_span_length)
        bottom_bar.addWidget(self.ex_len_chk)

        # Hide/Show Pole Names & Labels
        self.pole_label_chk = QCheckBox("Mark")
        self.pole_label_chk.setChecked(True)
        self.pole_label_chk.setToolTip("Show or hide pole name labels (PLT1, PHT1, P331, etc.) on drawing")
        self.pole_label_chk.setStyleSheet("font-size:10px; color:#555; spacing:3px;")
        self.pole_label_chk.toggled.connect(self._toggle_pole_labels)
        bottom_bar.addWidget(self.pole_label_chk)

        # Separator
        sep1_2 = QLabel("|")
        sep1_2.setStyleSheet("color:#ccc; font-size:12px;")
        bottom_bar.addWidget(sep1_2)

        # Hide/Show PDF Legend Table
        self.legend_chk = QCheckBox("Legend")
        self.legend_chk.setChecked(True)
        self.legend_chk.setToolTip("Include the legend table and object counts in PDF export")
        self.legend_chk.setStyleSheet("font-size:10px; color:#555; spacing:3px;")
        self.legend_chk.toggled.connect(self._toggle_pdf_legend)
        bottom_bar.addWidget(self.legend_chk)

        # Separator
        sep2 = QLabel("|")
        sep2.setStyleSheet("color:#ccc; font-size:12px;")
        bottom_bar.addWidget(sep2)

        # Scale label + dropdown
        lbl_scale = QLabel("Scale:")
        lbl_scale.setStyleSheet("font-size:10px;")
        bottom_bar.addWidget(lbl_scale)
        self.scale_cb = QComboBox()
        self.scale_cb.addItems([
            "1:150", "1:200", "1:300"
        ])
        self.scale_cb.setCurrentText("1:200")
        self.scale_cb.setToolTip(
            "Sets how much drawing area fits on one A4 page.\n"
            "1:150 = more detailed  |  1:300 = wider area."
        )
        self.scale_cb.currentTextChanged.connect(self._on_scale_changed)
        self.scale_cb.setStyleSheet(
            "font-size:10px; font-weight:bold; color:#1a5276;"
        )
        bottom_bar.addWidget(self.scale_cb)

        # Orientation mode
        lbl_orient = QLabel("Orient:")
        lbl_orient.setStyleSheet("font-size:10px;")
        bottom_bar.addWidget(lbl_orient)
        self.orient_cb = QComboBox()
        self.orient_cb.addItems([
            "Landscape (All)",
            "Portrait (All)",
            "Auto (Global Best)",
            "Auto + Overrides",
        ])
        self.orient_cb.setCurrentText(self.pdf_orientation_mode)
        self.orient_cb.setToolTip(
            "Landscape/Portrait force all pages.\n"
            "Auto (Global Best) picks one best orientation for the full drawing.\n"
            "Auto + Overrides allows manual page overrides."
        )
        self.orient_cb.currentTextChanged.connect(self._on_orientation_mode_changed)
        self.orient_cb.setStyleSheet("font-size:10px; color:#1a5276;")
        bottom_bar.addWidget(self.orient_cb)

        self.page_override_btn = QPushButton("Overrides")
        self.page_override_btn.setToolTip(
            "Set manual orientation for specific pages, e.g. 2:P, 5:L.\n"
            "Note: overrides that conflict with current grid geometry are ignored."
        )
        self.page_override_btn.setStyleSheet(
            "font-size:10px; padding:2px 5px;"
        )
        self.page_override_btn.clicked.connect(self._edit_page_overrides)
        bottom_bar.addWidget(self.page_override_btn)

        # Separator
        sep3 = QLabel("|")
        sep3.setStyleSheet("color:#ccc; font-size:12px;")
        bottom_bar.addWidget(sep3)

        # GPS Background toggle
        self.gps_bg_chk = QCheckBox("GPS BG")
        self.gps_bg_chk.setChecked(False)
        self.gps_bg_chk.setToolTip("Show OpenStreetMap background for the project lat/long")
        self.gps_bg_chk.setStyleSheet("font-size:10px; font-weight:bold; color:#d35400; spacing:3px;")
        self.gps_bg_chk.toggled.connect(self._toggle_gps_bg)
        bottom_bar.addWidget(self.gps_bg_chk)

        self.gps_zoom_cb = QComboBox()
        self.gps_zoom_cb.addItems(["Zoom 17", "Zoom 18", "Zoom 19", "Zoom 20", "Zoom 21"])
        self.gps_zoom_cb.setCurrentText("Zoom 19")
        self.gps_zoom_cb.setEnabled(False)
        self.gps_zoom_cb.currentTextChanged.connect(self._change_gps_zoom)
        self.gps_zoom_cb.setStyleSheet("font-size:10px; font-weight:bold; color:#1a5276;")
        self.gps_zoom_cb.setToolTip("Map Resolution Level")
        bottom_bar.addWidget(self.gps_zoom_cb)

        self.gps_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.gps_opacity_slider.setRange(10, 100)
        self.gps_opacity_slider.setValue(50)
        self.gps_opacity_slider.setFixedWidth(65)
        self.gps_opacity_slider.setToolTip("Background Opacity")
        self.gps_opacity_slider.setEnabled(False)
        self.gps_opacity_slider.valueChanged.connect(self._change_gps_opacity)
        bottom_bar.addWidget(self.gps_opacity_slider)

        bottom_bar.addStretch()
        left_layout.addLayout(bottom_bar)

        self.splitter.addWidget(left_panel)

        # Right: properties + estimate table
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(self._build_properties_panel())
        right_splitter.addWidget(self._build_estimate_panel())
        right_splitter.setSizes([260, 600])

        self.splitter.addWidget(right_splitter)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([950, 420])

    def _build_icon_ribbon(self):
        """Small icon-only ribbon above the main drawing tools."""
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.setContentsMargins(0, 0, 0, 2)

        def _make_icon_btn(text, tooltip, bg, color="#000"):
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setFixedSize(28, 28)
            btn.setStyleSheet(f"font-size:16px; font-weight:bold; background:{bg}; color:{color}; border-radius:3px; border:1px solid #ccc;")
            return btn

        def _make_svg_btn(icon_name, tooltip, bg="#f5f5f5"):
            btn = QPushButton()
            btn.setToolTip(tooltip)
            btn.setFixedSize(28, 28)
            btn.setIcon(QIcon(resource_path(f"assets/icons/{icon_name}")))
            btn.setIconSize(QSize(20, 20))
            btn.setStyleSheet(
                f"background:{bg}; border-radius:3px; border:1px solid #ccc;"
            )
            return btn

        # Undo / Redo
        self.undo_btn = _make_icon_btn("↶", "Undo (Ctrl+Z)", "#e6e6e6")
        self.undo_btn.clicked.connect(self.undo)
        bar.addWidget(self.undo_btn)

        self.redo_btn = _make_icon_btn("↷", "Redo (Ctrl+Y)", "#e6e6e6")
        self.redo_btn.clicked.connect(self.redo)
        bar.addWidget(self.redo_btn)

        sep = QLabel("|")
        sep.setStyleSheet("color:#bbb; padding:0 2px;")
        bar.addWidget(sep)

        # PDF / Excel
        btn_pdf = _make_icon_btn("📑", "Export PDF Drawing", "#f9ebea", "#78281f")
        btn_pdf.clicked.connect(self.export_pdf)
        bar.addWidget(btn_pdf)

        btn_xl = _make_icon_btn("📊", "Export Excel Estimate", "#eaf2f8", "#154360")
        btn_xl.clicked.connect(self.generate_excel)
        bar.addWidget(btn_xl)

        sep2 = QLabel("|")
        sep2.setStyleSheet("color:#bbb; padding:0 2px;")
        bar.addWidget(sep2)

        # Settings quick-access icons
        btn_proj = _make_icon_btn("⚙", "Project Settings", "#eaf4fb")
        btn_proj.clicked.connect(lambda: self._run_project_wizard(first_run=False))
        bar.addWidget(btn_proj)

        btn_db = _make_icon_btn("🗄", "Master Database", "#eafaf1")
        btn_db.clicked.connect(self.open_db_manager)
        bar.addWidget(btn_db)

        btn_rules = _make_icon_btn("📋", "Ruleset Manager", "#fef9e7")
        btn_rules.clicked.connect(self.open_rule_manager)
        bar.addWidget(btn_rules)

        btn_defs = _make_icon_btn("🔧", "Placement Defaults", "#fdf2f8")
        btn_defs.clicked.connect(self.open_placement_defaults)
        bar.addWidget(btn_defs)

        # Property Editor icon
        btn_prop_editor = _make_icon_btn("🧩", "Property Editor", "#f7fafd", "#1a5276")
        btn_prop_editor.clicked.connect(self.open_property_editor)
        bar.addWidget(btn_prop_editor)

        bar.addStretch()
        return bar

    def _build_draw_toolbar(self):
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.tools_btns = {}
        menu_style = """
            QMenu {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 5px 16px 5px 10px;
                font-weight: bold;
                font-size: 11px;
                color: #1e293b;
            }
            QMenu::item:selected {
                background-color: #eff6ff;
                color: #2563eb;
            }
        """
        for key, txt in TOOLS.items():
            if key == "ADD_HT":
                btn = QToolButton()
                btn.setText("🟥 HT Pole ▼")
                btn.setToolTip("Click to choose 11kV HT Pole (Square) or 33kV HT Pole (Diamond)")
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(btn)
                menu.setStyleSheet(menu_style)

                def _set_ht(v_level):
                    self.active_ht_voltage = v_level
                    self.set_tool("ADD_HT")

                a_11 = menu.addAction("⬛ 11kV HT Pole (Square)")
                a_11.triggered.connect(lambda: _set_ht("11kV"))
                a_33 = menu.addAction("🔷 33kV HT Pole (Diamond)")
                a_33.triggered.connect(lambda: _set_ht("33kV"))

                btn.setMenu(menu)
                bar.addWidget(btn)
                self.tools_btns[key] = btn
            elif key == "ADD_STRUCTURE":
                btn = QToolButton()
                btn.setText("🟩 Structure ▼")
                btn.setToolTip("Click to choose Structure type (DP, TP, 4P, or DTR Substation)")
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(btn)
                menu.setStyleSheet(menu_style)
                
                def _set_struct(st_type):
                    self.active_structure_type = st_type
                    self.set_tool("ADD_STRUCTURE")

                a_dp = menu.addAction("🟢 DP Structure")
                a_dp.triggered.connect(lambda: _set_struct("DP"))
                a_tp = menu.addAction("🔷 TP Structure")
                a_tp.triggered.connect(lambda: _set_struct("TP"))
                a_4p = menu.addAction("🔶 4P Structure")
                a_4p.triggered.connect(lambda: _set_struct("4P"))
                a_dtr = menu.addAction("⚡ DTR Substation")
                a_dtr.triggered.connect(lambda: _set_struct("DTR"))

                btn.setMenu(menu)
                bar.addWidget(btn)
                self.tools_btns[key] = btn
            elif key == "ADD_EXISTING":
                btn = QToolButton()
                btn.setText("⚪ Ex. Objects ▼")
                btn.setToolTip("Click to choose Existing Pole or Structure type")
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(btn)
                menu.setStyleSheet(menu_style)

                def _set_ex(ex_type):
                    self.active_existing_subtype = ex_type
                    self.set_tool("ADD_EXISTING")

                a_lt = menu.addAction("⚪ Ex LT Pole")
                a_lt.triggered.connect(lambda: _set_ex("LT"))
                a_ht = menu.addAction("⬛ Ex 11kV HT Pole")
                a_ht.triggered.connect(lambda: _set_ex("HT"))
                a_33 = menu.addAction("🔷 Ex 33kV HT Pole")
                a_33.triggered.connect(lambda: _set_ex("33"))
                a_dp = menu.addAction("🟢 Ex DP Structure")
                a_dp.triggered.connect(lambda: _set_ex("DP"))
                a_tp = menu.addAction("🔷 Ex TP Structure")
                a_tp.triggered.connect(lambda: _set_ex("TP"))
                a_4p = menu.addAction("🔶 Ex 4P Structure")
                a_4p.triggered.connect(lambda: _set_ex("4P"))
                a_dtr = menu.addAction("⚡ Ex DTR Substation")
                a_dtr.triggered.connect(lambda: _set_ex("DTR"))

                btn.setMenu(menu)
                bar.addWidget(btn)
                self.tools_btns[key] = btn
            else:
                btn = QPushButton(txt)
                btn.clicked.connect(lambda checked, t=key: self.set_tool(t))
                bar.addWidget(btn)
                self.tools_btns[key] = btn

        # Thin visual separator
        sep = QLabel("|")
        sep.setStyleSheet("color:#bbb; font-size:14px; padding:0 2px;")
        bar.addWidget(sep)

        # ── Symbol button ──────────────────────────────────────────────────
        sym_btn = QPushButton("⬡ Symbol")
        sym_btn.setToolTip("Place a decorative symbol on the canvas (circle, square, arrow, line)")
        sym_btn.setStyleSheet(
            "padding:4px 6px; font-weight:bold; font-size:11px;"
            "background:#eaf7ea; color:#1e8449; border-radius:3px; border:1px solid #c2e2c2;"
        )
        sym_btn.clicked.connect(self._show_symbol_picker)
        bar.addWidget(sym_btn)
        self.tools_btns["ADD_SYMBOL"] = sym_btn

        # ── Text Box button ────────────────────────────────────────────────
        txt_btn = QPushButton("T Text")
        txt_btn.setToolTip("Place a draggable text box on the canvas")
        txt_btn.setStyleSheet(
            "padding:4px 6px; font-weight:bold; font-size:11px;"
            "background:#fef9e7; color:#7d6608; border-radius:3px; border:1px solid #f6e58d;"
        )
        txt_btn.clicked.connect(lambda: self.set_tool("ADD_TEXTBOX"))
        bar.addWidget(txt_btn)
        self.tools_btns["ADD_TEXTBOX"] = txt_btn

        # Thin visual separator
        sep2 = QLabel("|")
        sep2.setStyleSheet("color:#bbb; font-size:14px; padding:0 2px;")
        bar.addWidget(sep2)

        # Fit-View button — also triggered by F key on the canvas
        fit_btn = QPushButton("⬡ Fit View")
        fit_btn.setToolTip(
            "Fit all drawing content in view  [F or Ctrl+0]\n"
            "Useful after zooming out too far or after loading a project."
        )
        fit_btn.setStyleSheet(
            "padding:4px 6px; font-weight:bold; font-size:11px;"
            "background:#d5e8f7; color:#1a5276; border-radius:3px; border:1px solid #b8daef;"
        )
        fit_btn.clicked.connect(self._fit_view)
        bar.addWidget(fit_btn)

        bar.addStretch()
        return bar

    def _show_symbol_picker(self):
        """Show a small popup menu to pick symbol shape, then activate ADD_SYMBOL tool."""
        menu = QMenu(self)
        shapes = [("⬤ Circle", "circle"), ("■ Square", "square"),
                  ("➤ Arrow", "arrow"),   ("― Line",  "line"),
                  ("╌ Dashed Line", "dashed_line"),
                  ("═ Road", "road"),
                  ("╪ Rail Line", "rail")]
        for label, shape in shapes:
            act = QAction(label, self)
            act.triggered.connect(lambda checked, s=shape: self._activate_symbol_tool(s))
            menu.addAction(act)
        btn = self.tools_btns.get("ADD_SYMBOL")
        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec()

    def _activate_symbol_tool(self, shape: str):
        self._pending_symbol_shape = shape
        self.set_tool("ADD_SYMBOL")

    def _annotation_bring_front(self):
        """Move selected annotation symbols/text boxes one Z-level forward."""
        for item in self.scene.selectedItems():
            if isinstance(item, (CanvasSymbol, CanvasTextBox)):
                item.setZValue(item.zValue() + 1)

    def _annotation_send_back(self):
        """Move selected annotation symbols/text boxes one Z-level backward."""
        for item in self.scene.selectedItems():
            if isinstance(item, (CanvasSymbol, CanvasTextBox)):
                item.setZValue(item.zValue() - 1)

    def _build_properties_panel(self):
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        w.setMinimumWidth(180)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 0)
        lay.setSpacing(3)

        # Project info strip with edit button
        info_row = QHBoxLayout()
        info_row.setSpacing(0)
        self.proj_info_label = _ElidedLabel()
        self.proj_info_label.setWordWrap(False)
        self.proj_info_label.setMinimumWidth(0)
        self.proj_info_label.setFixedHeight(26)
        self.proj_info_label.setStyleSheet(
            "font-size:10px; color:#444; padding:2px 4px;"
            "background:#f4f6f8; border:1px solid #d0d5da;"
            "border-radius:3px 0 0 3px; border-right:none;"
        )
        info_row.addWidget(self.proj_info_label, 1)

        self.edit_proj_btn = QPushButton("✏️")
        self.edit_proj_btn.setToolTip("Edit Project Settings")
        self.edit_proj_btn.setFixedSize(24, 22)
        self.edit_proj_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_proj_btn.setStyleSheet(
            "QPushButton { background:#f4f6f8; border:1px solid #d0d5da;"
            "  border-left:none; border-radius:0 3px 3px 0; font-size:11px; }"
            "QPushButton:hover { background:#d5e8f7; }"
        )
        self.edit_proj_btn.clicked.connect(lambda: self._run_project_wizard(first_run=False))
        info_row.addWidget(self.edit_proj_btn)
        lay.addLayout(info_row)
        self._refresh_proj_label()

        # Object property editor
        self.editor_group = QGroupBox("Object Properties")
        self.editor_layout = QFormLayout()
        self.editor_layout.setSpacing(2)
        self.editor_layout.setHorizontalSpacing(4)
        self.editor_layout.setVerticalSpacing(2)
        self.editor_layout.setContentsMargins(4, 3, 4, 3)
        self.editor_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.editor_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.editor_layout.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.DontWrapRows
        )
        self.editor_group.setLayout(self.editor_layout)
        self.editor_group.setStyleSheet(
            "QGroupBox { font-size:10px; font-weight:600;"
            "  padding-top:10px; margin-top:2px; }"
            "QGroupBox::title { subcontrol-origin:margin;"
            "  left:6px; padding:0 3px; }"
            "QLabel { font-size:10px; }"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {"
            "  min-height:18px; max-height:22px;"
            "  padding:0px 3px; font-size:10px;"
            "}"
            "QPushButton { min-height:18px; padding:1px 4px; font-size:10px; }"
            "QCheckBox { font-size:10px; spacing:4px; min-height:16px; }"
            "QCheckBox::indicator { width:12px; height:12px; }"
        )

        # Property editor UX prefs (kept simple and session-local)
        self._show_advanced_pole_props = False

        scroll = QScrollArea()
        self.editor_scroll = scroll
        scroll.setWidget(self.editor_group)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(scroll, 1)

        return w

    def _build_estimate_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 0, 6, 6)
        lay.setSpacing(4)

        # ── Header row: title + toggle buttons ────────────────────────────────
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a365d, stop:1 #2b6cb0);
                border-radius: 6px;
                padding: 3px 6px;
            }
        """)
        hdr_row = QHBoxLayout(hdr_frame)
        hdr_row.setContentsMargins(6, 4, 6, 4)
        hdr_row.setSpacing(6)

        self._panel_title_label = QLabel("📊  <b>Live Estimate</b>")
        self._panel_title_label.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: bold;")
        hdr_row.addWidget(self._panel_title_label, 1)

        self._btn_show_estimate = QPushButton("Estimate")
        self._btn_show_breakup  = QPushButton("Iron Breakup")
        for btn, active in [(self._btn_show_estimate, True), (self._btn_show_breakup, False)]:
            btn.setCheckable(True)
            btn.setChecked(active)
            btn.setStyleSheet("""
                QPushButton {
                    padding: 3px 10px;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: bold;
                    border: none;
                }
                QPushButton:checked {
                    background: #ffffff;
                    color: #1a365d;
                }
                QPushButton:!checked {
                    background: rgba(255, 255, 255, 0.2);
                    color: #ffffff;
                }
                QPushButton:hover:!checked {
                    background: rgba(255, 255, 255, 0.35);
                }
            """)
        self._btn_show_estimate.clicked.connect(lambda: self._switch_panel_view(0))
        self._btn_show_breakup.clicked.connect(lambda: self._switch_panel_view(1))
        hdr_row.addWidget(self._btn_show_estimate)
        hdr_row.addWidget(self._btn_show_breakup)
        lay.addWidget(hdr_frame)

        # ── Stacked widget: page 0 = estimate, page 1 = breakup ───────────────
        self._panel_stack = QStackedWidget()
        lay.addWidget(self._panel_stack, 1)

        # Page 0 — Estimate table
        est_page = QWidget()
        est_lay = QVBoxLayout(est_page)
        est_lay.setContentsMargins(0, 0, 0, 0)
        est_lay.setSpacing(3)

        self.live_table = QTableWidget(0, 6)
        self.live_table.setHorizontalHeaderLabels(
            ["Type", "Code", "Name", "Qty", "Unit", "Total (₹)"]
        )
        self.live_table.setStyleSheet("""
            QTableWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10px;
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                selection-background-color: #e0f2fe;
                selection-color: #0369a1;
            }
            QTableWidget::item {
                padding: 1px 4px;
                border: none;
            }
            QTableWidget::item:hover {
                background-color: #f1f5f9;
            }
            QHeaderView::section {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10px;
                font-weight: bold;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8fafc, stop:1 #e2e8f0);
                color: #334155;
                padding: 2px 4px;
                border: none;
                border-right: 1px solid #cbd5e1;
                border-bottom: 1px solid #cbd5e1;
                height: 22px;
            }
        """)
        self.live_table.setAlternatingRowColors(True)
        live_hdr = self.live_table.horizontalHeader()
        assert live_hdr is not None
        live_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.live_table.setColumnWidth(0, 42)   # Type: Mat / Lab
        self.live_table.setColumnWidth(1, 70)   # Code: item/lab code
        self.live_table.setColumnWidth(3, 46)   # Qty
        self.live_table.setColumnWidth(4, 36)   # Unit
        self.live_table.setColumnWidth(5, 68)   # Total (₹)
        live_v_hdr = self.live_table.verticalHeader()
        if live_v_hdr is not None:
            live_v_hdr.setDefaultSectionSize(19)
            live_v_hdr.setVisible(False)
        self.live_table.itemChanged.connect(self.on_table_edit)
        # Transparency: right-click or double-click a line to see where it came from
        self.live_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.live_table.customContextMenuRequested.connect(self._show_bom_provenance_menu)
        self.live_table.cellDoubleClicked.connect(self._on_bom_cell_double_clicked)
        est_lay.addWidget(self.live_table)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        add_mat = QPushButton("＋ Add Material")
        add_lab = QPushButton("＋ Add Labor")
        add_mat.clicked.connect(lambda: self.open_search("Material"))
        add_lab.clicked.connect(lambda: self.open_search("Labor"))
        add_mat.setStyleSheet("""
            QPushButton {
                background: #0284c7;
                color: white;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 8px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover { background: #0369a1; }
        """)
        add_lab.setStyleSheet("""
            QPushButton {
                background: #ea580c;
                color: white;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 8px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover { background: #c2410c; }
        """)
        btn_row.addWidget(add_mat)
        btn_row.addWidget(add_lab)
        est_lay.addLayout(btn_row)
        self._panel_stack.addWidget(est_page)

        # Page 1 — Iron breakup table
        brk_page = QWidget()
        brk_lay = QVBoxLayout(brk_page)
        brk_lay.setContentsMargins(0, 0, 0, 0)
        brk_lay.setSpacing(2)

        self.breakup_table = QTableWidget(0, 5)
        self.breakup_table.setHorizontalHeaderLabels(
            ["Description", "No", "Length", "Total (m)", "Iron (MT)"]
        )
        self.breakup_table.setStyleSheet("""
            QTableWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10px;
                background-color: #ffffff;
                gridline-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                selection-background-color: #bfdbfe;
                selection-color: #1e3a8a;
            }
            QHeaderView::section {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10px;
                font-weight: bold;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8fafc, stop:1 #e2e8f0);
                color: #334155;
                padding: 2px 4px;
                border: none;
                border-right: 1px solid #cbd5e1;
                border-bottom: 1px solid #cbd5e1;
                height: 22px;
            }
        """)
        brk_hdr = self.breakup_table.horizontalHeader()
        assert brk_hdr is not None
        brk_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.breakup_table.setColumnWidth(1, 40)
        self.breakup_table.setColumnWidth(2, 60)
        self.breakup_table.setColumnWidth(3, 65)
        self.breakup_table.setColumnWidth(4, 70)
        brk_v_hdr = self.breakup_table.verticalHeader()
        if brk_v_hdr is not None:
            brk_v_hdr.setDefaultSectionSize(19)
            brk_v_hdr.setVisible(False)
        self.breakup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.breakup_table.setAlternatingRowColors(False)
        brk_lay.addWidget(self.breakup_table)
        self._panel_stack.addWidget(brk_page)

        # ── Grand total card ──────────────────────────────────────────────────
        total_card = QFrame()
        total_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fffbeb, stop:1 #fef3c7);
                border: 1px solid #fcd34d;
                border-radius: 5px;
                padding: 3px 6px;
                margin-top: 2px;
            }
        """)
        tot_layout = QHBoxLayout(total_card)
        tot_layout.setContentsMargins(6, 4, 6, 4)

        self.grand_total_label = QLabel("<b>Estimated Cost (incl. taxes): ₹0.00</b>")
        self.grand_total_label.setStyleSheet("font-size: 11px; color: #92400e; font-weight: bold;")
        tot_layout.addWidget(self.grand_total_label, 1)

        hint_lbl = QLabel("<span style='font-size:8px; color:#b45309;'>Right-click / dbl-click for rule info</span>")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tot_layout.addWidget(hint_lbl)

        lay.addWidget(total_card)

        return w

    def _switch_panel_view(self, page: int):
        self._panel_stack.setCurrentIndex(page)
        self._btn_show_estimate.setChecked(page == 0)
        self._btn_show_breakup.setChecked(page == 1)
        if page == 0:
            self._panel_title_label.setText("<b>Live Estimate</b> (double-click Qty to edit)")
        else:
            self._panel_title_label.setText("<b>Iron Breakup</b> (read-only)")
            self._refresh_breakup_view()

    def _refresh_breakup_view(self):
        """
        Populate the Iron Breakup table from canvas items and recipes matching the Excel export.
        Shows detailed structural piece breakup (No, Length, Total m, Iron MT) per section.
        """
        from collections import defaultdict
        from PyQt6.QtGui import QColor, QFont as QFontQt
        from PyQt6.QtCore import Qt as Qt_
        from canvas import SmartPole, SmartStructure

        tbl = self.breakup_table
        tbl.setRowCount(0)

        def _row(texts, bg="#FFFFFF", bold=False, fg="#000000", italic=False, center_cols=(1, 2, 3)):
            r = tbl.rowCount()
            tbl.insertRow(r)
            for c, txt in enumerate(texts):
                cell = QTableWidgetItem(str(txt) if txt is not None else "")
                cell.setBackground(QColor(bg))
                f = QFontQt("Segoe UI", 9)
                f.setBold(bold)
                f.setItalic(italic)
                cell.setFont(f)
                cell.setForeground(QColor(fg))
                if c in center_cols:
                    cell.setTextAlignment(Qt_.AlignmentFlag.AlignCenter)
                elif c == 4:
                    cell.setTextAlignment(Qt_.AlignmentFlag.AlignRight | Qt_.AlignmentFlag.AlignVCenter)
                else:
                    cell.setTextAlignment(Qt_.AlignmentFlag.AlignLeft | Qt_.AlignmentFlag.AlignVCenter)
                cell.setFlags(cell.flags() & ~Qt_.ItemFlag.ItemIsEditable)
                tbl.setItem(r, c, cell)
            tbl.setRowHeight(r, 20)

        def _span_row(text, bg, bold=False, fg="#000000"):
            r = tbl.rowCount()
            tbl.insertRow(r)
            cell = QTableWidgetItem(text)
            cell.setBackground(QColor(bg))
            f = QFontQt("Segoe UI", 9)
            f.setBold(bold)
            cell.setFont(f)
            cell.setForeground(QColor(fg))
            cell.setFlags(cell.flags() & ~Qt_.ItemFlag.ItemIsEditable)
            tbl.setItem(r, 0, cell)
            tbl.setSpan(r, 0, 1, 5)
            tbl.setRowHeight(r, 22)

        KG_PER_METRE = {
            "CH_75X40":    6.8,
            "CH_100X50":   9.8,
            "ANG_65X65X6": 5.8,
            "ANG_50X50X6": 4.5,
            "FLAT_65X6":   3.1,
            "FLAT_50X6":   2.5,
        }
        SECTION_LABELS = {
            "CH_75X40":    "M.S. Channel (75X40mm)",
            "CH_100X50":   "M.S. Channel (100X50mm)",
            "ANG_65X65X6": "M.S. Angle (65X65X6mm)",
            "ANG_50X50X6": "M.S. Angle (50X50X6mm)",
            "FLAT_65X6":   "M.S. Flat (65X6mm)",
            "FLAT_50X6":   "M.S. Flat (50X6mm)",
        }
        SECTION_ORDER = ["CH_100X50", "CH_75X40", "ANG_65X65X6", "ANG_50X50X6", "FLAT_65X6", "FLAT_50X6"]

        # Load dynamic sections and recipes
        try:
            from core import db_gateway as _dbg
            recipes_list = _dbg.get_recipes()
            sections_dict = _dbg.get_sections()
        except Exception:
            recipes_list = []
            sections_dict = {}

        def find_recipe(rkey):
            return next((r for r in recipes_list if r["recipe_key"] == rkey), None)

        # ── Canvas Items & Counts ──────────────────────────────────────────────
        scene_items = self.scene.items() if hasattr(self, "scene") and self.scene else []
        poles = [i for i in scene_items if isinstance(i, SmartPole)]
        structs = [i for i in scene_items if isinstance(i, SmartStructure)]
        new_lt_poles = [p for p in poles if not p.is_existing and p.pole_type == "LT"]
        new_ht_poles = [p for p in poles if not p.is_existing and p.pole_type == "HT"]

        lt_recipe_counts = defaultdict(int)
        for p in new_lt_poles:
            rkey = getattr(p, "iron_recipe", "None") or "None"
            if rkey == "None":
                rkey = "POLE_LT_IRON"
            lt_recipe_counts[rkey] += 1

        ht_recipe_counts = defaultdict(int)
        for p in new_ht_poles:
            rkey = getattr(p, "iron_recipe", "None") or "None"
            if rkey == "None":
                rkey = "POLE_HT_IRON"
            ht_recipe_counts[rkey] += 1

        ext_lt = [p for p in poles if not p.is_existing and p.pole_type == "LT" and getattr(p, "has_extension", False)]
        lt_ext_count = len(ext_lt)
        avg_ext_lt = round(sum(float(getattr(p, "extension_height", 1.5) or 1.5) for p in ext_lt) / lt_ext_count if lt_ext_count else 1.5, 2)

        ext_ht = [p for p in poles if not p.is_existing and p.pole_type == "HT" and getattr(p, "has_extension", False)]
        ht_ext_count = len(ext_ht)
        avg_ext_ht = round(sum(float(getattr(p, "extension_height", 3.0) or 3.0) for p in ext_ht) / ht_ext_count if ht_ext_count else 3.0, 2)

        dp_count = len([s for s in structs if s.structure_type == "DP"])
        tp_count = len([s for s in structs if s.structure_type == "TP"])
        p4_count = len([s for s in structs if s.structure_type == "4P"])
        dtr_count = len([s for s in structs if s.structure_type == "DTR"])

        from canvas.span import SmartSpan
        spans = [i for i in scene_items if isinstance(i, SmartSpan)]
        new_poles_all = [p for p in poles if not p.is_existing]
        cg_pole_brackets = sum(
            sum(1 for s in getattr(p, "connected_spans", []) if getattr(s, "has_cg", False))
            for p in new_poles_all
        )
        cg_dp_brackets = sum(
            sum(1 for s in getattr(st, "connected_spans", []) if getattr(s, "has_cg", False))
            for st in structs if getattr(st, "structure_type", "") in ("DP", "DTR")
        )
        lt_acsr_count = (
            len([p for p in new_lt_poles if any(getattr(s, "conductor", "") == "ACSR" for s in getattr(p, "connected_spans", []))]) +
            len([p for p in poles if getattr(p, "is_existing", False) and getattr(p, "pole_type", "") == "LT" and bool(getattr(p, "lt_extension_continuous", lambda: False)())])
        )
        ab_cable_count = len([sp for sp in spans if getattr(sp, "conductor", "") == "AB Cable" and not getattr(sp, "is_existing_span", False)])

        objects = []

        def add_recipe_obj(title, recipe_key, canvas_count):
            rec = find_recipe(recipe_key)
            if not rec or canvas_count <= 0:
                return
            items = []
            for ri in rec.get("items", []):
                lpp = float(ri.get("length_per_piece", ri.get("length", 0.0)))
                qpo = int(ri.get("qty_per_object", ri.get("qty", 1)))
                if lpp <= 0:
                    continue
                items.append({
                    "description": ri.get("description", ""),
                    "section": ri.get("section", ""),
                    "lpp": lpp, "qpo": qpo,
                })
            if items:
                objects.append({"title": title, "canvas_count": canvas_count, "items": items})

        def add_direct_obj(title, canvas_count, direct_items):
            if canvas_count <= 0:
                return
            items = [dict(it) for it in direct_items if it.get("lpp", 0) > 0]
            if items:
                objects.append({"title": title, "canvas_count": canvas_count, "items": items})

        # Build objects matching the estimate
        for rkey, cnt in lt_recipe_counts.items():
            rec = find_recipe(rkey)
            label = rec["name"] if rec else rkey
            add_recipe_obj(f"LT Pole Iron — {label}", rkey, cnt)

        add_direct_obj(f"LT Pole Extension ({lt_ext_count} nos)", lt_ext_count, [
            {"description": "Single Pole Extension (Angle)", "section": "ANG_65X65X6",
             "lpp": avg_ext_lt, "qpo": 1},
        ])

        add_recipe_obj("DP Structure Iron", "DP_IRON", dp_count)
        add_recipe_obj(f"CG Cradle Guard Bracket ({cg_pole_brackets} sets)", "CG_BRACKET", cg_pole_brackets)
        add_recipe_obj(f"CG Cradle Guard Bracket DP ({cg_dp_brackets} sets)", "CG_DP_BRACKET", cg_dp_brackets)

        add_recipe_obj("TP Structure Iron", "TP_IRON", tp_count)
        add_recipe_obj("4-Pole Structure Iron", "4P_IRON", p4_count)
        add_recipe_obj("DTR Substation Iron", "DTR_IRON", dtr_count)

        # Structure extensions
        for _slabel, _stypes, _ppc in (("DP/DTR", ("DP", "DTR"), 2), ("TP", ("TP",), 3), ("4P", ("4P",), 4)):
            _grp = [s for s in structs if getattr(s, "structure_type", "") in _stypes and getattr(s, "has_extension", False)]
            if not _grp:
                continue
            _cnt = len(_grp)
            _avg = round(sum(float(getattr(s, "extension_height", 3.0) or 3.0) for s in _grp) / _cnt, 2)
            add_direct_obj(f"{_slabel} Structure Extension ({_cnt} nos)", _cnt, [
                {"description": "Structure Extension (Channel)", "section": "CH_75X40",
                 "lpp": round(_avg * 2, 2), "qpo": _ppc},
                {"description": "Structure Extension (Flat)", "section": "FLAT_65X6",
                 "lpp": 3.0, "qpo": _ppc},
            ])

        for rkey, cnt in ht_recipe_counts.items():
            rec = find_recipe(rkey)
            label = rec["name"] if rec else rkey
            add_recipe_obj(f"HT Pole Iron — {label}", rkey, cnt)

        add_direct_obj(f"HT Pole Extension ({ht_ext_count} nos)", ht_ext_count, [
            {"description": "HT Pole Extension (Channel)", "section": "CH_75X40",
             "lpp": round(avg_ext_ht * 2, 2), "qpo": 1},
            {"description": "HT Pole Extension (Flat)", "section": "FLAT_65X6",
             "lpp": 3.0, "qpo": 1},
        ])

        add_recipe_obj(f"LT ACSR Bracket ({lt_acsr_count} poles)", "LT_ACSR_BRACKET", lt_acsr_count)
        add_recipe_obj(f"AB Cable Clamp ({ab_cable_count} spans)", "AB_CABLE_CLAMP", ab_cable_count)

        # ── Group by Section ───────────────────────────────────────────────────
        extra_sections = []
        for obj in objects:
            for it in obj["items"]:
                sec = it["section"]
                if sec not in SECTION_ORDER and sec not in extra_sections:
                    extra_sections.append(sec)

        write_order = SECTION_ORDER + extra_sections
        section_map = defaultdict(list)
        for obj in objects:
            for sec_code in write_order:
                sec_items = [it for it in obj["items"] if it["section"] == sec_code]
                if sec_items:
                    section_map[sec_code].append({
                        "title": obj["title"],
                        "canvas_count": obj["canvas_count"],
                        "sec_items": sec_items,
                    })

        if not any(section_map.get(s) for s in write_order):
            _span_row("  No structural iron items in current estimate.", "#F8F8F8")
            return

        section_totals = []

        for sec_code in write_order:
            sec_objects = section_map.get(sec_code, [])
            if not sec_objects:
                continue

            kg_m = KG_PER_METRE.get(sec_code)
            if not kg_m and sec_code in sections_dict:
                kg_m = sections_dict[sec_code].get("kg_per_metre", 0.0)
            kg_m = kg_m or 0.0
            sec_label = SECTION_LABELS.get(sec_code, sec_code)
            kg_label = f"{kg_m} kg/m" if kg_m else ""

            # Section Header
            _span_row(f"  {sec_label}  {'— ' + kg_label if kg_label else ''}",
                      "#2A4365", bold=True, fg="#FFFFFF")

            # Column Sub-header
            _row(["  Description", "No", "Length", "Total (m)", "Iron (MT)"],
                 bg="#E2E8F0", bold=True, center_cols=(1, 2, 3, 4))

            sec_total_mt = 0.0

            for obj in sec_objects:
                # Object Sub-header
                _span_row(f"    ↳  {obj['title']}  ({obj['canvas_count']} nos on canvas)",
                          "#EDF2F7", bold=True, fg="#1A365D")

                obj_total_mt = 0.0
                for row_idx, it in enumerate(obj["sec_items"]):
                    canvas_cnt = obj["canvas_count"]
                    lpp = it["lpp"]
                    qpo = it["qpo"]
                    total_nos = canvas_cnt * qpo
                    total_len = round(total_nos * lpp, 2)
                    item_mt = round((total_len * kg_m) / 1000.0, 3)
                    obj_total_mt += item_mt

                    desc_text = f"      {it['description']}"
                    bg = "#FFFFFF" if row_idx % 2 == 0 else "#F7FAFC"
                    _row([desc_text, str(total_nos), f"{lpp:.2f}m", f"{total_len:.2f}", f"{item_mt:.3f}"],
                         bg=bg, center_cols=(1, 2, 3))

                sec_total_mt += obj_total_mt

            sec_total_mt = round(sec_total_mt, 3)
            section_totals.append((sec_label, sec_total_mt))
            _row(["  Section Total", "", "", "", f"{sec_total_mt:.3f} MT"],
                 bg="#D9E1F2", bold=True)
            _row(["", "", "", "", ""], bg="#F8F8F8")  # spacer

        # ── Iron Summary ───────────────────────────────────────────────────────
        if section_totals:
            _span_row("  IRON SUMMARY", "#2A4365", bold=True, fg="#FFFFFF")
            for sec_lbl, total_mt in section_totals:
                _row([f"  {sec_lbl}", "", "", "", f"{total_mt:.3f} MT"],
                     bg="#FEF3C7", bold=False)

    # =========================================================================
    #  PROJECT WIZARD
    # =========================================================================

    def _run_project_wizard(self, first_run=False):
        dlg = ProjectSetupDialog(self.project_meta, self, first_run=first_run)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            old_path = self.current_project_path
            self.project_meta = dlg.get_meta()
            
            # Compute new path
            folder_key = self.project_meta.get("folder_key", "default").strip()
            import re
            folder_key = re.sub(r'[\\/*?:"<>|]', "_", folder_key)
            stem = self._safe_subject_stem("project")
            project_dir = os.path.join(self._get_drawings_dir(), folder_key)
            os.makedirs(project_dir, exist_ok=True)
            new_path = os.path.join(project_dir, f"{stem}.json")
            
            # If the path changed and the old file exists, we rename/move it and update DB
            if old_path and old_path != new_path and os.path.exists(old_path):
                import shutil
                try:
                    shutil.move(old_path, new_path)
                    self.current_project_path = new_path
                    from core import db_gateway as _dbg
                    _dbg.rename_project_metadata(old_path, new_path, self.project_meta.get("subject", "Unnamed Project"))
                except Exception:
                    self.current_project_path = new_path
            else:
                self.current_project_path = new_path
                
            self._do_save_to_path(self.current_project_path)
            self._refresh_proj_label()
            self.refresh_live_estimate()

    def update_project_details(self):
        if not getattr(self, "current_project_path", None):
            QMessageBox.warning(self, "No Project", "Please open or create a project first before updating details.")
            return
            
        from ui.dialogs.project_setup import UpdateProjectDialog
        dlg = UpdateProjectDialog(self.project_meta, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.project_meta = dlg.get_meta()
            self._save_project_to_db()
            self._do_save_to_path(self.current_project_path)
            self._refresh_proj_label()
            self.statusBar().showMessage("Project billing/PO details updated and saved successfully.", 3000)

    def _refresh_proj_label(self):
        if getattr(self, "headless", False):
            return
        m = self.project_meta
        sup_pct = int(m.get("supervision_rate", 0.10) * 100)
        uh_txt  = "UH Materials" if m.get("use_uh") else "Raw Steel"
        path_txt = f"  ({os.path.basename(self.current_project_path)})" if getattr(self, "current_project_path", None) else ""
        text = (
            f"📌 {m.get('subject','(no subject)')}{path_txt}   |   "
            f"Type: {m.get('project_type','NSC')}   |   "
            f"Sup: {sup_pct}%   |   "
            f"Materials: {uh_txt}"
        )
        self.proj_info_label.setText(text)
        self.proj_info_label.setToolTip(text)
        self._update_lock_state()

    def _update_lock_state(self):
        if getattr(self, "headless", False):
            return
        self.project_locked = False
        if getattr(self, "current_project_path", None):
            from core import db_gateway as _dbg
            status = _dbg.get_project_status(self.current_project_path)
            if status == "Invoiced":
                self.project_locked = True

        if hasattr(self, "lock_banner"):
            self.lock_banner.setVisible(self.project_locked)

        enable = not self.project_locked
        if hasattr(self, "tools_btns"):
            for key, btn in self.tools_btns.items():
                btn.setEnabled(enable)
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(enable)
        if hasattr(self, "redo_btn"):
            self.redo_btn.setEnabled(enable)
        if hasattr(self, "editor_group"):
            self.editor_group.setEnabled(enable)
        if hasattr(self, "edit_proj_btn"):
            self.edit_proj_btn.setEnabled(enable)

        if self.project_locked:
            self.current_tool = "SELECT"
            for key, btn in self.tools_btns.items():
                active = key == "SELECT"
                btn.setStyleSheet(
                    "padding:4px 8px; font-weight:bold; font-size:11px; background:"
                    + ("lightblue;" if active else "lightgray;")
                )
            self.update_view_drag_mode()

        for item in self.scene.items():
            if hasattr(item, "setFlag"):
                try:
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, enable)
                except Exception:
                    pass

    # =========================================================================
    #  TOOL MANAGEMENT
    # =========================================================================

    # Drawing tools — switching between these keeps the auto-span chain alive
    _DRAWING_TOOLS = frozenset({"ADD_LT", "ADD_HT", "ADD_EXISTING", "ADD_STRUCTURE", "ADD_CONSUMER"})

    def set_tool(self, tool_name):
        if getattr(self, "project_locked", False) and tool_name != "SELECT":
            return
        prev_tool = self.current_tool
        self.current_tool = tool_name
        if self.span_start_pole:
            self.span_start_pole.setPen(QPen(Qt.GlobalColor.black, 1))
        self.span_start_pole = None

        if hasattr(self, "_active_drawing_symbol") and self._active_drawing_symbol is not None:
            if self._active_drawing_symbol.scene():
                self.scene.removeItem(self._active_drawing_symbol)
            self._active_drawing_symbol = None
            self._symbol_drag_start = None

        if hasattr(self, "_active_drawing_textbox") and self._active_drawing_textbox is not None:
            if self._active_drawing_textbox.scene():
                self.scene.removeItem(self._active_drawing_textbox)
            self._active_drawing_textbox = None
            self._textbox_drag_start = None

        # Clear auto-connect chain ONLY when leaving drawing mode
        # (i.e. switching to SELECT or ADD_SPAN — not between placement tools)
        leaving_drawing = tool_name not in self._DRAWING_TOOLS
        if leaving_drawing and self.last_placed_node is not None:
            try:
                self.last_placed_node.setPen(QPen(Qt.GlobalColor.black, 1))
            except RuntimeError:
                pass
            self.last_placed_node = None
        for key, btn in self.tools_btns.items():
            active = key == tool_name
            is_tb = isinstance(btn, QToolButton)
            bg = "#dbeafe" if active else "#f1f5f9"
            border = "#2563eb" if active else "#cbd5e1"
            color = "#1e40af" if active else "#334155"
            if is_tb:
                qss = f"""
                    QToolButton {{
                        padding: 4px 8px;
                        font-weight: bold;
                        font-size: 11px;
                        background-color: {bg};
                        border: 1.5px solid {border};
                        border-radius: 4px;
                        color: {color};
                    }}
                    QToolButton:hover {{
                        background-color: #e2e8f0;
                        border-color: #94a3b8;
                    }}
                    QToolButton::menu-indicator {{
                        image: none;
                        width: 0px;
                    }}
                """
            else:
                qss = f"""
                    QPushButton {{
                        padding: 4px 8px;
                        font-weight: bold;
                        font-size: 11px;
                        background-color: {bg};
                        border: 1.5px solid {border};
                        border-radius: 4px;
                        color: {color};
                    }}
                    QPushButton:hover {{
                        background-color: #e2e8f0;
                        border-color: #94a3b8;
                    }}
                """
            btn.setStyleSheet(qss)
        self.update_view_drag_mode()

    def update_view_drag_mode(self):
        """Delegate canvas interaction state to InteractiveView.

        SELECT mode now uses dynamic drag mode/cursor behavior:
        empty-space pan, hover-select pointer, selected-object drag pointer.
        """
        if self.current_tool == "SELECT":
            self.view.refresh_interaction_state()
        elif self.current_tool == "ADD_SYMBOL":
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.CrossCursor)
        elif self.current_tool == "ADD_TEXTBOX":
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.ArrowCursor)

    def _fit_view(self):
        """Fit all drawing content in view. Called by toolbar button and F key."""
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isNull():
            self.view.fitInView(
                bounds.adjusted(-60, -60, 60, 60),
                Qt.AspectRatioMode.KeepAspectRatio
            )

    def refresh_all_visuals(self):
        """Force an immediate visual update for all canvas objects.

        Uses vp.repaint() (synchronous) rather than update() (deferred) so
        the canvas re-draws even while a modal PropertyEditorDialog sits on top.
        """
        for item in self.scene.items():
            if isinstance(item, (SmartPole, SmartStructure, SmartSpan, SmartConsumer)):
                item.detail_view = self.detail_view
                item.update_visuals()
            else:
                item.update()
        self.scene.update()
        if hasattr(self, "view") and self.view:
            vp = self.view.viewport()
            if vp is not None:
                vp.repaint()



    def _toggle_detail_view(self, checked=None):
        self.detail_view = self.detail_chk.isChecked()
        self.refresh_all_visuals()


    def _toggle_existing_span_length(self, checked):
        """Show/hide the length label on existing spans (view-only declutter)."""
        SmartSpan.show_existing_length = checked
        for item in self.scene.items():
            if isinstance(item, SmartSpan) and getattr(item, "is_existing_span", False):
                item.update_visuals()

    def _toggle_pole_labels(self, checked):
        """Show/hide pole name labels (PLT1, PHT1, P331, ELT1, EHT1, E331, etc.) on canvas & export."""
        self.show_pole_labels = checked
        for item in self.scene.items():
            if isinstance(item, (SmartPole, SmartStructure, SmartConsumer)):
                if hasattr(item, "label") and item.label:
                    item.label.setVisible(checked)

    def _toggle_pdf_legend(self, checked):
        """Include/exclude the legend table and object counts in PDF export."""
        self.pdf_show_legend = checked
        self._refresh_page_grid()
    def _toggle_gps_bg(self, checked):
        if checked:
            import urllib.request
            try:
                req = urllib.request.Request("https://mt1.google.com/vt/lyrs=m&z=0&x=0&y=0", headers={'User-Agent': 'Mozilla'})
                urllib.request.urlopen(req, timeout=3)
            except Exception:
                QMessageBox.critical(self, "No Internet", "Internet connection is required to load GPS maps.")
                self.gps_bg_chk.blockSignals(True)
                self.gps_bg_chk.setChecked(False)
                self.gps_bg_chk.blockSignals(False)
                self.gps_opacity_slider.setEnabled(False)
                if hasattr(self, "gps_zoom_cb"):
                    self.gps_zoom_cb.setEnabled(False)
                return

        self.gps_opacity_slider.setEnabled(checked)
        if hasattr(self, "gps_zoom_cb"):
            self.gps_zoom_cb.setEnabled(checked)
        
        if checked:
            lat = self.project_meta.get("lat")
            lon = self.project_meta.get("long")
            if not lat or not lon:
                QMessageBox.warning(self, "No GPS Data", "Please enter project Latitude and Longitude in Project Settings to use GPS Background.")
                self.gps_bg_chk.setChecked(False)
                return
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except ValueError:
                QMessageBox.warning(self, "Invalid GPS Data", "Latitude and Longitude must be valid numbers.")
                self.gps_bg_chk.setChecked(False)
                return
            
            try:
                zoom = int(self.gps_zoom_cb.currentText().split()[1])
            except:
                zoom = 19

            self.gps_bg_item = GPSBackgroundItem(lat_f, lon_f, zoom=zoom)
            self.gps_bg_item.setOpacity(self.gps_opacity_slider.value() / 100.0)
            self.scene.addItem(self.gps_bg_item)
            
            # Update background clipping securely by forcing grid reload
            self._refresh_page_grid()
        else:
            if getattr(self, "gps_bg_item", None):
                try:
                    if self.gps_bg_item.scene() == self.scene:
                        self.scene.removeItem(self.gps_bg_item)
                except RuntimeError:
                    pass
                self.gps_bg_item = None

    def _change_gps_zoom(self, text):
        if self.gps_bg_chk.isChecked():
            self._toggle_gps_bg(False)
            self._toggle_gps_bg(True)

    def _change_gps_opacity(self, val):
        if getattr(self, "gps_bg_item", None):
            try:
                self.gps_bg_item.setOpacity(val / 100.0)
            except RuntimeError:
                pass

    def _on_scale_changed(self, text):
        """Called when user picks a new print scale from the dropdown."""
        try:
            self.pdf_scale = int(text.split(":")[1])
        except (IndexError, ValueError):
            self.pdf_scale = 200
        self._refresh_page_grid()

    def _on_orientation_mode_changed(self, text):
        self.pdf_orientation_mode = text
        use_override = (text == "Auto + Overrides")
        self.page_override_btn.setEnabled(use_override)
        self._refresh_page_grid()

    def _edit_page_overrides(self):
        if self.pdf_orientation_mode != "Auto + Overrides":
            QMessageBox.information(
                self,
                "Orientation Overrides",
                "Switch Orientation mode to 'Auto + Overrides' to edit page overrides.",
            )
            return

        self._refresh_page_grid()
        tiles = self.view.grid_tiles
        if not tiles:
            QMessageBox.information(self, "Orientation Overrides", "No pages available.")
            return

        total_pages = tiles[0].get("total", len(tiles))
        cur_parts = [f"{k}:{v}" for k, v in sorted(self.pdf_page_overrides.items())]
        cur_text = ", ".join(cur_parts)

        text, ok = QInputDialog.getText(
            self,
            "Page Orientation Overrides",
            (
                f"Enter overrides as page:orientation (L or P).\n"
                f"Example: 2:P, 5:L\n"
                f"Pages available: 1..{total_pages}\n"
                f"Conflicting overrides may be ignored to keep non-overlapping page grid."
            ),
            text=cur_text,
        )
        if not ok:
            return

        raw = text.strip()
        if not raw:
            self.pdf_page_overrides = {}
            self._refresh_page_grid()
            return

        parsed: dict[int, str] = {}
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for p in parts:
            if ":" not in p:
                QMessageBox.warning(self, "Invalid Override", f"Invalid token: {p}")
                return
            page_str, orient_str = p.split(":", 1)
            try:
                page_no = int(page_str.strip())
            except ValueError:
                QMessageBox.warning(self, "Invalid Override", f"Invalid page number: {page_str}")
                return
            orient = orient_str.strip().upper()
            if orient not in ("L", "P"):
                QMessageBox.warning(self, "Invalid Override", f"Invalid orientation for page {page_no}: {orient_str}")
                return
            if page_no < 1 or page_no > total_pages:
                QMessageBox.warning(
                    self,
                    "Invalid Override",
                    f"Page {page_no} is out of range (1..{total_pages}).",
                )
                return
            parsed[page_no] = orient

        self.pdf_page_overrides = parsed
        self._refresh_page_grid()

    # =========================================================================
    #  PAGE GRID COMPUTATION
    # =========================================================================








    def _refresh_page_grid(self):
        """Recompute the A4 page tiles using GridManager."""
        if hasattr(self, "grid_manager"):
            self.grid_manager.refresh()










    # =========================================================================
    #  INTERACTIVE DRAG-TO-SIZE & CANVAS CLICK HANDLERS
    # =========================================================================

    def handle_canvas_mouse_press(self, event, view) -> bool:
        if getattr(self, "project_locked", False):
            return False

        if self.current_tool in ("ADD_SYMBOL", "ADD_TEXTBOX"):
            if event.button() == Qt.MouseButton.RightButton:
                self.set_tool("SELECT")
                return True
            if event.button() == Qt.MouseButton.LeftButton:
                pos = view.mapToScene(event.pos())
                if self.current_tool == "ADD_SYMBOL":
                    shape = getattr(self, "_pending_symbol_shape", "circle")
                    self._symbol_drag_start = pos
                    item = CanvasSymbol(
                        shape=shape,
                        x=pos.x(),
                        y=pos.y(),
                        width=CanvasSymbol.MIN_DIM,
                        height=CanvasSymbol.MIN_DIM,
                    )
                    self.scene.addItem(item)
                    self._active_drawing_symbol = item
                    return True
                else:  # ADD_TEXTBOX
                    self._textbox_drag_start = pos
                    item = CanvasTextBox(
                        text="Text",
                        x=pos.x(),
                        y=pos.y(),
                        font_size=CanvasTextBox.DEFAULT_FONT_SIZE,
                    )
                    self.scene.addItem(item)
                    self._active_drawing_textbox = item
                    return True

        return False

    def handle_canvas_mouse_move(self, event, view) -> bool:
        # ── Symbol interactive drag-to-size ────────────────────────────────
        item_sym = getattr(self, "_active_drawing_symbol", None)
        if item_sym is not None and self.current_tool == "ADD_SYMBOL":
            start_pos = getattr(self, "_symbol_drag_start", None)
            if start_pos is None:
                return False

            curr_pos = view.mapToScene(event.pos())

            if item_sym._is_line():
                dx = curr_pos.x() - start_pos.x()
                dy = curr_pos.y() - start_pos.y()
                length = max(CanvasSymbol.MIN_DIM, math.hypot(dx, dy))
                angle = math.degrees(math.atan2(dy, dx))

                # Shift: snap angle to 15-degree increments
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    angle = round(angle / 15.0) * 15.0
                    rad = math.radians(angle)
                    curr_pos = QPointF(start_pos.x() + length * math.cos(rad),
                                       start_pos.y() + length * math.sin(rad))

                center = QPointF((start_pos.x() + curr_pos.x()) / 2.0,
                                 (start_pos.y() + curr_pos.y()) / 2.0)
                item_sym.prepareGeometryChange()
                item_sym._width = length
                item_sym._height = CanvasSymbol.MIN_DIM
                item_sym.setRotation(angle)
                item_sym.setPos(center)
            else:
                # 2D Shapes (circle, square, arrow)
                min_x = min(start_pos.x(), curr_pos.x())
                max_x = max(start_pos.x(), curr_pos.x())
                min_y = min(start_pos.y(), curr_pos.y())
                max_y = max(start_pos.y(), curr_pos.y())
                w = max_x - min_x
                h = max_y - min_y

                # Shift: constrain 1:1 aspect ratio
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    side = max(w, h)
                    w = side
                    h = side
                    if curr_pos.x() < start_pos.x():
                        min_x = start_pos.x() - side
                        max_x = start_pos.x()
                    else:
                        min_x = start_pos.x()
                        max_x = start_pos.x() + side
                    if curr_pos.y() < start_pos.y():
                        min_y = start_pos.y() - side
                        max_y = start_pos.y()
                    else:
                        min_y = start_pos.y()
                        max_y = start_pos.y() + side

                item_sym.prepareGeometryChange()
                item_sym._width = max(CanvasSymbol.MIN_DIM, w)
                item_sym._height = max(CanvasSymbol.MIN_DIM, h)
                item_sym.setPos((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

            item_sym.update()
            return True

        # ── Text interactive drag-to-size ──────────────────────────────────
        item_tb = getattr(self, "_active_drawing_textbox", None)
        if item_tb is not None and self.current_tool == "ADD_TEXTBOX":
            start_pos = getattr(self, "_textbox_drag_start", None)
            if start_pos is None:
                return False

            curr_pos = view.mapToScene(event.pos())
            dx = curr_pos.x() - start_pos.x()
            dy = curr_pos.y() - start_pos.y()
            drag_dist = math.hypot(dx, dy)

            # Proportional font size from drag distance
            new_fs = max(CanvasTextBox.MIN_FONT, min(CanvasTextBox.MAX_FONT, round(max(CanvasTextBox.DEFAULT_FONT_SIZE, drag_dist / 2.5))))
            if new_fs != item_tb._font_size:
                item_tb._font_size = new_fs
                item_tb._apply_font()
                item_tb.update()
            return True

        return False

    def handle_canvas_mouse_release(self, event, view) -> bool:
        # ── Release Symbol ─────────────────────────────────────────────────
        item_sym = getattr(self, "_active_drawing_symbol", None)
        if item_sym is not None and self.current_tool == "ADD_SYMBOL":
            if event.button() != Qt.MouseButton.LeftButton:
                return False

            start_pos = getattr(self, "_symbol_drag_start", None)
            end_pos = view.mapToScene(event.pos())
            drag_dist = math.hypot(end_pos.x() - start_pos.x(), end_pos.y() - start_pos.y()) if start_pos else 0.0

            # If user just clicked without dragging (or moved < 6px), place standard default 60x60 size
            if drag_dist < 6.0 and start_pos:
                item_sym.prepareGeometryChange()
                item_sym._width = 60.0
                item_sym._height = 60.0
                item_sym.setRotation(0.0)
                item_sym.setPos(start_pos)
                item_sym.update()

            self._active_drawing_symbol = None
            self._symbol_drag_start = None

            self.scene.clearSelection()
            item_sym.setSelected(True)
            self.on_selection_changed()
            self.set_tool("SELECT")
            self.refresh_live_estimate()
            return True

        # ── Release Textbox ────────────────────────────────────────────────
        item_tb = getattr(self, "_active_drawing_textbox", None)
        if item_tb is not None and self.current_tool == "ADD_TEXTBOX":
            if event.button() != Qt.MouseButton.LeftButton:
                return False

            start_pos = getattr(self, "_textbox_drag_start", None)
            end_pos = view.mapToScene(event.pos())
            drag_dist = math.hypot(end_pos.x() - start_pos.x(), end_pos.y() - start_pos.y()) if start_pos else 0.0

            if drag_dist < 6.0 and start_pos:
                item_tb._font_size = CanvasTextBox.DEFAULT_FONT_SIZE
                item_tb._apply_font()
                item_tb.update()

            self._active_drawing_textbox = None
            self._textbox_drag_start = None

            self.scene.clearSelection()
            item_tb.setSelected(True)
            self.on_selection_changed()
            self.set_tool("SELECT")
            self.refresh_live_estimate()

            # Immediate inline editing with "Text" selected so user can start typing directly
            QTimer.singleShot(50, lambda: item_tb.start_edit(select_all=True))
            return True

        return False

    def handle_canvas_click(self, event, view):
        if getattr(self, "project_locked", False):
            if event.button() == Qt.MouseButton.RightButton:
                self.set_tool("SELECT")
            return
        if event.button() == Qt.MouseButton.RightButton:
            if self.current_tool == "SELECT":
                pos = view.mapToScene(event.pos())
                hit = self.scene.itemAt(pos, view.transform())
                canvas_types = (SmartPole, SmartStructure, SmartSpan, SmartConsumer)
                while hit is not None and not isinstance(hit, canvas_types):
                    hit = hit.parentItem()
                if hit is not None:
                    self.scene.clearSelection()
                    hit.setSelected(True)
                    QTimer.singleShot(10, self.on_selection_changed)
                    self._show_item_context_menu(hit, event.globalPosition().toPoint())
                    return
            self.set_tool("SELECT")
            return
        if self.current_tool == "SELECT":
            return

        pos = view.mapToScene(event.pos())
        item_at = self.scene.itemAt(pos, view.transform())

        # ── Node placement (Poles, Structures, Consumers) ──────────────────
        if self.current_tool in ("ADD_LT", "ADD_HT", "ADD_EXISTING", "ADD_STRUCTURE", "ADD_CONSUMER"):
            if self._check_placement_blocked(pos):
                return
                
            if self.current_tool in ("ADD_LT", "ADD_HT", "ADD_EXISTING"):
                is_exist = self.current_tool == "ADD_EXISTING"
                if is_exist:
                    ex_sub = getattr(self, "active_existing_subtype", "LT")
                    p_type = "LT" if ex_sub == "LT" else "HT"
                    item = SmartPole(pos.x(), pos.y(), self.refresh_signal, p_type, is_existing=True, detail_view=self.detail_view, existing_subtype=ex_sub)
                    item.existing_subtype = ex_sub
                    if ex_sub in ("DP", "TP", "4P", "DTR"):
                        item.update_visuals()
                else:
                    p_type = "LT" if self.current_tool == "ADD_LT" else "HT"
                    v_level = getattr(self, "active_ht_voltage", "11kV") if self.current_tool == "ADD_HT" else "LT"
                    item = SmartPole(pos.x(), pos.y(), self.refresh_signal, p_type, is_existing=False, detail_view=self.detail_view)
                    item.voltage_level = v_level
                    item.update_visuals()
            elif self.current_tool == "ADD_STRUCTURE":
                st_type = getattr(self, "active_structure_type", "DP")
                item = SmartStructure(pos.x(), pos.y(), self.refresh_signal, detail_view=self.detail_view, structure_type=st_type)
                item.update_visuals()
            else: # ADD_CONSUMER
                item = SmartConsumer(pos.x(), pos.y(), self.refresh_signal, detail_view=self.detail_view)
                
            self.scene.addItem(item)
            self._auto_connect_span(item)
            self.scene.clearSelection()
            item.setSelected(True)
            self.on_selection_changed()
            self.refresh_live_estimate()

        # ── Span drawing ──────────────────────────────────────────────────
        elif self.current_tool == "ADD_SPAN":
            if not isinstance(item_at, (SmartPole, SmartStructure, SmartConsumer)):
                return
            if not self.span_start_pole:
                self.span_start_pole = item_at
                item_at.setPen(QPen(Qt.GlobalColor.yellow, 3))
            elif self.span_start_pole != item_at:
                # Warn on HT↔LT cross-connection
                p1, p2 = self.span_start_pole, item_at
                if self._is_ht_node(p1) != self._is_ht_node(p2):
                     ans = QMessageBox.question(
                         self, "Warning",
                         "Connect HT pole to LT pole?",
                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                     )
                     if ans == QMessageBox.StandardButton.No:
                         return

                ok, reason = self._validate_span_creation(p1, p2)
                if not ok:
                    QMessageBox.information(self, "Span blocked", reason)
                    return

                span = SmartSpan(p1, p2, detail_view=self.detail_view)
                p1.connected_spans.append(span)
                p2.connected_spans.append(span)
                self.scene.addItem(span)
                self.scene.addItem(span.label)
                self.span_start_pole.setPen(QPen(Qt.GlobalColor.black, 1))
                self.span_start_pole = None
                self.scene.clearSelection()
                span.setSelected(True)
                self.on_selection_changed()
                self.refresh_live_estimate()

        # ── Text placement ─────────────────────────────────────────────────
        elif self.current_tool == "ADD_TEXTBOX":
            text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
            if not (ok and text.strip()): return
            item = CanvasTextBox(text.strip(), pos.x(), pos.y())
            self.scene.addItem(item)
            self.scene.clearSelection()
            item.setSelected(True)
            self.on_selection_changed()
            self.set_tool("SELECT")
            self.refresh_live_estimate()

    def _check_placement_blocked(self, pos: QPointF) -> bool:
        if self._find_nearby_node(pos) is not None:
            QMessageBox.information(self, "Placement blocked", "Object is too close to an existing node.")
            return True
        return False

    # =========================================================================
    #  AUTO-CONNECT SPAN HELPER
    # =========================================================================

    # HT-class node types: includes HT poles and all existing structure subtypes
    _HT_SUBTYPES = frozenset({"HT", "DP", "TP", "4P", "DTR"})

    @staticmethod
    def _is_ht_node(node) -> bool:
        from canvas.canvas_ops import is_ht_node
        return is_ht_node(node)

    @staticmethod
    def _is_node_item(item) -> bool:
        return isinstance(item, (SmartPole, SmartStructure, SmartConsumer))

    def _iter_nodes(self):
        return [i for i in self.scene.items() if self._is_node_item(i)]

    def _find_nearby_node(self, pos: QPointF, min_gap: float | None = None):
        from canvas.canvas_ops import find_nearby_node
        gap = float(defaults.current.get("node_min_gap", self._MIN_NODE_GAP)) if min_gap is None else float(min_gap)
        return find_nearby_node(self._iter_nodes(), pos.x(), pos.y(), min_gap=gap)

    @staticmethod
    def _span_other_endpoint(span, node):
        from canvas.canvas_ops import span_other_endpoint
        return span_other_endpoint(span, node)

    def _active_connected_spans(self, node):
        from canvas.canvas_ops import active_connected_spans
        return active_connected_spans(node)

    def _span_exists_between(self, p1, p2) -> bool:
        from canvas.canvas_ops import span_exists_between
        return span_exists_between(p1, p2)

    def _has_path_between(self, start, target) -> bool:
        from canvas.canvas_ops import has_path_between
        return has_path_between(start, target)

    def _validate_span_creation(self, p1, p2):
        from canvas.canvas_ops import validate_span_creation
        return validate_span_creation(p1, p2)


    def _auto_connect_span(self, new_node):
        """
        Called every time a new pole / structure / consumer is placed.
        If a previous node exists (last_placed_node), automatically draw
        a span connecting it to the new node.
        The new node then becomes last_placed_node for the next placement.
        Right-click / switching to SELECT clears the chain.
        """
        prev = self.last_placed_node

        # Remove yellow highlight from previous node
        if prev is not None:
            try:
                prev.setPen(QPen(Qt.GlobalColor.black, 1))
            except RuntimeError:
                prev = None

        if prev is not None and prev is not new_node:
            p1, p2 = prev, new_node

            # HT ↔ LT cross-connection warning
            # DP/TP/4P/DTR existing poles are treated as HT
            if self._is_ht_node(p1) != self._is_ht_node(p2):
                ans = QMessageBox.question(
                    self, "Warning",
                    "Connect HT to LT node?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ans == QMessageBox.StandardButton.No:
                    # Break chain — don't connect, but still update chain start
                    self.last_placed_node = new_node
                    new_node.setPen(QPen(Qt.GlobalColor.yellow, 3))
                    return

            ok, _ = self._validate_span_creation(p1, p2)
            if not ok:
                self.last_placed_node = new_node
                new_node.setPen(QPen(Qt.GlobalColor.yellow, 3))
                return

            span = SmartSpan(p1, p2, detail_view=self.detail_view)
            p1.connected_spans.append(span)
            p2.connected_spans.append(span)
            self.scene.addItem(span)
            self.scene.addItem(span.label)

        # New node becomes the chain anchor — highlighted yellow
        self.last_placed_node = new_node
        new_node.setPen(QPen(Qt.GlobalColor.yellow, 3))

    # =========================================================================
    #  SELECTION / PROPERTY EDITOR
    # =========================================================================

    def on_selection_changed(self):
        try:
            if not self.scene.views():
                return
        except RuntimeError:
            return

        # Clear editor
        while self.editor_layout.count():
            child = self.editor_layout.takeAt(0)
            if child is None:
                continue
            w = child.widget()
            if w is not None:
                w.deleteLater()

        sel = self.scene.selectedItems()
        if not sel:
            self.editor_group.setTitle("Canvas Shortcuts")
            self._build_empty_editor_hint()
            return
        if len(sel) > 1:
            self.editor_group.setTitle(f"{len(sel)} items selected")
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 2)
            lay.addStretch(1)
            del_btn = QPushButton("🗑")
            del_btn.setToolTip(f"Delete {len(sel)} selected items from canvas (Del)")
            del_btn.setFixedSize(24, 20)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet(
                "QPushButton {"
                "  background: #fee2e2;"
                "  color: #dc2626;"
                "  border: 1px solid #fca5a5;"
                "  border-radius: 3px;"
                "  font-size: 11px;"
                "  padding: 0;"
                "}"
                "QPushButton:hover { background: #fecaca; border-color: #ef4444; }"
                "QPushButton:pressed { background: #f87171; color: white; }"
            )
            del_btn.clicked.connect(self.delete_selected_items)
            lay.addWidget(del_btn)
            self.editor_layout.addRow(row)
            return

        item = sel[0]
        if isinstance(item, DraggableLabel):
            self.editor_group.setTitle("Text label")
            self._add_delete_btn(item)
            return

        if isinstance(item, SmartPole):
            self._build_pole_editor(item)
        elif isinstance(item, SmartStructure):
            self._build_structure_editor(item)
        elif isinstance(item, SmartSpan):
            self._build_span_editor(item)
        elif isinstance(item, SmartConsumer):
            self._build_consumer_editor(item)
        elif isinstance(item, CanvasSymbol):
            self._build_symbol_editor(item)
        elif isinstance(item, CanvasTextBox):
            self._build_textbox_editor(item)

        self._normalize_editor_field_sizes()
        self._pack_editor_rows_two_columns()

    def _normalize_editor_field_sizes(self):
        """Keep editor controls visually consistent regardless of content text."""
        fields = self.editor_group.findChildren((QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox))
        for w in fields:
            w.setMinimumHeight(20)
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if isinstance(w, QComboBox):
                w.setMinimumContentsLength(1)
                w.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
                w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                # Prevent accidental value changes when scrolling the panel
                w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                w.installEventFilter(self._combo_wheel_filter)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                w.installEventFilter(self._combo_wheel_filter)

    def _pack_editor_rows_two_columns(self):
        """Compact editor by showing two form entries per visual row."""
        form = self.editor_layout

        entries = []
        for r in range(form.rowCount()):
            li = form.itemAt(r, QFormLayout.ItemRole.LabelRole)
            fi = form.itemAt(r, QFormLayout.ItemRole.FieldRole)
            if li is None and fi is None:
                continue

            lw = li.widget() if li is not None else None
            fw = fi.widget() if fi is not None else None

            if lw is None and fw is not None:
                entries.append(("full", fw))
            elif lw is not None and fw is not None:
                entries.append(("pair", lw, fw))

        # Detach all items from existing form rows before re-adding packed rows.
        while form.count():
            item = form.takeAt(0)
            if item is None:
                continue

        label_w = 72

        def _make_cell(lbl: QWidget, fld: QWidget) -> QWidget:
            cell = QWidget()
            lay = QHBoxLayout(cell)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            if isinstance(lbl, QLabel):
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lbl.setFixedWidth(label_w)
                lbl.setStyleSheet("color:#2f3b45;")
            lay.addWidget(lbl)
            lay.addWidget(fld, 1)
            lay.setStretch(0, 0)
            lay.setStretch(1, 1)
            return cell

        def _make_vline() -> QFrame:
            ln = QFrame()
            ln.setFrameShape(QFrame.Shape.VLine)
            ln.setFrameShadow(QFrame.Shadow.Plain)
            ln.setLineWidth(1)
            ln.setStyleSheet("color:#d9e0e7;")
            return ln

        def _make_full_row_widget(w: QWidget) -> QWidget:
            if isinstance(w, QCheckBox):
                wrap = QWidget()
                l = QHBoxLayout(wrap)
                l.setContentsMargins(label_w + 4, 0, 0, 0)
                l.setSpacing(0)
                l.addWidget(w)
                l.addStretch(1)
                return wrap
            return w

        idx = 0
        while idx < len(entries):
            e1 = entries[idx]
            if e1[0] == "full":
                form.addRow(_make_full_row_widget(e1[1]))
                idx += 1
                continue

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)
            row_l.addWidget(_make_cell(e1[1], e1[2]), 1)
            row_l.addWidget(_make_vline())

            if idx + 1 < len(entries) and entries[idx + 1][0] == "pair":
                e2 = entries[idx + 1]
                row_l.addWidget(_make_cell(e2[1], e2[2]), 1)
                idx += 2
            else:
                pad = QWidget()
                row_l.addWidget(pad, 1)
                idx += 1

            row_l.setStretch(0, 1)
            row_l.setStretch(2, 1)

            form.addRow(row_w)

    def keyPressEvent(self, event):
        sc = getattr(self, "scene", None)
        focus_item = sc.focusItem() if sc is not None else None
        is_editing_text = bool(
            focus_item is not None and
            hasattr(focus_item, "textInteractionFlags") and
            (focus_item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction)
        )
        if is_editing_text:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Shift:
            if self.current_tool != "SELECT":
                self.set_tool("SELECT")
            event.accept()
            return
        # Ctrl+A — select all canvas items
        if (event.key() == Qt.Key.Key_A and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            for item in self.scene.items():
                item.setSelected(True)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_items()
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Shift:
            sc = getattr(self, "scene", None)
            focus_item = sc.focusItem() if sc is not None else None
            is_editing_text = bool(
                focus_item is not None and
                hasattr(focus_item, "textInteractionFlags") and
                (focus_item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction)
            )
            if not is_editing_text and self.current_tool != "SELECT":
                self.set_tool("SELECT")
        return super().eventFilter(obj, event)

    def delete_selected_items(self):
        if getattr(self, "project_locked", False):
            return
        items = self.scene.selectedItems()
        for item in items:
            if isinstance(item, SmartSpan):
                self.delete_item(item)
        for item in items:
            if isinstance(item, (SmartPole, SmartStructure, SmartConsumer)):
                self.delete_item(item)
        for item in items:
            if isinstance(item, (CanvasSymbol, CanvasTextBox)):
                if item.scene():
                    self.scene.removeItem(item)

    def delete_item(self, item):
        if not item or not item.scene():
            return
        if hasattr(item, "connected_spans"):
            for span in list(item.connected_spans):
                if span.label and span.label.scene():
                    self.scene.removeItem(span.label)
                if span.scene():
                    self.scene.removeItem(span)
                for endpoint in (span.p1, span.p2):
                    if hasattr(endpoint, "connected_spans") and span in endpoint.connected_spans:
                        endpoint.connected_spans.remove(span)
        if isinstance(item, SmartSpan):
            # Remove from both endpoints' connected_spans BEFORE taking it off
            # the scene.  Without this, ghost references remain and cause:
            #   1. recalculate_all_span_types promoting a new pole to existing_set
            #      (it sees 2 existing neighbours instead of 1), so any manually
            #      drawn span to that pole is wrongly flagged is_existing_span.
            #   2. _auto_stay_update miscounting active spans, leaving the pole's
            #      stay count unreset after the span is deleted.
            for endpoint in (item.p1, item.p2):
                if hasattr(endpoint, "connected_spans") and item in endpoint.connected_spans:
                    endpoint.connected_spans.remove(item)
            if item.label and item.label.scene():
                self.scene.removeItem(item.label)
        if item.scene():
            self.scene.removeItem(item)
        if isinstance(item, (SmartPole, SmartStructure, SmartConsumer)):
            self._renumber_labels()
        self.refresh_live_estimate()

    # =========================================================================
    #  LIVE ESTIMATE ENGINE
    # =========================================================================

    def recalculate_all_span_types(self):
        """
        Propagation logic: spans between two effectively-existing endpoints
        become existing spans (no BOM contribution).
        """
        from canvas.canvas_ops import recalculate_span_types
        recalculate_span_types(self.scene.items())

    def _auto_stay_update(self):
        """Auto-update stay counts based on span angles."""
        from canvas.canvas_ops import auto_update_stays
        tol = float(defaults.current.get("existing_stay_angle_tolerance_deg", 20.0))
        auto_update_stays(self.scene.items(), angle_tolerance_deg=tol)


    def refresh_live_estimate(self):
        """
        Non-blocking, coalesced refresh.

        Returns immediately so the just-placed / just-moved item paints on the
        next event-loop tick. ALL recalculation — span-type propagation, stay
        auto-update, page grid, rule engine, BOM and the estimate table — runs
        once in _do_refresh_live_estimate after a short debounce, collapsing a
        burst of placements (and every pixel of a drag) into a single pass.

        This is the key to smoothness: span geometry already follows nodes live
        via _on_position_changed, so none of the heavy work needs to block the
        paint that shows the object the moment you click.
        """
        if not self._is_undoing:
            self._history_timer.start(500)
        self._refresh_timer.start(self._REFRESH_DEBOUNCE_MS)

    def _flush_refresh(self):
        """Run any pending refresh synchronously (call before exports / saves)."""
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
            self._do_refresh_live_estimate()

    @staticmethod
    def calculate_bom_static(*args):
        """Headless calculation of the BOM.

        Backwards-compatible wrapper: accepts either a single `state` dict
        or the older signature `(raw_nodes, raw_spans, overrides)`.
        """
        # Normalize arguments into a state dict
        if len(args) == 1:
            state = args[0]
        elif len(args) >= 3:
            raw_nodes, raw_spans, overrides = args[0], args[1], args[2]
            state = {
                "nodes": raw_nodes,
                "spans": raw_spans,
                "overrides": overrides,
            }
        else:
            raise TypeError("calculate_bom_static requires a state dict or (nodes, spans, overrides)")

        app = EstimateApp(headless=True)
        app.parse_load_data(state, fit_view=False)
        app._do_refresh_live_estimate()
        return app.live_bom_data

    def _do_refresh_live_estimate(self):
        if self._refreshing_live:
            return
        self._refreshing_live = True

        try:
            if not getattr(self, "headless", False):
                # Canvas-derived state (cheap-to-moderate). Kept here, off the
                # per-event path, so a drag stays at 60 fps and placements are instant.
                self.recalculate_all_span_types()
                self._auto_stay_update()
                self._refresh_page_grid()

            use_uh        = self.project_meta.get("use_uh", False)
            project_type  = self.project_meta.get("project_type", "NSC")
            sup_rate      = self.project_meta.get("supervision_rate", 0.10)

            # Load rules from database (falls back to empty list on failure)
            from core import db_gateway as _dbg
            rules = _dbg.get_rules()

            canvas_items = [
                i for i in self.scene.items()
                if isinstance(i, (SmartPole, SmartStructure, SmartSpan, SmartConsumer))
            ]

            from core.estimate_service import generate_live_bom
            self.live_bom_data, self.live_bom_provenance = generate_live_bom(
                canvas_items=canvas_items,
                rules=rules,
                rule_engine=self.rule_engine,
                project_meta=self.project_meta,
                bom_overrides=self.bom_overrides
            )

            self._refresh_table()
            self._recalculate_totals(sup_rate)
            if hasattr(self, "_panel_stack") and self._panel_stack.currentIndex() == 1:
                self._refresh_breakup_view()
        finally:
            self._refreshing_live = False

    def _db_lookup(self, cursor, item_type, name, rule_code=None, _prefetched=None):
        from core.estimate_service import db_lookup
        return db_lookup(cursor, item_type, name, rule_code=rule_code, _prefetched=_prefetched)


    @staticmethod
    def _fmt_qty(qty: float, unit: str) -> str:
        from ui.estimate_panel import format_quantity
        return format_quantity(qty, unit)

    def _refresh_table(self):
        if getattr(self, "headless", False):
            return
        try:
            self.live_table.itemChanged.disconnect(self.on_table_edit)
        except TypeError:
            pass

        self.live_table.setUpdatesEnabled(False)
        self.live_table.setRowCount(0)
        f_dense = QFont("Segoe UI", 9)
        f_bold  = QFont("Segoe UI", 9)
        f_bold.setBold(True)

        for i, item in enumerate(self.live_bom_data):
            self.live_table.insertRow(i)
            self.live_table.setRowHeight(i, 20)

            # Col 0: Type (Mat / Lab)
            it_type = item["type"]
            short_type = "Mat" if it_type == "Material" else ("Lab" if it_type == "Labor" else it_type)
            item_0 = QTableWidgetItem(short_type)
            item_0.setFont(f_dense)
            item_0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_0.setForeground(QColor("#1b4f72" if it_type == "Material" else "#78281f"))
            self.live_table.setItem(i, 0, item_0)

            # Col 1: Code
            item_1 = QTableWidgetItem(item["code"])
            item_1.setFont(f_dense)
            item_1.setToolTip(item["code"])
            self.live_table.setItem(i, 1, item_1)

            # Col 2: Name
            item_2 = QTableWidgetItem(item["name"])
            item_2.setFont(f_dense)
            item_2.setToolTip(item["name"])
            self.live_table.setItem(i, 2, item_2)

            # Col 3: Qty
            qty_text = self._fmt_qty(item["qty"], item.get("unit", ""))
            qty_item = QTableWidgetItem(qty_text)
            qty_item.setFont(f_bold)
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            qty_item.setBackground(QColor("#fff8e1"))
            qty_item.setToolTip("Double-click to override quantity")
            self.live_table.setItem(i, 3, qty_item)

            # Col 4: Unit
            item_4 = QTableWidgetItem(item["unit"])
            item_4.setFont(f_dense)
            item_4.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.live_table.setItem(i, 4, item_4)

            # Col 5: Total Amt
            item_5 = QTableWidgetItem(f"{item['amt']:.2f}")
            item_5.setFont(f_dense)
            item_5.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.live_table.setItem(i, 5, item_5)

            for col in (0, 1, 2, 4, 5):
                t = self.live_table.item(i, col)
                if t:
                    t.setFlags(t.flags() & ~Qt.ItemFlag.ItemIsEditable)

        self.live_table.setUpdatesEnabled(True)
        self.live_table.itemChanged.connect(self.on_table_edit)

    # =========================================================================
    #  ESTIMATE TRANSPARENCY  ("where did this number come from?")
    # =========================================================================

    def _on_bom_cell_double_clicked(self, row, col):
        # Column 3 (Qty) is the editable override cell — let it edit, don't hijack.
        if col == 3:
            return
        self._show_bom_provenance(row)

    def _show_bom_provenance_menu(self, pos):
        row = self.live_table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        act = QAction("Where did this come from?", self)
        act.triggered.connect(lambda: self._show_bom_provenance(row))
        menu.addAction(act)
        vp = self.live_table.viewport()
        menu.exec(vp.mapToGlobal(pos) if vp is not None else self.cursor().pos())

    @staticmethod
    def _humanize_condition(cond: str) -> str:
        from ui.estimate_panel import humanize_condition
        return humanize_condition(cond)

    @staticmethod
    def _humanize_formula(formula: str) -> str:
        from ui.estimate_panel import humanize_formula
        return humanize_formula(formula)


    def _show_bom_provenance(self, row):
        if row < 0 or row >= len(self.live_bom_data):
            return
        from ui.estimate_panel import show_bom_provenance_dialog
        item = self.live_bom_data[row]
        show_bom_provenance_dialog(
            parent_widget=self,
            item=item,
            on_refresh_callback=self.refresh_live_estimate,
            canvas_items=self.scene.items() if hasattr(self, "scene") else []
        )


    def change_rate_chart_year(self):
        curr_yr = int(defaults.current.get("rate_chart_base_year", 2026))
        now = datetime.now()
        max_yr = now.year if now.month >= 4 else now.year - 1

        start_yr = min(2018, curr_yr)
        options = []
        for yr in range(start_yr, max_yr + 1):
            options.append(f"{yr}-{str(yr+1)[-2:]}")

        curr_fy_str = f"{curr_yr}-{str(curr_yr+1)[-2:]}"
        try:
            curr_idx = options.index(curr_fy_str)
        except ValueError:
            curr_idx = len(options) - 1

        val_str, ok = QInputDialog.getItem(
            self,
            "Rate Chart Year",
            "Select the Base Financial Year for Escalation calculations:",
            options,
            curr_idx,
            False
        )
        if ok and val_str:
            val = int(val_str.split("-")[0])
            if val != curr_yr:
                defaults.save({"rate_chart_base_year": val})
                self.refresh_live_estimate()

    def _recalculate_totals(self, sup_rate):
        from ui.estimate_panel import calculate_estimate_totals

        base_yr_str = defaults.current.get("rate_chart_base_year", "2026")
        try:
            base_yr = int(base_yr_str)
        except ValueError:
            base_yr = 2026

        totals = calculate_estimate_totals(
            self.live_bom_data,
            sup_rate=sup_rate,
            base_year=base_yr
        )
        self.escalations = totals["escalations"]
        final = totals["final_total"]

        if not getattr(self, "headless", False):
            self.grand_total_label.setText(
                f"<b>Estimated Cost (incl. taxes): Rs. {final:,.2f}</b>"
            )


    def on_table_edit(self, item):
        if item.column() != 3:
            return
        try:
            new_qty   = float(item.text())
            name_item = self.live_table.item(item.row(), 2)
            type_item = self.live_table.item(item.row(), 0)
            if name_item is None or type_item is None:
                return
            name      = name_item.text()
            row_type  = type_item.text()
            self.bom_overrides[name] = {"qty": new_qty, "type": row_type}
            self.refresh_live_estimate()
        except (ValueError, RuntimeError):
            pass

    # =========================================================================
    #  SEARCH / CUSTOM ITEMS
    # =========================================================================

    def open_search(self, item_type):
        dlg = SearchDialog(item_type, self)
        if dlg.exec():
            sel = dlg.get_selected()
            if sel:
                self.bom_overrides[sel["name"]] = {
                    "qty": 1, "type": sel["type"]
                }
                self.refresh_live_estimate()

    def open_settings_dialog(self):
        SettingsDialog(self).exec()

    def open_placement_defaults(self):
        if getattr(self, "project_locked", False):
            QMessageBox.information(self, "Project Locked", "This project has been invoiced and is locked from further edits.")
            return
        PlacementDefaultsDialog(self).exec()

    def open_property_editor(self):
        if getattr(self, "project_locked", False):
            QMessageBox.information(self, "Project Locked", "This project has been invoiced and is locked from further edits.")
            return
        if PropertyEditorDialog(self).exec():
            self.on_selection_changed()

    def open_db_manager(self):
        DatabaseManagerDialog(self).exec()

    def open_rule_manager(self):
        # Collect canvas node data for simulator pre-fill
        canvas_nodes = self.compile_save_data().get("nodes", [])
        RulesetManagerDialog(self, canvas_objects=canvas_nodes).exec()

    def open_recipe_manager(self):
        if RecipeManagerDialog(self).exec():
            # Refresh live estimates immediately
            self.refresh_live_estimate()

    # =========================================================================
    #  EXCEL EXPORT
    # =========================================================================

    def _default_export_dir(self) -> str:
        if getattr(self, "current_project_path", None):
            proj_dir = os.path.dirname(self.current_project_path)
            if os.path.isdir(proj_dir):
                return proj_dir
        saved = str(defaults.current.get("export_last_dir", "") or "").strip()
        if saved and os.path.isdir(saved):
            return saved
        return os.getcwd()

    def _remember_export_path(self, saved_path: str) -> None:
        folder = os.path.dirname(saved_path)
        if not folder:
            return
        if not os.path.isdir(folder):
            return
        defaults.save({"export_last_dir": folder})

    def _open_saved_file(self, file_path: str) -> None:
        try:
            os.startfile(file_path)  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Open File Failed",
                f"Could not open file.\n\n{exc}",
            )

    def _open_saved_folder(self, path: str) -> None:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if not folder:
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Open Folder Failed",
                f"Could not open folder.\n\n{exc}",
            )

    def _safe_subject_stem(self, fallback: str) -> str:
        from core.project_io import sanitize_subject_stem
        return sanitize_subject_stem(self.project_meta.get("subject", ""), fallback)

    def save_project_bundle(self):
        self._flush_refresh()
        if self.scene.itemsBoundingRect().isNull():
            QMessageBox.warning(self, "Empty Canvas", "Nothing to export.")
            return

        # Ensure project is saved locally first
        if not getattr(self, "current_project_path", None):
            folder_key = self.project_meta.get("folder_key", "default").strip()
            import re
            folder_key = re.sub(r'[\\/*?:"<>|]', "_", folder_key)
            stem = self._safe_subject_stem("project")
            project_dir = os.path.join(self._get_drawings_dir(), folder_key)
            os.makedirs(project_dir, exist_ok=True)
            self.current_project_path = os.path.join(project_dir, f"{stem}.json")
            
        self._do_save_to_path(self.current_project_path)

        target_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Folder for Project Bundle",
            self._default_export_dir(),
        )
        if not target_dir:
            return

        stem = self._safe_subject_stem("project")
        json_path = os.path.join(target_dir, f"{stem}.json")
        pdf_path = os.path.join(target_dir, f"{stem}.pdf")
        excel_path = os.path.join(target_dir, f"{stem}_Estimate.xlsx")

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.compile_save_data(), f, indent=2)

            from exporters.pdf import PDFExporter
            from exporters.excel import ExcelExporter
            pdf_saved = PDFExporter(self).export(
                output_path=pdf_path,
                show_success=False,
            )
            excel_saved = ExcelExporter(self).generate(
                output_path=excel_path,
                show_success=False,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Bundle Export Failed",
                f"Could not save project bundle.\n\n{exc}",
            )
            return

        if not pdf_saved or not excel_saved:
            QMessageBox.warning(
                self,
                "Bundle Export Incomplete",
                "PDF or Excel export did not complete. JSON file was still saved.",
            )
            return

        self._remember_export_path(json_path)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Bundle Saved")
        msg.setText(
            "Saved project bundle:\n"
            f"- {json_path}\n"
            f"- {pdf_saved}\n"
            f"- {excel_saved}"
        )
        open_folder_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Close)
        msg.exec()
        if msg.clickedButton() == open_folder_btn:
            self._open_saved_folder(target_dir)

    def generate_excel(self):
        """Delegate to ExcelExporter."""
        self._flush_refresh()
        from exporters.excel import ExcelExporter
        saved_path = ExcelExporter(self).generate(
            initial_dir=self._default_export_dir()
        )
        if saved_path:
            self._remember_export_path(saved_path)

    # =========================================================================
    #  PDF EXPORT
    # =========================================================================

    def export_pdf(self):
        """Delegate to PDFExporter."""
        self._flush_refresh()
        from exporters.pdf import PDFExporter
        saved_path = PDFExporter(self).export(
            initial_dir=self._default_export_dir()
        )
        if saved_path:
            self._remember_export_path(saved_path)

    # =========================================================================
    #  SAVE / LOAD / AUTOSAVE
    # =========================================================================


    def compile_save_data(self):
        from core.project_io import compile_project_state
        view_settings = {
            "ex_len":     self.ex_len_chk.isChecked(),
            "pole_labels": self.pole_label_chk.isChecked(),
            "legend":     self.legend_chk.isChecked(),
            "detail":     self.detail_chk.isChecked(),
            "scale":      self.scale_cb.currentText(),
            "orient":     self.orient_cb.currentText(),
        }
        return compile_project_state(
            scene_items=self.scene.items(),
            project_meta=self.project_meta,
            bom_overrides=self.bom_overrides,
            current_project_path=getattr(self, "current_project_path", None),
            view_settings=view_settings
        )

    def parse_load_data(self, state, fit_view=True):
        self.scene.clear()
        version = state.get("version", 4)
        self.current_project_path = state.get("current_project_path", None)

        if version >= 5:
            saved_meta = state.get("project_meta", {})
            self.project_meta = {**DEFAULT_PROJECT_META, **saved_meta}
        else:
            self.project_meta = dict(DEFAULT_PROJECT_META)
            self.project_meta["subject"] = state.get("subject", "")
            self.project_meta["lat"]     = state.get("lat", "")
            self.project_meta["long"]    = state.get("long", "")
            self.project_meta["use_uh"]  = state.get("uh_toggle", False)

        self._refresh_proj_label()
        self.bom_overrides = state.get("overrides", {})
        node_map = {}

        for nd in state.get("nodes", []):
            ntype = nd.get("type", "Pole")
            x, y  = nd["x"], nd["y"]

            if ntype == "Pole":
                # v4 compat: old DTR poles become SmartStructure
                if nd.get("pole_type") == "DTR":
                    item = SmartStructure(x, y, self.refresh_signal, detail_view=self.detail_view)
                    item.apply_state(nd)
                    item.structure_type = "DTR"
                else:
                    item = SmartPole(x, y, self.refresh_signal, nd.get("pole_type", "LT"), 
                                     nd.get("is_existing", False), detail_view=self.detail_view,
                                     existing_subtype=nd.get("existing_subtype", "LT"))
                    if "voltage_level" in nd:
                        item.voltage_level = nd["voltage_level"]
                    item.apply_state(nd)
            elif ntype == "Structure":
                item = SmartStructure(x, y, self.refresh_signal, detail_view=self.detail_view)
                item.apply_state(nd)
            elif ntype in ("Consumer", "Home"):
                item = SmartConsumer(x, y, self.refresh_signal, detail_view=self.detail_view)
                item.apply_state(nd)
            else:
                continue

            item.update_visuals()
            self.scene.addItem(item)
            node_map[nd["id"]] = item

        for sd in state.get("spans", []):
            p1 = node_map.get(sd["p1_id"])
            p2 = node_map.get(sd["p2_id"])
            if not (p1 and p2):
                continue
            span = SmartSpan(p1, p2, detail_view=self.detail_view)
            span.apply_state(sd)
            span.update_visuals()
            p1.connected_spans.append(span)
            p2.connected_spans.append(span)
            self.scene.addItem(span)
            self.scene.addItem(span.label)

        # ── Annotations (symbols & text boxes) ───────────────────────────
        for ann in state.get("annotations", []):
            try:
                kind = ann.get("kind")
                if kind == "symbol":
                    self.scene.addItem(CanvasSymbol.from_dict(ann))
                elif kind == "textbox":
                    self.scene.addItem(CanvasTextBox.from_dict(ann))
            except Exception:
                pass

        self.refresh_live_estimate()

        # Restore view settings
        vs = state.get("view_settings", {})
        if vs:
            self.ex_len_chk.blockSignals(True)
            self.pole_label_chk.blockSignals(True)
            self.legend_chk.blockSignals(True)
            self.detail_chk.blockSignals(True)
            self.scale_cb.blockSignals(True)
            self.orient_cb.blockSignals(True)

            self.ex_len_chk.setChecked(vs.get("ex_len", True))
            self.pole_label_chk.setChecked(vs.get("pole_labels", True))
            self.legend_chk.setChecked(vs.get("legend", True))
            self.detail_chk.setChecked(vs.get("detail", False))
            if vs.get("scale"):
                self.scale_cb.setCurrentText(vs["scale"])
            if vs.get("orient"):
                self.orient_cb.setCurrentText(vs["orient"])

            self.ex_len_chk.blockSignals(False)
            self.pole_label_chk.blockSignals(False)
            self.legend_chk.blockSignals(False)
            self.detail_chk.blockSignals(False)
            self.scale_cb.blockSignals(False)
            self.orient_cb.blockSignals(False)

            # Apply the restored values to the app state directly
            SmartSpan.show_existing_length = vs.get("ex_len", True)
            self.show_pole_labels = vs.get("pole_labels", True)
            self.detail_view = vs.get("detail", False)

        self._calibrate_label_counters()

        # After loading, optionally fit the view
        if fit_view:
            def _fit_after_load():
                try:
                    b = self.scene.itemsBoundingRect()
                    if not b.isNull():
                        self.view.fitInView(
                            b.adjusted(-60, -60, 60, 60),
                            Qt.AspectRatioMode.KeepAspectRatio
                        )
                except RuntimeError:
                    pass  # view already deleted (e.g. temp EstimateApp in billing)
            QTimer.singleShot(80, _fit_after_load)

    # =========================================================================
    #  LABEL COUNTER HELPERS
    # =========================================================================

    def _renumber_labels(self) -> None:
        """
        After nodes are deleted or canvas is cleared, compact sequential label numbers
        for every category so there are no gaps and reset counters when items are removed.
        """
        buckets: dict = {
            "lt":  [],   # new LT poles
            "ht":  [],   # new HT 11kV poles
            "33":  [],   # new HT 33kV poles
            "DP":  [],
            "TP":  [],
            "4P":  [],
            "DTR": [],
            "con": [],   # consumers
        }
        ex_buckets: dict = {
            "LT": [], "HT": [], "33": [], "DP": [], "TP": [], "4P": [], "DTR": []
        }

        for item in self.scene.items():
            if isinstance(item, SmartPole):
                if item.is_existing:
                    sub = item.existing_subtype
                    ex_buckets.setdefault(sub, []).append(item)
                elif getattr(item, "voltage_level", "11kV") == "33kV":
                    buckets["33"].append(item)
                elif item.pole_type == "LT":
                    buckets["lt"].append(item)
                else:
                    buckets["ht"].append(item)
            elif isinstance(item, SmartStructure):
                st = getattr(item, "structure_type", "DP")
                if st in buckets:
                    buckets[st].append(item)
            elif isinstance(item, SmartConsumer):
                buckets["con"].append(item)

        # Sort each bucket by existing seq_id, then reassign compactly
        for key, group in buckets.items():
            group.sort(key=lambda o: getattr(o, "seq_id", 0))
            for new_id, obj in enumerate(group, start=1):
                if getattr(obj, "seq_id", 0) != new_id:
                    obj.seq_id = new_id
                    obj.update_visuals()

        # Compact existing poles separately by subtype
        for sub, group in ex_buckets.items():
            group.sort(key=lambda o: getattr(o, "seq_id", 0))
            for new_id, obj in enumerate(group, start=1):
                if getattr(obj, "seq_id", 0) != new_id:
                    obj.seq_id = new_id
                    obj.update_visuals()

        # Update class-level counters to match exact scene counts
        SmartPole._lt_seq = len(buckets["lt"])
        SmartPole._ht_seq = len(buckets["ht"])
        SmartPole._33_seq = len(buckets["33"])
        SmartPole._ex_type_seq = {s: len(g) for s, g in ex_buckets.items()}
        SmartStructure._type_seq = {
            "DP":  len(buckets["DP"]),
            "TP":  len(buckets["TP"]),
            "4P":  len(buckets["4P"]),
            "DTR": len(buckets["DTR"]),
        }
        SmartConsumer._con_seq = len(buckets["con"])

    def _calibrate_label_counters(self) -> None:
        """Calibrate class-level counters after loading or clearing drawing state."""
        self._renumber_labels()

    # =========================================================================
    #  UNDO / REDO
    # =========================================================================

    @property
    def _is_undoing(self) -> bool:
        if hasattr(self, "history_mgr"):
            return self.history_mgr.is_undoing
        return False

    @property
    def can_undo(self) -> bool:
        return getattr(self, "history_mgr", None) is not None and self.history_mgr.can_undo

    @property
    def can_redo(self) -> bool:
        return getattr(self, "history_mgr", None) is not None and self.history_mgr.can_redo

    def push_history(self):
        """Capture state and push to undo stack."""
        if hasattr(self, "history_mgr"):
            if self.history_mgr.push():
                self._drawing_dirty = True

    def undo(self):
        if hasattr(self, "history_mgr"):
            self.history_mgr.undo()

    def redo(self):
        if hasattr(self, "history_mgr"):
            self.history_mgr.redo()

    def _show_blank_start_page(self):
        """Show a clean blank A4 page on startup/new drawing with no auto-added objects."""
        self.last_placed_node = None
        self.span_start_pole  = None
        self.refresh_live_estimate()


        def _fit_blank_page():
            tiles = self.view.grid_tiles
            if tiles:
                self.view.fitInView(
                    tiles[0]["rect"].adjusted(-60, -60, 60, 60),
                    Qt.AspectRatioMode.KeepAspectRatio
                )

        QTimer.singleShot(80, _fit_blank_page)

    def new_project(self):
        ans = QMessageBox.question(
            self, "New Project", "Clear canvas and start fresh?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            # Ask for project details immediately (MUST)
            temp_meta = dict(DEFAULT_PROJECT_META)
            dlg = ProjectSetupDialog(temp_meta, self, first_run=True)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                # Abort project creation if setup is cancelled
                return

            # Auto-save current drawing before clearing
            self._save_unsaved_drawing()
            self.scene.clear()
            self.span_start_pole  = None
            self.last_placed_node = None
            self.bom_overrides.clear()
            self.project_meta = dlg.get_meta()
            
            # Formulate the project path immediately!
            folder_key = self.project_meta.get("folder_key", "default").strip()
            import re
            folder_key = re.sub(r'[\\/*?:"<>|]', "_", folder_key)
            stem = self._safe_subject_stem("project")
            project_dir = os.path.join(self._get_drawings_dir(), folder_key)
            os.makedirs(project_dir, exist_ok=True)
            self.current_project_path = os.path.join(project_dir, f"{stem}.json")
            
            self._do_save_to_path(self.current_project_path)
            
            SmartPole.reset_counters()
            SmartStructure.reset_counters()
            SmartConsumer.reset_counters()
            self._drawing_dirty = False
            self._show_blank_start_page()
            self._refresh_proj_label()

    def load_from_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Project", self._get_drawings_dir(), "JSON Files (*.json)"
        )
        if filename:
            with open(filename, "r", encoding="utf-8") as f:
                self.parse_load_data(json.load(f))
            self.current_project_path = filename
            self._drawing_dirty = False
            self._save_project_to_db()
            self._refresh_proj_label()

    def save_to_file(self):
        if getattr(self, "project_locked", False):
            QMessageBox.warning(self, "Project Locked", "This project has been billed/invoiced and is locked from further saving.")
            return
            
        if not getattr(self, "current_project_path", None):
            folder_key = self.project_meta.get("folder_key", "default").strip()
            import re
            folder_key = re.sub(r'[\\/*?:"<>|]', "_", folder_key)
            stem = self._safe_subject_stem("project")
            project_dir = os.path.join(self._get_drawings_dir(), folder_key)
            os.makedirs(project_dir, exist_ok=True)
            self.current_project_path = os.path.join(project_dir, f"{stem}.json")
            
        self._do_save_to_path(self.current_project_path)
        self.statusBar().showMessage(f"Project saved to: {self.current_project_path}", 3000)

    def _do_save_to_path(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.compile_save_data(), f, indent=2)
        self.current_project_path = path
        self._drawing_dirty = False
        self._save_project_to_db()
        self._refresh_proj_label()

    def _save_project_to_db(self):
        if not getattr(self, "current_project_path", None):
            return
        grand_total = self._calc_grand_total()
        m = self.project_meta
        from core import db_gateway as _dbg
        _dbg.save_project_metadata(
            name=m.get("subject", "Unnamed Project"),
            path=self.current_project_path,
            type=m.get("project_type", "NSC"),
            lat=m.get("lat", ""),
            lon=m.get("long", ""),
            cost=grand_total,
            project_id=m.get("project_id", ""),
            po_no=m.get("po_no", ""),
            po_date=m.get("po_date", ""),
            vendor_id=m.get("vendor_id", ""),
            comm_date=m.get("comm_date", ""),
            comp_date=m.get("comp_date", ""),
            meas_date=m.get("meas_date", ""),
            meas_taken_by=m.get("meas_taken_by", ""),
            certified_by=m.get("certified_by", "")
        )

    def _calc_grand_total(self) -> float:
        mat_base = sum(x["amt"] for x in self.live_bom_data if x["type"] == "Material")
        lab_sub  = sum(x["amt"] for x in self.live_bom_data if x["type"] == "Labor")

        now = datetime.now()
        fy_start = now.year if now.month >= 4 else now.year - 1

        base_yr_str = defaults.current.get("rate_chart_base_year", "2026")
        try:
            base_yr = int(base_yr_str)
        except ValueError:
            base_yr = 2026

        cur = mat_base
        for yr in range(base_yr + 1, fy_start + 1):
            esc = cur * 0.05
            cur += esc

        sun      = cur * 0.05
        mat_sub  = cur + sun
        sup_rate = self.project_meta.get("supervision_rate", 0.10)
        sup      = (mat_sub + lab_sub) * sup_rate
        gst      = lab_sub * 0.18
        cess     = (mat_sub + lab_sub + sup) * 0.01
        final    = mat_sub + lab_sub + sup + gst + cess
        return final

    def load_autosave(self):
        loaded_any = False
        if os.path.exists(self.autosave_file):
            try:
                if os.path.getsize(self.autosave_file) > 0:
                    with open(self.autosave_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # If autosave refers to a project file and that file exists,
                    # prefer loading the project file so the app opens the last project.
                    proj_path = data.get("current_project_path")
                    if proj_path and os.path.exists(proj_path):
                        try:
                            with open(proj_path, "r", encoding="utf-8") as pf:
                                pdata = json.load(pf)
                            if pdata.get("nodes") or pdata.get("spans") or pdata.get("annotations"):
                                self.parse_load_data(pdata)
                                loaded_any = True
                        except Exception:
                            # Fallback to autosave if project file can't be read
                            if data.get("nodes") or data.get("spans") or data.get("annotations"):
                                self.parse_load_data(data)
                                loaded_any = True
                    else:
                        # Only load autosave if there is actual canvas content
                        if data.get("nodes") or data.get("spans") or data.get("annotations"):
                            self.parse_load_data(data)
                            loaded_any = True
            except (json.JSONDecodeError, KeyError):
                pass
        # Blank canvas — show a blank A4 page only
        if not loaded_any:
            QTimer.singleShot(100, self._show_blank_start_page)

    def closeEvent(self, event):
        # During a factory reset the data files were just wiped on purpose —
        # don't recreate them on the way out.
        if getattr(self, "_resetting", False):
            super().closeEvent(event)
            return
        # Save working autosave (for session restore)
        with open(self.autosave_file, "w", encoding="utf-8") as f:
            json.dump(self.compile_save_data(), f)
        # Also save a named copy to Documents for the user
        self._save_unsaved_drawing()
        super().closeEvent(event)

    # ── Factory reset ─────────────────────────────────────────────────────

    def reset_all_app_data(self):
        """Restore the app to a fresh-install state after a soft confirmation.

        Wipes the current drawing + autosave, all placement defaults/settings,
        and the master database (custom rules, recipes, materials, rate edits),
        then re-seeds factory data. The app closes afterwards for a clean start.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Reset App Data?")
        box.setText("Restore the app to a fresh install?")
        box.setInformativeText(
            "This will permanently clear:\n"
            "   •  the current drawing and autosave\n"
            "   •  all placement defaults and settings\n"
            "   •  all custom rules, recipes, materials and rate edits\n\n"
            "Factory data will be restored. This can't be undone.\n"
            "The app will close when done — just reopen it to start fresh."
        )
        proceed_btn = box.addButton("Reset Everything", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        if box.clickedButton() is not proceed_btn:
            return

        ok, err = self._perform_full_reset()
        if not ok:
            QMessageBox.critical(
                self,
                "Reset Failed",
                "Could not complete the reset. Some files may be in use.\n\n"
                f"{err}\n\nPlease close the app and try again.",
            )
            return

        self._resetting = True   # closeEvent must not rewrite autosave
        QMessageBox.information(
            self,
            "Reset Complete",
            "All data has been restored to factory defaults.\n\n"
            "The app will now close. Please reopen it to start fresh.",
        )
        self.close()

    def _perform_full_reset(self) -> tuple[bool, str]:
        """Wipe all user data and re-seed factory data. Returns (ok, error)."""
        try:
            from core.database import setup_database
            from core import db_gateway as _dbg
            from app_config import get_user_data_path

            # 1. In-memory state
            self.scene.clear()
            self.bom_overrides.clear()
            self.history.clear()
            self.history_index = -1
            self.live_bom_data = []
            self.span_start_pole = None
            self.last_placed_node = None
            self.project_meta = dict(DEFAULT_PROJECT_META)
            SmartPole.reset_counters()
            SmartStructure.reset_counters()
            SmartConsumer.reset_counters()

            # 2. Drop the in-memory caches that mirror DB content
            _dbg._invalidate_rules_cache()
            _dbg._invalidate_sections_cache()

            # 3. Delete data files (DB + its WAL/SHM sidecars, autosave, defaults)
            targets = [
                self.autosave_file,
                DB_PATH,
                DB_PATH + "-wal",
                DB_PATH + "-shm",
                get_user_data_path("defaults.json"),
            ]
            for path in targets:
                if path and os.path.exists(path):
                    os.remove(path)   # raises on lock → reported to user

            # 4. Recreate + re-seed a fresh factory database
            setup_database()

            # 5. Reload factory defaults into memory
            defaults.load()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    # ── Auto-save helpers ────────────────────────────────────────────────

    @staticmethod
    def _get_drawings_dir() -> str:
        """Return (and create) the ERP_Estimates folder inside the user's Documents directory."""
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        drawings_dir = os.path.join(docs, "ERP_Estimates")
        os.makedirs(drawings_dir, exist_ok=True)
        return drawings_dir

    def _save_unsaved_drawing(self) -> None:
        """Save the current canvas state to Documents/ERP_Estimates/unsavedN.json.

        Picks the next available number (unsaved1.json, unsaved2.json, …).
        Skips silently if the canvas is empty.
        """
        try:
            # Skip if nothing was modified since last save/load
            if not self._drawing_dirty:
                return

            data = self.compile_save_data()
            # Don't save if there's nothing on the canvas
            if not data.get("nodes") and not data.get("spans") and not data.get("annotations"):
                return

            # If this session is associated with a project file, write the
            # working state back into that project JSON so the work stays with
            # the project instead of creating untidy files in Documents.
            target = None
            if getattr(self, "current_project_path", None):
                try:
                    proj_path = self.current_project_path
                    # Read existing project file if present, merge minimal fields
                    proj_data = {}
                    if os.path.exists(proj_path):
                        try:
                            with open(proj_path, "r", encoding="utf-8") as pf:
                                proj_data = json.load(pf)
                        except Exception:
                            proj_data = {}
                    # Update core canvas state fields
                    proj_data.update({
                        "version": data.get("version", proj_data.get("version", 5)),
                        "project_meta": data.get("project_meta", proj_data.get("project_meta", {})),
                        "overrides": data.get("overrides", proj_data.get("overrides", {})),
                        "nodes": data.get("nodes", proj_data.get("nodes", [])),
                        "spans": data.get("spans", proj_data.get("spans", [])),
                        "annotations": data.get("annotations", proj_data.get("annotations", [])),
                        "current_project_path": proj_path,
                    })
                    with open(proj_path, "w", encoding="utf-8") as pf:
                        json.dump(proj_data, pf, indent=2)
                    target = proj_path
                except Exception as exc:
                    print(f"[AutoSave] Could not write into project file {self.current_project_path}: {exc}")

            # Fallback: if not associated with a project file, continue saving
            # the traditional unsavedN.json into Documents for session restore.
            if not target:
                drawings_dir = self._get_drawings_dir()
                n = 1
                while os.path.exists(os.path.join(drawings_dir, f"unsaved{n}.json")):
                    n += 1
                target = os.path.join(drawings_dir, f"unsaved{n}.json")
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception as exc:
            # Never crash the app because of auto-save
            print(f"[AutoSave] Could not save drawing: {exc}")

    # =========================================================================
    #  INFO DIALOGS
    # =========================================================================

    def show_about_dialog(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("About")
        logo_path = resource_path("assets/logo.svg")
        if os.path.exists(logo_path):
            pix = QPixmap(logo_path).scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            dlg.setIconPixmap(pix)
        dlg.setText(
            f"""
        <h2>{APP_DISPLAY_NAME} v{APP_VERSION}</h2>
        <p>Interactive electrical network estimation tool for WBSEDCL projects.</p>
        <ul>
            <li>Project type-based supervision rates</li>
            <li>SmartPole, SmartStructure, SmartSpan, SmartConsumer objects</li>
            <li>Dynamic rule engine with JSON ruleset</li>
            <li>Iron breakup sheet in Excel export</li>
            <li>PDF drawings with legend</li>
        </ul>
        <p><b>Developed by: {APP_AUTHOR}</b></p>
        """
        )
        dlg.exec()

    def show_credits(self):
        QMessageBox.information(self, "Credits", """
        <h2 style='color:#3498db;'>Contributors</h2>
        <ul>
            <li><b>Praful Singh</b> — Visual improvements, PDF legend</li>
            <li><b>Rajsekhar Gorai</b> — 8mtr HT pole extension logic</li>
            <li><b>Amit Karmakar</b> — DTR properties, Lat/Long fields</li>
            <li><b>Santanu Das</b> — Providing data, manuals, circulars for proper integration</li>
            <li><b>Sourabh Jaiswal</b> — Suggesting HT LT restrictions</li>
            <li><b>Prakash</b> — CG symbol design</li>
            <li><b>Arindra</b> — DP/DTR rotation feature</li>
        </ul>
        <p style='font-style:italic;'>Thanks to all who provided feedback!</p>
        """)

    def show_help(self):
        help_path = resource_path("assets/HELP.html")
        if os.path.exists(help_path):
            with open(help_path, "r", encoding="utf-8") as f:
                html = f.read()
            html = (
                html.replace("{{APP_DISPLAY_NAME}}", APP_DISPLAY_NAME)
                    .replace("{{APP_VERSION}}", APP_VERSION)
                    .replace("{{APP_AUTHOR}}", APP_AUTHOR)
            )
        else:
            html = "<h2>Help file not found</h2><p>HELP.html is missing.</p>"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"User Guide — {APP_DISPLAY_NAME}")
        dlg.resize(820, 650)
        lay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        lay.addWidget(browser)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setStyleSheet(
            "padding:6px 20px; font-weight:bold; background:#3498db; color:white;"
        )
        lay.addWidget(close_btn)
        dlg.exec()

    # =========================================================================
    #  AUTO-UPDATE (GitHub Releases)
    # =========================================================================

    def maybe_check_for_updates_on_startup(self):
        from ui.auto_updater import AutoUpdaterController
        AutoUpdaterController(self).maybe_check_for_updates_on_startup()

    def check_for_updates(self):
        from ui.auto_updater import AutoUpdaterController
        AutoUpdaterController(self).check_for_updates()

    def open_user_profiles_dialog(self):
        from ui.dialogs.user_profile import UserProfileDialog
        dlg = UserProfileDialog(self)
        dlg.exec()

    def open_my_projects_dialog(self):
        from ui.dialogs.project_manager import ProjectManagerDialog
        dlg = ProjectManagerDialog(self)
        dlg.exec()

    def open_billing_dialog(self):
        try:
            from ui.dialogs.billing import BillingDialog
            dlg = BillingDialog(self)
            dlg.exec()
        except Exception as _exc:
            import traceback as _tb
            try:
                log_path = get_user_data_path("last_runtime_error.log")
                with open(log_path, "w", encoding="utf-8") as fh:
                    fh.write(f"{APP_DISPLAY_NAME} v{APP_VERSION}\n")
                    fh.write(f"{datetime.now().isoformat()}\n\n")
                    fh.write("".join(_tb.format_exception(type(_exc), _exc, _exc.__traceback__)))
            except Exception:
                pass
            try:
                QMessageBox.critical(
                    self,
                    f"{APP_DISPLAY_NAME} — Error",
                    f"Failed to open Billing dialog:\n{type(_exc).__name__}: {_exc}\n\nDetails written to: {log_path if 'log_path' in locals() else '(n/a)'}",
                )
            except Exception:
                pass

    def open_completion_cert_dialog(self):
        from ui.dialogs.billing import CompletionCertificateDialog
        dlg = CompletionCertificateDialog(self)
        dlg.exec()

    def open_all_projects_report(self):
        from ui.dialogs.billing import generate_all_projects_report
        generate_all_projects_report(self)

    def _check_profile_on_startup(self):
        from core import db_gateway as _dbg
        profiles = _dbg.get_user_profiles()
        if not profiles:
            QMessageBox.information(
                self, "Welcome",
                "Welcome to ERP Estimate Generator!\n\n"
                "Please take a moment to configure your organization profile (Name, GSTIN, Address, and Signature) "
                "which will be used to automatically personalize export files and generated invoices."
            )
            self.open_user_profiles_dialog()


def _log_startup_crash(exc: BaseException) -> None:
    """Persist a full startup traceback so windowed (no-console) builds are
    diagnosable, and show the user a dialog with the cause.

    PyInstaller ``--windowed`` builds have no console, so an import error (or
    any startup exception) otherwise dies silently. This writes the traceback
    to ``%APPDATA%/ERP_Estimate/last_crash.log`` and surfaces it in a dialog.
    """
    import traceback as _tb
    detail = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
    try:
        log_path = get_user_data_path("last_crash.log")
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(f"{APP_DISPLAY_NAME} v{APP_VERSION}\n")
            fh.write(f"{datetime.now().isoformat()}\n\n")
            fh.write(detail)
    except Exception:
        log_path = "(could not write crash log)"
    # Best-effort dialog — may itself fail if Qt never initialised.
    try:
        if QApplication.instance() is None:
            QApplication(sys.argv)
        QMessageBox.critical(
            None,
            f"{APP_DISPLAY_NAME} — Startup Error",
            f"The application failed to start:\n\n{type(exc).__name__}: {exc}\n\n"
            f"Details written to:\n{log_path}",
        )
    except Exception:
        pass


def main() -> int:
    if not check_expiry():
        return 1

    # ── Single-instance enforcement (Windows named mutex) ────────────
    # The handle is intentionally kept alive for the process lifetime; Windows
    # releases the mutex automatically on exit (including the updater's exit).
    global _single_instance_mutex
    _single_instance_mutex = None
    if sys.platform == "win32":
        import ctypes
        _single_instance_mutex = ctypes.windll.kernel32.CreateMutexW(
            None, True, "Global\\ERP_Estimate_Generator_SingleInstance"
        )
        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            # Another instance is running — show a simple message and exit
            _tmp_app = QApplication(sys.argv)
            QMessageBox.warning(
                None,
                "Already Running",
                f"{APP_DISPLAY_NAME} is already running.\n"
                "Please switch to the existing window.",
            )
            return 0

    # Install a Qt message handler to turn Qt warnings/errors into Python
    # exceptions so they generate tracebacks we can inspect during debugging.
    try:
        from PyQt6.QtCore import qInstallMessageHandler

        def _qt_msg_handler(msg_type, context, message):
            try:
                import traceback as _tb
                log_path = get_user_data_path("qt_messages.log")
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"--- Qt Message ---\n")
                    fh.write(f"Type: {msg_type}\n")
                    try:
                        fh.write(f"File: {context.file} Line: {context.line} Func: {context.function}\n")
                    except Exception:
                        pass
                    fh.write(f"Message: {message}\n")
                    fh.write("Python stack:\n")
                    fh.write("".join(_tb.format_stack()))
                    fh.write("\n")
            except Exception:
                pass

        qInstallMessageHandler(_qt_msg_handler)
    except Exception:
        # Best-effort; continue if qInstallMessageHandler is unavailable.
        pass

    # Install a global exception hook to capture uncaught exceptions during runtime
    def _global_excepthook(exc_type, exc_value, exc_tb):
        import traceback as _tb
        try:
            log_path = get_user_data_path("last_runtime_error.log")
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(f"{APP_DISPLAY_NAME} v{APP_VERSION}\n")
                fh.write(f"{datetime.now().isoformat()}\n\n")
                fh.write("".join(_tb.format_exception(exc_type, exc_value, exc_tb)))
        except Exception:
            pass
        # fallback to default
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _global_excepthook

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = EstimateApp()
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as _exc:  # noqa: BLE001 — top-level safety net
        _log_startup_crash(_exc)
        sys.exit(1)
