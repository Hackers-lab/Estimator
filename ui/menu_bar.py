"""
ui/menu_bar.py
==============
Constructs and styles the main application window's menu bar and actions.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from PyQt6.QtGui import QAction, QKeySequence
from app_config import APP_EXPIRY

if TYPE_CHECKING:
    from app import EstimateApp

def build_menu_bar(app: EstimateApp) -> None:
    """Build the menu bar and bind all standard top-level actions."""
    mb = app.menuBar()
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

    act_new_file = QAction("New Project", app)
    act_new_file.setShortcut(QKeySequence("Ctrl+N"))
    act_new_file.triggered.connect(app.new_project)
    file_menu.addAction(act_new_file)

    act_open = QAction("Open…", app)
    act_open.setShortcut(QKeySequence("Ctrl+O"))
    act_open.triggered.connect(app.load_from_file)
    file_menu.addAction(act_open)

    act_save = QAction("Save…", app)
    act_save.setShortcut(QKeySequence("Ctrl+S"))
    act_save.triggered.connect(app.save_to_file)
    file_menu.addAction(act_save)

    file_menu.addSeparator()

    app.act_undo = QAction("Undo", app)
    app.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
    app.act_undo.triggered.connect(app.undo)
    file_menu.addAction(app.act_undo)

    app.act_redo = QAction("Redo", app)
    app.act_redo.setShortcut(QKeySequence("Ctrl+Y"))
    app.act_redo.triggered.connect(app.redo)
    file_menu.addAction(app.act_redo)

    file_menu.addSeparator()

    act_exit = QAction("Exit", app)
    act_exit.setShortcut(QKeySequence("Ctrl+Q"))
    act_exit.triggered.connect(app.close)
    file_menu.addAction(act_exit)

    # ── Project ──────────────────────────────────────────────────────
    proj_menu = mb.addMenu("&Project")
    assert proj_menu is not None

    act_new = QAction("New Project", app)
    act_new.setShortcut(QKeySequence("Ctrl+N"))
    act_new.triggered.connect(app.new_project)
    proj_menu.addAction(act_new)

    act_my_projects = QAction("My Projects…", app)
    act_my_projects.setShortcut(QKeySequence("Ctrl+P"))
    act_my_projects.triggered.connect(app.open_my_projects_dialog)
    proj_menu.addAction(act_my_projects)

    act_proj = QAction("Project Settings", app)
    act_proj.triggered.connect(lambda: app._run_project_wizard(first_run=False))
    proj_menu.addAction(act_proj)

    act_update_proj = QAction("Update Project", app)
    act_update_proj.triggered.connect(app.update_project_details)
    proj_menu.addAction(act_update_proj)

    act_save_bundle = QAction("Save Project Bundle…", app)
    act_save_bundle.triggered.connect(app.save_project_bundle)
    proj_menu.addAction(act_save_bundle)

    proj_menu.addSeparator()

    act_all_projects_report = QAction("All Projects Report", app)
    act_all_projects_report.triggered.connect(app.open_all_projects_report)
    proj_menu.addAction(act_all_projects_report)

    # ── Export ────────────────────────────────────────────────────────
    export_menu = mb.addMenu("E&xport")
    assert export_menu is not None

    act_pdf = QAction("Export PDF Drawing", app)
    act_pdf.triggered.connect(app.export_pdf)
    export_menu.addAction(act_pdf)

    act_xl = QAction("Generate Excel Estimate", app)
    act_xl.triggered.connect(app.generate_excel)
    export_menu.addAction(act_xl)

    act_bundle = QAction("Save PDF + Excel + JSON Bundle", app)
    act_bundle.triggered.connect(app.save_project_bundle)
    export_menu.addAction(act_bundle)

    # ── Billing ───────────────────────────────────────────────────────
    billing_menu = mb.addMenu("&Billing")
    assert billing_menu is not None

    act_invoice = QAction("Generate Tax Invoice PDF…", app)
    act_invoice.setShortcut(QKeySequence("Ctrl+I"))
    act_invoice.triggered.connect(app.open_billing_dialog)
    billing_menu.addAction(act_invoice)

    act_cert = QAction("Generate Completion Certificate…", app)
    act_cert.triggered.connect(app.open_completion_cert_dialog)
    billing_menu.addAction(act_cert)

    # ── Settings ─────────────────────────────────────────────────────
    settings_menu = mb.addMenu("&Settings")
    assert settings_menu is not None

    act_profiles = QAction("User Profiles…", app)
    act_profiles.triggered.connect(app.open_user_profiles_dialog)
    settings_menu.addAction(act_profiles)

    settings_menu.addSeparator()

    act_db = QAction("Master Database", app)
    act_db.triggered.connect(app.open_db_manager)
    settings_menu.addAction(act_db)

    act_rules = QAction("Ruleset Manager", app)
    act_rules.triggered.connect(app.open_rule_manager)
    settings_menu.addAction(act_rules)

    settings_menu.addSeparator()

    act_year = QAction("Rate Chart Year", app)
    act_year.triggered.connect(app.change_rate_chart_year)
    settings_menu.addAction(act_year)

    act_defs = QAction("Placement Defaults", app)
    act_defs.triggered.connect(app.open_placement_defaults)
    settings_menu.addAction(act_defs)

    act_recipes = QAction("Iron Recipes Manager", app)
    act_recipes.triggered.connect(app.open_recipe_manager)
    settings_menu.addAction(act_recipes)

    act_props = QAction("Property Editor", app)
    act_props.triggered.connect(app.open_property_editor)
    settings_menu.addAction(act_props)

    settings_menu.addSeparator()

    act_reset = QAction("Reset App Data (Factory Reset)…", app)
    act_reset.setToolTip("Clear all data and restore the app to a fresh install")
    act_reset.triggered.connect(app.reset_all_app_data)
    settings_menu.addAction(act_reset)

    # ── Help ──────────────────────────────────────────────────────────
    help_menu = mb.addMenu("&Help")
    assert help_menu is not None

    act_help = QAction("User Guide", app)
    act_help.setShortcut(QKeySequence("F1"))
    act_help.triggered.connect(app.show_help)
    help_menu.addAction(act_help)

    help_menu.addSeparator()

    act_update = QAction("Check for Updates…", app)
    act_update.triggered.connect(app.check_for_updates)
    help_menu.addAction(act_update)

    help_menu.addSeparator()

    act_credits = QAction("Credits", app)
    act_credits.triggered.connect(app.show_credits)
    help_menu.addAction(act_credits)

    act_about = QAction("About", app)
    act_about.triggered.connect(app.show_about_dialog)
    help_menu.addAction(act_about)

    help_menu.addSeparator()

    exp_str = f"Valid Till: {APP_EXPIRY}" if APP_EXPIRY else "Permanent Build"
    act_valid = QAction(exp_str, app)
    act_valid.setEnabled(False)
    help_menu.addAction(act_valid)
