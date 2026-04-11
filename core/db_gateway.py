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

import sqlite3
from core.database import DB_PATH


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


# ─── Rules ────────────────────────────────────────────────────────────────────

def get_rules(object_type: str | None = None, enabled_only: bool = True) -> list[dict]:
    """Return list of rule dicts, ordered by sort_order.

    Each dict has keys: id, object, condition, formula, type, item_code, item_name.
    """
    con = _conn()
    try:
        cur = con.cursor()
        base = (
            "SELECT id, object_type, condition, formula, type, item_code, item_name "
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
        return [
            {
                "id":        r[0],
                "object":    r[1],
                "condition": r[2],
                "formula":   r[3],
                "type":      r[4],
                "item_code": r[5],
                "item_name": r[6],
            }
            for r in rows
        ]
    finally:
        con.close()


def save_rules(rules: list[dict]) -> None:
    """Replace ALL rules in DB with the given list.

    Each dict must have: object, condition, formula, type, item_code, item_name.
    Existing enabled flags and IDs are discarded — use for full save from editor.
    """
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM rules")
        for i, r in enumerate(rules):
            cur.execute(
                "INSERT INTO rules "
                "(object_type, condition, formula, type, item_code, item_name, enabled, sort_order) "
                "VALUES (?,?,?,?,?,?,1,?)",
                (
                    r.get("object", ""),
                    r.get("condition", "True"),
                    r.get("formula", "1"),
                    r.get("type", "Material"),
                    r.get("item_code", ""),
                    r.get("item_name", ""),
                    i,
                ),
            )
        con.commit()
    finally:
        con.close()


def add_rule(rule: dict) -> int:
    """Insert a single rule. Returns the new row id."""
    con = _conn()
    try:
        cur = con.cursor()
        cur.execute("SELECT COALESCE(MAX(sort_order),0) FROM rules")
        max_sort = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO rules "
            "(object_type, condition, formula, type, item_code, item_name, enabled, sort_order) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (
                rule.get("object", ""),
                rule.get("condition", "True"),
                rule.get("formula", "1"),
                rule.get("type", "Material"),
                rule.get("item_code", ""),
                rule.get("item_name", ""),
                max_sort + 1,
            ),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def update_rule(rule_id: int, rule: dict) -> None:
    """Update fields of an existing rule by id."""
    con = _conn()
    try:
        con.execute(
            "UPDATE rules SET object_type=?, condition=?, formula=?, type=?, "
            "item_code=?, item_name=? WHERE id=?",
            (
                rule.get("object", ""),
                rule.get("condition", "True"),
                rule.get("formula", "1"),
                rule.get("type", "Material"),
                rule.get("item_code", ""),
                rule.get("item_name", ""),
                rule_id,
            ),
        )
        con.commit()
    finally:
        con.close()


def delete_rule(rule_id: int) -> None:
    """Hard-delete a rule by id."""
    con = _conn()
    try:
        con.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        con.commit()
    finally:
        con.close()


def toggle_rule(rule_id: int, enabled: bool) -> None:
    """Enable or disable a rule without deleting it."""
    con = _conn()
    try:
        con.execute("UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
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
    """Return height strings like ['8MTR', '9.5MTR'] for a pole_type2."""
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


def add_height_option(pole_type2: str, height_val: float) -> bool:
    """Add a new height for a pole_type2. Returns False if already exists."""
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


def remove_height_option(pole_type2: str, height_val: float) -> None:
    """Remove a height option for a pole_type2."""
    con = _conn()
    try:
        con.execute(
            "DELETE FROM height_options WHERE pole_type2=? AND height_val=?",
            (pole_type2, height_val),
        )
        con.commit()
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
            opts = cur.execute(
                "SELECT option_val FROM property_options WHERE property_id=? ORDER BY sort_order, id",
                (prop_id,),
            ).fetchall()
            # Merge extended (user) options
            ext = cur.execute(
                "SELECT option_val FROM extended_options "
                "WHERE object_type=? AND prop_name=? ORDER BY sort_order, id",
                (object_type, prop_name),
            ).fetchall()
            options = [r[0] for r in opts]
            seen = {o.casefold() for o in options}
            for (ev,) in ext:
                if ev.casefold() not in seen:
                    options.append(ev)
                    seen.add(ev.casefold())
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
