from __future__ import annotations

from core import db_gateway


def make_context_key(parts: dict[str, str] | None = None) -> str:
    if not parts:
        return ""
    rows: list[str] = []
    for key in sorted(parts):
        rows.append(f"{key}={parts[key]}")
    return "|".join(rows)


def ensure_default(
    object_type: str,
    prop_name: str,
    option_val: str,
    default_color: str,
    context: dict[str, str] | None = None,
) -> None:
    db_gateway.upsert_option_color_default(
        object_type,
        prop_name,
        option_val,
        default_color,
        make_context_key(context),
    )


def set_user(
    object_type: str,
    prop_name: str,
    option_val: str,
    user_color: str,
    default_color: str,
    context: dict[str, str] | None = None,
) -> None:
    db_gateway.set_option_user_color(
        object_type,
        prop_name,
        option_val,
        user_color,
        make_context_key(context),
        default_color,
    )


def reset_user(
    object_type: str,
    prop_name: str,
    option_val: str,
    context: dict[str, str] | None = None,
) -> None:
    db_gateway.reset_option_user_color(
        object_type,
        prop_name,
        option_val,
        make_context_key(context),
    )


def resolve(
    object_type: str,
    prop_name: str,
    option_val: str,
    fallback_color: str,
    context: dict[str, str] | None = None,
) -> str:
    return db_gateway.resolve_option_color(
        object_type,
        prop_name,
        option_val,
        make_context_key(context),
        fallback_color,
    )


def get_record(
    object_type: str,
    prop_name: str,
    option_val: str,
    context: dict[str, str] | None = None,
) -> dict:
    return db_gateway.get_option_color_record(
        object_type,
        prop_name,
        option_val,
        make_context_key(context),
    )
