"""
constants.py
============
Shared configuration, lookup tables, and constant definitions for the
ERP Estimate Generator.

Consumers of this module
------------------------
app.py          — TOOLS, ["NSC", "FDS / TURNKEY"], SUPERVISION_RATES
ui_dialogs.py   — PROPERTY_DATA, FORMULA_VARS, ["NSC", "FDS / TURNKEY"],
                  SUPERVISION_RATES, HEIGHT_OPTIONS, CONDUCTOR_SIZES,
                  SERVICE_CABLE_SIZES, SIM_DEFAULTS
rule_engine.py  — (no direct import; context keys documented here)
canvas_objects.py — HEIGHT_OPTIONS, CONDUCTOR_SIZES (optional reference)
"""

# ─────────────────────────────────────────────────────────────────────────────
#  DRAWING TOOLS  (toolbar button order matters)
# ─────────────────────────────────────────────────────────────────────────────
TOOLS = {
    "SELECT":        "🖱 Select",
    "ADD_LT":        "🔵 LT Pole",
    "ADD_HT":        "🔴 HT Pole",
    "ADD_STRUCTURE": "🟩 Structure",
    "ADD_EXISTING":  "⚪ Ex. Pole",
    "ADD_CONSUMER":  "🏠 Consumer",
    "ADD_SPAN":      "📏 Span",
}

# ─────────────────────────────────────────────────────────────────────────────
#  PROJECT TYPES & SUPERVISION RATES
# ─────────────────────────────────────────────────────────────────────────────

# Display labels shown in the Project Setup Wizard dropdown

# List of available project types
PROJECT_TYPES = ["NSC", "FDS / TURNKEY"]

# Supervision charge rate keyed by project type string
# NSC = 10%, all others = 15%
SUPERVISION_RATES = {
    "NSC": 0.10,
    "FDS / TURNKEY": 0.15,
}

# ─────────────────────────────────────────────────────────────────────────────
#  POLE / STRUCTURE HEIGHT OPTIONS  (keyed by pole_type2)
# ─────────────────────────────────────────────────────────────────────────────
HEIGHT_OPTIONS = {
    "PCC":    ["8MTR", "9MTR"],
    "STP":    ["9MTR", "9.5MTR", "11MTR"],
    "H-BEAM": ["13MTR"],
}

# Default heights per pole voltage type when pole_type2 == PCC

# ─────────────────────────────────────────────────────────────────────────────
#  CONDUCTOR SIZE OPTIONS
# ─────────────────────────────────────────────────────────────────────────────
CONDUCTOR_SIZES = {
    # ACSR — same for LT and HT
    ("ACSR", "LT"):      ["30SQMM", "50SQMM"],
    ("ACSR", "HT"):      ["30SQMM", "50SQMM"],

    # LT Aerial Bunched Cable
    ("AB Cable", "LT"):  [
        "3CX50+1CX35",
        "3CX50+1CX16+1CX35",
        "3CX70+1CX16+1CX50",
    ],

    # HT Aerial Bunched Cable (11 kV)
    ("AB Cable", "HT"):  [
        "3CX50+1CX150",
        "3CX95+1CX70",
    ],

    # PVC underground / overhead cable — same range for LT and HT
    ("PVC Cable", "LT"): [
        "10 SQMM", "16 SQMM", "25 SQMM",
        "50 SQMM", "95 SQMM", "120 SQMM",
    ],
    ("PVC Cable", "HT"): [
        "10 SQMM", "16 SQMM", "25 SQMM",
        "50 SQMM", "95 SQMM", "120 SQMM",
    ],
}

# Service drop cable sizes per phase
SERVICE_CABLE_SIZES = {
    "1 Phase": ["10 SQMM", "16 SQMM"],
    "3 Phase": ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM"],
}

# ─────────────────────────────────────────────────────────────────────────────
#  STRUCTURE EARTH COUNT DEFAULTS  (keyed by structure_type)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  RULE BUILDER — PROPERTY_DATA
#  Defines what properties each canvas object exposes in the rule builder UI.
#  Value is either a list of allowed values (→ ComboBox) or 'int' (→ SpinBox).
# ─────────────────────────────────────────────────────────────────────────────
PROPERTY_DATA = {
    "SmartPole": {
        "pole_type":        ["LT", "HT"],
        "pole_type2":       ["PCC", "STP", "H-BEAM"],
        "height":           [8, 9],           # numeric metres for rule conditions
        "is_existing":      [True, False],
        "existing_subtype": ["LT", "HT", "DP", "TP", "4P", "DTR"],
        "existing_dtr_size": ["None", "10KVA", "16KVA", "25KVA", "63KVA", "100KVA", "160KVA"],
        "has_extension":    [True, False],
        "extension_height": "int",
        "earth_count":      "int",
        "stay_count":       "int",
        "has_cg":           [True, False],
        "ht_spans_count":   "int",
        "lt_acsr_count":    "int",
        "lt_wire_count":    "int",
        "ab_cable_count":   "int",
        "ab_needs_dead_end": [True, False],
        "ab_needs_suspension": [True, False],
        "use_uh":           [True, False],
        "project_type":     ["NSC", "FDS / TURNKEY"],
    },
    "SmartStructure": {
        "structure_type":   ["DP", "TP", "4P", "DTR"],
        "pole_type2":       ["PCC", "STP", "H-BEAM"],
        "height":           [8, 9],
        "has_extension":    [True, False],
        "extension_height": "int",
        "earth_count":      "int",
        "stay_count":       "int",
        "has_cg":           [True, False],
        "dtr_size":         [
            "None", "10KVA", "16KVA", "25KVA",
            "63KVA", "100KVA", "160KVA"
        ],
        "dtr_aug_required": [True, False],
        "dtr_to_size":      ["None", "10KVA", "16KVA", "25KVA", "63KVA", "100KVA", "160KVA"],
        "dtr_new_pole_type2": ["PCC", "STP", "H-BEAM"],
        "dtr_new_height":   ["8MTR", "9MTR", "9.5MTR", "11MTR", "13MTR"],
        "dtr_return_old_dtr": [True, False],
        "dtr_return_old_pole": [True, False],
        "dtr_return_old_iron": [True, False],
        "use_uh":           [True, False],
        "project_type":     ["NSC", "FDS / TURNKEY"],
    },
    "SmartSpan": {
        "conductor":        ["ACSR", "AB Cable", "PVC Cable", "Service Drop"],
        "conductor_size":   "text",           # free-text; too many combinations
        "is_service_drop":  [True, False],
        "is_existing_span": [True, False],
        "is_lt_span":       [True, False],
        "has_cg":           [True, False],
        "phase":            ["1 Phase", "3 Phase"],
        "aug_type":         ["New", "Replace 2W->4W", "Add-on 2W"],
        "conductor_aug_required": [True, False],
        "aug_from_config":  ["1P2W", "2P3W", "3P4W", "3P5W"],
        "aug_to_config":    ["1P2W", "2P3W", "3P4W", "3P5W"],
        "aug_to_conductor": ["ACSR", "AB Cable"],
        "consider_cable":   [True, False],
        "length":           "int",
        "wire_count":       "int",
        "use_uh":           [True, False],
        "project_type":     ["NSC", "FDS / TURNKEY"],
    },
    "SmartConsumer": {
        "phase":            ["1 Phase", "3 Phase"],
        "cable_size":       [
            "10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM"
        ],
        "agency_supply":    [True, False],
        "consider_cable":   [True, False],
        "service_length":   "int",
        "use_uh":           [True, False],
        "project_type":     ["NSC", "FDS / TURNKEY"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  RULE BUILDER — FORMULA_VARS
#  Numeric variables available inside qty formula strings.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  RULE BUILDER SIMULATOR — DEFAULT VALUES
#  Used by RulesetManagerDialog simulator panel to pre-populate widgets.
#  Format: prop_name → (widget_type, options_or_range, default)
#    widget_type: "combo" | "spin" | "dspin"
#    options_or_range: list of strings for combo; (min,max) tuple for spin
# ─────────────────────────────────────────────────────────────────────────────
SIM_DEFAULTS = {
    "SmartPole": {
        "pole_type":        ("combo", ["LT", "HT"],                     "LT"),
        "pole_type2":       ("combo", ["PCC", "STP", "H-BEAM"],         "PCC"),
        "is_existing":      ("combo", ["False", "True"],                 "False"),
        "height":           ("spin",  (8, 13),                           8),
        "has_extension":    ("combo", ["False", "True"],                 "False"),
        "extension_height": ("spin",  (1, 10),                           3),
        "earth_count":      ("spin",  (0, 10),                           1),
        "stay_count":       ("spin",  (0, 10),                           0),
        "has_cg":           ("combo", ["False", "True"],                 "False"),
        "ht_spans_count":   ("spin",  (0, 10),                           0),
        "lt_acsr_count":    ("spin",  (0, 10),                           0),
        "lt_wire_count":    ("spin",  (0, 10),                           0),
        "ab_cable_count":   ("spin",  (0, 10),                           0),
        "ab_needs_dead_end": ("combo", ["False", "True"],                "False"),
        "ab_needs_suspension": ("combo", ["False", "True"],              "False"),
        "use_uh":           ("combo", ["False", "True"],                 "False"),
        "project_type":     ("combo", ["NSC", "FDS / TURNKEY"],                     "NSC"),
    },
    "SmartStructure": {
        "structure_type":   ("combo", ["DP", "TP", "4P", "DTR"],        "DP"),
        "pole_type2":       ("combo", ["PCC", "STP", "H-BEAM"],         "PCC"),
        "height":           ("spin",  (8, 13),                           9),
        "has_extension":    ("combo", ["False", "True"],                 "False"),
        "extension_height": ("spin",  (1, 10),                           3),
        "earth_count":      ("spin",  (0, 20),                           2),
        "stay_count":       ("spin",  (0, 20),                           4),
        "has_cg":           ("combo", ["False", "True"],                 "False"),
        "dtr_size":         ("combo",
                             ["None","10KVA","16KVA","25KVA",
                              "63KVA","100KVA","160KVA"],                "None"),
        "dtr_aug_required": ("combo", ["False", "True"],                 "False"),
        "dtr_to_size":      ("combo", ["None","10KVA","16KVA","25KVA","63KVA","100KVA","160KVA"], "None"),
        "dtr_new_pole_type2": ("combo", ["PCC", "STP", "H-BEAM"],       "PCC"),
        "dtr_new_height":   ("combo", ["8MTR", "9MTR", "9.5MTR", "11MTR", "13MTR"], "9MTR"),
        "dtr_return_old_dtr": ("combo", ["False", "True"],                "True"),
        "dtr_return_old_pole": ("combo", ["False", "True"],               "True"),
        "dtr_return_old_iron": ("combo", ["False", "True"],               "False"),
        "use_uh":           ("combo", ["False", "True"],                 "False"),
        "project_type":     ("combo", ["NSC", "FDS / TURNKEY"],                     "NSC"),
    },
    "SmartSpan": {
        "conductor":        ("combo",
                             ["AB Cable", "ACSR", "PVC Cable",
                              "Service Drop"],                           "AB Cable"),
        "conductor_size":   ("combo",
                             ["50SQMM", "30SQMM",
                              "3CX50+1CX35", "3CX50+1CX16+1CX35",
                              "3CX70+1CX16+1CX50",
                              "3CX50+1CX150", "3CX95+1CX70",
                              "10 SQMM", "16 SQMM", "25 SQMM",
                              "50 SQMM", "95 SQMM", "120 SQMM"],        "50SQMM"),
        "is_existing_span": ("combo", ["False", "True"],                 "False"),
        "is_service_drop":  ("combo", ["False", "True"],                 "False"),
        "is_lt_span":       ("combo", ["True", "False"],                 "True"),
        "length":           ("spin",  (1, 1000),                         40),
        "wire_count":       ("combo", ["2", "3", "4"],                   "3"),
        "phase":            ("combo", ["1 Phase", "3 Phase"],            "3 Phase"),
        "has_cg":           ("combo", ["False", "True"],                 "False"),
        "aug_type":         ("combo",
                             ["New", "Replace 2W->4W", "Add-on 2W"],    "New"),
        "conductor_aug_required": ("combo", ["False", "True"],           "False"),
        "aug_from_config":  ("combo", ["1P2W", "2P3W", "3P4W", "3P5W"], "2P3W"),
        "aug_to_config":    ("combo", ["1P2W", "2P3W", "3P4W", "3P5W"], "3P4W"),
        "aug_to_conductor": ("combo", ["ACSR", "AB Cable"],               "ACSR"),
        "consider_cable":   ("combo", ["False", "True"],                 "False"),
        "use_uh":           ("combo", ["False", "True"],                 "False"),
        "project_type":     ("combo", ["NSC", "FDS / TURNKEY"],                     "NSC"),
    },
    "SmartConsumer": {
        "phase":            ("combo", ["1 Phase", "3 Phase"],            "3 Phase"),
        "cable_size":       ("combo",
                             ["10 SQMM", "16 SQMM",
                              "25 SQMM", "50 SQMM"],                    "10 SQMM"),
        "agency_supply":    ("combo", ["False", "True"],                 "False"),
        "consider_cable":   ("combo", ["False", "True"],                 "False"),
        "service_length":   ("spin",  (0, 200),                           20),
        "project_type":     ("combo", ["NSC", "FDS / TURNKEY"],                     "NSC"),
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  RULE BUILDER TREE DEFINITION
#  Hierarchy shown in the left panel of RulesetManagerDialog.
#  Format per entry: (display_label, obj_type, filter_dict, children)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  RULE BUILDER — FILTER CHIPS
#  Context-aware checkbox filters shown above the card list per object type.
#  Format: (display_label, context_key, match_value)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  IRON BREAKUP — UNIT WEIGHTS  (kg per metre)
# ─────────────────────────────────────────────────────────────────────────────
IRON_UNIT_WEIGHTS = {
    "MS Channel 75x40":  7.14,
    "MS Angle 65x65x6":  6.50,
    "MS Angle 50x50x6":  5.00,
    "MS Flat 65x6":      3.50,
}
