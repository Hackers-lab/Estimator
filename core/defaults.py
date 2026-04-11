"""
defaults.py
===========
User-configurable placement defaults for canvas objects.

Values are persisted to ``defaults.json`` in the project directory so
they survive restarts.  The module-level ``current`` dict is always
populated (from file or factory values) at import time.

Usage
-----
    import defaults

    # Read a value
    h = defaults.current["lt_height"]

    # Persist user changes (from the Defaults dialog)
    defaults.save({"lt_height": "9MTR", "lt_earth_count": 2})
"""
from __future__ import annotations

import json
import os

from app_config import get_data_path

_DEFAULTS_FILE = get_data_path("defaults.json")

# ── Factory defaults ──────────────────────────────────────────────────────────
_FACTORY: dict = {
    # LT Pole
    "lt_pole_type2":      "PCC",
    "lt_height":          "8MTR",
    "lt_earth_count":     1,
    "lt_stay_count":      0,
    "lt_dist_box_required": True,

    # HT Pole
    "ht_pole_type2":      "PCC",
    "ht_height":          "9MTR",
    "ht_earth_count":     1,
    "ht_stay_count":      0,

    # Extension
    "extension_height":   3.0,

    # Placement rule
    "node_min_gap":       36,
    "existing_stay_angle_tolerance_deg": 20,

    # Structure
    "struct_pole_type2":  "PCC",
    "struct_height":      "9MTR",
    "struct_stay_count":  4,
    "struct_orientation": "Horizontal",
    "dtr_kiosk_required": True,

    # LT Span
    "lt_conductor":       "AB Cable",
    "lt_conductor_size":  "3CX50+1CX16+1CX35",
    "lt_span_length":     40,
    "lt_wire_count":      "4",

    # HT Span
    "ht_conductor":       "ACSR",
    "ht_conductor_size":  "50SQMM",
    "ht_span_length":     40,
    "ht_wire_count":      "3",
    "ht_cg_required":     True,

    # Service Drop
    "sd_conductor_size":  "10 SQMM",
    "sd_length":          20,
    "sd_phase":           "3 Phase",

    # Canvas symbol colours  (hex strings; customisable via Property Editor → Canvas Symbols)
    "canvas_lt_pole":         "#2980b9",   # LT pole fill
    "canvas_ht_pole":         "#c0392b",   # HT pole fill
    "canvas_ex_pole":         "#cccccc",   # Existing pole fill
    "canvas_ex_aug_dtr":      "#f7b267",   # Existing augmented-DTR fill
    "canvas_dp":              "#27ae60",   # DP structure fill
    "canvas_tp":              "#1abc9c",   # TP structure fill
    "canvas_4p":              "#16a085",   # 4P structure fill
    "canvas_dtr":             "#e67e22",   # DTR structure fill
    "canvas_consumer":        "#f1c40f",   # Consumer fill (WBSEDCL)
    "canvas_consumer_agency": "#f39c12",   # Consumer fill (Agency)
    "canvas_acsr":            "#222222",   # ACSR span pen
    "canvas_ab_cable":        "#1a5276",   # AB Cable span pen
    "canvas_pvc_cable":       "#107C41",   # PVC Cable span pen
    "canvas_svc_drop":        "#d35400",   # Service Drop span pen

    # Export settings
    "export_last_dir":    "",

    # Canvas label prefixes (prefix + sequential number shown on canvas objects)
    "label_new_lt":   "PP",    # New LT pole     e.g. PP1, PP2
    "label_new_ht":   "HP",    # New HT pole     e.g. HP1, HP2
    "label_ex_pole":  "EP",    # Existing pole   e.g. EP1, EP2
    "label_dp":       "DP",    # DP structure    e.g. DP1, DP2
    "label_tp":       "TP",    # TP structure    e.g. TP1, TP2
    "label_4p":       "4P",    # 4P structure    e.g. 4P1, 4P2
    "label_dtr":      "DTR",   # DTR sub-station e.g. DTR1, DTR2
    "label_consumer": "SC",    # Consumer        e.g. SC1,  SC2
}

# Module-level mutable dict — read by canvas_objects.py on each new item
current: dict = dict(_FACTORY)


def _cast(value_str: str, factory_default):
    """Cast a string value from DB to the Python type matching the factory default."""
    if isinstance(factory_default, bool):
        return value_str.lower() in ("true", "1", "yes")
    if isinstance(factory_default, int):
        try:
            return int(value_str)
        except (ValueError, TypeError):
            return factory_default
    if isinstance(factory_default, float):
        try:
            return float(value_str)
        except (ValueError, TypeError):
            return factory_default
    return value_str


def load() -> None:
    """Load settings from DB (primary) with JSON file and factory as fallbacks."""
    global current
    merged = dict(_FACTORY)

    # ── Primary: DB settings table ──────────────────────────────────────────
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        db_settings = _dbg.get_all_settings()
        for k, v_str in db_settings.items():
            if k in _FACTORY:
                merged[k] = _cast(v_str, _FACTORY[k])
            # Accept unknown keys (future additions) as strings too
        current = merged
        return
    except Exception:
        pass  # DB not ready yet (e.g. first-launch before setup_database)

    # ── Fallback: JSON file ────────────────────────────────────────────────
    try:
        with open(_DEFAULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged.update({k: v for k, v in data.items() if k in _FACTORY})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    current = merged


def save(values: dict) -> None:
    """Persist *values*, update ``current`` in-place, write to DB and JSON."""
    current.update({k: v for k, v in values.items() if k in _FACTORY})

    # ── DB (primary) ───────────────────────────────────────────────────────
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.save_settings({k: str(v) for k, v in current.items()})
    except Exception:
        pass

    # ── JSON (legacy fallback, keep for backward compat) ──────────────────
    try:
        os.makedirs(os.path.dirname(_DEFAULTS_FILE), exist_ok=True)
        with open(_DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except OSError:
        pass


def reset_to_factory() -> None:
    """Reset ``current`` to factory values and clear from DB + JSON."""
    global current
    current = dict(_FACTORY)

    # Reset DB settings to factory
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.save_settings({k: str(v) for k, v in _FACTORY.items()})
    except Exception:
        pass

    # Remove JSON file
    try:
        os.remove(_DEFAULTS_FILE)
    except FileNotFoundError:
        pass


# Load on import
load()
