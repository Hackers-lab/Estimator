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
_SEED_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..","data","seed_data.json")


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


_SEED_MATERIALS, _SEED_LABOUR = _load_seed_data()


# Rows to add to existing v4 databases (INSERT OR IGNORE)
_NEW_MATERIALS = [
    r for r in _SEED_MATERIALS
    if r[0].startswith(("0110010", "0110011", "0110020", "0110051",
                         "0101011011", "0103011611", "0103011911", "0103012311",
                         "0502010621", "0502011221",
                         "0501030321", "0501030421", "0501031121",
                         "0501017921", "0501018121", "0501018221", "0501018321",
                         "0301010541", "0301011041", "0301018341", "0301018741",
                         "0301019041", "0301019141", "0301019341",
                         "0407010741", "0407010541",
                         "0504070341",
                         "195021741", "597011541", "597011741",
                         "0508040441"))
]

_NEW_LABOUR = [
    r for r in _SEED_LABOUR
    if r[0] in {
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
]


def setup_database():
    """Called on every app launch."""
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

    if is_empty:
        cursor.executemany("INSERT INTO materials VALUES (?,?,?,?)", _SEED_MATERIALS)
        cursor.executemany("INSERT INTO labor VALUES (?,?,?,?)", _SEED_LABOUR)
    else:
        cursor.executemany("INSERT OR IGNORE INTO materials VALUES (?,?,?,?)", _NEW_MATERIALS)
        cursor.executemany("INSERT OR IGNORE INTO labor VALUES (?,?,?,?)", _NEW_LABOUR)

    conn.commit()
    conn.close()


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
