"""
core/service_allocator.py
=========================
Pure headless service allocation module for Multi-Consumer / Pole-Case Estimates.

Given a list of canvas items (poles, structures, spans, consumers):
1. Identifies all source nodes (existing poles/structures, or first structure/pole).
2. For each SmartConsumer, finds the unique path from source through intermediate poles/structures.
3. Allocates each network element (new pole, structure, line span) to the FIRST consumer along the path that traverses it.
   - For example: if Consumer 1 is connected at Pole 8, Poles 1..8 and Spans 1..8 are attributed to Consumer 1.
   - If Consumer 2 branches or continues from Pole 8 to Pole 10, Poles 9..10 and Spans 9..10 are attributed to Consumer 2.
4. Each consumer's dedicated service drop and connection execution cost are attributed directly to that consumer.
5. Runs the rule engine and database lookup per consumer bucket to generate exact per-consumer material and labor quantities.
"""
from __future__ import annotations
import math
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from canvas._base import SmartPole
from canvas.nodes import SmartStructure, SmartConsumer
from canvas.span import SmartSpan
from core.constants import SAG_ITEMS
from core.database import DB_PATH
from core.nsc_calculator import calculate_nsc_service_cost
from core import rule_engine
from core.estimate_service import db_lookup, _COUNT_UNITS


def get_consumer_label(consumer: SmartConsumer) -> str:
    """Returns a clean display identifier for the consumer (Appl No or Seq ID)."""
    appl = getattr(consumer, "appl_no", "").strip()
    if appl:
        return appl
    seq = getattr(consumer, "seq_id", 1)
    return f"SC{seq}"


def get_consumer_full_name(consumer: SmartConsumer) -> str:
    """Returns consumer name or default label."""
    name = getattr(consumer, "consumer_name", "").strip()
    if name:
        return name
    return f"Consumer SC{getattr(consumer, 'seq_id', 1)}"


def find_source_nodes(canvas_items: List[Any]) -> List[Any]:
    """
    Finds the root/source nodes for power flow tracing.
    Sources are preferably:
    1. Existing HT/LT poles or structures.
    2. If no existing poles exist, nodes with degree 1 that have no incoming parent.
    3. Fallback: all poles/structures.
    """
    existing_nodes = [
        item for item in canvas_items
        if isinstance(item, (SmartPole, SmartStructure)) and getattr(item, "is_existing", False)
    ]
    if existing_nodes:
        return existing_nodes

    # If no existing node is marked, pick nodes with only 1 connected line span
    all_poles = [
        item for item in canvas_items
        if isinstance(item, (SmartPole, SmartStructure))
    ]
    if not all_poles:
        return []

    leaf_poles = []
    for p in all_poles:
        line_spans = [
            s for s in getattr(p, "connected_spans", [])
            if s is not None and getattr(s, "scene", lambda: None)() is not None
            and not getattr(s, "is_service_drop", False)
        ]
        if len(line_spans) <= 1:
            leaf_poles.append(p)

    return leaf_poles if leaf_poles else all_poles


def trace_path_from_sources(
    target_consumer: SmartConsumer,
    sources: List[Any],
    canvas_items: List[Any],
) -> Tuple[List[Any], List[SmartSpan]]:
    """
    Finds the shortest network path (list of poles/structures and line spans)
    from any source node to the target_consumer's tap pole.
    Returns (nodes_in_path, spans_in_path).
    """
    # 1. Find tap pole connected to target_consumer via service drop
    tap_pole = None
    service_span = None
    for s in getattr(target_consumer, "connected_spans", []):
        if s is not None and getattr(s, "scene", lambda: None)() is not None:
            if getattr(s, "is_service_drop", False):
                service_span = s
                tap_pole = s.p1 if s.p2 == target_consumer else s.p2
                break

    if tap_pole is None:
        return [], []

    # 2. BFS from all sources simultaneously to find shortest path to tap_pole
    visited = set(sources)
    # queue contains (current_node, [nodes_visited], [spans_visited])
    queue = [(src, [src], []) for src in sources]

    found_nodes: List[Any] = []
    found_spans: List[SmartSpan] = []

    if tap_pole in sources:
        return [tap_pole], []

    while queue:
        curr, path_nodes, path_spans = queue.pop(0)
        if curr == tap_pole:
            found_nodes = path_nodes
            found_spans = path_spans
            break

        for span in getattr(curr, "connected_spans", []):
            if span is None or getattr(span, "scene", lambda: None)() is None:
                continue
            if getattr(span, "is_service_drop", False):
                continue
            nxt = span.p1 if span.p2 == curr else span.p2
            if nxt is None or nxt in visited:
                continue

            visited.add(nxt)
            queue.append((nxt, path_nodes + [nxt], path_spans + [span]))

    return found_nodes, found_spans


def allocate_network_to_consumers(
    canvas_items: List[Any],
) -> Dict[SmartConsumer, Dict[str, Any]]:
    """
    Allocates canvas items incrementally to each consumer along network branches.
    Returns:
    {
        consumer: {
            "poles": [pole, ...],
            "spans": [span, ...],
            "service_drop": SmartSpan or None,
            "path_distance": int (number of poles from source),
        }
    }
    """
    consumers = [
        item for item in canvas_items
        if isinstance(item, SmartConsumer) and getattr(item, "scene", lambda: None)() is not None
    ]
    if not consumers:
        return {}

    sources = find_source_nodes(canvas_items)

    # Compute path for each consumer
    consumer_paths = []
    for c in consumers:
        nodes_path, spans_path = trace_path_from_sources(c, sources, canvas_items)
        consumer_paths.append({
            "consumer": c,
            "nodes": nodes_path,
            "spans": spans_path,
            "path_length": len(nodes_path),
        })

    # Sort consumers in ascending order of path length (closest to source gets their share first)
    consumer_paths.sort(key=lambda cp: (cp["path_length"], getattr(cp["consumer"], "seq_id", 0)))

    allocated_nodes: Set[Any] = set()
    allocated_spans: Set[SmartSpan] = set()
    allocation_result: Dict[SmartConsumer, Dict[str, Any]] = {}

    for cp in consumer_paths:
        c = cp["consumer"]
        # Find new/unallocated poles along this consumer's path (skip existing poles)
        my_poles = []
        for n in cp["nodes"]:
            if n not in allocated_nodes:
                if not getattr(n, "is_existing", False):
                    my_poles.append(n)
                allocated_nodes.add(n)

        # Find new/unallocated line spans along this consumer's path (skip existing spans)
        my_spans = []
        for s in cp["spans"]:
            if s not in allocated_spans:
                if not getattr(s, "is_existing_span", False):
                    my_spans.append(s)
                allocated_spans.add(s)

        # Find service drop connected to this consumer
        sd = next(
            (s for s in getattr(c, "connected_spans", [])
             if s is not None and getattr(s, "is_service_drop", False) and getattr(s, "scene", lambda: None)() is not None),
            None
        )

        allocation_result[c] = {
            "poles": my_poles,
            "spans": my_spans,
            "service_drop": sd,
            "path_distance": cp["path_length"],
        }

    return allocation_result


def compile_per_consumer_estimates(
    canvas_items: List[Any],
    rules: List[Dict[str, Any]],
    project_meta: Dict[str, Any],
    bom_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Computes a breakdown matrix of all materials and labor with quantities attributed to each consumer.
    Returns:
    {
        "consumers": [c1, c2, ...],
        "consumer_headers": ["2005770600", "2005705641", ...],
        "allocations": {consumer: {...}},
        "materials": [
            {
                "code": str,
                "name": str,
                "unit": str,
                "rate": float,
                "quantities": {consumer: float, ...},
                "total_qty": float,
                "total_price": float,
            }, ...
        ],
        "labor": [
            {
                "code": str,
                "name": str,
                "unit": str,
                "rate": float,
                "quantities": {consumer: float, ...},
                "total_qty": float,
                "total_price": float,
            }, ...
        ],
        "totals": {
            "materials_total": float,
            "materials_sundries": float,
            "materials_grand": float,
            "labor_total": float,
            "supervision": float,
            "grand_total": float,
        }
    }
    """
    if bom_overrides is None:
        bom_overrides = {}

    allocations = allocate_network_to_consumers(canvas_items)
    consumers = list(allocations.keys())

    use_uh = project_meta.get("use_uh", False)
    project_type = project_meta.get("project_type", "NSC")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
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

        # Dictionaries to aggregate per item across all consumers:
        # mat_map[code or name] = {"code": ..., "name": ..., "unit": ..., "rate": ..., "quantities": {c: qty}}
        mat_map: Dict[str, Dict[str, Any]] = {}
        lab_map: Dict[str, Dict[str, Any]] = {}

        for c, alloc in allocations.items():
            # Build item list for this consumer's portion
            sub_items = alloc["poles"] + alloc["spans"]
            if alloc["service_drop"] is not None:
                sub_items.append(alloc["service_drop"])
            sub_items.append(c)

            prov: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            engine = rule_engine.DynamicRuleEngine()
            raw_bom, raw_lab = engine.process(
                sub_items, rules, use_uh, project_type, provenance_out=prov
            )

            # Apply 3% sag on continuous materials
            for name in list(raw_bom):
                upper_name = name.upper()
                if any(tag in upper_name for tag in SAG_ITEMS):
                    db_row = db_lookup(cursor, "Material", name, rule_code_map.get(name), _prefetched=prefetched)
                    unit_str = (db_row[2] if db_row else "").lower().strip().rstrip(".")
                    if unit_str not in _COUNT_UNITS:
                        raw_bom[name] = raw_bom[name] * 1.03

            # Record Materials
            for name, qty in raw_bom.items():
                if qty <= 0:
                    continue
                row = db_lookup(cursor, "Material", name, rule_code_map.get(name), _prefetched=prefetched)
                if row:
                    code, rate, unit, db_name = row
                else:
                    code, rate, unit, db_name = rule_code_map.get(name, "MAT-GEN"), 0.0, "Nos", name

                key = code if code else db_name
                if key not in mat_map:
                    mat_map[key] = {
                        "code": code,
                        "name": db_name,
                        "unit": unit,
                        "rate": float(rate or 0.0),
                        "quantities": {con: 0.0 for con in consumers},
                    }
                mat_map[key]["quantities"][c] += qty

            # Record Labor (including NSC Connection Cost line for each consumer)
            for name, qty in raw_lab.items():
                if qty <= 0:
                    continue
                row = db_lookup(cursor, "Labor", name, rule_code_map.get(name), _prefetched=prefetched)
                if row:
                    code, rate, unit, db_name = row
                else:
                    code, rate, unit, db_name = rule_code_map.get(name, "LAB-GEN"), 0.0, "Nos", name

                # If this is service drop execution (LAB-68 / LAB-67), customize task name to consumer
                if code in ("LAB-68", "LAB-67"):
                    c_appl = getattr(c, "appl_no", "").strip() or f"SC{getattr(c, 'seq_id', 1)}"
                    c_name = getattr(c, "consumer_name", "").strip() or f"CONSUMER {c_appl}"
                    sd = alloc["service_drop"]
                    actual_len = float(sd.length) if sd else float(getattr(c, "service_length", 20.0))
                    conn_t = getattr(c, "connection_type", getattr(sd, "connection_type", "I Type") if sd else "I Type")
                    target_phase = getattr(c, "phase", "1 Phase")
                    cable_sz = getattr(c, "cable_size", getattr(sd, "conductor_size", "4 SQMM" if target_phase == "1 Phase" else "16 SQMM") if sd else "4 SQMM")
                    c_info = calculate_nsc_service_cost(target_phase, conn_t, cable_sz, actual_len)
                    
                    line_name = f"{c_name} {c_appl} ({c_info['type_code']})"
                    key = f"NSC_{c_appl}_{c.seq_id}"
                    lab_map[key] = {
                        "code": code,
                        "name": line_name,
                        "unit": "Nos",
                        "rate": float(c_info["execution_cost"]),
                        "quantities": {con: 0.0 for con in consumers},
                    }
                    lab_map[key]["quantities"][c] = 1.0
                else:
                    key = code if code else db_name
                    if key not in lab_map:
                        lab_map[key] = {
                            "code": code,
                            "name": db_name,
                            "unit": unit,
                            "rate": float(rate or 0.0),
                            "quantities": {con: 0.0 for con in consumers},
                        }
                    lab_map[key]["quantities"][c] += qty

        # Finalize and calculate totals
        materials_list = list(mat_map.values())
        for m_item in materials_list:
            tot = sum(m_item["quantities"].values())
            # Round quantity to 3 decimal places
            m_item["total_qty"] = round(tot, 3)
            m_item["total_price"] = round(m_item["total_qty"] * m_item["rate"], 2)

        labor_list = list(lab_map.values())
        for l_item in labor_list:
            tot = sum(l_item["quantities"].values())
            l_item["total_qty"] = round(tot, 3)
            l_item["total_price"] = round(l_item["total_qty"] * l_item["rate"], 2)

        mat_total = sum(x["total_price"] for x in materials_list)
        mat_sundries = round(mat_total * 0.05, 2)
        mat_grand = round(mat_total + mat_sundries, 2)

        lab_total = sum(x["total_price"] for x in labor_list)
        supervision = round((mat_grand + lab_total) * 0.10, 2)
        grand_total = round(mat_grand + lab_total + supervision, 2)

        consumer_headers = [get_consumer_label(c) for c in consumers]

        return {
            "consumers": consumers,
            "consumer_headers": consumer_headers,
            "allocations": allocations,
            "materials": materials_list,
            "labor": labor_list,
            "totals": {
                "materials_total": mat_total,
                "materials_sundries": mat_sundries,
                "materials_grand": mat_grand,
                "labor_total": lab_total,
                "supervision": supervision,
                "grand_total": grand_total,
            }
        }

    finally:
        conn.close()
