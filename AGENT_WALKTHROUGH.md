# ERP Estimate Generator — Agent Walkthrough
> **Version:** 7.5 | **Language:** Python 3.x | **Framework:** PyQt6 | **Author:** Pramod Verma
> 
> This document is a quick-reference map for coding agents. Read this first — do NOT scan all files blindly.

---

## What This App Does

**ERP Estimate Generator** is a PyQt6 desktop application for electrical network estimation, used by WBSEDCL field engineers. The user draws an electrical network schematic on a 2D canvas (poles, structures, spans, consumers), and the app automatically generates a Bill of Materials (BOM) + Labour estimate by evaluating a rule engine against every drawn object. Final output is an Excel workbook (multi-sheet) and a PDF drawing.

**Core user workflow:**
1. Launch → Project Setup Wizard (project type, subject, GPS coords, UH toggle)
2. Draw network on canvas using toolbar tools (LT poles, HT poles, structures, spans, consumers)
3. Live estimate updates in real time in the right panel
4. Export → Excel estimate + PDF drawing

---

## Directory Structure (Current — v7.5)

```
Estimator/
│
├── app.py                    ← MAIN ENTRY POINT & APPLICATION WINDOW
├── app_config.py             ← Version, expiry, paths, API key loader
├── api_secrets.py            ← Groq API key (gitignored in prod)
├── requirements.txt          ← PyQt6, openpyxl, pyinstaller
├── build.py                  ← PyInstaller build script
├── ERP_Estimate.spec         ← PyInstaller spec (auto-generated)
├── erp_master.db             ← SQLite DB: materials + labour rates
├── version.json              ← Version metadata
├── .env                      ← Environment variables (if any)
│
├── core/                     ← BUSINESS LOGIC LAYER
│   ├── constants.py          ← All enums, lookup tables, property definitions
│   ├── database.py           ← DB setup, database schema creation
│   ├── db_gateway.py         ← Unified DB read/write API for config and rates
│   ├── rule_engine.py        ← DynamicRuleEngine: reads rules from DB, evaluates canvas
│   ├── expression_engine.py  ← Safe math/condition evaluation engine
│   ├── property_catalog.py   ← Exposes definitions of standard properties
│   ├── property_registry.py  ← Registry for runtime object properties
│   ├── ai_rule_parser.py     ← Plain-English rule parsing logic (Groq API)
│   ├── rule_templates.py     ← Standard rule templates for rule creation
│   ├── data_mgr.py           ← User AppData directory initializer and synchronizer
│   ├── expiry.py             ← App expiry date check (APP_EXPIRY in app_config)
│   ├── defaults.py           ← Default property values for canvas objects
│   ├── option_colors.py      ← Display colors of canvas options
│   └── __init__.py
│
├── canvas/                   ← CANVAS DRAWING OBJECTS
│   ├── __init__.py           ← Exports: SmartPole, SmartStructure, SmartSpan,
│   │                            SmartConsumer, CanvasSymbol, CanvasTextBox, GridManager
│   ├── _base.py              ← SmartPole: LT/HT/Existing pole; _NodeMixin (position logic)
│   ├── nodes.py              ← SmartStructure (DP/TP/4P/DTR) and SmartConsumer (house symbol)
│   ├── span.py               ← SmartSpan: conductor span between two nodes
│   ├── annotations.py        ← CanvasSymbol (draw shapes) and CanvasTextBox (draggable labels)
│   ├── grid.py               ← GridManager: A4 page grid overlay on canvas
│   └── map_overlay.py        ← GPSBackgroundItem: OpenStreetMap tile overlay
│
├── ui/                       ← UI LAYER (widgets, dialogs, editors)
│   ├── __init__.py
│   ├── components.py         ← InteractiveView (canvas viewport), DraggableLabel
│   │
│   ├── dialogs/              ← MODULAR MODAL DIALOGS
│   │   ├── __init__.py
│   │   ├── _shared.py        ← Shared UI utilities and custom dialog bases
│   │   ├── project_setup.py  ← ProjectSetupDialog: settings on startup
│   │   ├── search.py         ← SearchDialog: searches DB to add manual items
│   │   ├── settings.py       ← SettingsDialog: gateway to master tools
│   │   ├── database_mgr.py   ← DatabaseManagerDialog: manage materials/labour rates
│   │   ├── ruleset_mgr.py    ← RulesetManagerDialog: tree, rules lists, simulator
│   │   ├── ai_assistant.py   ← AiAssistantDialog: plain-English rules AI setup
│   │   ├── placement.py      ← PlacementDefaultsDialog: placement preferences
│   │   └── property_editor.py ← PropertyEditorDialog: custom property slots
│   │
│   └── editors/              ← PROPERTY SIDEBAR PANEL
│       ├── __init__.py
│       ├── editor_mixin.py   ← EditorMixin: right-panel property editor for selected objects
│       └── _raw_extract.py   ← Raw values extraction helpers
│
├── exporters/                ← EXPORT LOGIC
│   ├── __init__.py
│   ├── excel.py              ← Generates multi-sheet .xlsx (Materials, Labour, Iron Breakup, Summary)
│   └── pdf.py                ← Renders canvas to multi-page PDF via QPrinter
│
├── data/                     ← RUNTIME DATA BACKUPS & SEEDS
│   ├── rules.json            ← 230+ baseline estimation rules
│   ├── seed_data.json        ← Baseline WBSEDCL materials and labour rates
│   ├── property_catalog.json ← Baseline property declarations
│   └── defaults.json         ← Backup / default configuration settings
│
├── assets/                   ← STATIC ASSETS
│   ├── logo.svg              ← App icon (vector)
│   ├── logo.ico              ← App icon (Windows executable)
│   ├── HELP.html             ← In-app help document
│   └── icons/                ← Toolbar icon SVGs
│
├── DOCS/                     ← Sample project JSON files for testing
├── CHANGELOG.md
├── FUTURE_FEATURES.md        ← Planned features backlog
└── PROJECT_STRUCTURE.md      ← Original structure doc (may be slightly outdated)
```

> **Note:** The `__pycache__/` folder at root is a Python bytecode cache — ignore it.

---

## File-by-File Purpose

### Root Level

| File | Purpose |
|------|---------|
| `app.py` | `EstimateApp(QMainWindow, EditorMixin)` — entire UI layout, tool management, canvas interaction, autosave timer, project open/save/new, calls rule engine, populates live estimate table, triggers exports |
| `app_config.py` | `APP_VERSION`, `APP_EXPIRY`, `APP_AUTHOR`, `get_data_path()`, `get_user_data_path()` — single place to bump version or expiry date |
| `api_secrets.py` | Holds `GROQ_API_KEY` for the AI Rule Creator feature; imported by `app_config.py` with a safe fallback |
| `build.py` | Runs PyInstaller to package standalone EXE alongside a pre-seeded database, zips output |
| `erp_master.db` | SQLite database — holds rates, rules, options, settings, and custom slots; seeded from JSON backups |
| `requirements.txt` | `PyQt6>=6.4.0`, `openpyxl>=3.1.0`, `pyinstaller>=6.0.0` |

---

### `core/` — Business Logic

| File | Key Contents |
|------|-------------|
| `core/constants.py` | `TOOLS` dict, `PROJECT_TYPES`, `SUPERVISION_RATES`, `HEIGHT_OPTIONS`, `CONDUCTOR_SIZES`, `SERVICE_CABLE_SIZES`, `SAG_ITEMS`, `PROPERTY_DATA`, `FORMULA_VARS`, `SIM_DEFAULTS`, `TREE_DEF`, `FILTER_CHIPS` |
| `core/database.py` | `setup_database()` — creates `erp_master.db` on launch; syncs and imports from `seed_data.json`, `rules.json`, `property_catalog.json` |
| `core/db_gateway.py` | Unified SQLite CRUD operations for rules, settings, material rates, custom properties, and heights/conductor sizes |
| `core/rule_engine.py` | `DynamicRuleEngine` — reads rules directly from DB and evaluates canvas object attributes against them |
| `core/expression_engine.py`| Safely evaluates conditional expressions and mathematical formulas with restricted namespaces (using `math` + `int` builtins) |
| `core/expiry.py` | `check_expiry()` — compares today vs `APP_EXPIRY` to manage subscription/trial validity |
| `core/defaults.py` | Default property dictionaries for new poles, structures, spans, and consumers |
| `core/option_colors.py` | Maps specific canvas object properties to their dynamic colors |
| `core/data_mgr.py` | Performs safe copying and syncing of JSON baseline configuration files into `%APPDATA%` |

---

### `canvas/` — Drawing Objects

All canvas items are `QGraphicsItem` subclasses. They draw themselves and notify `app.py` of changes via Qt signals.

| Class / Mixin | File | What it Draws / Does | Key Properties / Context |
|-------|------|---------------|----------------|
| `SmartPole` | `canvas/_base.py` | Circle + stay wire + earth symbol. LT=blue, HT=red, Existing=grey | `pole_type`, `pole_type2`, `height`, `stay_count`, `earth_count`, `sin_number`, `is_dp_end`, `is_existing` |
| `SmartStructure` | `canvas/nodes.py` | 2/3/4 circles arranged for DP/TP/4P; DTR=orange box | `structure_type` (DP/TP/4P/DTR), `pole_type2`, `height`, `dtr_size`, `stay_count`, `earth_count` |
| `SmartSpan` | `canvas/span.py` | Straight or wavy line between two node endpoints; CG bracket at midpoint | `conductor_type`, `conductor_size`, `length` (auto-computed), `voltage` (auto-detected), `wire_count`, `is_existing_span`, `is_service_drop` |
| `SmartConsumer` | `canvas/nodes.py` | House symbol connected via service drop to a nearby pole | `phase` (Single / Three), `cable_size`, `agency_supply` |
| `CanvasSymbol` | `canvas/annotations.py` | Decorative shape: circle, square, arrow, solid line, dashed line | `shape`, `color`, `size` |
| `CanvasTextBox` | `canvas/annotations.py` | Draggable text label; double-click to edit inline | `text`, `font_size`, `color` |
| `GridManager` | `canvas/grid.py` | Computes A4 page grid tiles from canvas bounding box; used for PDF pagination and visual grid overlay | Reads `pdf_scale`, `pdf_orientation_mode`, `pdf_page_overrides` from `app.py` |
| `GPSBackgroundItem` | `canvas/map_overlay.py` | Fetches OpenStreetMap tiles for given lat/lon/zoom and composites them as a background `QGraphicsItem` | Requires internet; tiles cached in session |
| `_NodeMixin` | `canvas/_base.py` | Shared connection management. mixed into `SmartPole` and `SmartStructure` | Propagates moves to all connected `SmartSpan` objects |

**`get_connection_point()`** — calculates the precise edge point where a span line meets a pole/structure boundary (not the center).

---

### `ui/` — Interface Layer

| File | Key Contents |
|------|-------------|
| `ui/components.py` | `InteractiveView(QGraphicsView)` — mouse-wheel zoom, middle-mouse pan, spacebar-pan, routes clicks to `app.handle_canvas_click()`; `DraggableLabel` — on-canvas labels with pill background |
| `ui/editors/editor_mixin.py` | `EditorMixin` — mixed into `EstimateApp`; builds and populates the right-panel "Object Properties" form dynamically when a canvas item is selected; handles all property fields and updates items live |
| `ui/dialogs/` | Modular dialogue classes loaded on demand (see detailed list below) |

**Dialogues in `ui/dialogs/`:**

| Dialog Class | File | Purpose |
|---|---|---|
| `ProjectSetupDialog` | `ui/dialogs/project_setup.py` | Wizard on launch/new project capturing metadata (Project Type, Subject, lat/long, UH selection) |
| `SearchDialog` | `ui/dialogs/search.py` | Performs safe SQLite searches against `erp_master.db` to add materials/labour overrides manually |
| `SettingsDialog` | `ui/dialogs/settings.py` | Configuration dialog providing shortcuts to Ruleset and DB manager tools |
| `DatabaseManagerDialog` | `ui/dialogs/database_mgr.py` | Interactive grid to edit, search, add, or bulk import/export rates from Excel in the master database |
| `RulesetManagerDialog` | `ui/dialogs/ruleset_mgr.py` | Multi-panel rule suite: Left tree category selection, middle rules list, right editor panel with live sandbox testing |
| `AiAssistantDialog` | `ui/dialogs/ai_assistant.py` | Captures plain-English descriptions and uses the Groq AI API to generate clean rule syntax |
| `PlacementDefaultsDialog`| `ui/dialogs/placement.py` | Configures defaults for LT/HT poles, spans, and consumer labels |
| `PropertyEditorDialog` | `ui/dialogs/property_editor.py` | Custom Property manager enabling user-defined select inputs (Custom 1..N) and database Heights & Sizes |

---

### `exporters/` — Output Generation

| File | Purpose |
|------|---------|
| `exporters/excel.py` | Uses `openpyxl` to generate a multi-sheet `.xlsx` workbook: Sheet 1 = Estimate BOM, Sheet 2 = Iron Breakup (weights categorized by pole types), and manages automatic 5% escalation/sundries calculations |
| `exporters/pdf.py` | Scaled multi-page A4 canvas export via `QPainter` onto `QPrinter`. Formats title blocks dynamically, handles legends, and prints continue-page indicators |

---

### `data/rules.json` — Rule Database

This is the most important configuration file. Each rule is a JSON object:

```json
{
  "object": "SmartPole",
  "condition": "pole_type == 'LT' and height == '8 mtr'",
  "type": "Material",
  "item_code": "M-001",
  "item_name": "PCC Pole 8m",
  "formula": "1"
}
```

Fields:
- `object` — which canvas class: `SmartPole`, `SmartStructure`, `SmartSpan`, `SmartConsumer`
- `condition` — Python expression; evaluated against item context dict
- `type` — `"Material"` or `"Labor"`
- `item_code` — must match `item_code` in `erp_master.db`
- `item_name` — display name in estimate table
- `formula` — Python expression returning quantity (can reference context variables)

**Context variables available in conditions/formulas:** All object properties + `use_uh`, `project_type`, `supervision_rate`, `ab_cable_count`, `ab_needs_dead_end`, `ab_needs_suspension`, `lt_acsr_count`, `lt_wire_count`, `ht_spans_count`

---

## How Modules Are Linked

```
app.py (EstimateApp)
  │
  ├── imports EditorMixin from ui/editors/editor_mixin.py (property side-form)
  ├── imports InteractiveView from ui/components.py       (canvas viewport widget)
  ├── imports dialogs on-demand from ui/dialogs/
  │
  ├── imports SmartPole, SmartStructure, SmartSpan,
  │          SmartConsumer, CanvasSymbol, CanvasTextBox,
  │          GridManager from canvas/
  │
  ├── imports DynamicRuleEngine from core/rule_engine.py
  │     └── rule_engine reads rules from SQLite database via core/db_gateway.py
  │
  ├── imports setup_database, DB_PATH from core/database.py
  │     └── database.py creates erp_master.db and seeds it via seed_data.json
  │
  ├── imports constants from core/constants.py            (lookups and enums)
  ├── imports defaults from core/defaults.py              (default property values)
  ├── imports check_expiry from core/expiry.py
  │
  ├── calls exporters/excel.py on "Generate Excel"
  └── calls exporters/pdf.py on "Export PDF"
```

**Data flow for live estimate:**
1. User places/moves a canvas object → `QGraphicsScene` item change → `app.refresh_signal` emitted
2. `EstimateApp.refresh_live_estimate()` collects all `SmartPole/Structure/Span/Consumer` items from scene
3. Passes them + `project_meta` to `DynamicRuleEngine.evaluate()`
4. Rule engine builds an `item_context` dict per object, evaluates all matching rules
5. Returns aggregated list of `(code, name, type, qty)` tuples
6. `app.py` populates `live_table` (QTableWidget) and recomputes grand total

**Data flow for save/load:**
- **Save:** Serializes all canvas items to JSON (`nodes` list + `spans` list + `project_meta` + `bom_overrides`) → written to `.json` file
- **Load:** Reads JSON, recreates all items by calling the appropriate canvas class constructors, reconnects spans by matching node IDs

---

## Key Classes & Their Responsibilities

| Class / Mixin | File | Role |
|-------|------|------|
| `EstimateApp` | `app.py` | God class — owns QMainWindow, scene, all state |
| `EditorMixin` | `ui/editors/editor_mixin.py` | Mixin that adds property editor panel methods to EstimateApp |
| `DynamicRuleEngine` | `core/rule_engine.py` | Stateless evaluator: given items + meta → returns BOM rows |
| `InteractiveView` | `ui/components.py` | Canvas view with zoom/pan; routes mouse events |
| `SmartPole` | `canvas/_base.py` | Self-drawing QGraphicsItem; holds all pole state |
| `SmartSpan` | `canvas/span.py` | Connects two nodes; auto-updates geometry on node move |
| `GridManager` | `canvas/grid.py` | Computes page tile layout; used by view overlay + PDF exporter |

---

## Important Constants & Configuration Points

| Where to change | What it controls |
|----------------|-----------------|
| `app_config.py → APP_VERSION` | Version number shown in title bar and About dialog |
| `app_config.py → APP_EXPIRY` | Hard expiry date (set `None` to disable) |
| `app_config.py → APP_AUTHOR` | Author name in credits |
| `core/constants.py → TOOLS` | Toolbar button list (adding/removing tools) |
| `core/constants.py → PROJECT_TYPES` | Dropdown options in Project Setup |
| `core/constants.py → SUPERVISION_RATES` | Rate % per project type |
| `core/constants.py → PROPERTY_DATA` | Editable properties per object type |
| SQLite DB rules table | All estimation rules (add/edit via Ruleset Manager UI or direct DB edit) |
| SQLite DB rates table | Material/labour rates (edit via Database Manager UI or SQLite) |

---

## Project Save Format (`.json`)

```json
{
  "version": 7,
  "project_meta": {
    "subject": "Project Name",
    "lat": "22.5726",
    "long": "88.3639",
    "project_type": "NSC",
    "use_uh": false,
    "supervision_rate": 0.10
  },
  "overrides": { "M-001": 5 },
  "nodes": [
    {
      "type": "SmartPole",
      "id": "pole_001",
      "x": 100, "y": 200,
      "pole_type": "LT",
      "pole_type2": "PCC",
      "height": "8 mtr",
      "label_offset": [0, -40],
      ...
    }
  ],
  "spans": [
    {
      "from_id": "pole_001",
      "to_id": "pole_002",
      "conductor_type": "ACSR",
      "conductor_size": "35 sq.mm",
      ...
    }
  ]
}
```

Autosave writes to `autosave_erp.json` every 60 seconds in the working directory.

---

## Tech Stack Summary

| Concern | Technology |
|---------|-----------|
| UI framework | PyQt6 (`QMainWindow`, `QGraphicsScene/View`, `QDialog`) |
| Canvas drawing | `QGraphicsItem` subclasses with custom `paint()` |
| Database | SQLite3 (stdlib) via `erp_master.db` |
| Excel export | `openpyxl` |
| PDF export | `QPrinter` (built into PyQt6) |
| AI Rule Creator | Groq API (configured in `api_secrets.py`) |
| GPS maps | OpenStreetMap tile HTTP fetch → `QPixmap` |
| Build/packaging | PyInstaller (onedir, windowed) |
| Python version | 3.x (3.10+ recommended for PyQt6) |

---

## Common Agent Tasks — Where to Look

| Task | Files to touch |
|------|---------------|
| Add a new canvas object type | `canvas/` (new file) + `canvas/__init__.py` + `core/constants.py (PROPERTY_DATA)` + `app.py (tool handling, save/load)` + SQLite rules table |
| Add a new toolbar tool | `core/constants.py → TOOLS` + `app.py → set_tool()` + `ui/components.py → handle_canvas_click()` |
| Add/modify estimation rules | SQLite rules table (or use Ruleset Manager UI) |
| Change material/labour rates | `erp_master.db` (or use Database Manager UI); seed data in `core/database.py` |
| Change export format | `exporters/excel.py` or `exporters/pdf.py` |
| Add a new dialog | `ui/dialogs/` (new file) + wire trigger in `app.py` menu/button |
| Change app version or expiry | `app_config.py` |
| Modify property editor fields | `core/constants.py → PROPERTY_DATA` + `ui/editors/editor_mixin.py` |
| Add canvas annotations | `canvas/annotations.py` |

---

## Known Architecture Notes

- `EstimateApp` inherits from both `QMainWindow` and `EditorMixin` (Python multiple inheritance). `EditorMixin` must NOT call `super().__init__()` — it is a pure mixin.
- The rule engine uses safe parsing/evaluation in `core/expression_engine.py` — **do not expose arbitrary builtins**.
- `resource_path()` in `app.py` handles PyInstaller's `_MEIPASS` temp directory for bundled assets.
- User data (DB, autosave) goes to `%APPDATA%/ERP_Estimate/` on Windows, `~/.local/share/ERP_Estimate/` on Linux — managed by `app_config.get_user_data_path()`.
- The canvas uses **17.5 scene units ≈ 1 real-world metre** (calibrated: 40m span ≈ 700 scene units). Span lengths shown in estimate are computed from this ratio.
- `SmartSpan.length` is computed automatically from the Euclidean distance between connected node positions — users should not set it manually.
- Undo/redo uses a JSON snapshot history (`app.history` list). A `QTimer` (single-shot, 300ms debounce) calls `push_history()` after changes.

---

*Last updated: May 2026 | Based on repo state at v7.5*
