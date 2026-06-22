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
from datetime import datetime, date

# pyrefly: ignore [missing-import]
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QGraphicsScene,
    QFormLayout, QGroupBox, QSpinBox, QLineEdit,
    QFileDialog, QMessageBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QGraphicsView,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QScrollArea,
    QFrame, QMenu, QTextBrowser, QInputDialog, QSizePolicy, QStyle, QSlider,
    QStackedWidget, QProgressDialog
)
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainter, QFont,
    QAction, QKeySequence, QIcon, QPixmap
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QEvent, QSize, pyqtSignal, QThread

from core.constants import (
    TOOLS, PROJECT_TYPES, SUPERVISION_RATES, 
    HEIGHT_OPTIONS, CONDUCTOR_SIZES, SERVICE_CABLE_SIZES,
    SAG_ITEMS
)
from core import defaults
from core.expiry import check_expiry
from app_config import (
    APP_DISPLAY_NAME, APP_NAME, APP_VERSION, APP_AUTHOR, APP_EXPIRY,
    get_data_path, get_user_data_path
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
}


# ─────────────────────────────────────────────────────────────────────────────
#  AUTO-UPDATE WORKER THREADS
# ─────────────────────────────────────────────────────────────────────────────
class _UpdateCheckThread(QThread):
    """Query GitHub Releases off the UI thread. Emits the result dict or None."""
    done = pyqtSignal(object)

    def run(self):
        try:
            from core.updater import check_for_update
            self.done.emit(check_for_update())
        except Exception:
            self.done.emit(None)


class _UpdateDownloadThread(QThread):
    """Download the installer off the UI thread, reporting progress."""
    progress = pyqtSignal(int, int)   # downloaded, total
    finished_path = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            from core.updater import download_installer
            path = download_installer(
                self._url, lambda d, t: self.progress.emit(d, t)
            )
            self.finished_path.emit(path)
        except Exception as exc:
            self.failed.emit(str(exc))


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

    def __init__(self):
        super().__init__()

        setup_database()
        defaults.load()

        # ── Project-level state ────────────────────────────────────────────
        self.project_meta   = dict(DEFAULT_PROJECT_META)
        self.bom_overrides  = {}
        self.live_bom_data  = []
        self.escalations    = []
        self.detail_view    = True          # show stay/earth/CG symbols
        self.span_start_pole = None
        self.last_placed_node = None        # for auto-span chain when placing nodes
        self.autosave_file  = "autosave_erp.json"
        self._drawing_dirty = False            # True when canvas has unsaved changes
        self._resetting     = False            # True during a factory reset (skips close autosave)
        self.current_tool   = "SELECT"
        self._pending_symbol_shape = "circle"   # last chosen symbol shape

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
        self.history = []
        self.history_index = -1
        self._is_undoing = False
        self._refreshing_live = False
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.timeout.connect(self.push_history)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh_live_estimate)

        self.grid_manager = GridManager(self)

        # ── Build UI ───────────────────────────────────────────────────────
        self.setWindowTitle(f"{APP_DISPLAY_NAME} — v{APP_VERSION}")
        self.setGeometry(50, 50, 1650, 930)
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

    # =========================================================================
    #  MENU BAR
    # =========================================================================

    def _build_menu_bar(self):
        mb = self.menuBar()
        assert mb is not None
        mb.setStyleSheet("""
            QMenuBar {
                background: #ffffff;
                border-bottom: 1px solid #e0e0e0;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                padding: 2px 0px;
            }
            QMenuBar::item {
                padding: 4px 10px;
                background: transparent;
                border-radius: 3px;
            }
            QMenuBar::item:selected {
                background: #e8e8e8;
                color: #1a1a1a;
            }
            QMenuBar::item:pressed {
                background: #d0d0d0;
            }
            QMenu {
                background: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 6px 24px 6px 16px;
                color: #1a1a1a;
            }
            QMenu::item:selected {
                background: #0078d4;
                color: #ffffff;
                border-radius: 2px;
            }
            QMenu::item:disabled {
                color: #a0a0a0;
            }
            QMenu::separator {
                height: 1px;
                background: #e8e8e8;
                margin: 3px 8px;
            }
        """)

        # ── File ──────────────────────────────────────────────────────────
        file_menu = mb.addMenu("&File")
        assert file_menu is not None

        act_new = QAction("New Drawing", self)
        act_new.setShortcut(QKeySequence("Ctrl+N"))
        act_new.triggered.connect(self.new_drawing)
        file_menu.addAction(act_new)

        act_open = QAction("Open…", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self.load_from_file)
        file_menu.addAction(act_open)

        act_save = QAction("Save…", self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self.save_to_file)
        file_menu.addAction(act_save)

        act_save_bundle = QAction("Save Project Bundle…", self)
        act_save_bundle.triggered.connect(self.save_project_bundle)
        file_menu.addAction(act_save_bundle)

        file_menu.addSeparator()

        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_undo.triggered.connect(self.undo)
        file_menu.addAction(self.act_undo)

        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self.act_redo.triggered.connect(self.redo)
        file_menu.addAction(self.act_redo)

        file_menu.addSeparator()

        act_exit = QAction("Exit", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # ── Export ────────────────────────────────────────────────────────
        export_menu = mb.addMenu("E&xport")
        assert export_menu is not None

        act_pdf = QAction("Export PDF Drawing", self)
        act_pdf.triggered.connect(self.export_pdf)
        export_menu.addAction(act_pdf)

        act_xl = QAction("Generate Excel Estimate", self)
        act_xl.triggered.connect(self.generate_excel)
        export_menu.addAction(act_xl)

        act_bundle = QAction("Save PDF + Excel + JSON Bundle", self)
        act_bundle.triggered.connect(self.save_project_bundle)
        export_menu.addAction(act_bundle)

        # ── Settings ─────────────────────────────────────────────────────
        settings_menu = mb.addMenu("&Settings")
        assert settings_menu is not None

        act_proj = QAction("Project Settings", self)
        act_proj.triggered.connect(lambda: self._run_project_wizard(first_run=False))
        settings_menu.addAction(act_proj)

        settings_menu.addSeparator()

        act_db = QAction("Master Database", self)
        act_db.triggered.connect(self.open_db_manager)
        settings_menu.addAction(act_db)

        act_rules = QAction("Ruleset Manager", self)
        act_rules.triggered.connect(self.open_rule_manager)
        settings_menu.addAction(act_rules)

        settings_menu.addSeparator()

        act_year = QAction("Rate Chart Year", self)
        act_year.triggered.connect(self.change_rate_chart_year)
        settings_menu.addAction(act_year)

        act_defs = QAction("Placement Defaults", self)
        act_defs.triggered.connect(self.open_placement_defaults)
        settings_menu.addAction(act_defs)

        act_recipes = QAction("Iron Recipes Manager", self)
        act_recipes.triggered.connect(self.open_recipe_manager)
        settings_menu.addAction(act_recipes)

        act_props = QAction("Property Editor", self)
        act_props.triggered.connect(self.open_property_editor)
        settings_menu.addAction(act_props)

        settings_menu.addSeparator()

        act_reset = QAction("Reset App Data (Factory Reset)…", self)
        act_reset.setToolTip("Clear all data and restore the app to a fresh install")
        act_reset.triggered.connect(self.reset_all_app_data)
        settings_menu.addAction(act_reset)

        # ── Help ──────────────────────────────────────────────────────────
        help_menu = mb.addMenu("&Help")
        assert help_menu is not None

        act_help = QAction("User Guide", self)
        act_help.setShortcut(QKeySequence("F1"))
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)

        help_menu.addSeparator()

        act_update = QAction("Check for Updates…", self)
        act_update.triggered.connect(self.check_for_updates)
        help_menu.addAction(act_update)

        help_menu.addSeparator()

        act_credits = QAction("Credits", self)
        act_credits.triggered.connect(self.show_credits)
        help_menu.addAction(act_credits)

        act_about = QAction("About", self)
        act_about.triggered.connect(self.show_about_dialog)
        help_menu.addAction(act_about)

        help_menu.addSeparator()

        exp_str = f"Valid Till: {APP_EXPIRY}" if APP_EXPIRY else "Permanent Build"
        act_valid = QAction(exp_str, self)
        act_valid.setEnabled(False)
        help_menu.addAction(act_valid)

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
        self.splitter.addWidget(left_panel)

        left_layout.addLayout(self._build_icon_ribbon())
        left_layout.addLayout(self._build_draw_toolbar())

        self.scene = QGraphicsScene()
        self.view  = InteractiveView(self.scene, self)
        left_layout.addWidget(self.view)

        # ── Bottom canvas control bar ──────────────────────────────────────
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)
        bottom_bar.setContentsMargins(2, 0, 2, 0)

        # Show Symbols checkbox
        self.detail_chk = QCheckBox("Show Symbols")
        self.detail_chk.setChecked(True)
        self.detail_chk.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#555; spacing:4px;"
        )
        self.detail_chk.toggled.connect(self._toggle_detail_view)
        bottom_bar.addWidget(self.detail_chk)

        # Separator
        sep1 = QLabel("|");
        sep1.setStyleSheet("color:#ccc; font-size:14px;")
        bottom_bar.addWidget(sep1)

        # Page Grid toggle
        self.grid_chk = QCheckBox("Page Grid")
        self.grid_chk.setChecked(True)
        self.grid_chk.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#3a7bd5; spacing:4px;"
        )
        self.grid_chk.toggled.connect(self._toggle_page_grid)
        bottom_bar.addWidget(self.grid_chk)

        # Crosshatch toggle
        self.hatch_chk = QCheckBox("Crosshatch")
        self.hatch_chk.setChecked(True)
        self.hatch_chk.setStyleSheet(
            "font-size:11px; color:#555; spacing:4px;"
        )
        self.hatch_chk.toggled.connect(self._toggle_crosshatch)
        bottom_bar.addWidget(self.hatch_chk)

        # Separator
        sep2 = QLabel("|");
        sep2.setStyleSheet("color:#ccc; font-size:14px;")
        bottom_bar.addWidget(sep2)

        # Scale label + dropdown
        bottom_bar.addWidget(QLabel("Print Scale:"))
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
            "font-size:11px; font-weight:bold; color:#1a5276;"
        )
        bottom_bar.addWidget(self.scale_cb)

        # Orientation mode
        bottom_bar.addWidget(QLabel("Orientation:"))
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
        self.orient_cb.setStyleSheet("font-size:11px; color:#1a5276;")
        bottom_bar.addWidget(self.orient_cb)

        self.page_override_btn = QPushButton("Page Overrides")
        self.page_override_btn.setToolTip(
            "Set manual orientation for specific pages, e.g. 2:P, 5:L.\n"
            "Note: overrides that conflict with current grid geometry are ignored."
        )
        self.page_override_btn.setStyleSheet(
            "font-size:10px; padding:3px 6px;"
        )
        self.page_override_btn.clicked.connect(self._edit_page_overrides)
        bottom_bar.addWidget(self.page_override_btn)

        # Separator
        sep3 = QLabel("|")
        sep3.setStyleSheet("color:#ccc; font-size:14px;")
        bottom_bar.addWidget(sep3)

        # GPS Background toggle
        self.gps_bg_chk = QCheckBox("GPS BG")
        self.gps_bg_chk.setChecked(False)
        self.gps_bg_chk.setToolTip("Show OpenStreetMap background for the project lat/long")
        self.gps_bg_chk.setStyleSheet("font-size:11px; font-weight:bold; color:#d35400; spacing:4px;")
        self.gps_bg_chk.toggled.connect(self._toggle_gps_bg)
        bottom_bar.addWidget(self.gps_bg_chk)

        self.gps_zoom_cb = QComboBox()
        self.gps_zoom_cb.addItems(["Zoom 17", "Zoom 18", "Zoom 19", "Zoom 20", "Zoom 21"])
        self.gps_zoom_cb.setCurrentText("Zoom 19")
        self.gps_zoom_cb.setEnabled(False)
        self.gps_zoom_cb.currentTextChanged.connect(self._change_gps_zoom)
        self.gps_zoom_cb.setStyleSheet("font-size:11px; font-weight:bold; color:#1a5276;")
        self.gps_zoom_cb.setToolTip("Map Resolution Level")
        bottom_bar.addWidget(self.gps_zoom_cb)

        self.gps_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.gps_opacity_slider.setRange(10, 100)
        self.gps_opacity_slider.setValue(50)
        self.gps_opacity_slider.setFixedWidth(80)
        self.gps_opacity_slider.setToolTip("Background Opacity")
        self.gps_opacity_slider.setEnabled(False)
        self.gps_opacity_slider.valueChanged.connect(self._change_gps_opacity)
        bottom_bar.addWidget(self.gps_opacity_slider)

        bottom_bar.addStretch()
        left_layout.addLayout(bottom_bar)

        # Right: properties + estimate table
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(right_splitter)
        self.splitter.setSizes([1000, 650])

        right_splitter.addWidget(self._build_properties_panel())
        right_splitter.addWidget(self._build_estimate_panel())
        right_splitter.setSizes([320, 680])

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
        bar.setSpacing(3)
        self.tools_btns = {}
        for key, txt in TOOLS.items():
            btn = QPushButton(txt)
            btn.clicked.connect(lambda checked, t=key: self.set_tool(t))
            btn.setStyleSheet(
                "padding:7px 5px; font-weight:bold; background:lightgray;"
            )
            bar.addWidget(btn)
            self.tools_btns[key] = btn

        # Thin visual separator
        sep = QLabel("|")
        sep.setStyleSheet("color:#bbb; font-size:16px; padding:0 4px;")
        bar.addWidget(sep)

        # ── Symbol button ──────────────────────────────────────────────────
        sym_btn = QPushButton("⬡ Symbol")
        sym_btn.setToolTip("Place a decorative symbol on the canvas (circle, square, arrow, line)")
        sym_btn.setStyleSheet(
            "padding:7px 10px; font-weight:bold;"
            "background:#eaf7ea; color:#1e8449; border-radius:3px;"
        )
        sym_btn.clicked.connect(self._show_symbol_picker)
        bar.addWidget(sym_btn)
        self.tools_btns["ADD_SYMBOL"] = sym_btn

        # ── Text Box button ────────────────────────────────────────────────
        txt_btn = QPushButton("T Text")
        txt_btn.setToolTip("Place a draggable text box on the canvas")
        txt_btn.setStyleSheet(
            "padding:7px 10px; font-weight:bold;"
            "background:#fef9e7; color:#7d6608; border-radius:3px;"
        )
        txt_btn.clicked.connect(lambda: self.set_tool("ADD_TEXTBOX"))
        bar.addWidget(txt_btn)
        self.tools_btns["ADD_TEXTBOX"] = txt_btn

        # Thin visual separator
        sep2 = QLabel("|")
        sep2.setStyleSheet("color:#bbb; font-size:16px; padding:0 4px;")
        bar.addWidget(sep2)

        # Fit-View button — also triggered by F key on the canvas
        fit_btn = QPushButton("⬡ Fit View")
        fit_btn.setToolTip(
            "Fit all drawing content in view  [F or Ctrl+0]\n"
            "Useful after zooming out too far or after loading a project."
        )
        fit_btn.setStyleSheet(
            "padding:7px 10px; font-weight:bold;"
            "background:#d5e8f7; color:#1a5276; border-radius:3px;"
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
                  ("╌ Dashed Line", "dashed_line")]
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
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 0)
        lay.setSpacing(4)

        # Project info strip with edit button
        info_row = QHBoxLayout()
        info_row.setSpacing(0)
        self.proj_info_label = QLabel()
        self.proj_info_label.setWordWrap(True)
        self.proj_info_label.setMinimumWidth(0)
        self.proj_info_label.setStyleSheet(
            "font-size:11px; color:#555; padding:3px 5px;"
            "background:#f0f0f0; border-radius:3px 0 0 3px;"
        )
        info_row.addWidget(self.proj_info_label, 1)

        edit_btn = QPushButton("✏️")
        edit_btn.setToolTip("Edit Project Settings")
        edit_btn.setFixedSize(28, 24)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet(
            "QPushButton { background:#f0f0f0; border:1px solid #ccc;"
            "  border-left:none; border-radius:0 3px 3px 0; font-size:13px; }"
            "QPushButton:hover { background:#d5e8f7; }"
        )
        edit_btn.clicked.connect(lambda: self._run_project_wizard(first_run=False))
        info_row.addWidget(edit_btn)
        lay.addLayout(info_row)
        self._refresh_proj_label()

        # Object property editor
        self.editor_group = QGroupBox("Object Properties")
        self.editor_layout = QFormLayout()
        self.editor_layout.setSpacing(3)
        self.editor_layout.setHorizontalSpacing(6)
        self.editor_layout.setVerticalSpacing(3)
        self.editor_layout.setContentsMargins(6, 4, 6, 4)
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
            "QGroupBox { font-size:11px; }"
            "QLabel { font-size:11px; }"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {"
            "  min-height:22px; padding:1px 4px; font-size:11px;"
            "}"
            "QPushButton { min-height:22px; padding:2px 6px; font-size:11px; }"
            "QCheckBox { font-size:11px; spacing:6px; min-height:22px; }"
            "QCheckBox::indicator { width:14px; height:14px; }"
        )

        # Property editor UX prefs (kept simple and session-local)
        self._show_advanced_pole_props = False

        scroll = QScrollArea()
        self.editor_scroll = scroll
        scroll.setWidget(self.editor_group)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(scroll)

        return w

    def _build_estimate_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 0, 6, 6)
        lay.setSpacing(4)

        # ── Header row: title + toggle buttons ────────────────────────────────
        hdr_row = QHBoxLayout()
        self._panel_title_label = QLabel("<b>Live Estimate</b> (double-click Qty to edit)")
        hdr_row.addWidget(self._panel_title_label, 1)

        self._btn_show_estimate = QPushButton("Estimate")
        self._btn_show_breakup  = QPushButton("Iron Breakup")
        for btn, active in [(self._btn_show_estimate, True), (self._btn_show_breakup, False)]:
            btn.setCheckable(True)
            btn.setChecked(active)
            btn.setStyleSheet(
                "QPushButton{padding:3px 8px; border-radius:4px; font-size:11px;}"
                "QPushButton:checked{background:#1F4E79; color:white; font-weight:bold;}"
                "QPushButton:!checked{background:#d0d0d0; color:#333;}"
            )
        self._btn_show_estimate.clicked.connect(lambda: self._switch_panel_view(0))
        self._btn_show_breakup.clicked.connect(lambda: self._switch_panel_view(1))
        hdr_row.addWidget(self._btn_show_estimate)
        hdr_row.addWidget(self._btn_show_breakup)
        lay.addLayout(hdr_row)

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
            ["Type", "Code", "Name", "Qty", "Unit", "Total (Rs)"]
        )
        live_hdr = self.live_table.horizontalHeader()
        assert live_hdr is not None
        live_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.live_table.setColumnWidth(0, 65)
        self.live_table.setColumnWidth(1, 85)
        self.live_table.setColumnWidth(3, 65)
        self.live_table.itemChanged.connect(self.on_table_edit)
        est_lay.addWidget(self.live_table)

        btn_row = QHBoxLayout()
        add_mat = QPushButton("+ Add Material")
        add_lab = QPushButton("+ Add Labor")
        add_mat.clicked.connect(lambda: self.open_search("Material"))
        add_lab.clicked.connect(lambda: self.open_search("Labor"))
        add_mat.setStyleSheet("background:#3498db; color:white; font-weight:bold; padding:5px;")
        add_lab.setStyleSheet("background:#e67e22; color:white; font-weight:bold; padding:5px;")
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
        brk_hdr = self.breakup_table.horizontalHeader()
        assert brk_hdr is not None
        brk_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.breakup_table.setColumnWidth(1, 40)
        self.breakup_table.setColumnWidth(2, 80)
        self.breakup_table.setColumnWidth(3, 68)
        self.breakup_table.setColumnWidth(4, 68)
        self.breakup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.breakup_table.setAlternatingRowColors(False)
        brk_lay.addWidget(self.breakup_table)
        self._panel_stack.addWidget(brk_page)

        # ── Grand total label (shown for both views) ───────────────────────────
        self.grand_total_label = QLabel("<b>Grand Total: Rs. 0.00</b>")
        self.grand_total_label.setStyleSheet("font-size:15px; color:#d32f2f; margin-top:4px;")
        lay.addWidget(self.grand_total_label)

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
        Populate the Iron Breakup table from self.live_bom_data (same source as estimate).
        Only items that matched a rule condition appear here — no independent canvas scan.
        """
        from collections import defaultdict

        SECTION_LABELS = {
            "CH_75X40":    "M.S. Channel (75X40mm)",
            "CH_100X50":   "M.S. Channel (100X50mm)",
            "ANG_65X65X6": "M.S. Angle (65X65X6mm)",
            "ANG_50X50X6": "M.S. Angle (50X50X6mm)",
            "FLAT_65X6":   "M.S. Flat (65X6mm)",
            "FLAT_50X6":   "M.S. Flat (50X6mm)",
        }
        SECTION_ORDER = [
            "CH_100X50", "CH_75X40",
            "ANG_65X65X6", "ANG_50X50X6",
            "FLAT_65X6", "FLAT_50X6",
        ]
        IRON_SECTIONS = set(SECTION_ORDER)

        # Load section kg/m info from DB (for the section header labels)
        try:
            from core import db_gateway as _dbg
            sections_dict = _dbg.get_sections()
        except Exception:
            sections_dict = {}

        # Map DB material names (as they appear in live_bom_data) → section codes.
        # Covers both capitalisation variants that appear in the materials table.
        DB_NAME_TO_SECTION: dict[str, str] = {
            "M.S Channel 75X40 mm":   "CH_75X40",
            "M.S Channel 100X50 mm":  "CH_100X50",
            "M.S Angle 65X65X6mm":    "ANG_65X65X6",
            "M.S Angle 50X50X6mm":    "ANG_50X50X6",
            "M.S Flat 65X6 mm":       "FLAT_65X6",
            "M.S Flat 50X6 mm":       "FLAT_50X6",
            "M.S Channel 75x40 mm":   "CH_75X40",
            "M.S Channel 100x50 mm":  "CH_100X50",
            "M.S Angle 65x65x6 mm":   "ANG_65X65X6",
            "M.S Angle 50x50x6 mm":   "ANG_50X50X6",
            "M.S Flat 65x6 mm":       "FLAT_65X6",
            "M.S Flat 50x6 mm":       "FLAT_50X6",
        }

        # Alphanumeric normalisation map to support user's custom database names robustly
        def normalize_name(s):
            return "".join(c.lower() for c in s if c.isalnum())

        NORM_NAME_TO_SECTION = {normalize_name(k): v for k, v in DB_NAME_TO_SECTION.items()}

        # ── Filter live_bom_data: only MT items that are structural iron sections ─
        # This is the single source of truth — exactly what the estimate shows.
        section_items: dict[str, list[tuple[str, float]]] = defaultdict(list)
        extra_secs: list[str] = []

        for item in self.live_bom_data:
            if item.get("unit", "").upper() != "MT":
                continue
            sec = NORM_NAME_TO_SECTION.get(normalize_name(item["name"]), "")
            if not sec:
                continue  # G.I. Wire, Stay Wire, etc. — not structural iron
            if sec not in IRON_SECTIONS:
                if sec not in extra_secs:
                    extra_secs.append(sec)
            section_items[sec].append((item["name"], item["qty"]))

        # ── Populate QTableWidget ──────────────────────────────────────────────
        from PyQt6.QtGui import QColor, QFont as QFontQt
        from PyQt6.QtCore import Qt as Qt_

        tbl = self.breakup_table
        tbl.setRowCount(0)

        def _row(texts, bg="#FFFFFF", bold=False, fg="#000000", italic=False):
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
                cell.setFlags(cell.flags() & ~Qt_.ItemFlag.ItemIsEditable)
                tbl.setItem(r, c, cell)
            tbl.setRowHeight(r, 20)

        def _span_row(text, bg, bold=False, fg="#000000"):
            r = tbl.rowCount()
            tbl.insertRow(r)
            cell = QTableWidgetItem(text)
            cell.setBackground(QColor(bg))
            f = QFontQt("Segoe UI", 10); f.setBold(bold)
            cell.setFont(f)
            cell.setForeground(QColor(fg))
            cell.setFlags(cell.flags() & ~Qt_.ItemFlag.ItemIsEditable)
            tbl.setItem(r, 0, cell)
            tbl.setSpan(r, 0, 1, 5)
            tbl.setRowHeight(r, 22)

        if not any(section_items.get(s) for s in SECTION_ORDER + extra_secs):
            _span_row("  No structural iron items in current estimate.", "#F8F8F8")
            return

        # Track section totals for the summary block
        section_totals: list[tuple[str, float]] = []

        for sec_code in SECTION_ORDER + extra_secs:
            items = section_items.get(sec_code, [])
            if not items:
                continue

            sec_info = sections_dict.get(sec_code, {})
            kg_m = sec_info.get("kg_per_metre", 0.0)
            sec_label = SECTION_LABELS.get(sec_code, sec_code)
            kg_label  = f"{kg_m} kg/m" if kg_m else ""

            # Section header
            _span_row(f"  {sec_label}  {'— ' + kg_label if kg_label else ''}",
                      "#1F4E79", bold=True, fg="#FFFFFF")

            # Column sub-header
            _row(["  Description", "", "", "", "Iron (MT)"],
                 bg="#BDD7EE", bold=True)

            sec_total = 0.0
            for idx, (desc, qty_mt) in enumerate(items):
                bg = "#FFFFFF" if idx % 2 == 0 else "#EBF3FB"
                _row([f"  {desc}", "", "", "", f"{qty_mt:.3f}"], bg=bg)
                sec_total += qty_mt

            sec_total = round(sec_total, 3)
            section_totals.append((sec_label, sec_total))
            _row(["  Section Total", "", "", "", f"{sec_total:.3f} MT"],
                 bg="#D9E1F2", bold=True)
            _row(["", "", "", "", ""], bg="#F8F8F8")  # spacer

        # ── Iron Summary (per section only — no combined grand total) ──────────
        if section_totals:
            _span_row("  IRON SUMMARY", "#1F4E79", bold=True, fg="#FFFFFF")
            for sec_lbl, total_mt in section_totals:
                _row([f"  {sec_lbl}", "", "", "", f"{total_mt:.3f} MT"],
                     bg="#FFF2CC", bold=False)

    # =========================================================================
    #  PROJECT WIZARD
    # =========================================================================

    def _run_project_wizard(self, first_run=False):
        dlg = ProjectSetupDialog(self.project_meta, self, first_run=first_run)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.project_meta = dlg.get_meta()
            self._refresh_proj_label()
            self.refresh_live_estimate()

    def _refresh_proj_label(self):
        m = self.project_meta
        sup_pct = int(m.get("supervision_rate", 0.10) * 100)
        uh_txt  = "UH Materials" if m.get("use_uh") else "Raw Steel"
        self.proj_info_label.setText(
            f"📌 {m.get('subject','(no subject)')}   |   "
            f"Type: {m.get('project_type','NSC')}   |   "
            f"Sup: {sup_pct}%   |   "
            f"Materials: {uh_txt}"
        )

    # =========================================================================
    #  TOOL MANAGEMENT
    # =========================================================================

    # Drawing tools — switching between these keeps the auto-span chain alive
    _DRAWING_TOOLS = frozenset({"ADD_LT", "ADD_HT", "ADD_EXISTING", "ADD_STRUCTURE", "ADD_CONSUMER"})

    def set_tool(self, tool_name):
        prev_tool = self.current_tool
        self.current_tool = tool_name
        if self.span_start_pole:
            self.span_start_pole.setPen(QPen(Qt.GlobalColor.black, 1))
        self.span_start_pole = None
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
            btn.setStyleSheet(
                "padding:7px 5px; font-weight:bold; background:"
                + ("lightblue;" if active else "lightgray;")
            )
        self.update_view_drag_mode()

    def update_view_drag_mode(self):
        """Delegate canvas interaction state to InteractiveView.

        SELECT mode now uses dynamic drag mode/cursor behavior:
        empty-space pan, hover-select pointer, selected-object drag pointer.
        """
        if self.current_tool == "SELECT":
            self.view.refresh_interaction_state()
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


    def _toggle_page_grid(self, checked):
        self.show_page_grid = checked
        self.view.grid_show = checked
        vp = self.view.viewport()
        assert vp is not None
        vp.update()

    def _toggle_crosshatch(self, checked):
        self.show_crosshatch = checked
        self.view.grid_crosshatch = checked
        vp = self.view.viewport()
        assert vp is not None
        vp.update()
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
    #  CANVAS CLICK HANDLER
    # =========================================================================

    def handle_canvas_click(self, event, view):
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
                p_type = "LT" if self.current_tool in ("ADD_LT", "ADD_EXISTING") else "HT"
                is_exist = self.current_tool == "ADD_EXISTING"
                item = SmartPole(pos.x(), pos.y(), self.refresh_signal, p_type, is_exist, detail_view=self.detail_view)
            elif self.current_tool == "ADD_STRUCTURE":
                item = SmartStructure(pos.x(), pos.y(), self.refresh_signal, detail_view=self.detail_view)
            else: # ADD_CONSUMER
                item = SmartConsumer(pos.x(), pos.y(), self.refresh_signal, detail_view=self.detail_view)
                
            self.scene.addItem(item)
            self._auto_connect_span(item)
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
                self.refresh_live_estimate()

        # ── Symbol/Text placement ──────────────────────────────────────────
        elif self.current_tool in ("ADD_SYMBOL", "ADD_TEXTBOX"):
            if self.current_tool == "ADD_SYMBOL":
                shape = getattr(self, "_pending_symbol_shape", "circle")
                item = CanvasSymbol(shape, pos.x() - 20, pos.y() - 20)
            else: # ADD_TEXTBOX
                text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
                if not (ok and text.strip()): return
                item = CanvasTextBox(text.strip(), pos.x(), pos.y())
                item.setSelected(True)
            
            self.scene.addItem(item)
            self.scene.clearSelection()
            if self.current_tool == "ADD_SYMBOL" or (self.current_tool == "ADD_TEXTBOX"):
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
        """
        Returns True if a node is effectively HT.
        SmartStructure is always HT.
        SmartPole: uses its voltage type (pole_type).
        SmartConsumer: always LT.
        """
        if isinstance(node, SmartStructure):
            return True
        if isinstance(node, SmartPole):
            return node.pole_type == "HT"
        return False  # SmartConsumer = LT

    @staticmethod
    def _is_node_item(item) -> bool:
        return isinstance(item, (SmartPole, SmartStructure, SmartConsumer))

    def _iter_nodes(self):
        return [i for i in self.scene.items() if self._is_node_item(i)]

    def _find_nearby_node(self, pos: QPointF, min_gap: float | None = None):
        gap = float(defaults.current.get("node_min_gap", self._MIN_NODE_GAP)) if min_gap is None else float(min_gap)
        for node in self._iter_nodes():
            if math.hypot(node.x() - pos.x(), node.y() - pos.y()) < gap:
                return node
        return None

    @staticmethod
    def _span_other_endpoint(span, node):
        if span.p1 == node:
            return span.p2
        if span.p2 == node:
            return span.p1
        return None

    def _active_connected_spans(self, node):
        return [s for s in getattr(node, "connected_spans", []) if s is not None and s.scene() is not None]

    def _span_exists_between(self, p1, p2) -> bool:
        for s in self._active_connected_spans(p1):
            if (s.p1 == p1 and s.p2 == p2) or (s.p1 == p2 and s.p2 == p1):
                return True
        return False

    def _has_path_between(self, start, target) -> bool:
        if start == target:
            return True
        visited = {start}
        queue = [start]
        while queue:
            node = queue.pop(0)
            for span in self._active_connected_spans(node):
                other = self._span_other_endpoint(span, node)
                if other is None:
                    continue
                if other == target:
                    return True
                if other not in visited:
                    visited.add(other)
                    queue.append(other)
        return False

    def _validate_span_creation(self, p1, p2):
        if p1 == p2:
            return False, "Start and end node must be different."
        if self._span_exists_between(p1, p2):
            return False, "A span already exists between these two nodes."
        # Prevent closing loops; layout should stay tree-like.
        if self._has_path_between(p1, p2):
            return False, "This connection would create a loop."
        return True, ""

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
            return

        item = sel[0]
        if isinstance(item, DraggableLabel):
            self.editor_group.setTitle("Text label")
            return

        if isinstance(item, SmartPole):
            self._build_pole_editor(item)
        elif isinstance(item, SmartStructure):
            self._build_structure_editor(item)
        elif isinstance(item, SmartSpan):
            self._build_span_editor(item)
        elif isinstance(item, SmartConsumer):
            self._build_consumer_editor(item)

        self._normalize_editor_field_sizes()
        self._pack_editor_rows_two_columns()

    def _normalize_editor_field_sizes(self):
        """Keep editor controls visually consistent regardless of content text."""
        fields = self.editor_group.findChildren((QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox))
        for w in fields:
            w.setMinimumHeight(24)
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if isinstance(w, QComboBox):
                w.setMinimumContentsLength(1)
                w.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
                w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

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

        label_w = 88

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
            if self.current_tool != "SELECT":
                self.set_tool("SELECT")
        return super().eventFilter(obj, event)

    def delete_selected_items(self):
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
        all_poles = [
            i for i in self.scene.items()
            if isinstance(i, (SmartPole, SmartStructure))
        ]
        existing_set = {p for p in all_poles if getattr(p, "is_existing", False)}

        while True:
            promoted = set()
            for pole in all_poles:
                if pole in existing_set:
                    continue
                existing_connections = sum(
                    1 for s in pole.connected_spans
                    if (s.p1 in existing_set or s.p2 in existing_set)
                    and (s.p1 != pole and s.p2 != pole
                         or (s.p1 in existing_set and s.p2 in existing_set))
                )
                neighbours_existing = sum(
                    1 for s in pole.connected_spans
                    if (s.p1 if s.p2 == pole else s.p2) in existing_set
                )
                # Only relay SmartPoles can be promoted — SmartStructures
                # (DP, TP, 4P, DTR) are always new infrastructure and must
                # never be silently reclassified as existing.
                if neighbours_existing >= 2 and isinstance(pole, SmartPole):
                    promoted.add(pole)
            if not promoted:
                break
            existing_set.update(promoted)

        for span in self.scene.items():
            if not isinstance(span, SmartSpan):
                continue
            both_existing = (
                span.p1 in existing_set and span.p2 in existing_set
            )
            new_val = both_existing and not span.is_service_drop
            if span.is_existing_span != new_val:
                span.is_existing_span = new_val
                # When a HT ACSR span first becomes existing, default wire_count to 3
                if new_val and not span.is_lt_span and span.conductor == "ACSR":
                    span.wire_count = "3"
                span.update_visuals()

    def _auto_stay_update(self):
        """Auto-update stay counts based on span angles."""
        for pole in self.scene.items():
            if not isinstance(pole, SmartPole):
                continue
            if pole.override_auto_stay:
                continue
            if pole.pole_type == "DTR":
                continue

            # Existing pole policy:
            # Only evaluate stay when at least one NEW non-service span exists.
            # Then compare each existing-span angle with each new-span angle.
            # If angle is outside (180 +/- tolerance), stay is required.
            if pole.is_existing:
                existing_spans = [
                    s for s in pole.connected_spans
                    if not s.is_service_drop and s.is_existing_span
                ]
                new_spans = [
                    s for s in pole.connected_spans
                    if not s.is_service_drop and not s.is_existing_span
                ]

                should_stay = False

                if new_spans and existing_spans:
                    tol = float(defaults.current.get("existing_stay_angle_tolerance_deg", 20.0))
                    lo = 180.0 - tol
                    hi = 180.0 + tol

                    def _span_angle_deg(span: SmartSpan) -> float | None:
                        other = span.p1 if span.p2 == pole else span.p2
                        dx = other.x() - pole.x()
                        dy = other.y() - pole.y()
                        if math.hypot(dx, dy) <= 0:
                            return None
                        return math.degrees(math.atan2(dy, dx)) % 360.0

                    ex_angles = [a for a in (_span_angle_deg(s) for s in existing_spans) if a is not None]
                    new_angles = [a for a in (_span_angle_deg(s) for s in new_spans) if a is not None]

                    for exa in ex_angles:
                        for nwa in new_angles:
                            pair_angle = (nwa - exa) % 360.0
                            # Stay required when angle < 160 or > 200 for default tol=20.
                            if pair_angle < lo or pair_angle > hi:
                                should_stay = True
                                break
                        if should_stay:
                            break

                target = 1 if should_stay else 0
                needs_visual_refresh = (pole.stay_count != target)
                if needs_visual_refresh:
                    pole.stay_count = target
                # Keep existing poles aligned to auto strain direction unless
                # stay count is explicitly locked in manual mode.
                if pole.stay_angle_override is not None:
                    pole.stay_angle_override = None
                    needs_visual_refresh = True
                if needs_visual_refresh:
                    pole.update_visuals()
                continue

            active_spans = [
                s for s in pole.connected_spans
                if not s.is_service_drop and not s.is_existing_span
            ]
            n = len(active_spans)
            should_stay = False

            if n == 1:
                should_stay = True
            elif n == 2:
                s1, s2 = active_spans
                other1 = s1.p1 if s1.p2 == pole else s1.p2
                other2 = s2.p1 if s2.p2 == pole else s2.p2
                v1 = (other1.x() - pole.x(), other1.y() - pole.y())
                v2 = (other2.x() - pole.x(), other2.y() - pole.y())
                mag1 = math.hypot(*v1)
                mag2 = math.hypot(*v2)
                if mag1 > 0 and mag2 > 0:
                    dot = v1[0] * v2[0] + v1[1] * v2[1]
                    angle = math.degrees(
                        math.acos(min(1.0, max(-1.0, dot / (mag1 * mag2))))
                    )
                    if (180 - angle) > 20:
                        should_stay = True

            target = 1 if should_stay else 0
            needs_visual_refresh = (pole.stay_count != target)
            if pole.stay_count != target:
                pole.stay_count = target
            if needs_visual_refresh:
                pole.update_visuals()

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

    def _do_refresh_live_estimate(self):
        if self._refreshing_live:
            return
        self._refreshing_live = True

        try:
            # Canvas-derived state (cheap-to-moderate). Kept here, off the
            # per-event path, so a drag stays at 60 fps and placements are instant.
            self.recalculate_all_span_types()
            self._auto_stay_update()
            self._refresh_page_grid()

            use_uh        = self.project_meta.get("use_uh", False)
            project_type  = self.project_meta.get("project_type", "NSC")
            sup_rate      = self.project_meta.get("supervision_rate", 0.10)

            # Load rules from database (falls back to empty list on failure)
            from core import db_gateway as _dbg  # noqa: PLC0415
            rules = _dbg.get_rules()

            canvas_items = [
                i for i in self.scene.items()
                if isinstance(i, (SmartPole, SmartStructure, SmartSpan, SmartConsumer))
            ]
            raw_bom, raw_lab = self.rule_engine.process(
                canvas_items, rules, use_uh, project_type
            )

            # Build live_bom_data
            self.live_bom_data = []
            conn   = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Pre-fetch every row from both lookup tables once.
            # _db_lookup is called for each BOM item; without this it would
            # issue a full-table SELECT on every fallback tier (Tiers 3-5),
            # turning an O(n) refresh into O(n × m) DB queries.
            cursor.execute("SELECT item_code, rate, unit, item_name FROM materials")
            _all_mat = cursor.fetchall()
            cursor.execute("SELECT labor_code, rate, unit, task_name FROM labor")
            _all_lab = cursor.fetchall()
            _prefetched = {"Material": _all_mat, "Labor": _all_lab}

            # Apply 3% sag/wastage to conductor and wire materials.
            # Guard: only items whose DB unit is a continuous measurement (MT, KM, M…)
            # get the multiplier.  Items whose name happens to contain "ACSR" (e.g.
            # "Composite Hardware Fittings for ACSR…", unit=SET) are excluded.
            
            # Build standard mapping from rules of item_name -> item_code
            rule_code_map = {}
            for r in rules:
                for item in r.get("items", []):
                    iname = item.get("item_name")
                    icode = item.get("item_code")
                    if iname and icode:
                        rule_code_map[iname] = icode

            _COUNT_UNITS = {
                "nos", "no.", "no", "set", "sets", "pair", "pairs",
                "pcs", "piece", "each", "ea", "day", "days", "job", "ls",
            }
            for name in list(raw_bom):
                upper_name = name.upper()
                if any(tag in upper_name for tag in SAG_ITEMS):
                    db_row = self._db_lookup(cursor, "Material", name, rule_code_map.get(name), _prefetched=_prefetched)
                    unit_str = (db_row[2] if db_row else "").lower().strip().rstrip(".")
                    if unit_str not in _COUNT_UNITS:
                        raw_bom[name] = raw_bom[name] * 1.03

            processed = set()

            combined = (
                [("Material", n, q) for n, q in raw_bom.items()] +
                [("Labor",    n, q) for n, q in raw_lab.items()]
            )

            for item_type, name, qty in combined:
                if name in self.bom_overrides and self.bom_overrides[name]["type"] == item_type:
                    qty = self.bom_overrides[name]["qty"]

                row = self._db_lookup(cursor, item_type, name, rule_code_map.get(name), _prefetched=_prefetched)
                if row:
                    code, rate, unit, db_name = row
                    if db_name in self.bom_overrides and self.bom_overrides[db_name]["type"] == item_type:
                        qty = self.bom_overrides[db_name]["qty"]
                    qty_rounded = round(qty, 3)
                    self.live_bom_data.append({
                        "type": item_type, "code": code, "name": db_name,
                        "qty": qty_rounded, "unit": unit, "rate": rate,
                        "amt": qty_rounded * rate
                    })
                    processed.add(name)
                    processed.add(db_name)

            # Custom overrides not in auto-BOM
            for name, override in self.bom_overrides.items():
                if name not in processed:
                    row = self._db_lookup(cursor, override["type"], name, _prefetched=_prefetched)
                    if row:
                        code, rate, unit, db_name = row
                        qty = override["qty"]
                        qty_rounded = round(qty, 3)
                        self.live_bom_data.append({
                            "type": override["type"], "code": code, "name": db_name,
                            "qty": qty_rounded, "unit": unit, "rate": rate,
                            "amt": qty_rounded * rate
                        })
                        processed.add(name)
                        processed.add(db_name)

            conn.close()
            self._refresh_table()
            self._recalculate_totals(sup_rate)
        finally:
            self._refreshing_live = False

    def _db_lookup(self, cursor, item_type, name, rule_code=None, _prefetched=None):
        def normalize(s):
            s = s.lower()
            s = s.replace("distribution transformer", "dtr")
            s = s.replace("transformer", "dtr")
            return "".join(c for c in s if c.isalnum())

        if item_type == "Material":
            tbl = "materials"
            name_col = "item_name"
            code_col = "item_code"
        else:
            tbl = "labor"
            name_col = "task_name"
            code_col = "labor_code"

        # Tier 1: Exact Match by Name
        cursor.execute(f"SELECT {code_col}, rate, unit, {name_col} FROM {tbl} WHERE {name_col}=?", (name,))
        row = cursor.fetchone()
        if row:
            return row[0], row[1], row[2], row[3]

        # Tier 2: Code Match
        if rule_code:
            rule_code_str = str(rule_code).strip()
            cursor.execute(f"SELECT {code_col}, rate, unit, {name_col} FROM {tbl} WHERE {code_col}=?", (rule_code_str,))
            row = cursor.fetchone()
            if row:
                return row[0], row[1], row[2], row[3]

        # Fetch all items to perform case-insensitive, normalized, and fuzzy matching.
        # Use the pre-fetched list when available (avoids a full-table DB query per item).
        if _prefetched is not None:
            all_items = _prefetched.get(item_type, [])
        else:
            cursor.execute(f"SELECT {code_col}, rate, unit, {name_col} FROM {tbl}")
            all_items = cursor.fetchall()

        # Tier 2.5: Code Match with leading-zero safety (e.g. "05105252525" matches "5105252525")
        if rule_code:
            rule_code_stripped = str(rule_code).strip().lstrip('0')
            if rule_code_stripped:
                for row in all_items:
                    db_code = str(row[0]).strip().lstrip('0')
                    if db_code == rule_code_stripped:
                        return row[0], row[1], row[2], row[3]

        # Tier 3: Case-Insensitive Match
        name_lower = name.lower()
        for row in all_items:
            db_name = row[3]
            if db_name and db_name.lower() == name_lower:
                return row[0], row[1], row[2], row[3]

        # Tier 4: Normalized Match
        name_norm = normalize(name)
        for row in all_items:
            db_name = row[3]
            if db_name and normalize(db_name) == name_norm:
                return row[0], row[1], row[2], row[3]

        # Tier 4.5: Labor-specific normalization for common prefix variants.
        if item_type == "Labor":
            alt_names = []
            low_name = name.lower().strip()
            if low_name.startswith("aug. "):
                alt_names.append(low_name[5:])
            if low_name.startswith("dtr aug. "):
                alt_names.append(low_name[9:])
            if low_name.startswith("dtr s/stn "):
                alt_names.append(low_name[10:])
            if low_name.startswith("dtr "):
                alt_names.append(low_name[4:])

            for alt in alt_names:
                alt_norm = normalize(alt)
                if not alt_norm or alt_norm == name_norm:
                    continue
                for row in all_items:
                    db_name = row[3]
                    if not db_name:
                        continue
                    db_norm = normalize(db_name)
                    if alt_norm == db_norm or alt_norm in db_norm or db_norm in alt_norm:
                        return row[0], row[1], row[2], row[3]

        # Tier 5: Normalized Substring Match with Number Safety
        rule_nums = re.findall(r'\d+', name)
        for row in all_items:
            db_name = row[3]
            if not db_name:
                continue
            db_norm = normalize(db_name)
            if name_norm in db_norm or db_norm in name_norm:
                # Extra guard: numbers must match!
                db_nums = re.findall(r'\d+', db_name)
                num_match = True
                for num in rule_nums:
                    if num in {"8", "9", "11", "16", "25", "63", "100", "160", "315"} and num not in db_nums:
                        num_match = False
                        break
                if num_match:
                    return row[0], row[1], row[2], row[3]

        return None

    @staticmethod
    def _fmt_qty(qty: float, unit: str) -> str:
        """Format qty as integer for count units (Nos/Set/etc), else 3 decimal places."""
        _COUNT = {"nos", "no.", "no", "set", "sets", "pair", "pairs", "pcs", "piece", "each", "ea", "day", "days", "job", "ls"}
        if unit.lower().strip().rstrip(".") in _COUNT:
            return str(int(round(qty)))
        return f"{qty:.3f}"

    def _refresh_table(self):
        try:
            self.live_table.itemChanged.disconnect(self.on_table_edit)
        except TypeError:
            pass

        self.live_table.setUpdatesEnabled(False)
        self.live_table.setRowCount(0)
        for i, item in enumerate(self.live_bom_data):
            self.live_table.insertRow(i)
            self.live_table.setItem(i, 0, QTableWidgetItem(item["type"]))
            self.live_table.setItem(i, 1, QTableWidgetItem(item["code"]))
            self.live_table.setItem(i, 2, QTableWidgetItem(item["name"]))
            qty_text = self._fmt_qty(item["qty"], item.get("unit", ""))
            qty_item = QTableWidgetItem(qty_text)
            qty_item.setBackground(QColor("#fff3cd"))
            self.live_table.setItem(i, 3, qty_item)
            self.live_table.setItem(i, 4, QTableWidgetItem(item["unit"]))
            self.live_table.setItem(i, 5, QTableWidgetItem(f"{item['amt']:.2f}"))
            for col in (0, 1, 2, 4, 5):
                t = self.live_table.item(i, col)
                if t:
                    t.setFlags(t.flags() & ~Qt.ItemFlag.ItemIsEditable)

        self.live_table.setUpdatesEnabled(True)
        self.live_table.itemChanged.connect(self.on_table_edit)

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
        mat_base = sum(x["amt"] for x in self.live_bom_data if x["type"] == "Material")
        lab_sub  = sum(x["amt"] for x in self.live_bom_data if x["type"] == "Labor")

        now = datetime.now()
        fy_start = now.year if now.month >= 4 else now.year - 1

        base_yr_str = defaults.current.get("rate_chart_base_year", "2026")
        try:
            base_yr = int(base_yr_str)
        except ValueError:
            base_yr = 2026

        self.escalations = []
        cur = mat_base
        for yr in range(base_yr + 1, fy_start + 1):
            esc = cur * 0.05
            self.escalations.append((f"{str(yr)[-2:]}-{str(yr+1)[-2:]}", esc))
            cur += esc

        sun      = cur * 0.05
        mat_sub  = cur + sun
        sup      = (mat_sub + lab_sub) * sup_rate
        gst      = lab_sub * 0.18
        cess     = (mat_sub + lab_sub + sup) * 0.01
        final    = mat_sub + lab_sub + sup + gst + cess

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
        PlacementDefaultsDialog(self).exec()

    def open_property_editor(self):
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
        import re
        sanitized = re.sub(r'[\\/*?:"<>|]', "_", (self.project_meta.get("subject") or "").strip())
        stem = "_".join(sanitized.split()[:6])
        return stem if stem else fallback

    def save_project_bundle(self):
        self._flush_refresh()
        if self.scene.itemsBoundingRect().isNull():
            QMessageBox.warning(self, "Empty Canvas", "Nothing to export.")
            return

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
        state = {
            "version":       5,
            "project_meta":  self.project_meta,
            "overrides":     self.bom_overrides,
            "nodes":         [],
            "spans":         [],
            "annotations":   [],
        }
        node_id_by_obj = {}
        for i, item in enumerate(self.scene.items()):
            if isinstance(item, (SmartPole, SmartStructure, SmartConsumer)):
                node_id_by_obj[id(item)] = i
                nd = item.to_dict()
                nd["id"] = i
                state["nodes"].append(nd)

        for item in self.scene.items():
            if isinstance(item, SmartSpan):
                p1_id = node_id_by_obj.get(id(item.p1))
                p2_id = node_id_by_obj.get(id(item.p2))
                if p1_id is None or p2_id is None:
                    continue
                sd = item.to_dict()
                sd.update({"p1_id": p1_id, "p2_id": p2_id})
                state["spans"].append(sd)

        for item in self.scene.items():
            if isinstance(item, (CanvasSymbol, CanvasTextBox)):
                state["annotations"].append(item.to_dict())

        return state

    def parse_load_data(self, state, fit_view=True):
        self.scene.clear()
        version = state.get("version", 4)

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
                                     nd.get("is_existing", False), detail_view=self.detail_view)
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
        self._calibrate_label_counters()

        # After loading, optionally fit the view
        if fit_view:
            def _fit_after_load():
                b = self.scene.itemsBoundingRect()
                if not b.isNull():
                    self.view.fitInView(
                        b.adjusted(-60, -60, 60, 60),
                        Qt.AspectRatioMode.KeepAspectRatio
                    )
            QTimer.singleShot(80, _fit_after_load)

    # =========================================================================
    #  LABEL COUNTER HELPERS
    # =========================================================================

    def _renumber_labels(self) -> None:
        """
        After a node is deleted, compact the sequential label numbers for every
        category so there are no gaps.
        """
        buckets: dict = {
            "lt":  [],   # new LT poles
            "ht":  [],   # new HT poles
            "DP":  [],
            "TP":  [],
            "4P":  [],
            "DTR": [],
            "con": [],   # consumers
        }
        # Dynamic ex buckets
        ex_buckets: dict = {}

        for item in self.scene.items():
            if isinstance(item, SmartPole):
                if item.is_existing:
                    sub = item.existing_subtype
                    ex_buckets.setdefault(sub, []).append(item)
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

        # Update class-level counters to match new maximums
        SmartPole._lt_seq = len(buckets["lt"])
        SmartPole._ht_seq = len(buckets["ht"])
        SmartPole._ex_type_seq = {s: len(g) for s, g in ex_buckets.items()}
        SmartStructure._type_seq = {
            "DP":  len(buckets["DP"]),
            "TP":  len(buckets["TP"]),
            "4P":  len(buckets["4P"]),
            "DTR": len(buckets["DTR"]),
        }
        SmartConsumer._con_seq = len(buckets["con"])

    def _calibrate_label_counters(self) -> None:
        """
        After loading a file, set each class-level label counter to the
        maximum seq_id already in use so that newly placed objects get
        the next available number rather than potentially colliding with
        existing labels.
        """
        ex_max = lt_max = ht_max = 0
        dp_max = tp_max = fp_max = dtr_max = 0
        con_max = 0

        for item in self.scene.items():
            if isinstance(item, SmartPole):
                sid = getattr(item, "seq_id", 0)
                if item.is_existing:
                    ex_max = max(ex_max, sid)
                elif item.pole_type == "LT":
                    lt_max = max(lt_max, sid)
                else:
                    ht_max = max(ht_max, sid)
            elif isinstance(item, SmartStructure):
                sid = getattr(item, "seq_id", 0)
                st  = getattr(item, "structure_type", "DP")
                if st == "DP":
                    dp_max = max(dp_max, sid)
                elif st == "TP":
                    tp_max = max(tp_max, sid)
                elif st == "4P":
                    fp_max = max(fp_max, sid)
                elif st == "DTR":
                    dtr_max = max(dtr_max, sid)
            elif isinstance(item, SmartConsumer):
                con_max = max(con_max, getattr(item, "seq_id", 0))

        SmartPole._ex_seq = ex_max
        SmartPole._lt_seq = lt_max
        SmartPole._ht_seq = ht_max
        SmartStructure._type_seq = {"DP": dp_max, "TP": tp_max, "4P": fp_max, "DTR": dtr_max}
        SmartConsumer._con_seq   = con_max

    # =========================================================================
    #  UNDO / REDO
    # =========================================================================

    def push_history(self):
        """Capture state and push to undo stack."""
        if self._is_undoing:
            return
        
        state = self.compile_save_data()
        
        # Don't push if nothing structurally changed
        if self.history and self.history_index >= 0:
            if state == self.history[self.history_index]:
                return

        # If user did something after undoing, truncate the 'redo' future
        self.history = self.history[:self.history_index + 1]
        self.history.append(state)
        self._drawing_dirty = True
        
        if len(self.history) > 50:
            self.history.pop(0)
        else:
            self.history_index += 1

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self._is_undoing = True
            
            self.parse_load_data(self.history[self.history_index], fit_view=False)
            
            self._is_undoing = False

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._is_undoing = True
            
            self.parse_load_data(self.history[self.history_index], fit_view=False)
            
            self._is_undoing = False

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

    def new_drawing(self):
        ans = QMessageBox.question(
            self, "New Canvas", "Clear canvas and start fresh?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            # Auto-save current drawing before clearing
            self._save_unsaved_drawing()
            self.scene.clear()
            self.span_start_pole  = None
            self.last_placed_node = None
            self.bom_overrides.clear()
            SmartPole.reset_counters()
            SmartStructure.reset_counters()
            SmartConsumer.reset_counters()
            self._drawing_dirty = False
            self._show_blank_start_page()

    def load_from_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Project", self._get_drawings_dir(), "JSON Files (*.json)"
        )
        if filename:
            with open(filename, "r", encoding="utf-8") as f:
                self.parse_load_data(json.load(f))
            self._drawing_dirty = False

    def save_to_file(self):
        last_dir = str(defaults.current.get("export_last_dir", "") or "").strip()
        stem     = self._safe_subject_stem("project")
        default  = os.path.join(last_dir, f"{stem}.json") if last_dir else f"{stem}.json"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Project", default, "JSON Files (*.json)"
        )
        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(self.compile_save_data(), f, indent=2)
            self._drawing_dirty = False
            defaults.save({"export_last_dir": os.path.dirname(filename)})
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Project Saved")
            msg.setText(f"Project saved to:\n{filename}")
            open_folder_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Close)
            msg.exec()
            if msg.clickedButton() == open_folder_btn:
                self._open_saved_folder(filename)

    def load_autosave(self):
        loaded_any = False
        if os.path.exists(self.autosave_file):
            try:
                if os.path.getsize(self.autosave_file) > 0:
                    with open(self.autosave_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Only load if there is actual canvas content
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
        """Silent background update check, run shortly after launch.

        Only runs in the packaged (frozen) build so the installer-based update
        path is meaningful; dev runs are never interrupted.
        """
        if not getattr(sys, "frozen", False):
            return
        self._launch_update_check(silent=True)

    def check_for_updates(self):
        """Manual 'Check for Updates…' — gives feedback even when up to date."""
        self._launch_update_check(silent=False)

    def _launch_update_check(self, silent: bool):
        # Keep a reference so the thread isn't garbage-collected mid-run.
        self._update_check_thread = _UpdateCheckThread()
        self._update_check_thread.done.connect(
            lambda info: self._on_update_check_result(info, silent)
        )
        self._update_check_thread.start()

    def _on_update_check_result(self, info, silent: bool):
        if not info:
            if not silent:
                QMessageBox.information(
                    self, "No Updates",
                    f"You are running the latest version (v{APP_VERSION}).",
                )
            return

        notes = info.get("notes", "")
        if len(notes) > 600:
            notes = notes[:600] + "…"
        ans = QMessageBox.question(
            self, "Update Available",
            f"Version {info['version']} is available "
            f"(you have v{APP_VERSION}).\n\n"
            f"{notes}\n\nDownload and install now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._download_and_install_update(info)

    def _download_and_install_update(self, info):
        dlg = QProgressDialog("Downloading update…", "Cancel", 0, 100, self)
        dlg.setWindowTitle("Updating")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)

        self._update_dl_thread = _UpdateDownloadThread(info["url"], self)

        def _on_progress(done, total):
            if total > 0:
                dlg.setMaximum(total)
                dlg.setValue(done)
            else:
                dlg.setMaximum(0)  # indeterminate

        def _on_finished(path):
            dlg.close()
            try:
                # Release the single-instance mutex and quit so the installer
                # (CloseApplications=yes) can replace files, then relaunch us.
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception as exc:
                QMessageBox.critical(self, "Update Failed", f"Could not launch installer:\n{exc}")
                return
            app_inst = QApplication.instance()
            if app_inst is not None:
                app_inst.quit()

        def _on_failed(msg):
            dlg.close()
            QMessageBox.critical(self, "Update Failed", f"Download failed:\n{msg}")

        self._update_dl_thread.progress.connect(_on_progress)
        self._update_dl_thread.finished_path.connect(_on_finished)
        self._update_dl_thread.failed.connect(_on_failed)
        dlg.canceled.connect(self._update_dl_thread.terminate)
        self._update_dl_thread.start()


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
