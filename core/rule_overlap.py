"""
core/rule_overlap.py
====================
Deterministic overlap/duplicate detection for rule conditions.

Used by the Ruleset Manager on Save to *warn* (never block) when a rule's
condition duplicates or subsumes another rule for the same object type.

Kept conservative on purpose — only high-confidence findings are reported so
the warning stays trustworthy:
  - "exact"    : identical (normalised) condition.
  - "broader"  : the new condition's constraints are a strict subset of an
                 existing rule's (so the new rule fires whenever that one does,
                 and more) — AND-only conditions.
  - "narrower" : the reverse.
Partial/ambiguous overlaps and OR-conditions are intentionally not flagged.
"""

from __future__ import annotations

import re

_OP = r"==|!=|>=|<=|>|<"
_CMP_RE = re.compile(rf"(\w+)\s*({_OP})\s*('[^']*'|\"[^\"]*\"|[\w.]+)")
_IN_RE = re.compile(r"(\w+)\s+(not\s+in|in)\s*\(([^)]*)\)")


def _norm(cond: str) -> str:
    """Collapse whitespace for stable string comparison."""
    return " ".join(str(cond or "").split()).strip()


def _is_and_only(cond: str) -> bool:
    """True if the condition is a pure AND-chain (no OR), so subset logic holds."""
    return " or " not in f" {cond.lower()} "


def signatures(cond: str) -> set[str]:
    """Return the set of normalised comparison clauses in a condition.

    e.g. "structure_type == 'DTR' and height >= 9"
         → {"structure_type==dtr", "height>=9"}
    """
    sigs: set[str] = set()
    for prop, op, val in _CMP_RE.findall(cond or ""):
        v = val.strip().strip("'\"").lower()
        sigs.add(f"{prop}{op}{v}")
    for prop, op, vals in _IN_RE.findall(cond or ""):
        members = sorted(v.strip().strip("'\"").lower() for v in vals.split(",") if v.strip())
        sigs.add(f"{prop} {op.replace(' ', '')} ({','.join(members)})")
    return sigs


def analyze_overlap(
    new_object: str,
    new_condition: str,
    existing_rules: list[dict],
    exclude_index: int | None = None,
) -> list[dict]:
    """Compare new_condition against existing rules of the same object type.

    Returns a list of findings: {index, id, kind, condition, items}.
    """
    findings: list[dict] = []
    new_norm = _norm(new_condition)
    new_sigs = signatures(new_condition)
    new_and_only = _is_and_only(new_condition)

    for i, rule in enumerate(existing_rules):
        if i == exclude_index:
            continue
        if rule.get("object") != new_object:
            continue
        ex_cond = rule.get("condition", "")
        ex_norm = _norm(ex_cond)
        if not ex_norm:
            continue

        kind = ""
        if ex_norm == new_norm:
            kind = "exact"
        elif new_and_only and _is_and_only(ex_cond) and new_sigs and signatures(ex_cond):
            ex_sigs = signatures(ex_cond)
            if new_sigs < ex_sigs:
                kind = "broader"
            elif ex_sigs < new_sigs:
                kind = "narrower"

        if kind:
            findings.append({
                "index": i,
                "id": rule.get("id"),
                "kind": kind,
                "condition": ex_cond,
                "items": [it.get("item_name", "") for it in rule.get("items", [])],
            })
    return findings
