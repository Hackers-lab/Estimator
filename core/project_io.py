"""
core/project_io.py
==================
Serializes and deserializes project drawing graphs and metadata to/from JSON.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any
from PyQt6.QtCore import Qt, QTimer
from canvas import (
    SmartPole, SmartStructure, SmartSpan, SmartConsumer,
    CanvasSymbol, CanvasTextBox
)

def compile_project_state(
    scene_items: list[Any],
    project_meta: dict,
    bom_overrides: dict,
    current_project_path: str | None = None
) -> dict:
    """Compile canvas scene items and project properties into a serializable dict."""
    state = {
        "version": 5,
        "project_meta": project_meta,
        "overrides": bom_overrides,
        "nodes": [],
        "spans": [],
        "annotations": [],
        "current_project_path": current_project_path
    }
    node_id_by_obj = {}
    for i, item in enumerate(scene_items):
        if isinstance(item, (SmartPole, SmartStructure, SmartConsumer)):
            node_id_by_obj[id(item)] = i
            nd = item.to_dict()
            nd["id"] = i
            state["nodes"].append(nd)

    for item in scene_items:
        if isinstance(item, SmartSpan):
            p1_id = node_id_by_obj.get(id(item.p1))
            p2_id = node_id_by_obj.get(id(item.p2))
            if p1_id is None or p2_id is None:
                continue
            sd = item.to_dict()
            sd.update({"p1_id": p1_id, "p2_id": p2_id})
            state["spans"].append(sd)

    for item in scene_items:
        if isinstance(item, (CanvasSymbol, CanvasTextBox)):
            state["annotations"].append(item.to_dict())

    return state

def save_project_to_file(path: str, state: dict) -> None:
    """Write project state dictionary to JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def load_project_from_file(path: str) -> dict:
    """Read and parse project JSON file from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def sanitize_subject_stem(subject: str, fallback: str = "project") -> str:
    """Sanitize project subject into a safe file path stem."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", (subject or "").strip())
    stem = "_".join(sanitized.split()[:6])
    return stem if stem else fallback
