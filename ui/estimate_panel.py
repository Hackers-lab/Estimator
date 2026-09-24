"""
ui/estimate_panel.py
====================
Provides estimation calculation helpers, cost escalations, and formatting
for the Live Estimate summary table and transparency dialogs.
"""
from __future__ import annotations
import math
import re
from datetime import datetime
from typing import Any

def format_quantity(qty: float, unit: str) -> str:
    """Format quantity as integer for discrete units (Nos/Set/etc), else 3 decimals."""
    count_units = {
        "nos", "no.", "no", "set", "sets", "pair", "pairs",
        "pcs", "piece", "each", "ea", "day", "days", "job", "ls"
    }
    if unit.lower().strip().rstrip(".") in count_units:
        return str(int(round(qty)))
    return f"{qty:.3f}"

def calculate_estimate_totals(
    live_bom_data: list[dict[str, Any]],
    sup_rate: float = 0.10,
    base_year: int = 2026,
    now: datetime | None = None
) -> dict[str, Any]:
    """
    Compute base material, escalated material, sundries, supervision, GST,
    cess, and grand total.
    """
    if now is None:
        now = datetime.now()

    mat_base = sum(x["amt"] for x in live_bom_data if x["type"] == "Material")
    lab_sub = sum(x["amt"] for x in live_bom_data if x["type"] == "Labor")

    fy_start = now.year if now.month >= 4 else now.year - 1

    escalations = []
    cur = mat_base
    for yr in range(base_year + 1, fy_start + 1):
        esc = cur * 0.05
        escalations.append((f"{str(yr)[-2:]}-{str(yr+1)[-2:]}", esc))
        cur += esc

    sun = cur * 0.05
    mat_sub = cur + sun
    sup = (mat_sub + lab_sub) * sup_rate
    gst = lab_sub * 0.18
    cess = (mat_sub + lab_sub + sup) * 0.01
    final = mat_sub + lab_sub + sup + gst + cess

    return {
        "mat_base": mat_base,
        "lab_sub": lab_sub,
        "escalations": escalations,
        "sundries": sun,
        "mat_sub": mat_sub,
        "supervision": sup,
        "gst": gst,
        "cess": cess,
        "final_total": final
    }

def humanize_condition(cond: str) -> str:
    """Convert raw python condition strings into readable English text."""
    if not cond or cond.strip().lower() in ("true", ""):
        return "Applied automatically to all instances"

    clauses = re.split(r'\s+(?:and|&)\s+', cond, flags=re.IGNORECASE)
    parts = []

    phrase_map = {
        ("is_existing", "False"): "New",
        ("is_existing", "True"): "Existing",
        ("is_new", "True"): "New",
        ("is_new", "False"): "Existing",
        ("is_existing_span", "False"): "New line",
        ("is_existing_span", "True"): "Existing line",
        ("is_new_span", "True"): "New line",
        ("is_new_span", "False"): "Existing line",
        ("is_distribution_span", "True"): "Distribution line",
        ("is_distribution_span", "False"): "Service connection",
        ("is_service_drop", "True"): "Service connection",
        ("is_service_drop", "False"): "Distribution line",
        ("is_lt_span", "True"): "LT (Low Tension)",
        ("is_lt_span", "False"): "HT (High Tension)",
        ("is_ht_span", "True"): "HT (High Tension)",
        ("is_ht_span", "False"): "LT (Low Tension)",
        ("has_cg", "True"): "with Cradle Guard",
        ("has_cg", "False"): "without Cradle Guard",
        ("has_extension", "True"): "with Extension",
        ("has_extension", "False"): "Standard (no extension)",
        ("use_uh", "True"): "Underground/UH Project",
        ("use_uh", "False"): "Standard Material",
        ("agency_supply", "True"): "Agency Supply",
        ("agency_supply", "False"): "WBSEDCL / Dept Supply",
        ("consider_cable", "True"): "Include Cable",
        ("consider_cable", "False"): "Exclude Cable",
        ("ab_needs_dead_end", "True"): "Dead-End Pole",
        ("ab_needs_suspension", "True"): "Intermediate Suspension",
    }

    for cl in clauses:
        cl = cl.strip().strip("()")
        if not cl:
            continue

        m_not = re.match(r'^not\s+(\w+)$', cl, re.IGNORECASE)
        if m_not:
            k = m_not.group(1)
            parts.append(phrase_map.get((k, "False"), f"Not {k}"))
            continue

        m_op = re.match(r"^(\w+)\s*(==|!=|>=|<=|>|<)\s*['\"]?(.+?)['\"]?$", cl)
        if m_op:
            k, op, v = m_op.group(1), m_op.group(2), m_op.group(3)
            mapped = phrase_map.get((k, v))
            if mapped:
                parts.append(mapped)
            else:
                parts.append(f"{k} {op} {v}")
        else:
            parts.append(cl)

    return " • ".join(parts) if parts else cond

def humanize_formula(formula: str, recipe_item_desc: str = "") -> str:
    """Convert formula / recipe expressions into clean English."""
    if not formula:
        return "1 unit"
    s = str(formula).strip()
    if s.startswith("recipe:"):
        m = re.match(r"^recipe:([A-Z0-9_]+)(?:\*([0-9.]+))?\s*→\s*(.+)$", s)
        if m:
            rkey, mult, sec = m.group(1), m.group(2), m.group(3)
            rname = rkey.replace("POLE_", "").replace("_IRON", "").replace("_", " ").title()
            mult_txt = f" × {mult}" if mult and mult != "1" else ""
            if recipe_item_desc:
                return f"{recipe_item_desc}{mult_txt} ({sec})"
            return f"{rname} Recipe{mult_txt} ({sec})"
        if recipe_item_desc:
            return recipe_item_desc
        return s.replace("recipe:", "Recipe: ")
    elif s == "1":
        return "1 per object"
    elif s.isdigit():
        return f"{s} per object"
    return s


def show_bom_provenance_dialog(
    parent_widget,
    item: dict[str, Any],
    on_refresh_callback=None,
    canvas_items=None
) -> None:
    """Show modal breakdown dialog of where a BOM item's quantities came from."""
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
        QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
    )
    from PyQt6.QtCore import Qt

    contribs = item.get("provenance", []) or []

    dlg = QDialog(parent_widget)
    dlg.setWindowTitle("Estimate Line Breakdown")
    dlg.resize(840, 420)
    lay = QVBoxLayout(dlg)
    lay.setSpacing(10)
    lay.setContentsMargins(16, 16, 16, 16)

    hdr_frame = QFrame()
    hdr_frame.setStyleSheet("background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px;")
    hdr_lay = QVBoxLayout(hdr_frame)
    hdr_lay.setContentsMargins(0, 0, 0, 0)
    hdr_lay.setSpacing(4)

    qty_str = format_quantity(item["qty"], item.get("unit", ""))
    hdr = QLabel(
        f"<span style='font-size:14px; font-weight:bold; color:#0f172a;'>{item['name']}</span> &nbsp; "
        f"<span style='font-size:11px; color:#64748b;'>({item['type']}, Code: {item['code']})</span><br>"
        f"Line Total: <b style='color:#0369a1;'>{qty_str} {item['unit']}</b>"
        f" &nbsp;&nbsp;|&nbsp;&nbsp; Cost: <b style='color:#15803d;'>Rs. {item['amt']:,.2f}</b>"
    )
    hdr.setWordWrap(True)
    hdr_lay.addWidget(hdr)
    lay.addWidget(hdr_frame)

    if not contribs:
        note = QLabel(
            "This line was added manually or as an override — it is not "
            "generated by a rule, so there is no automatic breakdown to show."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b; padding:16px; font-style:italic;")
        lay.addWidget(note)
    else:
        top_bar = QHBoxLayout()
        lbl_title = QLabel(f"<b>Breakdown of Contributions ({len(contribs)}):</b>")
        lbl_title.setStyleSheet("font-size:12px; color:#334155;")
        top_bar.addWidget(lbl_title)
        top_bar.addStretch()

        toggle_raw_btn = QPushButton("Show Technical Conditions")
        toggle_raw_btn.setCheckable(True)
        toggle_raw_btn.setStyleSheet("""
            QPushButton { font-size:11px; padding:3px 10px; border:1px solid #cbd5e1; border-radius:4px; background:#ffffff; color:#475569; }
            QPushButton:checked { background:#e2e8f0; color:#0f172a; font-weight:bold; }
        """)
        top_bar.addWidget(toggle_raw_btn)
        lay.addLayout(top_bar)

        tbl = QTableWidget(len(contribs), 6)
        tbl.setHorizontalHeaderLabels(
            ["Applied To", "Rule #", "Why was this added? (Condition)", "Formula / Recipe", "Qty", "Action"]
        )
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setStyleSheet("""
            QTableWidget { background:#ffffff; border:1px solid #cbd5e1; border-radius:4px; font-size:11px; }
            QHeaderView::section { background:#f1f5f9; font-weight:bold; color:#334155; padding:5px; border:none; border-bottom:1px solid #cbd5e1; }
        """)
        hh = tbl.horizontalHeader()
        if hh is not None:
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        def _refresh_table_conditions(show_raw: bool):
            for r, c in enumerate(contribs):
                cond_str = c.get("condition", "")
                disp_cond = cond_str if show_raw else humanize_condition(cond_str)
                cond_item = QTableWidgetItem(disp_cond)
                cond_item.setToolTip(cond_str)
                tbl.setItem(r, 2, cond_item)

        for r, c in enumerate(contribs):
            obj = c.get("object_label") or c.get("object_type", "")
            rule_id = str(c.get("rule_id", "") or "")
            raw_formula = str(c.get("formula", "") or "")
            rec_desc = c.get("recipe_item_desc", "")
            disp_formula = humanize_formula(raw_formula, rec_desc)
            c_qty_str = format_quantity(round(float(c.get("qty", 0)), 3), item.get("unit", ""))

            tbl.setItem(r, 0, QTableWidgetItem(obj))
            tbl.setItem(r, 1, QTableWidgetItem(f"Rule #{rule_id}" if rule_id else "Dynamic"))
            formula_item = QTableWidgetItem(disp_formula)
            if rec_desc:
                formula_item.setToolTip(f"{rec_desc} ({raw_formula})")
            tbl.setItem(r, 3, formula_item)
            tbl.setItem(r, 4, QTableWidgetItem(c_qty_str))

            # Col 5: Action Button to jump to Rule / Recipe Editor
            action_btn = QPushButton("✏️ Edit")
            action_btn.setToolTip("Open in Editor to customize or tweak")
            action_btn.setStyleSheet("""
                QPushButton {
                    background:#f0f9ff; color:#0284c7; border:1px solid #bae6fd;
                    border-radius:3px; padding:2px 8px; font-weight:bold; font-size:10px;
                }
                QPushButton:hover { background:#e0f2fe; color:#0369a1; }
            """)

            is_recipe_action = raw_formula.startswith("recipe:") or "recipe" in raw_formula.lower() or bool(c.get("recipe_key"))
            recipe_key_match = c.get("recipe_key")
            if not recipe_key_match and is_recipe_action:
                m = re.match(r"^recipe:([A-Z0-9_]+)", raw_formula)
                if m:
                    recipe_key_match = m.group(1)

            def make_handler(rid=rule_id, rkey=recipe_key_match, is_rec=is_recipe_action):
                def handler():
                    dlg.accept()
                    if is_rec and rkey:
                        from ui.dialogs.recipe_manager import RecipeManagerDialog
                        rm_dlg = RecipeManagerDialog(parent_widget, initial_recipe_key=rkey)
                        if rm_dlg.exec() == QDialog.DialogCode.Accepted and on_refresh_callback:
                            on_refresh_callback()
                    elif rid and rid.isdigit():
                        from ui.dialogs.ruleset_mgr import RulesetManagerDialog
                        rule_dlg = RulesetManagerDialog(
                            parent_widget,
                            canvas_objects=canvas_items if canvas_items is not None else [],
                            initial_rule_id=rid
                        )
                        if rule_dlg.exec() == QDialog.DialogCode.Accepted and on_refresh_callback:
                            on_refresh_callback()
                    elif is_rec:
                        from ui.dialogs.recipe_manager import RecipeManagerDialog
                        rm_dlg = RecipeManagerDialog(parent_widget)
                        if rm_dlg.exec() == QDialog.DialogCode.Accepted and on_refresh_callback:
                            on_refresh_callback()
                    elif rid:
                        from ui.dialogs.ruleset_mgr import RulesetManagerDialog
                        rule_dlg = RulesetManagerDialog(
                            parent_widget,
                            canvas_objects=canvas_items if canvas_items is not None else [],
                            initial_rule_id=rid
                        )
                        if rule_dlg.exec() == QDialog.DialogCode.Accepted and on_refresh_callback:
                            on_refresh_callback()
                return handler

            action_btn.clicked.connect(make_handler())
            tbl.setCellWidget(r, 5, action_btn)

        _refresh_table_conditions(False)
        toggle_raw_btn.toggled.connect(_refresh_table_conditions)

        tbl.setColumnWidth(0, 130)
        tbl.setColumnWidth(1, 65)
        tbl.setColumnWidth(3, 190)
        tbl.setColumnWidth(4, 60)
        tbl.setColumnWidth(5, 75)
        lay.addWidget(tbl)

        foot = QLabel(f"Sum of {len(contribs)} breakdown item(s) matches the line total above.")
        foot.setStyleSheet("color:#64748b; font-size:11px; padding:2px;")
        lay.addWidget(foot)

    bot_lay = QHBoxLayout()
    bot_lay.addStretch()
    btn = QPushButton("Close")
    btn.clicked.connect(dlg.accept)
    btn.setStyleSheet("padding:6px 24px; font-weight:bold; background:#0284c7; color:white; border-radius:4px;")
    bot_lay.addWidget(btn)
    lay.addLayout(bot_lay)
    dlg.exec()


