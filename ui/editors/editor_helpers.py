"""
ui/editors/editor_helpers.py
============================
Stateless/pure helper routines for property options and canvas node relations.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from core import property_catalog as _pc
from canvas import SmartConsumer

def get_height_options(pole_type2: str, obj_type: str = "SmartPole") -> list[str]:
    """Return height option strings for the given pole_type2 from DB or defaults."""
    try:
        from core import db_gateway as _dbg
        opts = _dbg.get_height_options(pole_type2)
        if opts:
            return opts
    except Exception:
        pass
    base: list[str] = {
        "PCC":    ["8MTR", "9MTR"],
        "STP":    ["9MTR", "9.5MTR", "11MTR"],
        "H-BEAM": ["13MTR"],
    }.get(pole_type2, ["8MTR", "9MTR"])
    ext = _pc.get_extended_options(obj_type, f"height__{pole_type2}")
    base_fold = {v.casefold() for v in base}
    return base + [o for o in ext if o.casefold() not in base_fold]

def get_conductor_sizes(conductor: str, is_lt: bool) -> list[str]:
    """Return conductor-size option strings from DB or defaults."""
    try:
        from core import db_gateway as _dbg
        vc = "LT" if is_lt else "HT"
        opts = _dbg.get_conductor_options(conductor, vc)
        if opts:
            return opts
    except Exception:
        pass
    if conductor == "ACSR":
        base = ["30SQMM", "50SQMM"]
    elif conductor == "AB Cable":
        base = (
            ["3CX50+1CX35", "3CX50+1CX16+1CX35", "3CX70+1CX16+1CX50"]
            if is_lt else ["3CX50+1CX150", "3CX95+1CX70"]
        )
    elif conductor == "PVC Cable":
        base = ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM", "95 SQMM", "120 SQMM"]
    else:
        base = ["10 SQMM"]
    vlt = "lt" if is_lt else "ht"
    ext = _pc.get_extended_options("SmartSpan", f"conductor_size__{vlt}_{conductor}")
    base_fold = {v.casefold() for v in base}
    return base + [o for o in ext if o.casefold() not in base_fold]

def get_service_conn_types(phase: str) -> list[str]:
    """Connection types for consumer / service drop."""
    if phase == "1 Phase":
        return ["I Type", "L Type"]
    return ["I Type", "L Type", "Drop Type"]

def get_service_cable_sizes(phase: str) -> list[str]:
    """Cable sizes for consumer / service drop according to phase."""
    if phase == "1 Phase":
        return ["4 SQMM", "6 SQMM"]
    return ["16 SQMM", "25 SQMM"]

def get_consumer_service_drop(consumer):
    """Return the active service-drop span connected to a consumer, or None."""
    for s in getattr(consumer, "connected_spans", []):
        if getattr(s, "is_service_drop", False) and s.scene() is not None:
            return s
    return None

def get_service_drop_consumer(span):
    """Return the SmartConsumer endpoint of a service-drop span, or None."""
    if isinstance(span.p1, SmartConsumer):
        return span.p1
    if isinstance(span.p2, SmartConsumer):
        return span.p2
    return None

def get_pole_type2_options(obj_type: str = "SmartPole") -> list[str]:
    """Pole material options (PCC/STP/H-BEAM) merged with user-added values."""
    base = ["PCC", "STP", "H-BEAM"]
    ext = _pc.get_extended_options(obj_type, "pole_type2")
    base_fold = {v.casefold() for v in base}
    return base + [o for o in ext if o.casefold() not in base_fold]

def get_dtr_size_options(obj_type: str = "SmartStructure", prop: str = "dtr_size") -> list[str]:
    """DTR kVA size options merged with user-added values."""
    base = ["None", "10KVA", "16KVA", "25KVA", "63KVA", "100KVA", "160KVA"]
    ext = _pc.get_extended_options(obj_type, prop)
    base_fold = {v.casefold() for v in base}
    return base + [o for o in ext if o.casefold() not in base_fold]

def parse_kva(size_text: str) -> int:
    txt = str(size_text or "").upper().replace("KVA", "").strip()
    try:
        return int(txt)
    except ValueError:
        return 0
