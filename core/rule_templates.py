"""
core/rule_templates.py
======================
Pre-built rule templates for the Ruleset Manager.

Each template provides a realistic, ready-to-use rule based on actual
patterns from the production ruleset.  Templates are grouped by object
type and include at least three entries per type.

Structure
---------
Each template is a dict with keys:
    name         — short human-readable label
    description  — what this template covers
    object       — canvas object type
    condition    — condition expression
    formula      — quantity formula
    type         — "Material" or "Labor"
    item_name    — default item name (user should change via DB picker)
    item_code    — default item code
"""

from __future__ import annotations

TEMPLATES: list[dict] = [
    # ═════════════════════════════════════════════════════════════════════════
    #  SmartPole
    # ═════════════════════════════════════════════════════════════════════════
    {
        "name": "New LT PCC 8m pole (material + erection)",
        "description": "Material for a new LT PCC 8-metre pole and its erection labour.",
        "object": "SmartPole",
        "condition": "is_existing == False and pole_type == 'LT' and pole_type2 == 'PCC' and height == 8",
        "formula": "1",
        "type": "Material",
        "item_name": "P C C POLE:8 Mtrs.Long",
        "item_code": "0110030141",
    },
    {
        "name": "Earth set for any pole",
        "description": "Earth spike, GI wire, and labour — fires when earth_count > 0.",
        "object": "SmartPole",
        "condition": "earth_count > 0",
        "formula": "earth_count",
        "type": "Material",
        "item_name": "G.I. Earth Spike 1833X20MM",
        "item_code": "0504110541",
    },
    {
        "name": "LT stay set (material)",
        "description": "Stay set hardware for LT poles with stays.",
        "object": "SmartPole",
        "condition": "stay_count > 0 and pole_type == 'LT'",
        "formula": "stay_count",
        "type": "Material",
        "item_name": "G.I. Stay Set LT (1680X16MM) WRKG LD-5100KG",
        "item_code": "0504130332",
    },
    {
        "name": "HT pole with CG bracket",
        "description": "Cattle guard bracket iron for HT poles with has_cg enabled.",
        "object": "SmartPole",
        "condition": "has_cg and pole_type == 'HT'",
        "formula": "1.9 * ANG_65X65X6 / 1000",
        "type": "Material",
        "item_name": "M.S Angle 65X65X6mm",
        "item_code": "0101011311",
    },
    {
        "name": "HT pole extension iron",
        "description": "Channel iron for extending an HT pole.",
        "object": "SmartPole",
        "condition": "is_new == True and pole_type == 'HT' and has_extension",
        "formula": "extension_height * 2 * CH_75X40 / 1000",
        "type": "Material",
        "item_name": "M.S Channel 75X40 mm",
        "item_code": "0102010611",
    },

    # ═════════════════════════════════════════════════════════════════════════
    #  SmartStructure
    # ═════════════════════════════════════════════════════════════════════════
    {
        "name": "New DP structure (PCC 8m)",
        "description": "Two PCC 8-metre poles for a DP structure.",
        "object": "SmartStructure",
        "condition": "structure_type == 'DP' and pole_type2 == 'PCC' and height == 8",
        "formula": "2",
        "type": "Material",
        "item_name": "P C C POLE:8 Mtrs.Long",
        "item_code": "0110030141",
    },
    {
        "name": "DP structure channel iron",
        "description": "MS Channel 75×40 mm for DP cross-arm fabrication.",
        "object": "SmartStructure",
        "condition": "structure_type == 'DP'",
        "formula": "5.0 * CH_75X40 / 1000",
        "type": "Material",
        "item_name": "M.S Channel 75X40 mm",
        "item_code": "0102010611",
    },
    {
        "name": "DTR station 25KVA (material)",
        "description": "DTR transformer for a 25KVA distribution sub-station.",
        "object": "SmartStructure",
        "condition": "structure_type == 'DTR' and dtr_size == '25KVA'",
        "formula": "1",
        "type": "Material",
        "item_name": "DISTRIBUTION TRANSFORMER 25 KVA",
        "item_code": "0301010241",
    },
    {
        "name": "TP structure with stays",
        "description": "Stay set hardware for TP structures.",
        "object": "SmartStructure",
        "condition": "structure_type == 'TP' and stay_count > 0",
        "formula": "stay_count",
        "type": "Material",
        "item_name": "G.I. Stay Set HT (1830X20MM) WRKG LD-7900KG",
        "item_code": "0504130432",
    },

    # ═════════════════════════════════════════════════════════════════════════
    #  SmartSpan
    # ═════════════════════════════════════════════════════════════════════════
    {
        "name": "New LT ACSR 50mm distribution span",
        "description": "ACSR 50mm conductor for a new LT distribution span.",
        "object": "SmartSpan",
        "condition": "is_new_span and is_lt_span and conductor == 'ACSR' and conductor_size == '50SQMM' and is_distribution_span",
        "formula": "length * wire_count * 0.001",
        "type": "Material",
        "item_name": "ACSR Conductor 50SQMM (Rabbit)",
        "item_code": "0201010341",
    },
    {
        "name": "AB Cable distribution span",
        "description": "LT Aerial Bunched Cable for overhead distribution.",
        "object": "SmartSpan",
        "condition": "is_new_span and is_lt_span and conductor == 'AB Cable' and is_distribution_span",
        "formula": "length * 0.001",
        "type": "Material",
        "item_name": "LT AB CABLE 1.1KV 3CX50+1CX16+1CX35SQMM",
        "item_code": "0204010841",
    },
    {
        "name": "Service drop PVC cable",
        "description": "PVC cable for a consumer service drop connection.",
        "object": "SmartSpan",
        "condition": "is_service_drop and conductor == 'PVC Cable'",
        "formula": "length * 0.001",
        "type": "Material",
        "item_name": "CABLE (PVC 1.1KV GRADE) 4CORE X10SQMM",
        "item_code": "0205010141",
    },
    {
        "name": "HT ACSR span stringing labour",
        "description": "Labour for stringing one HT ACSR span.",
        "object": "SmartSpan",
        "condition": "is_new_span and is_ht_span and conductor == 'ACSR'",
        "formula": "length * 0.001",
        "type": "Labor",
        "item_name": "Stringing HT ACSR 50SQ.MM.(Rabbit) conductor per KM",
        "item_code": "LAB-31",
    },

    # ═════════════════════════════════════════════════════════════════════════
    #  SmartConsumer
    # ═════════════════════════════════════════════════════════════════════════
    {
        "name": "1-Phase consumer point",
        "description": "Basic single-phase consumer service connection material.",
        "object": "SmartConsumer",
        "condition": "phase == '1 Phase'",
        "formula": "1",
        "type": "Material",
        "item_name": "1PH Consumer Meter Box with CT",
        "item_code": "0810010141",
    },
    {
        "name": "3-Phase consumer with cable",
        "description": "Three-phase consumer with cable consideration enabled.",
        "object": "SmartConsumer",
        "condition": "phase == '3 Phase' and consider_cable == True",
        "formula": "service_length * 0.001",
        "type": "Material",
        "item_name": "CABLE (PVC 1.1KV GRADE) 4CX25SQMM",
        "item_code": "0205010341",
    },
    {
        "name": "Agency supply consumer",
        "description": "Consumer point where the power agency supplies materials.",
        "object": "SmartConsumer",
        "condition": "agency_supply == True",
        "formula": "1",
        "type": "Labor",
        "item_name": "Service Connection Labour (Agency Supply)",
        "item_code": "LAB-56",
    },
]


def get_templates_by_object() -> dict[str, list[dict]]:
    """Return templates grouped by object type.

    Returns
    -------
    dict[str, list[dict]]
        ``{"SmartPole": [...], "SmartStructure": [...], ...}``
    """
    grouped: dict[str, list[dict]] = {}
    for t in TEMPLATES:
        grouped.setdefault(t["object"], []).append(t)
    return grouped
