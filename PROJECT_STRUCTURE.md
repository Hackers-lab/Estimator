# ERP Estimate Generator — Project Structure

Overview of every file in the project and what it does.

---

## Python Source Files

### `app.py`
**Main application window and entry point.**

- Initialises the PyQt6 `QApplication` and the `QMainWindow` (`ERPApp`).
- Builds the entire UI: toolbar, drawing canvas (`InteractiveView` + `QGraphicsScene`), live estimate panel (`QTableWidget`), detail editor panel, and menu bar.
- Handles all user interactions on the canvas: tool selection, placing poles/structures/spans/consumers, selecting and editing objects.
- Manages project lifecycle: new project, open, save, autosave, save-as (all as `.json`).
- Calls `DynamicRuleEngine` to evaluate rules whenever the canvas changes and populates the live estimate table.
- Exports the estimate to a formatted Excel workbook (`.xlsx`) with multiple sheets (Materials, Labour, Iron Breakup, Summary).
- Exports the canvas drawing to PDF via `QPrinter`.
- Hosts the autosave timer (saves to `autosave_erp.json` every 60 seconds).
- Provides the `resource_path()` helper for PyInstaller-compatible asset loading.

---

### `canvas_objects.py`
**All interactive drawing items that appear on the canvas.**

Defines four `QGraphicsPathItem` subclasses:

| Class | Description |
|---|---|
| `SmartPole` | LT or HT single pole (PCC / STP / H-BEAM). Draws pole circle, stay wire, earth symbol. Colour-coded: LT=blue, HT=red, Existing=grey. |
| `SmartStructure` | Multi-pole HT structures: DP, TP, 4P, DTR sub-station. Draws 2/3/4-circle arrangements. Colour: DP/TP/4P=dark-green, DTR=orange. |
| `SmartSpan` | Conductor span between any two node endpoints. Draws straight or wavy line (wavy for AB Cable, PVC Cable, Service Drop). Draws CG bracket at midpoint when enabled. |
| `SmartConsumer` | Consumer service point (house symbol). |

Also contains:
- `_NodeMixin` — shared mixin for poles and structures: position flags, `itemChange` position propagation, connected-span update triggering.
- Path helper functions: `_stay_path()`, `_earth_path()`, `_cg_path()` for drawing symbols.
- `get_connection_point()` — calculates the precise edge point where a span line meets a pole or structure shape.

---

### `constants.py`
**Single source of truth for all configuration, lookup tables, and metadata.**

Contains:

| Constant | Purpose |
|---|---|
| `TOOLS` | Toolbar button definitions (key → display label). |
| `PROJECT_TYPES` | List of project type strings shown in the setup wizard. |
| `SUPERVISION_RATES` | Dict mapping each project type to its supervision charge rate. |
| `HEIGHT_OPTIONS` | Valid pole height strings per pole type. |
| `CONDUCTOR_SIZES` | Valid conductor size strings per conductor type. |
| `SERVICE_CABLE_SIZES` | Valid cable size strings for service drops. |
| `PROPERTY_DATA` | All user-editable properties for each object type (SmartPole, SmartStructure, SmartSpan, SmartConsumer) — used by the Rule Manager property picker and simulator. |
| `FORMULA_VARS` | Variable names available in rule formula expressions. |
| `SIM_DEFAULTS` | Default simulation values for each object type, used in the Rule Manager simulator. |
| `TREE_DEF` | Nested tree structure definition for the Rule Manager left-panel tree. |
| `FILTER_CHIPS` | Quick-filter chip labels shown above the Rule Manager card list. |

---

### `database.py`
**SQLite database setup and seeding.**

- Defines `setup_database(db_path)` which creates and seeds `erp_master.db` if it does not already exist.
- Contains `_SEED_MATERIALS` — a large list of all material items (code, name, rate, unit) sourced from WBSEDCL official orders (CED/36 FY2023-24 and supplementary FY2021-22 data).
- Contains `_SEED_LABOUR` — all labour task items (code, name, rate, unit) sourced from WBSEDCL erection rate orders (CED/13 and CED/15 dated 2018).
- Includes inline comments documenting official source documents for each rate, and notes on items requiring field verification.

---

### `rule_engine.py`
**Dynamic rule evaluation engine.**

- `DynamicRuleEngine` loads `rules.json` on startup.
- For each canvas item, builds an `item_context` dict containing all properties of that object plus global project properties (`use_uh`, `project_type`, supervision rate).
- Also computes derived context keys: `ab_cable_count`, `ab_needs_dead_end`, `ab_needs_suspension`, `lt_acsr_count`, `lt_wire_count`, `ht_spans_count`.
- Evaluates each rule's `condition` expression (safe eval — only `math` and `int` builtins allowed) against the context dict.
- When a condition passes, evaluates the `formula` expression to get the quantity.
- Returns a list of `(item_code, item_name, type, qty)` tuples that `app.py` uses to populate the live estimate table.

---

### `ui_components.py`
**Custom reusable Qt widgets.**

| Class | Description |
|---|---|
| `InteractiveView` | `QGraphicsView` subclass for the drawing canvas. Handles mouse-wheel zoom, middle-mouse pan, left/right click forwarding to `app.handle_canvas_click()`, Space-bar pan mode, and Escape to select mode. |
| `DraggableLabel` | `QGraphicsTextItem` for all on-canvas text labels (pole labels, span labels). Independently movable, double-click to edit inline, white pill background behind each line for legibility. |

---

### `ui_dialogs.py`
**All `QDialog` subclasses.**

| Dialog | Description |
|---|---|
| `ProjectSetupDialog` | Project wizard shown on launch and from "Project Settings". Captures project type, subject, lat/long, division, circle, UH toggle. |
| `SearchDialog` | Search the materials/labour database and add items directly to the estimate. |
| `SettingsDialog` | Gateway dialog linking to Database Manager and Ruleset Manager. |
| `DatabaseManagerDialog` | View, add, edit, delete, import (Excel), and export the SQLite master database of materials and labour rates. |
| `RulesetManagerDialog` | Full rule builder, editor, and simulator. Three-panel layout: tree navigator (left), rule cards (centre), rule editor (right). Includes a guided condition composer with property picker, operator picker, and token buttons (AND/OR/NOT/brackets). Rules are saved back to `rules.json`. |
| `ClickableCard` | Internal `QWidget` subclass used by `RulesetManagerDialog` to render each rule as a clickable card without monkey-patching `mousePressEvent`. |

---

## Data Files

### `rules.json`
**The live rule database — 193 rules across all object types.**

Each rule is a JSON object with:
- `object` — which canvas type it applies to (`SmartPole`, `SmartStructure`, `SmartSpan`, `SmartConsumer`).
- `condition` — a Python expression evaluated against the item context.
- `type` — `"Material"` or `"Labor"`.
- `item_code` — matches `item_code` in `erp_master.db`.
- `item_name` — human-readable material/labour description.
- `formula` — Python expression returning the quantity.

This file is read by `rule_engine.py` at startup and written by the Ruleset Manager when rules are saved.

---

### `erp_master.db`
**SQLite database of all material and labour rates.**

Two tables:
- `materials` — columns: `item_code`, `item_name`, `rate`, `unit`. Seeded from WBSEDCL official purchase order CED/36 FY2023-24.
- `labour` — columns: `item_code`, `task_name`, `rate`, `unit`. Seeded from WBSEDCL erection rate orders CED/13 and CED/15 (2018).

Created automatically by `database.py` on first run if not present. Managed through the Database Manager dialog in the app.

---

### `project.json`
**Last manually saved project file.**

Stores the full state of the current drawing:
- `version` — file format version number.
- `project_meta` — subject, lat/long, project type, UH toggle, supervision rate.
- `overrides` — any manual quantity overrides entered in the estimate table.
- `nodes` — list of all poles, structures, and consumers with all their properties and label positions.
- `spans` — list of all span connections with conductor details and label positions.

---

### `autosave_erp.json`
**Autosave file written every 60 seconds by the app.**

Same format as `project.json`. Loaded automatically if the app detects an unsaved session on startup (crash recovery).

---

## Build Files

### `build.py`
**PyInstaller build script.**

Running `python build.py`:
1. Cleans previous `build/` and `dist/` folders.
2. Runs PyInstaller in `--onedir --windowed` mode to produce a self-contained folder in `dist/`.
3. Copies data files (`rules.json`, `logo.svg`, `HELP.html`) next to the executable.
4. Zips the output folder into `dist/ERP_Estimate_v6.0.zip` for distribution.

---

### `ERP_Estimate.spec`
**PyInstaller spec file (auto-generated).**

Defines the build configuration for PyInstaller: entry point (`app.py`), hidden imports (`openpyxl`, `sqlite3`), windowed mode, UPX compression. Used internally by PyInstaller when `build.py` runs. Can also be invoked directly with `pyinstaller ERP_Estimate.spec`.

---

## Asset Files

### `logo.ico`
**Application icon** used as the window icon and the taskbar icon in the packaged executable.

### `logo.svg`
**Vector version of the application logo.** Bundled next to the executable by the build script; used for display inside the app where a high-resolution icon is needed.

### `HELP.html`
**In-app help document.** Displayed in the Help viewer dialog. Covers tool usage, rule manager, keyboard shortcuts, and export instructions.

---

## Documentation / Reference Files

### `DOCS/`
Sample saved project files used for testing and reference:
- `KUSHIDA PHE III.json` — a complete project drawing saved in v6 format.
- `NSC 6000123455.json` — another complete project drawing saved in v6 format.

### `df.pdf` / `Project_Drawing.pdf`
Reference PDF documents (field drawings / estimates) used during development for cross-checking generated output against real WBSEDCL estimate formats.

---

## Dependency / Environment Files

### `.venv/`
Python virtual environment containing all installed packages (`PyQt6`, `openpyxl`, `pyinstaller`, etc.). Not committed to version control.

### `build/`
Intermediate PyInstaller build artefacts (`.toc`, `.pyz`, analysis files). Generated by `build.py`, not committed.

### `dist/`
Final distributable output folder generated by `build.py`. Contains the packaged `ERP_Estimate/` folder and the `.zip` archive.

### `__pycache__/`
Python bytecode cache. Auto-generated, not committed.
