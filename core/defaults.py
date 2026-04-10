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


def load() -> None:
    """Load from JSON file; fall back silently to factory values."""
    global current
    try:
        with open(_DEFAULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_FACTORY)
        merged.update({k: v for k, v in data.items() if k in _FACTORY})
        current = merged
    except (FileNotFoundError, json.JSONDecodeError):
        current = dict(_FACTORY)


def save(values: dict) -> None:
    """Persist *values* and update ``current`` in-place."""
    current.update({k: v for k, v in values.items() if k in _FACTORY})
    try:
        os.makedirs(os.path.dirname(_DEFAULTS_FILE), exist_ok=True)
        with open(_DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except OSError:
        pass  # Silently ignore write failures (read-only fs, permissions, etc)


def reset_to_factory() -> None:
    """Reset ``current`` to factory values and delete the JSON file."""
    global current
    current = dict(_FACTORY)
    try:
        os.remove(_DEFAULTS_FILE)
    except FileNotFoundError:
        pass


# Load on import
load()
