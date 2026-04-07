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

_DEFAULTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "defaults.json"
)

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

    # Structure
    "struct_pole_type2":  "PCC",
    "struct_height":      "9MTR",
    "struct_stay_count":  4,

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
    with open(_DEFAULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)


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
