"""
core/ai_rule_parser.py
======================
Deterministic, pure-Python rule search (no AI / no external services).

Find existing rules that overlap with a described intent, scored by how many
intent properties appear in their condition strings. Used by the Rule Manager's
Smart Search to rank and surface similar rules. Fast, transparent, offline.

(The former AI "describe in plain English" rule creator and its `groq`
dependency were removed; only the deterministic search helpers remain.)

Public API
----------
    find_similar_rules(obj_type, properties, item_name_hint, current_rules, top_n)
    search_existing_rules(intent, current_rules, top_n, threshold)
    infer_properties_from_text(text)
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 helpers — pure Python rule search (no AI)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_condition_tokens(condition: str) -> dict[str, str]:
    """
    Parse a condition string into {prop: value} pairs for scoring.
    Handles:  prop == 'val'  |  prop == val  |  prop == True/False
              not prop  (→ prop: False)  |  prop  (→ prop: True)
    """
    tokens: dict[str, str] = {}
    # Standard comparisons:  prop == 'val'  or  prop == val
    for m in re.finditer(
        r"(\w+)\s*([=!<>]+)\s*(['\"]?)([^'\"\s,)]+)\3", condition
    ):
        prop, op, _, val = m.groups()
        tokens[prop] = val
    # Boolean shorthand:  not prop
    for m in re.finditer(r"\bnot\s+(\w+)\b", condition):
        tokens[m.group(1)] = "False"
    # Bare prop (True-ish)
    for m in re.finditer(r"\b(\w+)\b", condition):
        word = m.group(1)
        if word not in {"and", "or", "not", "True", "False", "in", "is"}:
            tokens.setdefault(word, "True")
    return tokens


def _score_rule_vs_intent(rule: dict, intent: dict) -> float:
    """
    Returns 0.0–1.0: how closely an existing rule matches an intent dict.

    intent keys that matter:
        object       — must match exactly (else 0)
        properties   — dict of {prop: value} from Stage 1
        item_name    — fuzzy matched against rule item_name
    """
    if rule.get("object") != intent.get("object"):
        return 0.0

    cond_tokens = _extract_condition_tokens(rule.get("condition", ""))
    intent_props: dict = intent.get("properties", {})

    if not intent_props:
        return 0.1   # object match only

    matched = 0
    for prop, val in intent_props.items():
        rule_val = cond_tokens.get(prop)
        if rule_val is not None and str(rule_val).lower() == str(val).lower():
            matched += 1

    prop_score = matched / max(len(intent_props), 1)

    # Fuzzy item-name match bonus
    intent_name = intent.get("item_name_hint", "").lower()
    rule_name   = rule.get("item_name", "").lower()
    name_score  = SequenceMatcher(None, intent_name, rule_name).ratio() if intent_name else 0.0

    return min(1.0, prop_score * 0.7 + name_score * 0.3)


def search_existing_rules(
    intent: dict,
    current_rules: list[dict],
    top_n: int = 6,
    threshold: float = 0.15,
) -> list[tuple[int, dict, float]]:
    """
    Returns list of (original_index, rule, score) for the top matches,
    sorted descending by score, filtered to >= threshold.
    """
    scored = []
    for i, rule in enumerate(current_rules):
        s = _score_rule_vs_intent(rule, intent)
        if s >= threshold:
            scored.append((i, rule, s))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# Public API — UI helpers
# (used by the Rule Manager's Smart Search to surface "similar rules")
# ─────────────────────────────────────────────────────────────────────────────

def find_similar_rules(
    obj_type: str,
    properties: dict,
    item_name_hint: str,
    current_rules: list[dict],
    top_n: int = 5,
) -> list[tuple[int, dict, float]]:
    """
    Utility: search existing rules.
    Used by the Rule Manager's Smart Search / "Check for similar rules".

    Parameters
    ----------
    obj_type        : e.g. "SmartStructure"
    properties      : e.g. {"structure_type": "DTR", "dtr_size": "25KVA"}
    item_name_hint  : e.g. "kiosk"
    current_rules   : the full rules list
    top_n           : how many results to return

    Returns
    -------
    list of (original_index, rule_dict, score)
    """
    intent = {
        "object": obj_type,
        "properties": properties,
        "item_name_hint": item_name_hint,
    }
    return search_existing_rules(intent, current_rules, top_n=top_n, threshold=0.1)


def infer_properties_from_text(text: str) -> dict:
    """
    Lightweight keyword scan to build a properties dict for rule search.
    Pure pattern matching on common electrical terms.
    """
    s = text.lower()
    props: dict = {}

    # Object sub-type keywords
    type_keywords = {
        "structure_type": {
            "dtr": "DTR", "distribution transformer": "DTR",
            "dp": "DP", "double pole": "DP",
            "tp": "TP", "triple pole": "TP",
            "4p": "4P", "four pole": "4P",
        },
        "pole_type": {
            "lt pole": "LT", "ht pole": "HT",
        },
    }
    for prop, kw_map in type_keywords.items():
        for kw, val in kw_map.items():
            if kw in s:
                props[prop] = val
                break

    # DTR sizes
    for size in ["10kva", "16kva", "25kva", "63kva", "100kva", "160kva"]:
        if size in s.replace(" ", ""):
            props["dtr_size"] = size.upper().replace("KVA", "KVA")
            break

    # Heights
    for h in ["8mtr", "9mtr", "8 mtr", "9 mtr", "8m", "9m", "8 m", "9 m"]:
        if h in s:
            props["height"] = 8 if "8" in h else 9
            break

    # Conductor
    for cond in ["ab cable", "acsr", "pvc cable", "service drop"]:
        if cond in s:
            props["conductor"] = cond.title()
            break

    # Booleans
    if any(w in s for w in ["existing", "ex."]):
        props["is_existing"] = True
    if "kiosk" in s:
        props["kiosk_required"] = True
    if "stay" in s:
        props["stay_count"] = "> 0"
    if "earth" in s:
        props["earth_count"] = "> 0"

    return props
