"""
core/repositories/recipe_repo.py
================================
Repository for steel sections and iron fabrication recipes.
"""
from __future__ import annotations
import json
import sqlite3
from core.repositories.base import get_connection

_sections_cache: dict | None = None

def _invalidate_sections_cache() -> None:
    global _sections_cache
    _sections_cache = None

def get_sections() -> dict[str, dict]:
    """Get all steel sections indexed by code (cached)."""
    global _sections_cache
    if _sections_cache is not None:
        return _sections_cache
    con = get_connection()
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
    con = get_connection()
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
    con = get_connection()
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
    con = get_connection()
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
    con = get_connection()
    try:
        con.execute("DELETE FROM recipes WHERE recipe_key=?", (recipe_key,))
        con.commit()
    finally:
        con.close()
