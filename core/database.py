"""
database.py
===========
Database setup for ERP Estimate Generator.

DATA SOURCES (all material rates are inclusive of GST):
--------------------------------------------------------
1. Material codes & rates — PRIMARY SOURCE:
   O/O No. CED/36 dated 20-07-2023, Chief Engineer (Distribution), WBSEDCL
   "Central Purchase Item for Estimation Purpose Only, FY 2023-2024"

2. Material codes & rates — SUPPLEMENTARY (items not in 2023-24 list):
   Material Cost Data FY 2021-22, WBSEDCL (COST_DATA_ALL_IN_ONE.pdf)

3. Labour rates:
   O/O No. CED/13 dt. 15.05.2018 — Erection Rate for New Construction Works
   O/O No. CED/15 dt. 15.05.2018 — Erection Rate for HT & LT AB Cables
   O/O No. CED/UG Cable Rate Contract — Underground Cable Rates
   As adopted in ESTIMATE_FORMAT_2023.xlsx (Durgapur Division)

ITEMS NEEDING FIELD VERIFICATION:
-----------------------------------
- STP 9.5M rate: CED/36 scan reads 116598.41 — likely OCR error for 16598.41.
  Update via DB Manager once verified.
- DTR 25KVA rate: CED/36 shows same code as 63KVA (both 0301018141/0301018241).
  Used separate codes from 2021-22 data for 25KVA.
- ABC cable rates had lakh-notation artifacts in scan — cleaned versions used.

ITEMS WITHOUT OFFICIAL WBSEDCL CODE:
--------------------------------------
- UH readymade materials use "LOCAL-UH0x" prefix.
  Replace with official codes when available.
"""

import sqlite3
import json
import os

from app_config import get_app_root as _get_app_root
DB_PATH = os.path.join(_get_app_root(), "erp_master.db")
_SEED_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "seed_data.json")
_RULES_FILE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "rules.json")
_CATALOG_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "property_catalog.json")

# Prefixes / codes for incremental rows added to existing databases
_NEW_MATERIAL_PREFIXES = (
    "0110010", "0110011", "0110020", "0110051",
    "0101011011", "0103011611", "0103011911", "0103012311",
    "0502010621", "0502011221",
    "0501030321", "0501030421", "0501031121",
    "0501017921", "0501018121", "0501018221", "0501018321",
    "0301010541", "0301011041", "0301018341", "0301018741",
    "0301019041", "0301019141", "0301019341",
    "0407010741", "0407010541",
    "0504070341",
    "195021741", "597011541", "597011741",
    "0508040441",
)
_NEW_LABOUR_CODES = {
    "LAB-04", "LAB-07", "LAB-08",
    "LAB-09", "LAB-10", "LAB-11", "LAB-12",
    "LAB-13", "LAB-14", "LAB-15", "LAB-16",
    "LAB-17", "LAB-18",
    "LAB-19", "LAB-20", "LAB-21",
    "LAB-23", "LAB-24", "LAB-26", "LAB-27", "LAB-28", "LAB-29",
    "LAB-32", "LAB-33", "LAB-34", "LAB-35",
    "LAB-36", "LAB-37", "LAB-38", "LAB-39",
    "LAB-61", "LAB-62", "LAB-63", "LAB-71", "LAB-72", "LAB-73",
    "LAB-64", "LAB-65", "LAB-66",
    "LAB-67", "LAB-68", "LAB-69", "LAB-70",
}


def _load_seed_data() -> tuple[list, list]:
    """Load seed materials and labour from seed_data.json."""
    try:
        with open(_SEED_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        materials = [tuple(r) for r in data.get("materials", [])]
        labour    = [tuple(r) for r in data.get("labour", [])]
        return materials, labour
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"[DB] Warning: could not load seed_data.json ({exc}). Using empty seed.")
        return [], []


def setup_database():
    """Called on every app launch. Seed data is loaded lazily only when needed."""
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            item_code  TEXT,
            item_name  TEXT PRIMARY KEY,
            rate       REAL,
            unit       TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS labor (
            labor_code TEXT PRIMARY KEY,
            task_name  TEXT,
            rate       REAL,
            unit       TEXT
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM materials")
    is_empty = cursor.fetchone()[0] == 0

    seed_materials, seed_labour = _load_seed_data()

    if is_empty:
        cursor.executemany("INSERT INTO materials VALUES (?,?,?,?)", seed_materials)
        cursor.executemany("INSERT INTO labor VALUES (?,?,?,?)", seed_labour)
    else:
        new_materials = [r for r in seed_materials if r[0].startswith(_NEW_MATERIAL_PREFIXES)]
        new_labour    = [r for r in seed_labour    if r[0] in _NEW_LABOUR_CODES]
        cursor.executemany("INSERT OR IGNORE INTO materials VALUES (?,?,?,?)", new_materials)
        cursor.executemany("INSERT OR IGNORE INTO labor VALUES (?,?,?,?)", new_labour)

    # ── Config tables (added in v7.0) ──────────────────────────────────────────
    _create_config_tables(cursor)

    # Seed config tables the first time (rules table empty = fresh DB or migration)
    cursor.execute("SELECT COUNT(*) FROM rules")
    if cursor.fetchone()[0] == 0:
        _seed_config_tables(cursor)

    conn.commit()
    conn.close()


def _create_config_tables(cursor) -> None:
    """Create all configuration tables (idempotent)."""

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            condition   TEXT NOT NULL,
            formula     TEXT NOT NULL,
            type        TEXT NOT NULL,
            item_code   TEXT NOT NULL DEFAULT '',
            item_name   TEXT NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1,
            sort_order  INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type  TEXT NOT NULL,
            prop_name    TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            widget_type  TEXT NOT NULL DEFAULT 'combo',
            sim_default  TEXT NOT NULL DEFAULT '',
            sim_min      REAL DEFAULT NULL,
            sim_max      REAL DEFAULT NULL,
            is_formula_var BOOLEAN DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            UNIQUE(object_type, prop_name)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS property_options (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            option_val  TEXT NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS height_options (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pole_type2  TEXT NOT NULL,
            height_val  REAL NOT NULL,
            is_builtin  INTEGER NOT NULL DEFAULT 1,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            UNIQUE(pole_type2, height_val)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conductor_options (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            conductor_type TEXT NOT NULL,
            voltage_class  TEXT NOT NULL,
            size_value     TEXT NOT NULL,
            is_builtin     INTEGER NOT NULL DEFAULT 1,
            sort_order     INTEGER NOT NULL DEFAULT 0,
            UNIQUE(conductor_type, voltage_class, size_value)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key      TEXT PRIMARY KEY,
            value    TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS extended_options (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            prop_name   TEXT NOT NULL,
            option_val  TEXT NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            UNIQUE(object_type, prop_name, option_val)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_properties (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            label       TEXT NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            UNIQUE(object_type, label)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_property_options (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            custom_property_id INTEGER NOT NULL,
            option_val         TEXT NOT NULL,
            sort_order         INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conductor_meta (
            name    TEXT PRIMARY KEY,
            voltage TEXT NOT NULL DEFAULT 'Both'
        )
    """)

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT UNIQUE,
            supervision_rate REAL NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rule_tree_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER,
            label TEXT NOT NULL,
            object_type TEXT NOT NULL,
            filter_dict_json TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(parent_id) REFERENCES rule_tree_nodes(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rule_filter_chips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            label TEXT NOT NULL,
            prop_name TEXT NOT NULL,
            match_value TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    ''')

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_color_overrides (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type   TEXT NOT NULL,
            prop_name     TEXT NOT NULL,
            option_val    TEXT NOT NULL DEFAULT '*',
            context_key   TEXT NOT NULL DEFAULT '',
            default_color TEXT NOT NULL,
            user_color    TEXT DEFAULT NULL,
            UNIQUE(object_type, prop_name, option_val, context_key)
        )
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rules_object ON rules(object_type, enabled)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_props_object ON properties(object_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prop_opts ON property_options(property_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ext_opts ON extended_options(object_type, prop_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cp_obj ON custom_properties(object_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cpo_cp ON custom_property_options(custom_property_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_height_pt2 ON height_options(pole_type2)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cond_opts ON conductor_options(conductor_type, voltage_class)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_color_overrides "
        "ON option_color_overrides(object_type, prop_name, option_val, context_key)"
    )


def _seed_config_tables(cursor) -> None:
    """Seed all config tables from existing JSON / constants.  Called once on fresh DB or schema migration."""

    # ── Project Types, Tree Def, Filter Chips, Formula Vars (Phase 3) ──────────
    try:
        from core.constants import PROJECT_TYPES, SUPERVISION_RATES, TREE_DEF, FILTER_CHIPS, FORMULA_VARS
        
        # Project Types
        for pt in PROJECT_TYPES:
            rate = SUPERVISION_RATES.get(pt, 0.10)
            cursor.execute("INSERT OR IGNORE INTO project_types (type_name, supervision_rate) VALUES (?, ?)", (pt, rate))

        # Formula Vars
        for obj_type, vars_list in FORMULA_VARS.items():
            for v in vars_list:
                cursor.execute("UPDATE properties SET is_formula_var=1 WHERE object_type=? AND prop_name=?", (obj_type, v))

        # Rule Tree Nodes
        cursor.execute("SELECT COUNT(*) FROM rule_tree_nodes")
        if cursor.fetchone()[0] == 0:
            def _insert_tree_node(parent_id, node, order):
                label, obj, filter_dict, children = node
                filter_json = json.dumps(filter_dict)
                cursor.execute(
                    "INSERT INTO rule_tree_nodes (parent_id, label, object_type, filter_dict_json, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (parent_id, label, obj, filter_json, order)
                )
                node_id = cursor.lastrowid
                for idx, child in enumerate(children):
                    _insert_tree_node(node_id, child, idx)

            for idx, root in enumerate(TREE_DEF):
                _insert_tree_node(None, root, idx)

        # Filter Chips
        cursor.execute("SELECT COUNT(*) FROM rule_filter_chips")
        if cursor.fetchone()[0] == 0:
            for obj_type, chips in FILTER_CHIPS.items():
                for idx, chip in enumerate(chips):
                    label = chip[0]
                    prop_name = chip[1]
                    match_val = str(chip[2])
                    cursor.execute(
                        "INSERT INTO rule_filter_chips (object_type, label, prop_name, match_value, sort_order) VALUES (?, ?, ?, ?, ?)",
                        (obj_type, label, prop_name, match_val, idx)
                    )
    except ImportError:
        pass

    # ── Rules ──────────────────────────────────────────────────────────────────
    rules_data: list = []
    try:
        with open(_RULES_FILE, "r", encoding="utf-8") as _f:
            rules_data = json.load(_f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    for _i, _r in enumerate(rules_data):
        cursor.execute(
            "INSERT OR IGNORE INTO rules "
            "(object_type, condition, formula, type, item_code, item_name, enabled, sort_order) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (
                _r.get("object", ""),
                _r.get("condition", "True"),
                _r.get("formula", "1"),
                _r.get("type", "Material"),
                _r.get("item_code", ""),
                _r.get("item_name", ""),
                _i,
            ),
        )

    # ── Properties + PropertyOptions (from constants) ──────────────────────────
    try:
        from core.constants import (  # noqa: PLC0415
            PROPERTY_DATA as _PD,
            SIM_DEFAULTS  as _SD,
        )
    except ImportError:
        _PD, _SD = {}, {}

    for _obj_type, _props in _PD.items():
        for _sort_idx, (_prop_name, _prop_val) in enumerate(_props.items()):
            _sim_entry = _SD.get(_obj_type, {}).get(_prop_name)
            if _sim_entry:
                _wtype, _wrange, _wdefault = _sim_entry
                _sim_default = str(_wdefault)
                if _wtype in ("spin", "dspin") and isinstance(_wrange, tuple):
                    _sim_min, _sim_max = float(_wrange[0]), float(_wrange[1])
                    _widget_type = _wtype
                else:
                    _sim_min = _sim_max = None
                    _widget_type = "combo"
            else:
                if isinstance(_prop_val, list):
                    _widget_type = "combo"
                    _sim_default = str(_prop_val[0]) if _prop_val else ""
                    _sim_min = _sim_max = None
                elif _prop_val == "int":
                    _widget_type = "spin"
                    _sim_default = "0"
                    _sim_min, _sim_max = 0.0, 100.0
                else:
                    _widget_type = "text"
                    _sim_default = ""
                    _sim_min = _sim_max = None

            _display = _prop_name.replace("_", " ").title()
            cursor.execute(
                "INSERT OR IGNORE INTO properties "
                "(object_type, prop_name, display_name, widget_type, sim_default, sim_min, sim_max, sort_order) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_obj_type, _prop_name, _display, _widget_type, _sim_default, _sim_min, _sim_max, _sort_idx),
            )

            cursor.execute(
                "SELECT id FROM properties WHERE object_type=? AND prop_name=?",
                (_obj_type, _prop_name),
            )
            _prop_row = cursor.fetchone()
            if not _prop_row:
                continue
            _prop_id = _prop_row[0]

            # Collect options: merge PROPERTY_DATA list + SIM_DEFAULTS combo list
            _options: list[str] = []
            if isinstance(_prop_val, list):
                _options = [str(v) for v in _prop_val]
            if _sim_entry and _widget_type == "combo" and isinstance(_sim_entry[1], list):
                for _opt in _sim_entry[1]:
                    if str(_opt) not in _options:
                        _options.append(str(_opt))

            for _opt_idx, _opt_val in enumerate(_options):
                cursor.execute(
                    "INSERT OR IGNORE INTO property_options (property_id, option_val, sort_order) VALUES (?,?,?)",
                    (_prop_id, _opt_val, _opt_idx),
                )

    # ── Height Options (from constants.HEIGHT_OPTIONS) ─────────────────────────
    try:
        from core.constants import HEIGHT_OPTIONS as _HO  # noqa: PLC0415
    except ImportError:
        _HO = {}

    for _pt2, _heights in _HO.items():
        for _hi, _h_str in enumerate(_heights):
            try:
                _hval = float(str(_h_str).replace("MTR", "").strip())
            except (ValueError, AttributeError):
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO height_options (pole_type2, height_val, is_builtin, sort_order) VALUES (?,?,1,?)",
                (_pt2, _hval, _hi),
            )

    # ── Conductor Options (from constants.CONDUCTOR_SIZES) ─────────────────────
    try:
        from core.constants import CONDUCTOR_SIZES as _CS  # noqa: PLC0415
    except ImportError:
        _CS = {}

    for (_ctype, _vclass), _sizes in _CS.items():
        for _ci, _sz in enumerate(_sizes):
            cursor.execute(
                "INSERT OR IGNORE INTO conductor_options "
                "(conductor_type, voltage_class, size_value, is_builtin, sort_order) VALUES (?,?,?,1,?)",
                (_ctype, _vclass, _sz, _ci),
            )

    # ── Settings (inline copy of defaults._FACTORY to avoid circular import) ───
    _SETTINGS_SEED: list[tuple[str, str, str]] = [
        # key, value, category
        ("lt_pole_type2",      "PCC",                "placement"),
        ("lt_height",          "8MTR",               "placement"),
        ("lt_earth_count",     "1",                  "placement"),
        ("lt_stay_count",      "0",                  "placement"),
        ("lt_dist_box_required", "true",             "placement"),
        ("ht_pole_type2",      "PCC",                "placement"),
        ("ht_height",          "9MTR",               "placement"),
        ("ht_earth_count",     "1",                  "placement"),
        ("ht_stay_count",      "0",                  "placement"),
        ("extension_height",   "3.0",                "placement"),
        ("node_min_gap",       "36",                 "placement"),
        ("existing_stay_angle_tolerance_deg", "20",  "placement"),
        ("struct_pole_type2",  "PCC",                "placement"),
        ("struct_height",      "9MTR",               "placement"),
        ("struct_stay_count",  "4",                  "placement"),
        ("struct_orientation", "Horizontal",         "placement"),
        ("dtr_kiosk_required", "true",               "placement"),
        ("lt_conductor",       "AB Cable",           "placement"),
        ("lt_conductor_size",  "3CX50+1CX16+1CX35",  "placement"),
        ("lt_span_length",     "40",                 "placement"),
        ("lt_wire_count",      "4",                  "placement"),
        ("ht_conductor",       "ACSR",               "placement"),
        ("ht_conductor_size",  "50SQMM",             "placement"),
        ("ht_span_length",     "40",                 "placement"),
        ("ht_wire_count",      "3",                  "placement"),
        ("ht_cg_required",     "true",               "placement"),
        ("sd_conductor_size",  "10 SQMM",            "placement"),
        ("sd_length",          "20",                 "placement"),
        ("sd_phase",           "3 Phase",            "placement"),
        ("canvas_lt_pole",         "#2980b9",         "canvas_color"),
        ("canvas_ht_pole",         "#c0392b",         "canvas_color"),
        ("canvas_ex_pole",         "#cccccc",         "canvas_color"),
        ("canvas_ex_aug_dtr",      "#f7b267",         "canvas_color"),
        ("canvas_dp",              "#27ae60",         "canvas_color"),
        ("canvas_tp",              "#1abc9c",         "canvas_color"),
        ("canvas_4p",              "#16a085",         "canvas_color"),
        ("canvas_dtr",             "#e67e22",         "canvas_color"),
        ("canvas_consumer",        "#f1c40f",         "canvas_color"),
        ("canvas_consumer_agency", "#f39c12",         "canvas_color"),
        ("canvas_acsr",            "#222222",         "canvas_color"),
        ("canvas_ab_cable",        "#1a5276",         "canvas_color"),
        ("canvas_pvc_cable",       "#107C41",         "canvas_color"),
        ("canvas_svc_drop",        "#d35400",         "canvas_color"),
        ("export_last_dir",        "",                "export"),
        ("label_new_lt",   "PP",   "label"),
        ("label_new_ht",   "HP",   "label"),
        ("label_ex_pole",  "EP",   "label"),
        ("label_dp",       "DP",   "label"),
        ("label_tp",       "TP",   "label"),
        ("label_4p",       "4P",   "label"),
        ("label_dtr",      "DTR",  "label"),
        ("label_consumer", "SC",   "label"),
    ]
    for _key, _val, _cat in _SETTINGS_SEED:
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value, category) VALUES (?,?,?)",
            (_key, _val, _cat),
        )

    # Migrate existing defaults.json (user's customised values take precedence)
    _dfile = os.path.join(_get_app_root(), "data", "defaults.json")
    if os.path.exists(_dfile):
        try:
            with open(_dfile, "r", encoding="utf-8") as _df:
                _existing_defaults = json.load(_df)
            for _k, _v in _existing_defaults.items():
                cursor.execute(
                    "UPDATE settings SET value=? WHERE key=?",
                    (str(_v), _k),
                )
        except (json.JSONDecodeError, OSError):
            pass

    # ── Property catalog (custom entries, extended options, conductor meta) ─────
    _catalog: dict = {}
    try:
        with open(_CATALOG_FILE, "r", encoding="utf-8") as _cf:
            _catalog = json.load(_cf)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    _OBJ_TYPES = ("SmartPole", "SmartStructure", "SmartSpan", "SmartConsumer")
    for _ot in _OBJ_TYPES:
        _td = _catalog.get(_ot, {})
        if not isinstance(_td, dict):
            continue

        # Custom entries
        for _si, _entry in enumerate(_td.get("custom_entries", [])):
            if not isinstance(_entry, dict):
                continue
            _label = str(_entry.get("label") or "").strip()
            if not _label:
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO custom_properties (object_type, label, sort_order) VALUES (?,?,?)",
                (_ot, _label, _si),
            )
            cursor.execute(
                "SELECT id FROM custom_properties WHERE object_type=? AND label=?",
                (_ot, _label),
            )
            _cp_row = cursor.fetchone()
            if not _cp_row:
                continue
            _cp_id = _cp_row[0]
            for _oi, _opt in enumerate(_entry.get("options", [])):
                _s = str(_opt or "").strip()
                if _s:
                    cursor.execute(
                        "INSERT INTO custom_property_options (custom_property_id, option_val, sort_order) VALUES (?,?,?)",
                        (_cp_id, _s, _oi),
                    )

        # Extended options
        for _pname, _opts in _td.get("extended_options", {}).items():
            if not isinstance(_opts, list):
                continue
            for _oi, _opt in enumerate(_opts):
                _s = str(_opt or "").strip()
                if _s:
                    cursor.execute(
                        "INSERT OR IGNORE INTO extended_options (object_type, prop_name, option_val, sort_order) VALUES (?,?,?,?)",
                        (_ot, _pname, _s, _oi),
                    )

        # Conductor metadata (SmartSpan only)
        if _ot == "SmartSpan":
            for _cname, _cm in _td.get("conductor_meta", {}).items():
                if not isinstance(_cm, dict):
                    continue
                _voltage = _cm.get("voltage", "Both")
                if _voltage not in ("LT", "HT", "Both"):
                    _voltage = "Both"
                cursor.execute(
                    "INSERT OR REPLACE INTO conductor_meta (name, voltage) VALUES (?,?)",
                    (str(_cname), _voltage),
                )


def get_material_rate(item_name: str) -> float:
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT rate FROM materials WHERE item_name=?", (item_name,))
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else 0.0


def get_labour_rate(task_name: str) -> float:
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT rate FROM labor WHERE task_name=?", (task_name,))
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else 0.0


def get_all_catalog_items() -> dict[str, list[str]]:
    """Return {'materials': [...], 'labor': [...]} list of all current item/task names."""
    conn = sqlite3.connect(DB_PATH)
    try:
        mats = [r[0] for r in conn.execute("SELECT item_name FROM materials ORDER BY item_name").fetchall()]
        labs = [r[0] for r in conn.execute("SELECT task_name FROM labor ORDER BY task_name").fetchall()]
        return {"materials": mats, "labor": labs}
    finally:
        conn.close()
