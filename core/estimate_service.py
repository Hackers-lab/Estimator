"""
core/estimate_service.py
========================
Provides headless live estimate compilation, rule processing, and database item lookup.
Decoupled from PyQt UI elements to allow background estimation, clean testing,
and maintainable app architecture.
"""
from __future__ import annotations
import math
import re
import sqlite3
from typing import Any, Tuple, Optional, Dict, List, Set

from core.constants import SAG_ITEMS
from core.database import DB_PATH
from core.nsc_calculator import calculate_nsc_service_cost


_COUNT_UNITS = {
    "nos", "no.", "no", "set", "sets", "pair", "pairs",
    "pcs", "piece", "each", "ea", "day", "days", "job", "ls",
}


def normalize_db_name(s: str) -> str:
    """Normalize names for fuzzy database matching."""
    s = s.lower()
    s = s.replace("distribution transformer", "dtr")
    s = s.replace("transformer", "dtr")
    return "".join(c for c in s if c.isalnum())


def db_lookup(
    cursor: sqlite3.Cursor,
    item_type: str,
    name: str,
    rule_code: Optional[str] = None,
    _prefetched: Optional[Dict[str, List[Tuple]]] = None
) -> Optional[Tuple[str, float, str, str]]:
    """
    Look up item code, rate, unit, and exact DB name from SQLite materials or labor table.
    Uses a multi-tier matching strategy (Exact -> Code -> Normalized -> Prefix -> Fuzzy substring).
    Returns (code, rate, unit, db_name) or None.
    """
    if item_type == "Material":
        tbl = "materials"
        name_col = "item_name"
        code_col = "item_code"
    else:
        tbl = "labor"
        name_col = "task_name"
        code_col = "labor_code"

    # Tier 1: Exact Match by Name
    cursor.execute(f"SELECT {code_col}, rate, unit, {name_col} FROM {tbl} WHERE {name_col}=?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0], row[1], row[2], row[3]

    # Tier 2: Code Match
    if rule_code:
        rule_code_str = str(rule_code).strip()
        cursor.execute(f"SELECT {code_col}, rate, unit, {name_col} FROM {tbl} WHERE {code_col}=?", (rule_code_str,))
        row = cursor.fetchone()
        if row:
            return row[0], row[1], row[2], row[3]

    # Fetch all items to perform case-insensitive, normalized, and fuzzy matching.
    if _prefetched is not None:
        all_items = _prefetched.get(item_type, [])
    else:
        cursor.execute(f"SELECT {code_col}, rate, unit, {name_col} FROM {tbl}")
        all_items = cursor.fetchall()

    # Tier 2.5: Code Match with leading-zero safety (e.g. "05105252525" matches "5105252525")
    if rule_code:
        rule_code_stripped = str(rule_code).strip().lstrip('0')
        if rule_code_stripped:
            for r in all_items:
                db_code = str(r[0]).strip().lstrip('0')
                if db_code == rule_code_stripped:
                    return r[0], r[1], r[2], r[3]

    # Tier 3: Case-Insensitive Match
    name_lower = name.lower()
    for r in all_items:
        db_name = r[3]
        if db_name and db_name.lower() == name_lower:
            return r[0], r[1], r[2], r[3]

    # Tier 4: Normalized Match
    name_norm = normalize_db_name(name)
    for r in all_items:
        db_name = r[3]
        if db_name and normalize_db_name(db_name) == name_norm:
            return r[0], r[1], r[2], r[3]

    # Tier 4.5: Labor-specific normalization for common prefix variants.
    if item_type == "Labor":
        alt_names = []
        low_name = name.lower().strip()
        if low_name.startswith("aug. "):
            alt_names.append(low_name[5:])
        if low_name.startswith("dtr aug. "):
            alt_names.append(low_name[9:])
        if low_name.startswith("dtr s/stn "):
            alt_names.append(low_name[10:])
        if low_name.startswith("dtr "):
            alt_names.append(low_name[4:])

        for alt in alt_names:
            alt_norm = normalize_db_name(alt)
            if not alt_norm or alt_norm == name_norm:
                continue
            for r in all_items:
                db_name = r[3]
                if not db_name:
                    continue
                db_norm = normalize_db_name(db_name)
                if alt_norm == db_norm or alt_norm in db_norm or db_norm in alt_norm:
                    return r[0], r[1], r[2], r[3]

    # Tier 5: Normalized Substring Match with Number Safety
    rule_nums = re.findall(r'\d+', name)
    for r in all_items:
        db_name = r[3]
        if not db_name:
            continue
        db_norm = normalize_db_name(db_name)
        if name_norm in db_norm or db_norm in name_norm:
            # Extra guard: numbers must match!
            db_nums = re.findall(r'\d+', db_name)
            num_match = True
            for num in rule_nums:
                if num in {"8", "9", "11", "16", "25", "63", "100", "160", "315"} and num not in db_nums:
                    num_match = False
                    break
            if num_match:
                return r[0], r[1], r[2], r[3]

    return None


def generate_live_bom(
    canvas_items: List[Any],
    rules: List[Dict[str, Any]],
    rule_engine: Any,
    project_meta: Dict[str, Any],
    bom_overrides: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], List[Dict[str, Any]]]]:
    """
    Generate live BOQ table data and provenance tree from canvas items, rules, and DB rates.
    Returns (live_bom_data, provenance_dict).
    """
    use_uh = project_meta.get("use_uh", False)
    project_type = project_meta.get("project_type", "NSC")

    prov: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    raw_bom, raw_lab = rule_engine.process(
        canvas_items, rules, use_uh, project_type, provenance_out=prov
    )

    live_bom_data: List[Dict[str, Any]] = []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Pre-fetch lookup tables once
        cursor.execute("SELECT item_code, rate, unit, item_name FROM materials")
        all_mat = cursor.fetchall()
        cursor.execute("SELECT labor_code, rate, unit, task_name FROM labor")
        all_lab = cursor.fetchall()
        prefetched = {"Material": all_mat, "Labor": all_lab}

        rule_code_map: Dict[str, str] = {}
        for r in rules:
            for item in r.get("items", []):
                iname = item.get("item_name")
                icode = item.get("item_code")
                if iname and icode:
                    rule_code_map[iname] = icode

        # 3% sag / wastage on continuous materials
        for name in list(raw_bom):
            upper_name = name.upper()
            if any(tag in upper_name for tag in SAG_ITEMS):
                db_row = db_lookup(cursor, "Material", name, rule_code_map.get(name), _prefetched=prefetched)
                unit_str = (db_row[2] if db_row else "").lower().strip().rstrip(".")
                if unit_str not in _COUNT_UNITS:
                    raw_bom[name] = raw_bom[name] * 1.03

        processed: Set[str] = set()

        combined = (
            [("Material", n, q) for n, q in raw_bom.items()] +
            [("Labor",    n, q) for n, q in raw_lab.items()]
        )

        from canvas import SmartConsumer

        for item_type, name, qty in combined:
            if name in bom_overrides and bom_overrides[name]["type"] == item_type:
                qty = bom_overrides[name]["qty"]

            row = db_lookup(cursor, item_type, name, rule_code_map.get(name), _prefetched=prefetched)
            if row:
                code, rate, unit, db_name = row
                if db_name in bom_overrides and bom_overrides[db_name]["type"] == item_type:
                    qty = bom_overrides[db_name]["qty"]

                # Dynamic NSC Service Connection Execution Cost
                if code in ("LAB-68", "LAB-67"):
                    target_phase = "1 Phase" if code == "LAB-68" else "3 Phase"
                    consumers = [
                        i for i in canvas_items
                        if isinstance(i, SmartConsumer) and (
                            (target_phase == "1 Phase" and getattr(i, "phase", "") == "1 Phase") or
                            (target_phase == "3 Phase" and getattr(i, "phase", "") != "1 Phase")
                        )
                    ]
                    if consumers:
                        cost_groups = {}
                        for c in consumers:
                            sd = next((s for s in getattr(c, "connected_spans", []) if getattr(s, "is_service_drop", False) and getattr(s, "scene", lambda: None)() is not None), None)
                            actual_len = float(sd.length) if sd else float(getattr(c, "service_length", 20.0))
                            conn_t = getattr(c, "connection_type", getattr(sd, "connection_type", "I Type") if sd else "I Type")
                            cable_sz = getattr(c, "cable_size", getattr(sd, "conductor_size", "4 SQMM" if target_phase == "1 Phase" else "16 SQMM") if sd else ("4 SQMM" if target_phase == "1 Phase" else "16 SQMM"))
                            c_info = calculate_nsc_service_cost(c.phase, conn_t, cable_sz, actual_len)
                            grp_key = (c_info["execution_cost"], c_info["type_code"], c_info["allowed_cable"], c_info["rate_m"], c_info["base_cost"], c_info["cable_code"])
                            cost_groups.setdefault(grp_key, []).append((c, c_info))

                        is_single_group = len(cost_groups) == 1
                        for grp_key, grp_items in cost_groups.items():
                            grp_cost, type_code, allowed_cable, rate_m, base_cost, cable_code = grp_key
                            grp_qty = len(grp_items)
                            if db_name in bom_overrides and bom_overrides[db_name]["type"] == item_type and is_single_group:
                                grp_qty = bom_overrides[db_name]["qty"]
                            line_name = db_name if is_single_group else f"{db_name} ({type_code} - {int(allowed_cable)}m)"
                            grp_prov = []
                            for c, c_info in grp_items:
                                grp_prov.append({
                                    "object_label": f"Consumer SC{getattr(c, 'seq_id', 1)}",
                                    "object_type": "SmartConsumer",
                                    "rule_id": 161 if target_phase == "1 Phase" else 160,
                                    "condition": f"phase=='{c.phase}' & {c_info['conn_type']} & {c_info['cable_size']}",
                                    "formula": f"{type_code} (Base ₹{base_cost:.2f} + {allowed_cable:.0f}m @ ₹{rate_m}/m)",
                                    "qty": 1,
                                })
                            live_bom_data.append({
                                "type": item_type, "code": code, "name": line_name,
                                "qty": round(grp_qty, 3), "unit": unit, "rate": grp_cost,
                                "amt": round(round(grp_qty, 3) * grp_cost, 2),
                                "provenance": grp_prov,
                            })
                        processed.add(name)
                        processed.add(db_name)
                        continue

                qty_rounded = round(qty, 3)
                live_bom_data.append({
                    "type": item_type, "code": code, "name": db_name,
                    "qty": qty_rounded, "unit": unit, "rate": rate,
                    "amt": round(qty_rounded * rate, 2),
                    "provenance": prov.get((item_type, name), []),
                })
                processed.add(name)
                processed.add(db_name)

        # Custom overrides not in auto-BOM
        for name, override in bom_overrides.items():
            if name not in processed:
                row = db_lookup(cursor, override["type"], name, _prefetched=prefetched)
                if row:
                    code, rate, unit, db_name = row
                    qty = override["qty"]
                    qty_rounded = round(qty, 3)
                    live_bom_data.append({
                        "type": override["type"], "code": code, "name": db_name,
                        "qty": qty_rounded, "unit": unit, "rate": rate,
                        "amt": qty_rounded * rate,
                        "provenance": [],
                    })
                    processed.add(name)
                    processed.add(db_name)

    finally:
        conn.close()

    return live_bom_data, prov
