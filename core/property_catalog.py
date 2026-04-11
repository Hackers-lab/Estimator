from __future__ import annotations

import json
from copy import deepcopy

from app_config import get_data_path

# All canvas object types that support custom properties.
OBJECT_TYPES: list[str] = [
    "SmartPole",
    "SmartStructure",
    "SmartSpan",
    "SmartConsumer",
]

_CATALOG_FILE = get_data_path("property_catalog.json")


def _empty_type_data() -> dict:
    return {"custom_entries": [], "extended_options": {}, "conductor_meta": {}}


_FACTORY: dict = {obj_type: _empty_type_data() for obj_type in OBJECT_TYPES}

current: dict = deepcopy(_FACTORY)


def load() -> None:
    """Load catalog from DB (primary) with JSON as fallback."""
    global current

    # ── Primary: DB ────────────────────────────────────────────────────────
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        merged: dict = deepcopy(_FACTORY)
        for obj_type in OBJECT_TYPES:
            merged[obj_type]["custom_entries"] = _dbg.get_custom_entries(obj_type)
            merged[obj_type]["extended_options"] = _dbg.get_all_extended_options(obj_type)
            if obj_type == "SmartSpan":
                conductors = _dbg.get_user_conductors()
                merged[obj_type]["conductor_meta"] = {
                    c["name"]: {"voltage": c["voltage"]} for c in conductors
                }
        current = merged
        return
    except Exception:
        pass  # DB not ready

    # ── Fallback: JSON file ────────────────────────────────────────────────
    try:
        with open(_CATALOG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        current = deepcopy(_FACTORY)
        return

    merged = deepcopy(_FACTORY)

    for obj_type in OBJECT_TYPES:
        type_data = data.get(obj_type, {})
        if not isinstance(type_data, dict):
            continue

        cleaned_entries: list[dict] = []
        seen_labels: set = set()
        for entry in type_data.get("custom_entries", []):
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", "") or "").strip()
            if not label or label.casefold() in seen_labels:
                continue
            seen_labels.add(label.casefold())
            raw_opts = entry.get("options", [])
            if isinstance(raw_opts, str):
                raw_opts = [raw_opts]
            seen_opts: set = set()
            options: list[str] = []
            for o in raw_opts:
                s = str(o or "").strip()
                if s and s.casefold() not in seen_opts:
                    seen_opts.add(s.casefold())
                    options.append(s)
            cleaned_entries.append({"label": label, "options": options})
        merged[obj_type]["custom_entries"] = cleaned_entries

        raw_ext = type_data.get("extended_options", {})
        extended: dict = {}
        if isinstance(raw_ext, dict):
            for prop_name, opts in raw_ext.items():
                if not isinstance(opts, list):
                    continue
                clean_opts: list[str] = []
                seen_o: set = set()
                for o in opts:
                    s = str(o or "").strip()
                    if s and s.casefold() not in seen_o:
                        seen_o.add(s.casefold())
                        clean_opts.append(s)
                if clean_opts:
                    extended[str(prop_name)] = clean_opts
        merged[obj_type]["extended_options"] = extended

        if obj_type == "SmartSpan":
            raw_meta = type_data.get("conductor_meta", {})
            c_meta: dict = {}
            if isinstance(raw_meta, dict):
                for cname, cm in raw_meta.items():
                    if not isinstance(cm, dict):
                        continue
                    voltage = cm.get("voltage", "Both")
                    if voltage not in ("LT", "HT", "Both"):
                        voltage = "Both"
                    c_meta[str(cname)] = {"voltage": voltage}
            merged[obj_type]["conductor_meta"] = c_meta

    current = merged


def save() -> None:
    """Write current catalog to JSON (legacy backup; DB is primary storage)."""
    try:
        with open(_CATALOG_FILE, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
    except OSError:
        pass


# ── Custom entries ────────────────────────────────────────────────────────────

def get_custom_entries(obj_type: str) -> list[dict]:
    return deepcopy(current.get(obj_type, {}).get("custom_entries", []))


def options_for_custom_label(obj_type: str, label: str | None) -> list[str]:
    if not label or label == "None":
        return []
    target = label.casefold()
    for entry in current.get(obj_type, {}).get("custom_entries", []):
        if str(entry.get("label", "")).casefold() == target:
            return list(entry.get("options", []))
    return []


def add_custom_entry(obj_type: str, label: str, options: list[str] | None = None) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.add_custom_entry(obj_type, label, options)
        current[obj_type]["custom_entries"] = _dbg.get_custom_entries(obj_type)
    except Exception:
        # DB fallback: update in-memory only
        entries = get_custom_entries(obj_type)
        entries.append({"label": label, "options": options or []})
        current[obj_type]["custom_entries"] = entries
    save()


def update_custom_entry(
    obj_type: str, old_label: str, new_label: str, options: list[str] | None = None
) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.update_custom_entry(obj_type, old_label, new_label, options)
        current[obj_type]["custom_entries"] = _dbg.get_custom_entries(obj_type)
    except Exception:
        entries: list[dict] = []
        for entry in get_custom_entries(obj_type):
            if entry["label"].casefold() == old_label.casefold():
                entries.append({"label": new_label, "options": options or []})
            else:
                entries.append(entry)
        current[obj_type]["custom_entries"] = entries
    save()


def delete_custom_entry(obj_type: str, label: str) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.delete_custom_entry(obj_type, label)
        current[obj_type]["custom_entries"] = _dbg.get_custom_entries(obj_type)
    except Exception:
        entries = [
            e for e in get_custom_entries(obj_type)
            if e["label"].casefold() != label.casefold()
        ]
        current[obj_type]["custom_entries"] = entries
    save()


# ── Extended options (user-added values for fixed properties) ─────────────────

def get_extended_options(obj_type: str, prop_name: str) -> list[str]:
    return list(current.get(obj_type, {}).get("extended_options", {}).get(prop_name, []))


def add_extended_option(obj_type: str, prop_name: str, option: str) -> bool:
    """Add a new option value to an existing fixed property. Returns False if duplicate."""
    if obj_type not in OBJECT_TYPES:
        return False
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        result = _dbg.add_extended_option(obj_type, prop_name, option)
        if result:
            current[obj_type]["extended_options"] = _dbg.get_all_extended_options(obj_type)
        return result
    except Exception:
        ext: dict = current[obj_type].setdefault("extended_options", {})
        existing: list[str] = list(ext.get(prop_name, []))
        if option.casefold() in {o.casefold() for o in existing}:
            return False
        existing.append(option)
        ext[prop_name] = existing
        save()
        return True


def remove_extended_option(obj_type: str, prop_name: str, option: str) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.remove_extended_option(obj_type, prop_name, option)
        current[obj_type]["extended_options"] = _dbg.get_all_extended_options(obj_type)
    except Exception:
        ext: dict = current.get(obj_type, {}).get("extended_options", {})
        filtered = [o for o in ext.get(prop_name, []) if o.casefold() != option.casefold()]
        if filtered:
            ext[prop_name] = filtered
        else:
            ext.pop(prop_name, None)
    save()


# ── User conductor metadata (SmartSpan only) ──────────────────────────────────

def get_user_conductors() -> list[dict]:
    """Return [{name, voltage}] for all user-added conductors."""
    meta = current.get("SmartSpan", {}).get("conductor_meta", {})
    return [{"name": n, "voltage": m.get("voltage", "Both")} for n, m in meta.items()]


def get_conductor_meta(conductor_name: str) -> dict:
    """Return {voltage} for a user-added conductor, or {} if not found."""
    return dict(current.get("SmartSpan", {}).get("conductor_meta", {}).get(conductor_name, {}))


def set_conductor_meta(conductor_name: str, voltage: str) -> None:
    """Store or update the voltage affinity for a user-added conductor."""
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.set_conductor_meta(conductor_name, voltage)
    except Exception:
        pass
    current["SmartSpan"].setdefault("conductor_meta", {})[conductor_name] = {"voltage": voltage}
    save()


def delete_user_conductor(conductor_name: str) -> None:
    """Remove a user-added conductor and ALL its associated catalog data."""
    try:
        from core import db_gateway as _dbg  # noqa: PLC0415
        _dbg.delete_user_conductor(conductor_name)
        current["SmartSpan"]["extended_options"] = _dbg.get_all_extended_options("SmartSpan")
        conductors = _dbg.get_user_conductors()
        current["SmartSpan"]["conductor_meta"] = {
            c["name"]: {"voltage": c["voltage"]} for c in conductors
        }
    except Exception:
        remove_extended_option("SmartSpan", "conductor", conductor_name)
        current.get("SmartSpan", {}).get("conductor_meta", {}).pop(conductor_name, None)
        ext = current.get("SmartSpan", {}).get("extended_options", {})
        for key in [f"conductor_size__lt_{conductor_name}",
                    f"conductor_size__ht_{conductor_name}"]:
            ext.pop(key, None)
    save()


# ── Build helpers for Ruleset Manager ─────────────────────────────────────────

def build_property_data(base_property_data: dict = None) -> dict:
    """Return a deep copy of PROPERTY_DATA using the global PropertyRegistry."""
    from core.property_registry import get_registry
    return get_registry().get_all_property_data()


def build_sim_defaults(base_sim_defaults: dict = None) -> dict:
    """Return a deep copy of SIM_DEFAULTS using the global PropertyRegistry."""
    from core.property_registry import get_registry
    return get_registry().get_all_sim_defaults()


def usage_details(rules: list[dict], obj_type: str | None = None) -> dict[str, list[str]]:
    """Return {label: [rule_names]} for custom labels of the given obj_type (or all types)."""
    types_to_check = (
        [obj_type] if obj_type and obj_type in OBJECT_TYPES else OBJECT_TYPES
    )
    all_labels: list[str] = []
    for ot in types_to_check:
        for entry in current.get(ot, {}).get("custom_entries", []):
            all_labels.append(entry["label"])

    usage: dict[str, list[str]] = {}
    for label in all_labels:
        hits: list[str] = []
        for index, rule in enumerate(rules, start=1):
            condition = str(rule.get("condition", "") or "")
            formula = str(rule.get("formula", "") or "")
            haystack = f"{condition}\n{formula}"
            if label in haystack:
                rule_name = str(rule.get("item_name", "") or f"Rule {index}")
                hits.append(rule_name)
        usage[label] = hits

    return usage


load()


# All canvas object types that support custom properties.
OBJECT_TYPES: list[str] = [
    "SmartPole",
    "SmartStructure",
    "SmartSpan",
    "SmartConsumer",
]

_CATALOG_FILE = get_data_path("property_catalog.json")


def _empty_type_data() -> dict:
    return {"custom_entries": [], "extended_options": {}, "conductor_meta": {}}


_FACTORY: dict = {obj_type: _empty_type_data() for obj_type in OBJECT_TYPES}

current: dict = deepcopy(_FACTORY)


def _clean_entry(entry: dict) -> dict | None:
    label = str(entry.get("label", "") or "").strip()
    if not label or label.lower() == "none":
        return None

    raw_options = entry.get("options", [])
    if isinstance(raw_options, str):
        raw_options = [raw_options]

    seen: set = set()
    options: list[str] = []
    for option in raw_options:
        clean = str(option or "").strip()
        if not clean or clean.lower() == "none":
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        options.append(clean)

    return {"label": label, "options": options}


def load() -> None:
    global current
    try:
        with open(_CATALOG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        current = deepcopy(_FACTORY)
        return

    merged: dict = deepcopy(_FACTORY)

    for obj_type in OBJECT_TYPES:
        type_data = data.get(obj_type, {})
        if not isinstance(type_data, dict):
            continue

        # Custom entries
        cleaned_entries: list[dict] = []
        seen_labels: set = set()
        for entry in type_data.get("custom_entries", []):
            if not isinstance(entry, dict):
                continue
            cleaned = _clean_entry(entry)
            if cleaned is None:
                continue
            key = cleaned["label"].casefold()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            cleaned_entries.append(cleaned)
        merged[obj_type]["custom_entries"] = cleaned_entries

        # Extended options (user-added values for fixed properties)
        raw_ext = type_data.get("extended_options", {})
        extended: dict = {}
        if isinstance(raw_ext, dict):
            for prop_name, opts in raw_ext.items():
                if not isinstance(opts, list):
                    continue
                clean_opts: list[str] = []
                seen_opts: set = set()
                for opt in opts:
                    s = str(opt or "").strip()
                    if s and s.casefold() not in seen_opts:
                        seen_opts.add(s.casefold())
                        clean_opts.append(s)
                if clean_opts:
                    extended[str(prop_name)] = clean_opts
        merged[obj_type]["extended_options"] = extended

        # Conductor metadata (SmartSpan only) — stores voltage affinity of user-added conductors
        if obj_type == "SmartSpan":
            raw_meta = type_data.get("conductor_meta", {})
            c_meta: dict = {}
            if isinstance(raw_meta, dict):
                for cname, cm in raw_meta.items():
                    if not isinstance(cm, dict):
                        continue
                    voltage = cm.get("voltage", "Both")
                    if voltage not in ("LT", "HT", "Both"):
                        voltage = "Both"
                    c_meta[str(cname)] = {"voltage": voltage}
            merged[obj_type]["conductor_meta"] = c_meta

    current = merged


def save() -> None:
    with open(_CATALOG_FILE, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2)


# ── Custom entries ────────────────────────────────────────────────────────────

def get_custom_entries(obj_type: str) -> list[dict]:
    return deepcopy(current.get(obj_type, {}).get("custom_entries", []))


def options_for_custom_label(obj_type: str, label: str | None) -> list[str]:
    if not label or label == "None":
        return []
    target = label.casefold()
    for entry in current.get(obj_type, {}).get("custom_entries", []):
        if str(entry.get("label", "")).casefold() == target:
            return list(entry.get("options", []))
    return []


def add_custom_entry(obj_type: str, label: str, options: list[str] | None = None) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    entries = get_custom_entries(obj_type)
    entries.append({"label": label, "options": options or []})
    current[obj_type]["custom_entries"] = entries
    save()


def update_custom_entry(
    obj_type: str, old_label: str, new_label: str, options: list[str] | None = None
) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    entries: list[dict] = []
    for entry in get_custom_entries(obj_type):
        if entry["label"].casefold() == old_label.casefold():
            entries.append({"label": new_label, "options": options or []})
        else:
            entries.append(entry)
    current[obj_type]["custom_entries"] = entries
    save()


def delete_custom_entry(obj_type: str, label: str) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    entries = [
        e for e in get_custom_entries(obj_type)
        if e["label"].casefold() != label.casefold()
    ]
    current[obj_type]["custom_entries"] = entries
    save()


# ── Extended options (user-added values for fixed properties) ─────────────────

def get_extended_options(obj_type: str, prop_name: str) -> list[str]:
    return list(current.get(obj_type, {}).get("extended_options", {}).get(prop_name, []))


def add_extended_option(obj_type: str, prop_name: str, option: str) -> bool:
    """Add a new option value to an existing fixed property. Returns False if duplicate."""
    if obj_type not in OBJECT_TYPES:
        return False
    ext: dict = current[obj_type].setdefault("extended_options", {})
    existing: list[str] = list(ext.get(prop_name, []))
    if option.casefold() in {o.casefold() for o in existing}:
        return False
    existing.append(option)
    ext[prop_name] = existing
    save()
    return True


def remove_extended_option(obj_type: str, prop_name: str, option: str) -> None:
    if obj_type not in OBJECT_TYPES:
        return
    ext: dict = current.get(obj_type, {}).get("extended_options", {})
    filtered = [o for o in ext.get(prop_name, []) if o.casefold() != option.casefold()]
    if filtered:
        ext[prop_name] = filtered
    else:
        ext.pop(prop_name, None)
    save()


# ── User conductor metadata (SmartSpan only) ──────────────────────────────────

def get_user_conductors() -> list[dict]:
    """Return [{name, voltage}] for all user-added conductors."""
    meta = current.get("SmartSpan", {}).get("conductor_meta", {})
    return [{"name": n, "voltage": m.get("voltage", "Both")} for n, m in meta.items()]


def get_conductor_meta(conductor_name: str) -> dict:
    """Return {voltage} for a user-added conductor, or {} if not found."""
    return dict(current.get("SmartSpan", {}).get("conductor_meta", {}).get(conductor_name, {}))


def set_conductor_meta(conductor_name: str, voltage: str) -> None:
    """Store or update the voltage affinity for a user-added conductor."""
    current["SmartSpan"].setdefault("conductor_meta", {})[conductor_name] = {"voltage": voltage}
    save()


def delete_user_conductor(conductor_name: str) -> None:
    """Remove a user-added conductor and ALL its associated catalog data."""
    remove_extended_option("SmartSpan", "conductor", conductor_name)
    current.get("SmartSpan", {}).get("conductor_meta", {}).pop(conductor_name, None)
    ext = current.get("SmartSpan", {}).get("extended_options", {})
    for key in [f"conductor_size__lt_{conductor_name}",
                f"conductor_size__ht_{conductor_name}"]:
        ext.pop(key, None)
    save()


# ── Build helpers for Ruleset Manager ─────────────────────────────────────────

def build_property_data(base_property_data: dict) -> dict:
    """Return a deep copy of PROPERTY_DATA with extended + custom entries injected per object type."""
    merged = deepcopy(base_property_data)
    for obj_type in OBJECT_TYPES:
        if obj_type not in merged:
            continue
        type_cur = current.get(obj_type, {})

        # Merge user-added options into existing list-type fixed properties
        for prop_name, extra_opts in type_cur.get("extended_options", {}).items():
            if prop_name in merged[obj_type] and isinstance(merged[obj_type][prop_name], list):
                existing = list(merged[obj_type][prop_name])
                existing_fold = {str(o).casefold() for o in existing}
                for opt in extra_opts:
                    if opt.casefold() not in existing_fold:
                        existing.append(opt)
                        existing_fold.add(opt.casefold())
                merged[obj_type][prop_name] = existing

        # Inject custom entries as new rule-accessible properties
        for entry in type_cur.get("custom_entries", []):
            label = entry["label"]
            options = entry.get("options", [])
            merged[obj_type][label] = (["None"] + options) if options else "text"

    return merged


def build_sim_defaults(base_sim_defaults: dict) -> dict:
    """Return a deep copy of SIM_DEFAULTS with extended + custom entries injected per object type."""
    merged = deepcopy(base_sim_defaults)
    for obj_type in OBJECT_TYPES:
        if obj_type not in merged:
            continue
        type_cur = current.get(obj_type, {})

        # Merge extended options into existing combo sim entries
        for prop_name, extra_opts in type_cur.get("extended_options", {}).items():
            if prop_name in merged[obj_type]:
                sim_entry = merged[obj_type][prop_name]
                if isinstance(sim_entry, tuple) and sim_entry[0] == "combo":
                    wtype, existing_opts, default = sim_entry
                    existing_fold = {str(o).casefold() for o in existing_opts}
                    new_opts = list(existing_opts)
                    for opt in extra_opts:
                        if opt.casefold() not in existing_fold:
                            new_opts.append(opt)
                            existing_fold.add(opt.casefold())
                    merged[obj_type][prop_name] = (wtype, new_opts, default)

        # Inject custom entries as new sim combo entries
        for entry in type_cur.get("custom_entries", []):
            label = entry["label"]
            options = entry.get("options", [])
            opts_list = ["None"] + options if options else ["None"]
            merged[obj_type][label] = ("combo", opts_list, "None")

    return merged


def usage_details(rules: list[dict], obj_type: str | None = None) -> dict[str, list[str]]:
    """Return {label: [rule_names]} for custom labels of the given obj_type (or all types)."""
    types_to_check = (
        [obj_type] if obj_type and obj_type in OBJECT_TYPES else OBJECT_TYPES
    )
    all_labels: list[str] = []
    for ot in types_to_check:
        for entry in current.get(ot, {}).get("custom_entries", []):
            all_labels.append(entry["label"])

    usage: dict[str, list[str]] = {}
    for label in all_labels:
        hits: list[str] = []
        for index, rule in enumerate(rules, start=1):
            condition = str(rule.get("condition", "") or "")
            formula = str(rule.get("formula", "") or "")
            haystack = f"{condition}\n{formula}"
            if label in haystack:
                rule_name = str(rule.get("item_name", "") or f"Rule {index}")
                hits.append(rule_name)
        usage[label] = hits

    return usage


load()