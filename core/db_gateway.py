"""
db_gateway.py
=============
Unified database access layer for all configuration tables (v7.0+).

Use this module as the single import for reading/writing:
  - Rules
  - Settings (canvas colours, placement defaults, labels)
  - Property options (user-added values for fixed properties)
  - Height options per pole_type2
  - Conductor size options
  - Custom properties (user-defined property definitions)
  - Conductor metadata (voltage affinity of user-added conductors)

Design: every function opens its own connection and closes it on exit.
Mirrors the existing materials/labour read pattern in database.py.
"""
from __future__ import annotations
import json

import sqlite3
from core.database import DB_PATH

# In-memory cache for enabled rules — invalidated whenever rules are written.
# get_rules() is called on every canvas interaction, so avoiding a DB round-trip
# here is the single highest-leverage read-path optimisation.
_rules_cache: "list | None" = None

# get_sections() is called from the expression evaluator on every condition/
# formula evaluation (thousands of times per refresh). Caching it removes a
# per-evaluation SQLite connection.
_sections_cache: "dict | None" = None


def _invalidate_rules_cache() -> None:
    global _rules_cache
    _rules_cache = None


def _invalidate_sections_cache() -> None:
    global _sections_cache
    _sections_cache = None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except:
        pass
    return conn


# ─── Rules ────────────────────────────────────────────────────────────────────

def get_rules(object_type: str | None = None, enabled_only: bool = True) -> list[dict]:
    """Return list of rule dicts, ordered by sort_order.

    Each dict has keys: id, object, condition, items, enabled.
    The common hot-path call (no filters) is served from an in-memory cache.
    """
    global _rules_cache
    if object_type is None and enabled_only and _rules_cache is not None:
        return _rules_cache
    con = _conn()
    try:
        cur = con.cursor()
        base = (
            "SELECT id, object_type, condition, items_json, enabled "
            "FROM rules"
        )
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
    """Replace ALL rules in DB with the given list, preserving IDs where possible.

    Each dict should have: object, condition, items, enabled.
    If 'id' is present and exists in DB, that row is updated.
    Rules not present in the 'rules' list are deleted from the DB.
    """
    con = _conn()
    try:
        cur = con.cursor()
        
        # 1. Map existing IDs
        existing_ids = {r[0] for r in cur.execute("SELECT id FROM rules").fetchall()}
        incoming_ids = {r["id"] for r in rules if "id" in r and r["id"] in existing_ids}
        
        # 2. Delete rules not in the incoming list
        to_delete = existing_ids - incoming_ids
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            cur.execute(f"DELETE FROM rules WHERE id IN ({placeholders})", list(to_delete))

        # 3. Upsert rules
        for i, r in enumerate(rules):
            rid = r.get("id")
            if rid and rid in existing_ids:
                # Update existing (preserves ID)
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
                # Insert new (Ensure ID starts from 7001 to avoid clashing with System Rules 1-7000)
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
    con = _conn()
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
    con = _conn()
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
    con = _conn()
    try:
        con.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        con.commit()
        _invalidate_rules_cache()
    finally:
        con.close()


def toggle_rule(rule_id: int, enabled: bool) -> None:
    """Enable or disable a rule without deleting it."""
    con = _conn()
    try:
        con.execute("UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
        con.commit()
        _invalidate_rules_cache()
    finally:
        con.close()


# ─── Iron Recipes & Steel Sections (Phase 2.1) ────────────────────────────────

def get_sections() -> dict[str, dict]:
    """Get all steel sections indexed by code (cached)."""
    global _sections_cache
    if _sections_cache is not None:
        return _sections_cache
    con = _conn()
    try:
        rows = con.execute("SELECT section_code, label, kg_per_metre FROM sections").fetchall()
        _sections_cache = {
            r[0]: {"label": r[1], "kg_per_metre": r[2]}
            for r in rows
        }
        return _sections_cache
    finally:
        con.close()


def save_sections(sections_dict: dict[str, dict]) -> None:
    """Save or update multiple steel sections."""
    con = _conn()
    try:
        for code, data in sections_dict.items():
            con.execute(
                "INSERT OR REPLACE INTO sections (section_code, label, kg_per_metre) VALUES (?, ?, ?)",
                (code, data["label"], data["kg_per_metre"])
            )
        con.commit()
        _invalidate_sections_cache()
    finally:
        con.close()


def get_recipes(object_type: str | None = None) -> list[dict]:
    """Get recipes, optionally filtered by object_type."""
    con = _conn()
    try:
        if object_type:
            rows = con.execute(
                "SELECT recipe_key, name, description, object_type, items_json FROM recipes WHERE object_type=?",
                (object_type,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT recipe_key, name, description, object_type, items_json FROM recipes"
            ).fetchall()
        
        recipes = []
        for r in rows:
            try:
                items = json.loads(r[4])
            except Exception:
                items = []
            recipes.append({
                "recipe_key": r[0],
                "name": r[1],
                "description": r[2],
                "object_type": r[3],
                "items": items
            })
        return recipes
    finally:
        con.close()


def save_recipe(recipe: dict) -> None:
    """Upsert an iron recipe template."""
    con = _conn()
    try:
        con.execute(
            "INSERT OR REPLACE INTO recipes (recipe_key, name, description, object_type, items_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                recipe["recipe_key"],
                recipe["name"],
                recipe.get("description", ""),
                recipe["object_type"],
                json.dumps(recipe.get("items", []))
            )
        )
        con.commit()
    finally:
        con.close()


def delete_recipe(recipe_key: str) -> None:
    """Hard delete a recipe template."""
    con = _conn()
    try:
        con.execute("DELETE FROM recipes WHERE recipe_key=?", (recipe_key,))
        con.commit()
    finally:
        con.close()


# ─── Settings ─────────────────────────────────────────────────────────────────

def get_all_settings() -> dict[str, str]:
    """Return all settings as a flat {key: value_str} dict."""
    con = _conn()
    try:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        con.close()


def get_setting(key: str, default: str | None = None) -> str | None:
    """Return a single setting value string, or default if not found."""
    con = _conn()
    try:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    finally:
        con.close()


def save_setting(key: str, value) -> None:
    """Upsert a single setting value."""
    con = _conn()
    try:
        con.execute(
            "INSERT INTO settings (key, value, category) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value), "general"),
        )
        con.commit()
    finally:
        con.close()


def save_settings(updates: dict) -> None:
    """Upsert multiple settings at once."""
    con = _conn()
    try:
        for key, value in updates.items():
            con.execute(
                "INSERT INTO settings (key, value, category) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value), "general"),
            )
        con.commit()
    finally:
        con.close()


# ─── Extended Options (user-added values for fixed properties) ────────────────

def get_extended_options(object_type: str, prop_name: str) -> list[str]:
    """Return user-added options for a fixed property, e.g. pole_type2."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT option_val FROM extended_options "
            "WHERE object_type=? AND prop_name=? ORDER BY sort_order, id",
            (object_type, prop_name),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def get_all_extended_options(object_type: str) -> dict[str, list[str]]:
    """Return all extended options for an object type as {prop_name: [values]}."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT prop_name, option_val FROM extended_options "
            "WHERE object_type=? ORDER BY prop_name, sort_order, id",
            (object_type,),
        ).fetchall()
        result: dict[str, list[str]] = {}
        for prop_name, opt_val in rows:
            result.setdefault(prop_name, []).append(opt_val)
        return result
    finally:
        con.close()


def add_extended_option(object_type: str, prop_name: str, option: str) -> bool:
    """Add a user option. Returns False if it already exists (case-insensitive)."""
    con = _conn()
    try:
        dup = con.execute(
            "SELECT 1 FROM extended_options "
            "WHERE object_type=? AND prop_name=? AND option_val=? COLLATE NOCASE",
            (object_type, prop_name, option),
        ).fetchone()
        if dup:
            return False
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM extended_options "
            "WHERE object_type=? AND prop_name=?",
            (object_type, prop_name),
        )
        max_sort = cur.fetchone()[0]
        cur.execute(
            "INSERT OR IGNORE INTO extended_options "
            "(object_type, prop_name, option_val, sort_order) VALUES (?,?,?,?)",
            (object_type, prop_name, option, max_sort + 1),
        )
        con.commit()
        return True
    finally:
        con.close()


def remove_extended_option(object_type: str, prop_name: str, option: str) -> None:
    """Remove a user-added extended option."""
    con = _conn()
    try:
        con.execute(
            "DELETE FROM extended_options "
            "WHERE object_type=? AND prop_name=? AND option_val=? COLLATE NOCASE",
            (object_type, prop_name, option),
        )
        con.commit()
    finally:
        con.close()


# ─── Height Options ───────────────────────────────────────────────────────────

def get_height_options(pole_type2: str) -> list[str]:
    """Return height strings like ['8MTR', '9.5MTR'] for a pole_type2.

    The 'MTR' suffix is REQUIRED so these match the canonical height format
    used everywhere else (factory defaults, item.height, get_all_height_options,
    the _height_options fallback). Returning bare numbers ('8', '9') caused the
    editor's height combo to fail to match a stored '9MTR' value and silently
    fall back to the first option ('8') while the BOM still counted 9.
    """
    con = _conn()
    try:
        rows = con.execute(
            "SELECT height_val FROM height_options WHERE pole_type2=? ORDER BY sort_order, height_val",
            (pole_type2,),
        ).fetchall()
        result = []
        for (hval,) in rows:
            hval = float(hval)
            if hval == int(hval):
                result.append(f"{int(hval)}MTR")
            else:
                result.append(f"{hval}MTR")
        return result
    finally:
        con.close()


def get_all_height_options() -> dict[str, list[str]]:
    """Return {pole_type2: ['8MTR', ...]} for all pole types."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT pole_type2, height_val FROM height_options ORDER BY pole_type2, sort_order, height_val"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for pt2, hval in rows:
            hval = float(hval)
            label = f"{int(hval)}MTR" if hval == int(hval) else f"{hval}MTR"
            result.setdefault(pt2, []).append(label)
        return result
    finally:
        con.close()


def get_all_pole_type2() -> list[str]:
    """Return distinct pole_type2 values from height_options."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT DISTINCT pole_type2 FROM height_options ORDER BY pole_type2"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def add_height_option(pole_type2: str, height_str: str) -> bool:
    """Add a new height for a pole_type2.  Accepts strings like '8MTR', '9.5MTR'.
    Returns False if already exists."""
    try:
        clean = height_str.strip().upper()
        if clean.endswith("MTR"):
            clean = clean[:-3].strip()
        height_val = float(clean)
    except (ValueError, AttributeError):
        return False
    con = _conn()
    try:
        dup = con.execute(
            "SELECT 1 FROM height_options WHERE pole_type2=? AND height_val=?",
            (pole_type2, height_val),
        ).fetchone()
        if dup:
            return False
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM height_options WHERE pole_type2=?",
            (pole_type2,),
        )
        max_sort = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO height_options (pole_type2, height_val, is_builtin, sort_order) VALUES (?,?,0,?)",
            (pole_type2, height_val, max_sort + 1),
        )
        con.commit()
        return True
    finally:
        con.close()


def remove_height_option(pole_type2: str, height_str: str) -> bool:
    """Remove a user-added height for a pole_type2.  Accepts strings like '8MTR'.
    Returns False if the value is built-in (protected) or not found."""
    try:
        clean = height_str.strip().upper()
        if clean.endswith("MTR"):
            clean = clean[:-3].strip()
        height_val = float(clean)
    except (ValueError, AttributeError):
        return False
    con = _conn()
    try:
        row = con.execute(
            "SELECT is_builtin FROM height_options WHERE pole_type2=? AND height_val=?",
            (pole_type2, height_val),
        ).fetchone()
        if row is None:
            return False
        if row[0]:  # built-in — refuse to delete
            return False
        con.execute(
            "DELETE FROM height_options WHERE pole_type2=? AND height_val=?",
            (pole_type2, height_val),
        )
        con.commit()
        return True
    finally:
        con.close()


def get_all_height_options_detail() -> dict:
    """Return {pole_type2: [{'val': '8MTR', 'builtin': True}, ...]} for the settings UI."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT pole_type2, height_val, is_builtin "
            "FROM height_options ORDER BY pole_type2, sort_order, height_val"
        ).fetchall()
        result: dict = {}
        for pt2, hval, builtin in rows:
            hval = float(hval)
            label = f"{int(hval)}MTR" if hval == int(hval) else f"{hval}MTR"
            result.setdefault(pt2, []).append({"val": label, "builtin": bool(builtin)})
        return result
    finally:
        con.close()


def get_all_conductor_options_detail() -> dict:
    """Return {(conductor_type, voltage_class): [{'val': str, 'builtin': bool}]} for the UI."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT conductor_type, voltage_class, size_value, is_builtin "
            "FROM conductor_options ORDER BY conductor_type, voltage_class, sort_order, id"
        ).fetchall()
        result: dict = {}
        for ct, vc, sv, builtin in rows:
            result.setdefault((ct, vc), []).append({"val": sv, "builtin": bool(builtin)})
        return result
    finally:
        con.close()


# ─── Conductor Size Options ────────────────────────────────────────────────────

def get_conductor_options(conductor_type: str, voltage_class: str) -> list[str]:
    """Return size values for a conductor type + voltage class."""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT size_value FROM conductor_options "
            "WHERE conductor_type=? AND voltage_class=? ORDER BY sort_order, id",
            (conductor_type, voltage_class),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def add_conductor_option(conductor_type: str, voltage_class: str, size_value: str) -> bool:
    """Add a size option. Returns False if duplicate."""
    con = _conn()
    try:
        dup = con.execute(
            "SELECT 1 FROM conductor_options "
            "WHERE conductor_type=? AND voltage_class=? AND size_value=?",
            (conductor_type, voltage_class, size_value),
        ).fetchone()
        if dup:
            return False
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM conductor_options "
            "WHERE conductor_type=? AND voltage_class=?",
            (conductor_type, voltage_class),
        )
        max_sort = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO conductor_options "
            "(conductor_type, voltage_class, size_value, is_builtin, sort_order) VALUES (?,?,?,0,?)",
            (conductor_type, voltage_class, size_value, max_sort + 1),
        )
        con.commit()
        return True
    finally:
        con.close()


def remove_conductor_option(conductor_type: str, voltage_class: str, size_value: str) -> None:
    """Remove a conductor size option."""
    con = _conn()
    try:
        con.execute(
            "DELETE FROM conductor_options "
            "WHERE conductor_type=? AND voltage_class=? AND size_value=?",
            (conductor_type, voltage_class, size_value),
        )
        con.commit()
    finally:
        con.close()


# ─── Custom Properties ────────────────────────────────────────────────────────

def get_custom_entries(object_type: str) -> list[dict]:
    """Return [{label, options}] of user-defined custom properties."""
    con = _conn()
    try:
        cur = con.cursor()
        entries = cur.execute(
            "SELECT id, label FROM custom_properties WHERE object_type=? ORDER BY sort_order, id",
            (object_type,),
        ).fetchall()
        result = []
        for cp_id, label in entries:
            opts = cur.execute(
                "SELECT option_val FROM custom_property_options "
                "WHERE custom_property_id=? ORDER BY sort_order, id",
                (cp_id,),
            ).fetchall()
            result.append({"label": label, "options": [r[0] for r in opts]})
        return result
    finally:
        con.close()


def add_custom_entry(object_type: str, label: str, options: list[str] | None = None) -> None:
    """Add a new custom property definition."""
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM custom_properties WHERE object_type=?",
            (object_type,),
        )
        max_sort = cur.fetchone()[0]
        cur.execute(
            "INSERT OR IGNORE INTO custom_properties (object_type, label, sort_order) VALUES (?,?,?)",
            (object_type, label, max_sort + 1),
        )
        cur.execute(
            "SELECT id FROM custom_properties WHERE object_type=? AND label=?",
            (object_type, label),
        )
        row = cur.fetchone()
        if not row:
            con.commit()
            return
        cp_id = row[0]
        for i, opt in enumerate(options or []):
            s = str(opt or "").strip()
            if s:
                cur.execute(
                    "INSERT INTO custom_property_options (custom_property_id, option_val, sort_order) VALUES (?,?,?)",
                    (cp_id, s, i),
                )
        con.commit()
    finally:
        con.close()


def update_custom_entry(
    object_type: str,
    old_label: str,
    new_label: str,
    options: list[str] | None = None,
) -> None:
    """Rename and/or update options of a custom property."""
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute(
            "UPDATE custom_properties SET label=? WHERE object_type=? AND label=?",
            (new_label, object_type, old_label),
        )
        cur.execute(
            "SELECT id FROM custom_properties WHERE object_type=? AND label=?",
            (object_type, new_label),
        )
        row = cur.fetchone()
        if row:
            cp_id = row[0]
            cur.execute("DELETE FROM custom_property_options WHERE custom_property_id=?", (cp_id,))
            for i, opt in enumerate(options or []):
                s = str(opt or "").strip()
                if s:
                    cur.execute(
                        "INSERT INTO custom_property_options (custom_property_id, option_val, sort_order) VALUES (?,?,?)",
                        (cp_id, s, i),
                    )
        con.commit()
    finally:
        con.close()


def delete_custom_entry(object_type: str, label: str) -> None:
    """Delete a custom property and all its options."""
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT id FROM custom_properties WHERE object_type=? AND label=?",
            (object_type, label),
        )
        row = cur.fetchone()
        if row:
            cp_id = row[0]
            cur.execute("DELETE FROM custom_property_options WHERE custom_property_id=?", (cp_id,))
            cur.execute("DELETE FROM custom_properties WHERE id=?", (cp_id,))
        con.commit()
    finally:
        con.close()


# ─── Conductor Metadata ────────────────────────────────────────────────────────

def get_user_conductors() -> list[dict]:
    """Return all user-added conductors as [{name, voltage}]."""
    con = _conn()
    try:
        rows = con.execute("SELECT name, voltage FROM conductor_meta ORDER BY name").fetchall()
        return [{"name": r[0], "voltage": r[1]} for r in rows]
    finally:
        con.close()


def get_conductor_meta(conductor_name: str) -> dict:
    """Return {voltage} for a user-added conductor, or {} if not found."""
    con = _conn()
    try:
        row = con.execute(
            "SELECT voltage FROM conductor_meta WHERE name=?", (conductor_name,)
        ).fetchone()
        return {"voltage": row[0]} if row else {}
    finally:
        con.close()


def set_conductor_meta(conductor_name: str, voltage: str) -> None:
    """Store or update voltage affinity for a user-added conductor."""
    con = _conn()
    try:
        con.execute(
            "INSERT OR REPLACE INTO conductor_meta (name, voltage) VALUES (?,?)",
            (conductor_name, voltage),
        )
        con.commit()
    finally:
        con.close()


def delete_user_conductor(conductor_name: str) -> None:
    """Remove a user conductor, its sizes from extended_options, and its meta."""
    con = _conn()
    try:
        con.execute("DELETE FROM conductor_meta WHERE name=?", (conductor_name,))
        # Remove conductor name from extended_options (the "conductor" prop option)
        con.execute(
            "DELETE FROM extended_options "
            "WHERE object_type='SmartSpan' AND prop_name='conductor' "
            "AND option_val=? COLLATE NOCASE",
            (conductor_name,),
        )
        # Remove its size options (stored under conductor_size__lt_NAME and _ht_NAME)
        con.execute(
            "DELETE FROM extended_options "
            "WHERE object_type='SmartSpan' AND prop_name IN (?,?)",
            (
                f"conductor_size__lt_{conductor_name}",
                f"conductor_size__ht_{conductor_name}",
            ),
        )
        con.commit()
    finally:
        con.close()


# ─── Rule Builder Helpers ─────────────────────────────────────────────────────

def get_properties_for_simulator(object_type: str) -> list[dict]:
    """Return property metadata needed to build the rule simulator panel.

    Each dict: {prop_name, display_name, widget_type, sim_default, sim_min, sim_max, options}
    """
    con = _conn()
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT id, prop_name, display_name, widget_type, sim_default, sim_min, sim_max "
            "FROM properties WHERE object_type=? ORDER BY sort_order, id",
            (object_type,),
        ).fetchall()
        result = []
        for prop_id, prop_name, display_name, widget_type, sim_default, sim_min, sim_max in rows:
            # 1. Start with built-in options from property_options
            opts = cur.execute(
                "SELECT option_val FROM property_options WHERE property_id=? ORDER BY sort_order, id",
                (prop_id,),
            ).fetchall()
            options = [r[0] for r in opts]
            seen = {o.casefold() for o in options}

            # 2. Merge extended (user-added generic) options
            ext = cur.execute(
                "SELECT option_val FROM extended_options "
                "WHERE object_type=? AND prop_name=? ORDER BY sort_order, id",
                (object_type, prop_name),
            ).fetchall()
            for (ev,) in ext:
                if ev.casefold() not in seen:
                    options.append(ev)
                    seen.add(ev.casefold())

            # 3. Merge specialized dynamic options (heights, conductors, pole types)
            if prop_name in ("height", "dtr_new_height", "extension_height"):
                h_rows = cur.execute("SELECT DISTINCT height_val FROM height_options").fetchall()
                for (hval,) in h_rows:
                    try:
                        fv = float(hval)
                        s = f"{int(fv)}" if fv == int(fv) else f"{fv}"
                        if s.casefold() not in seen:
                            options.append(s)
                            seen.add(s.casefold())
                    except: pass
            elif prop_name in ("pole_type2", "dtr_new_pole_type2"):
                p_rows = cur.execute("SELECT DISTINCT pole_type2 FROM height_options").fetchall()
                for (pt,) in p_rows:
                    if pt and pt.casefold() not in seen:
                        options.append(pt)
                        seen.add(pt.casefold())
            elif prop_name in ("conductor_size", "cable_size", "aug_to_conductor", "aug_to_config"):
                c_rows = cur.execute("SELECT DISTINCT size_value FROM conductor_options").fetchall()
                for (cv,) in c_rows:
                    if cv and cv.casefold() not in seen:
                        options.append(cv)
                        seen.add(cv.casefold())
            
            result.append({
                "prop_name":    prop_name,
                "display_name": display_name,
                "widget_type":  widget_type,
                "sim_default":  sim_default,
                "sim_min":      sim_min,
                "sim_max":      sim_max,
                "options":      options,
            })
        return result
    finally:
        con.close()


# ─── Option Color Overrides ──────────────────────────────────────────────────

def _norm_color(hex_color: str, fallback: str = "#888888") -> str:
    s = str(hex_color or "").strip()
    if len(s) == 7 and s.startswith("#"):
        try:
            int(s[1:], 16)
            return s.lower()
        except ValueError:
            return fallback
    return fallback


def upsert_option_color_default(
    object_type: str,
    prop_name: str,
    option_val: str,
    default_color: str,
    context_key: str = "",
) -> None:
    """Create or update the default color for an option key without touching user_color."""
    con = _conn()
    try:
        con.execute(
            """
            INSERT INTO option_color_overrides
            (object_type, prop_name, option_val, context_key, default_color, user_color)
            VALUES (?,?,?,?,?,NULL)
            ON CONFLICT(object_type, prop_name, option_val, context_key)
            DO UPDATE SET default_color=excluded.default_color
            """,
            (
                object_type,
                prop_name,
                option_val,
                context_key,
                _norm_color(default_color),
            ),
        )
        con.commit()
    finally:
        con.close()


def set_option_user_color(
    object_type: str,
    prop_name: str,
    option_val: str,
    user_color: str,
    context_key: str = "",
    default_color: str = "#888888",
) -> None:
    """Set or update user-selected color for an option key."""
    con = _conn()
    try:
        con.execute(
            """
            INSERT INTO option_color_overrides
            (object_type, prop_name, option_val, context_key, default_color, user_color)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(object_type, prop_name, option_val, context_key)
            DO UPDATE SET user_color=excluded.user_color
            """,
            (
                object_type,
                prop_name,
                option_val,
                context_key,
                _norm_color(default_color),
                _norm_color(user_color),
            ),
        )
        con.commit()
    finally:
        con.close()


def reset_option_user_color(
    object_type: str,
    prop_name: str,
    option_val: str,
    context_key: str = "",
) -> None:
    """Reset one option key back to its default by clearing user_color."""
    con = _conn()
    try:
        con.execute(
            """
            UPDATE option_color_overrides
            SET user_color=NULL
            WHERE object_type=? AND prop_name=? AND option_val=? AND context_key=?
            """,
            (object_type, prop_name, option_val, context_key),
        )
        con.commit()
    finally:
        con.close()


def get_option_color_record(
    object_type: str,
    prop_name: str,
    option_val: str,
    context_key: str = "",
) -> dict:
    """Return {'default_color', 'user_color'} for a key, or {} if not present."""
    con = _conn()
    try:
        row = con.execute(
            """
            SELECT default_color, user_color
            FROM option_color_overrides
            WHERE object_type=? AND prop_name=? AND option_val=? AND context_key=?
            """,
            (object_type, prop_name, option_val, context_key),
        ).fetchone()
        if not row:
            return {}
        return {"default_color": row[0], "user_color": row[1]}
    finally:
        con.close()


def resolve_option_color(
    object_type: str,
    prop_name: str,
    option_val: str,
    context_key: str = "",
    fallback_color: str = "#888888",
) -> str:
    """Resolve effective color: exact context -> contextless -> fallback."""
    con = _conn()
    try:
        if context_key:
            row = con.execute(
                """
                SELECT COALESCE(user_color, default_color)
                FROM option_color_overrides
                WHERE object_type=? AND prop_name=? AND option_val=? AND context_key=?
                """,
                (object_type, prop_name, option_val, context_key),
            ).fetchone()
            if row and row[0]:
                return _norm_color(row[0], _norm_color(fallback_color))

        row = con.execute(
            """
            SELECT COALESCE(user_color, default_color)
            FROM option_color_overrides
            WHERE object_type=? AND prop_name=? AND option_val=? AND context_key=''
            """,
            (object_type, prop_name, option_val),
        ).fetchone()
        if row and row[0]:
            return _norm_color(row[0], _norm_color(fallback_color))

        return _norm_color(fallback_color)
    finally:
        con.close()


def get_user_color_only(
    object_type: str,
    prop_name: str,
    option_val: str,
    context_key: str = "",
) -> str | None:
    """Return the user-set color override only — None if no explicit user choice.

    Unlike resolve_option_color(), this ignores the stored default_color so that
    canvas-symbol defaults (from core.defaults) always win unless the user has
    explicitly chosen a per-option color via the Properties panel.
    """
    con = _conn()
    try:
        if context_key:
            row = con.execute(
                """
                SELECT user_color FROM option_color_overrides
                WHERE object_type=? AND prop_name=? AND option_val=? AND context_key=?
                """,
                (object_type, prop_name, option_val, context_key),
            ).fetchone()
            if row and row[0]:
                return _norm_color(row[0])

        row = con.execute(
            """
            SELECT user_color FROM option_color_overrides
            WHERE object_type=? AND prop_name=? AND option_val=? AND context_key=''
            """,
            (object_type, prop_name, option_val),
        ).fetchone()
        if row and row[0]:
            return _norm_color(row[0])

        return None
    finally:
        con.close()


# ── Dynamic Structural Hierarchies (Phase 3 Expansion) ─────────────────────────

def get_project_types() -> list[str]:
    """Return list of project type names from the database."""
    con = _conn()
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT type_name FROM project_types ORDER BY id").fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()

def get_supervision_rates() -> dict[str, float]:
    """Return dict mapping project_type to supervision_rate from DB."""
    con = _conn()
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT type_name, supervision_rate FROM project_types").fetchall()
        return {r[0]: float(r[1]) for r in rows}
    finally:
        con.close()

def get_tree_def() -> list:
    """Reconstruct the nested rule tree definition from the DB."""
    con = _conn()
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT id, parent_id, label, object_type, filter_dict_json, sort_order FROM rule_tree_nodes ORDER BY sort_order, id").fetchall()
        
        # Build node dictionaries
        nodes = {}
        for r in rows:
            node_id, parent_id, label, obj_type, filter_json, sort_order = r
            filter_dict = {}
            if filter_json:
                try:
                    filter_dict = json.loads(filter_json)
                except json.JSONDecodeError:
                    pass
            # node record format tracking tree_def structure: (label, obj_type, filter_dict, [children])
            nodes[node_id] = {
                "parent_id": parent_id,
                "data": (label, obj_type, filter_dict, []),
                "sort_order": sort_order
            }
            
        tree = []
        # Populate children
        for n_id, n_data in nodes.items():
            pid = n_data["parent_id"]
            if pid is None:
                tree.append(n_data)
            else:
                if pid in nodes:
                    nodes[pid]["data"][3].append(n_data)
                    
        # Sort function
        def _sort_tree(n_list):
            n_list.sort(key=lambda x: x["sort_order"])
            for item in n_list:
                _sort_tree(item["data"][3])
                
        _sort_tree(tree)
        
        # Recursively strip wrapper dict mapping
        def _strip_wrap(n_list):
            res = []
            for item in n_list:
                child_data = item["data"]
                # data is a tuple right now as (label, obj_type, filter_dict, [children wrappers])
                stripped_children = _strip_wrap(child_data[3])
                res.append((child_data[0], child_data[1], child_data[2], stripped_children))
            return res
            
        return _strip_wrap(tree)
    finally:
        con.close()

def get_filter_chips() -> dict[str, list]:
    """Return filter chips structured by object type."""
    con = _conn()
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT object_type, label, prop_name, match_value FROM rule_filter_chips ORDER BY sort_order, id").fetchall()
        chips = {}
        for r in rows:
            obj_type, label, prop_name, match_val = r
            
            # Cast match_val correctly (True/False or text)
            if match_val == "True":
                val = True
            elif match_val == "False":
                val = False
            else:
                try:
                    val = int(match_val)
                except ValueError:
                    val = match_val
                    
            if obj_type not in chips:
                chips[obj_type] = []
            chips[obj_type].append((label, prop_name, val))
        return chips
    finally:
        con.close()

def get_formula_vars() -> dict[str, list[str]]:
    """Get all formula permitted variables by object type."""
    con = _conn()
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT object_type, prop_name FROM properties WHERE is_formula_var=1").fetchall()
        f_vars = {}
        for r in rows:
            obj, prop = r
            if obj not in f_vars:
                f_vars[obj] = []
            f_vars[obj].append(prop)
        # Ensure default empty lists if objects don't have formula vars yet
        for base in ["SmartPole", "SmartStructure", "SmartSpan", "SmartConsumer"]:
            if base not in f_vars:
                f_vars[base] = []
        return f_vars
    finally:
        con.close()


# ─── User Profiles (Phase 4) ──────────────────────────────────────────────────

def get_user_profiles() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute(
            "SELECT id, name, firm_name, address, gstin, signature_path, is_active, "
            "vendor_no, agency_details, billing_to_json, invoice_format, next_seq, logo_path "
            "FROM user_profiles ORDER BY name"
        ).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "firm_name": r[2],
                "address": r[3],
                "gstin": r[4],
                "signature_path": r[5],
                "is_active": bool(r[6]),
                "vendor_no": r[7] or "",
                "agency_details": r[8] or "",
                "billing_to_json": r[9] or "[]",
                "invoice_format": r[10] or "SE/{FY}/KSD/{SEQ}",
                "next_seq": r[11] or 1,
                "logo_path": r[12] or ""
            }
            for r in rows
        ]
    finally:
        con.close()

def add_user_profile(profile: dict) -> bool:
    con = _conn()
    try:
        dup = con.execute("SELECT 1 FROM user_profiles WHERE name=?", (profile["name"],)).fetchone()
        if dup:
            return False
        
        is_active = 1 if profile.get("is_active") else 0
        if is_active:
            con.execute("UPDATE user_profiles SET is_active=0")
        else:
            cnt = con.execute("SELECT COUNT(*) FROM user_profiles WHERE is_active=1").fetchone()[0]
            if cnt == 0:
                is_active = 1
                
        con.execute(
            "INSERT INTO user_profiles (name, firm_name, address, gstin, signature_path, is_active, "
            "vendor_no, agency_details, billing_to_json, invoice_format, next_seq, logo_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                profile["name"],
                profile["firm_name"],
                profile["address"],
                profile["gstin"],
                profile.get("signature_path"),
                is_active,
                profile.get("vendor_no", ""),
                profile.get("agency_details", ""),
                profile.get("billing_to_json", "[]"),
                profile.get("invoice_format", "SE/{FY}/KSD/{SEQ}"),
                profile.get("next_seq", 1),
                profile.get("logo_path", "")
            )
        )
        con.commit()
        return True
    finally:
        con.close()

def update_user_profile(profile_id: int, profile: dict) -> None:
    con = _conn()
    try:
        con.execute(
            "UPDATE user_profiles SET name=?, firm_name=?, address=?, gstin=?, signature_path=?, "
            "vendor_no=?, agency_details=?, billing_to_json=?, invoice_format=?, next_seq=?, logo_path=? "
            "WHERE id=?",
            (
                profile["name"],
                profile["firm_name"],
                profile["address"],
                profile["gstin"],
                profile.get("signature_path"),
                profile.get("vendor_no", ""),
                profile.get("agency_details", ""),
                profile.get("billing_to_json", "[]"),
                profile.get("invoice_format", "SE/{FY}/KSD/{SEQ}"),
                profile.get("next_seq", 1),
                profile.get("logo_path", ""),
                profile_id
            )
        )
        con.commit()
    finally:
        con.close()

def delete_user_profile(profile_id: int) -> None:
    con = _conn()
    try:
        row = con.execute("SELECT is_active FROM user_profiles WHERE id=?", (profile_id,)).fetchone()
        was_active = row and row[0]
        con.execute("DELETE FROM user_profiles WHERE id=?", (profile_id,))
        if was_active:
            other = con.execute("SELECT id FROM user_profiles LIMIT 1").fetchone()
            if other:
                con.execute("UPDATE user_profiles SET is_active=1 WHERE id=?", (other[0],))
        con.commit()
    finally:
        con.close()

def get_active_profile() -> dict | None:
    con = _conn()
    try:
        row = con.execute(
            "SELECT id, name, firm_name, address, gstin, signature_path, is_active, "
            "vendor_no, agency_details, billing_to_json, invoice_format, next_seq, logo_path "
            "FROM user_profiles WHERE is_active=1"
        ).fetchone()
        if row:
            return {
                "id": row[0],
                "name": row[1],
                "firm_name": row[2],
                "address": row[3],
                "gstin": row[4],
                "signature_path": row[5],
                "is_active": bool(row[6]),
                "vendor_no": row[7] or "",
                "agency_details": row[8] or "",
                "billing_to_json": row[9] or "[]",
                "invoice_format": row[10] or "SE/{FY}/KSD/{SEQ}",
                "next_seq": row[11] or 1,
                "logo_path": row[12] or ""
            }
        return None
    finally:
        con.close()

def set_active_profile(profile_id: int) -> None:
    con = _conn()
    try:
        con.execute("UPDATE user_profiles SET is_active=0")
        con.execute("UPDATE user_profiles SET is_active=1 WHERE id=?", (profile_id,))
        con.commit()
    finally:
        con.close()

def get_next_invoice_seq_and_fy(profile: dict) -> tuple[int, str]:
    from datetime import date, datetime
    today = date.today()
    if today.month >= 4:
        curr_start = today.year
    else:
        curr_start = today.year - 1
    curr_fy = f"{str(curr_start)[2:]}-{str(curr_start+1)[2:]}"
    
    con = _conn()
    try:
        row = con.execute("SELECT invoice_date FROM bills ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            last_date_str = row[0]
            try:
                last_dt = datetime.strptime(last_date_str, "%d-%m-%Y").date()
                if last_dt.month >= 4:
                    last_start = last_dt.year
                else:
                    last_start = last_dt.year - 1
                
                if last_start != curr_start:
                    con.execute("UPDATE user_profiles SET next_seq=1 WHERE id=?", (profile["id"],))
                    con.commit()
                    return 1, curr_fy
            except Exception:
                pass
        return profile.get("next_seq", 1), curr_fy
    finally:
        con.close()

def increment_active_profile_seq() -> None:
    con = _conn()
    try:
        con.execute("UPDATE user_profiles SET next_seq = next_seq + 1 WHERE is_active=1")
        con.commit()
    finally:
        con.close()

def format_invoice_number(template: str, seq: int) -> str:
    from datetime import date
    today = date.today()
    if today.month >= 4:
        start_yr = today.year
    else:
        start_yr = today.year - 1
    fy_short = f"{str(start_yr)[2:]}-{str(start_yr+1)[2:]}"
    fy_long = f"{start_yr}-{start_yr+1}"
    
    formatted = template.replace("{FY}", fy_short).replace("{FY_FULL}", fy_long)
    formatted = formatted.replace("{SEQ}", f"{seq:02d}")
    return formatted


# ─── Projects Metadata (Phase 4) ──────────────────────────────────────────────

def get_projects() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute(
            "SELECT project_name, file_path, project_type, latitude, longitude, estimated_cost, datetime(updated_at, 'localtime'), status, invoice_no, "
            "project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by "
            "FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [
            {
                "name": r[0],
                "path": r[1],
                "type": r[2],
                "lat": r[3],
                "long": r[4],
                "cost": r[5],
                "updated_at": r[6],
                "status": r[7],
                "invoice_no": r[8],
                "project_id": r[9] or "",
                "po_no": r[10] or "",
                "po_date": r[11] or "",
                "vendor_id": r[12] or "",
                "comm_date": r[13] or "",
                "comp_date": r[14] or "",
                "meas_date": r[15] or "",
                "meas_taken_by": r[16] or "",
                "certified_by": r[17] or ""
            }
            for r in rows
        ]
    finally:
        con.close()

def mark_project_invoiced(path: str, invoice_no: str) -> None:
    con = _conn()
    try:
        con.execute(
            "UPDATE projects SET status='Invoiced', invoice_no=?, updated_at=CURRENT_TIMESTAMP WHERE file_path=?",
            (invoice_no, path)
        )
        con.commit()
    finally:
        con.close()

def get_project_status(path: str) -> str:
    con = _conn()
    try:
        row = con.execute("SELECT status FROM projects WHERE file_path=?", (path,)).fetchone()
        return row[0] if row else "Active"
    finally:
        con.close()

def save_project_metadata(name: str, path: str, type: str, lat: str, lon: str, cost: float,
                          project_id: str = "", po_no: str = "", po_date: str = "",
                          vendor_id: str = "", comm_date: str = "", comp_date: str = "",
                          meas_date: str = "", meas_taken_by: str = "", certified_by: str = "") -> None:
    con = _conn()
    try:
        con.execute(
            "INSERT INTO projects (project_name, file_path, project_type, latitude, longitude, estimated_cost, "
            "project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "project_name=excluded.project_name, "
            "project_type=excluded.project_type, "
            "latitude=excluded.latitude, "
            "longitude=excluded.longitude, "
            "estimated_cost=excluded.estimated_cost, "
            "project_id=excluded.project_id, "
            "po_no=excluded.po_no, "
            "po_date=excluded.po_date, "
            "vendor_id=excluded.vendor_id, "
            "comm_date=excluded.comm_date, "
            "comp_date=excluded.comp_date, "
            "meas_date=excluded.meas_date, "
            "meas_taken_by=excluded.meas_taken_by, "
            "certified_by=excluded.certified_by, "
            "updated_at=CURRENT_TIMESTAMP",
            (name, path, type, lat, lon, cost, project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by)
        )
        con.commit()
    finally:
        con.close()

def update_project_billing_metadata(path: str, project_id: str, po_no: str, po_date: str,
                                   vendor_id: str, comm_date: str, comp_date: str,
                                   meas_date: str, meas_taken_by: str, certified_by: str) -> None:
    con = _conn()
    try:
        con.execute(
            "UPDATE projects SET "
            "project_id=?, po_no=?, po_date=?, vendor_id=?, comm_date=?, comp_date=?, meas_date=?, "
            "meas_taken_by=?, certified_by=?, updated_at=CURRENT_TIMESTAMP WHERE file_path=?",
            (project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by, path)
        )
        con.commit()
    finally:
        con.close()

def delete_project_metadata(path: str) -> None:
    con = _conn()
    try:
        con.execute("DELETE FROM projects WHERE file_path=?", (path,))
        con.commit()
    finally:
        con.close()

def rename_project_metadata(old_path: str, new_path: str, new_name: str) -> None:
    con = _conn()
    try:
        con.execute(
            "UPDATE projects SET file_path=?, project_name=?, updated_at=CURRENT_TIMESTAMP WHERE file_path=?",
            (new_path, new_name, old_path)
        )
        con.commit()
    finally:
        con.close()

def save_bill(bill_data: dict) -> bool:
    con = _conn()
    try:
        con.execute(
            "INSERT INTO bills (invoice_no, invoice_date, project_id, po_no, po_date, copy_type, "
            "client_name, client_address, client_gstin, description, labor_total, supervision, "
            "gst, cess, grand_total, project_paths, items_json, meas_taken_by, certified_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(invoice_no) DO UPDATE SET "
            "invoice_date=excluded.invoice_date, "
            "project_id=excluded.project_id, "
            "po_no=excluded.po_no, "
            "po_date=excluded.po_date, "
            "copy_type=excluded.copy_type, "
            "client_name=excluded.client_name, "
            "client_address=excluded.client_address, "
            "client_gstin=excluded.client_gstin, "
            "description=excluded.description, "
            "labor_total=excluded.labor_total, "
            "supervision=excluded.supervision, "
            "gst=excluded.gst, "
            "cess=excluded.cess, "
            "grand_total=excluded.grand_total, "
            "project_paths=excluded.project_paths, "
            "items_json=excluded.items_json, "
            "meas_taken_by=excluded.meas_taken_by, "
            "certified_by=excluded.certified_by",
            (
                bill_data["invoice_no"],
                bill_data["invoice_date"],
                bill_data["project_id"],
                bill_data["po_no"],
                bill_data["po_date"],
                bill_data["copy_type"],
                bill_data["client_name"],
                bill_data["client_address"],
                bill_data.get("client_gstin", ""),
                bill_data.get("description", ""),
                bill_data["labor_total"],
                bill_data.get("supervision", 0.0),  # legacy column; 0 for GST-only invoices
                bill_data["gst"],
                bill_data.get("cess", 0.0),          # legacy column; 0 for GST-only invoices
                bill_data["grand_total"],
                json.dumps(bill_data["project_paths"]),
                json.dumps(bill_data["items"]),
                bill_data.get("meas_taken_by", ""),
                bill_data.get("certified_by", "")
            )
        )
        con.commit()
        return True
    except sqlite3.Error as e:
        print(f"[DB] Error saving bill: {e}")
        return False
    finally:
        con.close()

def get_bills() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute(
            "SELECT id, invoice_no, invoice_date, project_id, po_no, po_date, copy_type, "
            "client_name, client_address, client_gstin, description, labor_total, supervision, "
            "gst, cess, grand_total, project_paths, items_json, datetime(created_at, 'localtime'), "
            "meas_taken_by, certified_by "
            "FROM bills ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                "id": r[0],
                "invoice_no": r[1],
                "invoice_date": r[2],
                "project_id": r[3],
                "po_no": r[4],
                "po_date": r[5],
                "copy_type": r[6],
                "client_name": r[7],
                "client_address": r[8],
                "client_gstin": r[9],
                "description": r[10],
                "labor_total": r[11],
                "supervision": r[12],
                "gst": r[13],
                "cess": r[14],
                "grand_total": r[15],
                "project_paths": json.loads(r[16]),
                "items": json.loads(r[17]),
                "created_at": r[18],
                "meas_taken_by": r[19] if len(r) > 19 else "",
                "certified_by": r[20] if len(r) > 20 else ""
            }
            for r in rows
        ]
    finally:
        con.close()

def delete_bill(bill_id: int) -> None:
    con = _conn()
    try:
        con.execute("DELETE FROM bills WHERE id=?", (bill_id,))
        con.commit()
    finally:
        con.close()

