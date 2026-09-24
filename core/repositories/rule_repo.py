"""
core/repositories/rule_repo.py
==============================
Repository for dynamic rule definitions and caching.
"""
from __future__ import annotations
import json
import sqlite3
from core.repositories.base import get_connection

# In-memory cache for enabled rules
_rules_cache: list | None = None

def _invalidate_rules_cache() -> None:
    global _rules_cache
    _rules_cache = None

def get_rules(object_type: str | None = None, enabled_only: bool = True) -> list[dict]:
    """Return list of rule dicts, ordered by sort_order."""
    global _rules_cache
    if object_type is None and enabled_only and _rules_cache is not None:
        return _rules_cache
    con = get_connection()
    try:
        cur = con.cursor()
        base = "SELECT id, object_type, condition, items_json, enabled FROM rules"
        where: list[str] = []
        params: list = []
        if object_type:
            where.append("object_type=?")
            params.append(object_type)
        if enabled_only:
            where.append("enabled=1")
        sql = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY sort_order, id"
        rows = cur.execute(sql, params).fetchall()
        result = [
            {
                "id":        r[0],
                "object":    r[1],
                "condition": r[2],
                "items":     json.loads(r[3]),
                "enabled":   r[4],
            }
            for r in rows
        ]
        if object_type is None and enabled_only:
            _rules_cache = result
        return result
    finally:
        con.close()

def save_rules(rules: list[dict]) -> None:
    """Replace ALL rules in DB with the given list, preserving IDs where possible."""
    con = get_connection()
    try:
        cur = con.cursor()
        existing_ids = {r[0] for r in cur.execute("SELECT id FROM rules").fetchall()}
        incoming_ids = {r["id"] for r in rules if "id" in r and r["id"] in existing_ids}
        
        to_delete = existing_ids - incoming_ids
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            cur.execute(f"DELETE FROM rules WHERE id IN ({placeholders})", list(to_delete))

        for i, r in enumerate(rules):
            rid = r.get("id")
            if rid and rid in existing_ids:
                cur.execute(
                    "UPDATE rules SET object_type=?, condition=?, items_json=?, "
                    "enabled=?, sort_order=? WHERE id=?",
                    (
                        r.get("object", ""),
                        r.get("condition", "True"),
                        json.dumps(r.get("items", [])),
                        1 if r.get("enabled", 1) else 0,
                        i,
                        rid,
                    ),
                )
            else:
                cur.execute("SELECT MAX(id) FROM rules")
                max_id = cur.fetchone()[0] or 7000
                target_id = max(max_id + 1, 7001)

                cur.execute(
                    "INSERT INTO rules "
                    "(id, object_type, condition, items_json, enabled, sort_order) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        target_id,
                        r.get("object", ""),
                        r.get("condition", "True"),
                        json.dumps(r.get("items", [])),
                        1 if r.get("enabled", 1) else 0,
                        i,
                    ),
                )
        con.commit()
        _invalidate_rules_cache()
    finally:
        con.close()

def add_rule(rule: dict) -> int:
    """Insert a single rule. Returns the new row id."""
    con = get_connection()
    try:
        cur = con.cursor()
        cur.execute("SELECT COALESCE(MAX(sort_order),0) FROM rules")
        max_sort = cur.fetchone()[0]

        cur.execute("SELECT MAX(id) FROM rules")
        max_id = cur.fetchone()[0] or 7000
        target_id = max(max_id + 1, 7001)

        cur.execute(
            "INSERT INTO rules "
            "(id, object_type, condition, items_json, enabled, sort_order) "
            "VALUES (?,?,?,?,?,?)",
            (
                target_id,
                rule.get("object", ""),
                rule.get("condition", "True"),
                json.dumps(rule.get("items", [])),
                1,
                max_sort + 1,
            ),
        )
        con.commit()
        _invalidate_rules_cache()
        return target_id
    finally:
        con.close()

def update_rule(rule_id: int, rule: dict) -> None:
    """Update fields of an existing rule by id."""
    con = get_connection()
    try:
        con.execute(
            "UPDATE rules SET object_type=?, condition=?, items_json=? WHERE id=?",
            (
                rule.get("object", ""),
                rule.get("condition", "True"),
                json.dumps(rule.get("items", [])),
                rule_id,
            ),
        )
        con.commit()
        _invalidate_rules_cache()
    finally:
        con.close()

def delete_rule(rule_id: int) -> None:
    """Hard-delete a rule by id."""
    con = get_connection()
    try:
        con.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        con.commit()
        _invalidate_rules_cache()
    finally:
        con.close()

def toggle_rule(rule_id: int, enabled: bool) -> None:
    """Enable or disable a rule without deleting it."""
    con = get_connection()
    try:
        con.execute("UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
        con.commit()
        _invalidate_rules_cache()
    finally:
        con.close()
