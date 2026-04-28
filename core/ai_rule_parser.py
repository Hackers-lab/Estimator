"""
core/ai_rule_parser.py
======================
Natural language → rule operations using a 3-stage pipeline.

Stage 1 — Intent extraction  (AI, tiny prompt)
    Understand WHAT object, WHICH properties, and WHAT action the user wants.

Stage 2 — Rule search  (pure Python, deterministic)
    Find existing rules that overlap with the intent.
    Scored by how many intent properties appear in their condition strings.
    No AI involved — fast, transparent, consistent.

Stage 3 — Proposal  (AI, focused prompt)
    Show the AI only the top overlapping rules + matching DB items.
    Ask: UPDATE existing rule / CREATE new rule / ALREADY EXISTS?

Public API
----------
    parse_natural_language_rules(sentence, active_obj_type, registry,
                                  current_rules, catalog, history)
        → list[dict]   each dict is a rule operation

Operation dict keys
-------------------
    action       — "CREATE" | "UPDATE" | "SKIP"
    object       — canvas object type string
    rule_id      — (UPDATE only) index into current_rules list
    item_name    — proposed item name (must exist in DB)
    item_code    — proposed item code
    condition    — condition expression string
    formula      — quantity formula string
    type         — "Material" | "Labor"
    confidence   — 0.0-1.0 (how confident the AI is)
    reason       — short human-readable explanation shown in the table

Requirements
------------
- groq pip package  (pip install groq)
- GROQ_API_KEY environment variable
  Set it in a .env file or your OS environment — never hardcode in source.
"""

from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from dotenv import load_dotenv

load_dotenv() # Load from .env if present


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
# Stage 1 — Intent extraction
# ─────────────────────────────────────────────────────────────────────────────

def _stage1_extract_intent(
    sentence: str,
    active_obj_type: str,
    registry,
    client,
    model: str,
) -> dict:
    """
    Ask the AI a small, focused question:
        Given this sentence, what object type, properties, and action
        is the user describing?
    Returns a dict with keys: object, properties, item_name_hint, rule_type, action_hint.
    """
    obj_types = ["SmartPole", "SmartStructure", "SmartSpan", "SmartConsumer"]
    props_ctx = ""
    for ot in obj_types:
        pd = registry.get_property_data(ot) or {}
        props_ctx += f"\n{ot}: " + ", ".join(
            f"{k}={v}" if not isinstance(v, list) else f"{k}={v}"
            for k, v in list(pd.items())[:12]
        ) + "\n"

    system = f"""You are an intent parser for an electrical estimating tool.
Extract the user's intent from their sentence and return ONLY a JSON object.

Available object types: {obj_types}
Active object type (use as default): {active_obj_type}

Property reference (abbreviated):
{props_ctx}

Return JSON with these keys:
  object         — one of the object types above
  properties     — dict of property-name: value pairs that characterise this scenario
                   (e.g. {{"structure_type": "DTR", "dtr_size": "25KVA"}})
  item_name_hint — a short phrase describing the material or labour item (e.g. "25KVA kiosk")
  rule_type      — "Material" or "Labor" or "Both"
  action_hint    — "add" | "update" | "remove" | "check"

Be concise. Output ONLY the JSON, no markdown fences."""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": sentence},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Proposal
# ─────────────────────────────────────────────────────────────────────────────

def _stage3_propose(
    sentence: str,
    intent: dict,
    top_matches: list[tuple[int, dict, float]],
    catalog: dict,
    registry,
    history: list[str],
    client,
    model: str,
) -> list[dict]:
    """
    Give the AI a focused set of context:
      - The user's sentence
      - The extracted intent
      - The top overlapping existing rules (scored)
      - DB items whose names fuzzy-match the intent item_name_hint
    Ask it to produce a list of CREATE / UPDATE / SKIP operations.
    """
    obj_type = intent.get("object", "SmartPole")

    # Get formula vars for this object type
    fvars = registry.get_formula_vars(obj_type) if hasattr(registry, "get_formula_vars") else []

    # Build existing-rule context (only top matches, with their index)
    rule_ctx_lines = []
    for orig_idx, rule, score in top_matches:
        rule_ctx_lines.append(
            f"  [{orig_idx}] score={score:.2f} | {rule.get('type','?'):8} | "
            f"cond: {rule.get('condition','')[:70]} | "
            f"item: {rule.get('item_name','')}"
        )
    rule_ctx = "\n".join(rule_ctx_lines) if rule_ctx_lines else "  (no closely matching rules found)"

    # Fuzzy-filter catalog to items whose name contains intent keywords
    hint = intent.get("item_name_hint", "").lower()
    hint_words = [w for w in hint.split() if len(w) > 2]
    mat_matches = [
        n for n in catalog.get("materials", [])
        if any(w in n.lower() for w in hint_words)
    ][:20]
    lab_matches = [
        n for n in catalog.get("labor", [])
        if any(w in n.lower() for w in hint_words)
    ][:20]
    db_ctx = (
        f"Matching materials: {mat_matches}\n"
        f"Matching labor: {lab_matches}"
    )

    # History for refinement
    hist_ctx = ""
    if history:
        hist_ctx = "Previous instructions:\n" + "\n".join(f"- {h}" for h in history[-3:])

    system = f"""You are an expert electrical estimator AI assistant.
The user gave an instruction. Python-eval rules fire conditions against object properties.

USER SENTENCE: {sentence}
EXTRACTED INTENT: {json.dumps(intent, indent=2)}

CLOSELY MATCHING EXISTING RULES (scored by property overlap):
{rule_ctx}

DATABASE ITEMS MATCHING THE INTENT (use EXACT names from this list):
{db_ctx}

FORMULA VARIABLES available for {obj_type}: {fvars}
{hist_ctx}

TASK: Return a JSON array of rule operations. Each operation must have:
  action        — "CREATE" | "UPDATE" | "SKIP"
                   UPDATE an existing rule if score >= 0.5 and same item category
                   SKIP if the rule already exists and nothing changes
                   CREATE only if no overlapping rule exists
  object        — canvas object type (e.g. "{obj_type}")
  rule_id       — (UPDATE only) the integer index in brackets from the rule list above
  item_name     — MUST be an EXACT name from the database items list above
  item_code     — best matching code if known, else ""
  condition     — valid Python expression using object properties
  formula       — Python expression returning a quantity (use formula variables)
  type          — "Material" or "Labor"
  confidence    — float 0.0-1.0
  reason        — one sentence explaining CREATE/UPDATE/SKIP decision

RULES:
- If score >= 0.7, strongly prefer UPDATE over CREATE
- If the user asks for a material, also propose a companion Labor rule if none exists
- Never duplicate a rule that already exists (same condition + item_name)
- Use EXACT item names from the DB list. If nothing matches, leave item_name as a descriptive hint
- Output ONLY the JSON array, no markdown fences"""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": sentence},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    # Groq returns a JSON object with a key wrapping the array — unwrap if needed
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        # Find the first list value
        for v in parsed.values():
            if isinstance(v, list):
                return v
        return []
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def parse_natural_language_rules(
    sentence: str,
    active_obj_type: str,
    registry,
    current_rules: list[dict] | None = None,
    catalog: dict[str, list[str]] | None = None,
    history: list[str] | None = None,
) -> list[dict]:
    """
    3-stage pipeline:
      1. Extract intent (AI)
      2. Search existing rules (Python)
      3. Propose operations (AI, focused context)

    Returns list of operation dicts for the AI Assistant dialog to display.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set.\n"
            "Add it to your .env file:  GROQ_API_KEY=gsk_...\n"
            "Never paste the key directly in source code."
        )

    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("groq package missing. Run: pip install groq")

    client = Groq(api_key=api_key)
    model = "llama-3.3-70b-versatile"   # best free model on Groq for JSON tasks

    rules = current_rules or []
    cat = catalog or {"materials": [], "labor": []}
    hist = history or []

    # ── Stage 1: Extract intent ───────────────────────────────────────────────
    try:
        intent = _stage1_extract_intent(sentence, active_obj_type, registry, client, model)
    except Exception as e:
        raise RuntimeError(f"Stage 1 (intent extraction) failed: {e}")

    # ── Stage 2: Search existing rules (pure Python) ──────────────────────────
    top_matches = search_existing_rules(intent, rules, top_n=6, threshold=0.15)

    # ── Stage 3: Propose operations ───────────────────────────────────────────
    try:
        operations = _stage3_propose(
            sentence, intent, top_matches, cat, registry, hist, client, model
        )
    except Exception as e:
        raise RuntimeError(f"Stage 3 (proposal) failed: {e}")

    # ── Post-process: validate item names against catalog ─────────────────────
    all_items = set(cat.get("materials", [])) | set(cat.get("labor", []))
    for op in operations:
        name = op.get("item_name", "")
        if name and name not in all_items:
            # Mark unverified names so the UI can highlight them
            op["item_name_unverified"] = True

    return operations


# ─────────────────────────────────────────────────────────────────────────────
# Helper: expose search_existing_rules for the UI to call independently
# (so the Rule Manager can show "similar rules" before the user even hits AI)
# ─────────────────────────────────────────────────────────────────────────────

def find_similar_rules(
    obj_type: str,
    properties: dict,
    item_name_hint: str,
    current_rules: list[dict],
    top_n: int = 5,
) -> list[tuple[int, dict, float]]:
    """
    Utility: search existing rules without calling AI at all.
    Used by the Rule Manager's "Check for similar rules" button.

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
    This runs WITHOUT AI — just pattern matching on common electrical terms.
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
