"""
core/nsc_calculator.py
======================
WBSEDCL New Service Connection (NSC) Rate & Execution Cost Calculator.
Implements the exact formulas and rate tables from:
- WBSEDCL Office Order No. 36 dated 27/09/2018 (Single Phase NSC)
- WBSEDCL Office Order No. 35 dated 27/09/2018 (Three Phase NSC)
- WBSEDCL_NSC_Rate_Calculator_Robust_Final.xlsx

Execution Cost Formula:
    Allowed Cable = min(Actual Cable Length, Max Cable)
    Cable Cost    = Rate per metre * Allowed Cable
    Execution Cost = Base Service Connection Cost + Cable Cost
"""

import re
from typing import TypedDict

class NSCCostResult(TypedDict):
    phase: str
    conn_type: str
    cable_size: str
    type_code: str
    cable_code: str
    base_cost: float
    rate_m: float
    max_cable: float
    actual_cable: float
    allowed_cable: float
    cable_cost: float
    execution_cost: float
    sep_charge_name: str
    sep_charge_amt: float


# Rate Master from Office Orders 35 & 36
# Single-Phase: Office Order 36, p1-3
# Three-Phase:  Office Order 35, p1
NSC_RATE_MASTER = {
    # 1-Phase
    ("1 Phase", "I", 4): {
        "type_code": "I4", "cable_code": "2C4S",
        "base_cost": 2041.24, "rate_m": 7.88, "max_cable": 27.0,
        "sep_name": "Mobilization", "sep_amt": 50.0
    },
    ("1 Phase", "I", 6): {
        "type_code": "I6", "cable_code": "2C6S",
        "base_cost": 2041.24, "rate_m": 28.06, "max_cable": 27.0,
        "sep_name": "Mobilization", "sep_amt": 50.0
    },
    ("1 Phase", "L", 4): {
        "type_code": "L4", "cable_code": "2C4S",
        "base_cost": 2759.79, "rate_m": 7.88, "max_cable": 27.0,
        "sep_name": "Mobilization", "sep_amt": 50.0
    },
    ("1 Phase", "L", 6): {
        "type_code": "L6", "cable_code": "2C6S",
        "base_cost": 2759.79, "rate_m": 28.06, "max_cable": 27.0,
        "sep_name": "Mobilization", "sep_amt": 50.0
    },
    # 3-Phase
    ("3 Phase", "I", 16): {
        "type_code": "I16", "cable_code": "4C16S",
        "base_cost": 3251.09, "rate_m": 106.05, "max_cable": 27.0,
        "sep_name": "Survey", "sep_amt": 53.0
    },
    ("3 Phase", "I", 25): {
        "type_code": "I25", "cable_code": "4C25S",
        "base_cost": 3339.38, "rate_m": 147.00, "max_cable": 27.0,
        "sep_name": "Survey", "sep_amt": 53.0
    },
    ("3 Phase", "L", 16): {
        "type_code": "L16", "cable_code": "4C16S",
        "base_cost": 3974.88, "rate_m": 106.05, "max_cable": 27.0,
        "sep_name": "Survey", "sep_amt": 53.0
    },
    ("3 Phase", "L", 25): {
        "type_code": "L25", "cable_code": "4C25S",
        "base_cost": 4254.39, "rate_m": 147.00, "max_cable": 27.0,
        "sep_name": "Survey", "sep_amt": 53.0
    },
    ("3 Phase", "DROP", 16): {
        "type_code": "Drop 16", "cable_code": "4C16S",
        "base_cost": 1937.85, "rate_m": 106.05, "max_cable": 10.0,
        "sep_name": "Survey", "sep_amt": 53.0
    },
    ("3 Phase", "DROP", 25): {
        "type_code": "Drop 25", "cable_code": "4C25S",
        "base_cost": 1937.85, "rate_m": 147.00, "max_cable": 10.0,
        "sep_name": "Survey", "sep_amt": 53.0
    },
}


def normalize_phase(phase: str) -> str:
    """Normalize phase string to '1 Phase' or '3 Phase'."""
    s = str(phase).strip().lower()
    if "1" in s or "single" in s or "1ph" in s:
        return "1 Phase"
    return "3 Phase"


def normalize_conn_type(conn_type: str) -> str:
    """Normalize connection type string to 'I', 'L', or 'DROP'."""
    s = str(conn_type).strip().upper()
    if "DROP" in s:
        return "DROP"
    if "L" in s:
        return "L"
    return "I"


def normalize_cable_size(cable_size: str, phase: str = "1 Phase") -> int:
    """Extract numeric SQMM size, defaulting to 4 (1Ph) or 16 (3Ph)."""
    nums = re.findall(r"\d+", str(cable_size))
    if nums:
        sz = int(nums[0])
        # Validate against known sizes
        if phase == "1 Phase":
            return 6 if sz >= 6 else 4
        else:
            return 25 if sz >= 25 else 16
    return 4 if phase == "1 Phase" else 16


def calculate_nsc_service_cost(
    phase: str = "1 Phase",
    conn_type: str = "I Type",
    cable_size: str = "4 SQMM",
    cable_length: float = 20.0,
) -> NSCCostResult:
    """
    Calculate the exact execution cost of a New Service Connection (NSC).

    Parameters
    ----------
    phase : "1 Phase" | "3 Phase"
    conn_type : "I Type" | "L Type" | "Drop Type"
    cable_size : e.g. "4 SQMM", "6 SQMM", "16 SQMM", "25 SQMM"
    cable_length : Actual cable length in metres

    Returns
    -------
    NSCCostResult dict
    """
    norm_phase = normalize_phase(phase)
    norm_conn = normalize_conn_type(conn_type)
    norm_sqmm = normalize_cable_size(cable_size, norm_phase)

    # For 1-Phase, DROP type doesn't exist in order, fallback to I
    if norm_phase == "1 Phase" and norm_conn == "DROP":
        norm_conn = "I"

    key = (norm_phase, norm_conn, norm_sqmm)
    master = NSC_RATE_MASTER.get(key)
    if master is None:
        # Fallback to defaults
        if norm_phase == "1 Phase":
            master = NSC_RATE_MASTER[("1 Phase", "I", 4)]
        else:
            master = NSC_RATE_MASTER[("3 Phase", "I", 16)]

    actual_len = max(0.0, float(cable_length))
    allowed_len = min(actual_len, master["max_cable"])
    cable_cost = round(master["rate_m"] * allowed_len, 2)
    execution_cost = round(master["base_cost"] + cable_cost, 2)

    return {
        "phase": norm_phase,
        "conn_type": f"{norm_conn} Type" if norm_conn != "DROP" else "Drop Type",
        "cable_size": f"{norm_sqmm} SQMM",
        "type_code": master["type_code"],
        "cable_code": master["cable_code"],
        "base_cost": master["base_cost"],
        "rate_m": master["rate_m"],
        "max_cable": master["max_cable"],
        "actual_cable": actual_len,
        "allowed_cable": allowed_len,
        "cable_cost": cable_cost,
        "execution_cost": execution_cost,
        "sep_charge_name": master["sep_name"],
        "sep_charge_amt": master["sep_amt"],
    }
