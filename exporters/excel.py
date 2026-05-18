"""
excel_exporter.py
=================
ExcelExporter class — all Excel generation logic extracted from app.py.

Usage::

    from excel_exporter import ExcelExporter
    ExcelExporter(app_instance).generate()
"""

from __future__ import annotations

import json as _json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from canvas import SmartPole, SmartStructure, SmartSpan, SmartConsumer
from app_config import get_data_path

if TYPE_CHECKING:
    import openpyxl as _openpyxl_t
    from app import EstimateApp


def _xl():
    """Lazy-load openpyxl and its styles. Cached after first call."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    return openpyxl, Font, Alignment, PatternFill, Border, Side


class ExcelExporter:
    """Handles all Excel estimate generation for the ERP Estimate Generator."""

    # Unit weights for iron sections (kg/m).  0 = wire (formula gives MT directly).
    _IRON_UNIT_WEIGHTS: dict[str, float] = {
        "0102010611": 6.8,    # CH_75X40
        "0102010911": 9.8,    # CH_100X50
        "0101011311": 5.8,    # ANG_65X65X6
        "0101011011": 4.5,    # ANG_50X50X6
        "0103011511": 3.1,    # FLAT_65X6
        "0503010811": 0,      # GI Wire 5mm (qty already MT)
        "0503010711": 0,      # GI Wire 4mm (qty already MT)
    }

    def __init__(self, app: "EstimateApp") -> None:
        self._app = app

    # ── Main entry point ─────────────────────────────────────────────────────

    def generate(
        self,
        output_path: str | None = None,
        initial_dir: str | None = None,
        show_success: bool = True,
    ) -> str | None:
        app = self._app
        m   = app.project_meta
        subject = m.get("subject", "ERP_Estimate")
        safe    = "".join(c for c in subject if c not in r'\/*?:"<>|')
        default = f"{safe}_Estimate.xlsx" if safe else "ERP_Estimate.xlsx"

        filename = output_path
        if not filename:
            start_path = default
            if initial_dir:
                start_path = os.path.join(initial_dir.rstrip('/\\'), default)
            filename, _ = QFileDialog.getSaveFileName(
                app, "Export ERP Estimate", start_path, "Excel Files (*.xlsx)"
            )
            if not filename:
                return None

        openpyxl, *_ = _xl()
        wb = openpyxl.Workbook()
        self._write_estimate_sheet(wb, m)
        self._write_iron_breakup_sheet(wb)
        wb.save(filename)
        if show_success:
            msg = QMessageBox(app)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Excel Saved")
            msg.setText(f"Excel saved to:\n{filename}")
            open_file_btn = msg.addButton("Open File", QMessageBox.ButtonRole.ActionRole)
            open_folder_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Close)
            msg.exec()
            if msg.clickedButton() == open_file_btn:
                try:
                    os.startfile(filename)  # type: ignore[attr-defined]
                except Exception as exc:
                    QMessageBox.warning(app, "Open File Failed", f"Could not open file.\n\n{exc}")
            elif msg.clickedButton() == open_folder_btn:
                try:
                    os.startfile(os.path.dirname(filename))  # type: ignore[attr-defined]
                except Exception as exc:
                    QMessageBox.warning(app, "Open Folder Failed", f"Could not open folder.\n\n{exc}")
        return filename

    def _write_estimate_sheet(self, wb: Any, m: dict) -> None:
        openpyxl, Font, Alignment, PatternFill, Border, Side = _xl()
        app = self._app
        escalation_count = len(getattr(app, 'escalations', [])) if hasattr(app, 'escalations') else 0

        # Find the actual cell for TOTAL MATERIAL COST (A)
        # This is always the last material summary row, which is after all escalations and sundries
        mat_total_row = 5 + len([x for x in app.live_bom_data if x["type"] == "Material"]) + 1 + escalation_count + 1  # +1 for 'Material Base Total', +escalation_count, +1 for sundries
        mat_total_cell = f'G{mat_total_row}'

        # Find the actual cell for TOTAL LABOR COST (B)
        lab_start_row = mat_total_row + 4  # 3 rows for blank, section header, then labor starts
        lab_total_row = lab_start_row + len([x for x in app.live_bom_data if x["type"] == "Labor"])  # after all labor rows
        lab_total_cell = f'G{lab_total_row}'
        ws  = wb.active
        assert ws is not None
        ws.title = "Estimate"

        sup_rate = m.get("supervision_rate", 0.10)
        sup_pct  = int(sup_rate * 100)

        # Header
        ws.merge_cells("A1:G1")
        ws["A1"] = "AUTOMATED ERP ESTIMATE"
        ws["A1"].font      = Font(bold=True, size=14, color="FFFFFF")
        ws["A1"].fill      = PatternFill("solid", fgColor="4F81BD")
        ws["A1"].alignment = Alignment(horizontal="center")

        ws.merge_cells("A2:G2")
        ws["A2"] = (
            f"Subject: {m.get('subject','')}  |  "
            f"Type: {m.get('project_type','')}  |  "
            f"Date: {datetime.now().strftime('%d-%m-%Y')}"
        )
        ws.merge_cells("A3:G3")
        ws["A3"] = (
            f"Lat: {m.get('lat','')}   Long: {m.get('long','')}   |   "
            f"Materials: {'UH (Readymade)' if m.get('use_uh') else 'Raw Steel'}"
        )

        header_row = ["Sl No.", "Code", "Description", "Qty", "Unit", "Rate", "Amount"]
        ws.append(header_row)
        for cell in ws[4]:
            cell.font = Font(bold=True)
        ws.column_dimensions["C"].width = 45
        ws.column_dimensions["B"].width = 15

        row = 5
        mat_items = [x for x in app.live_bom_data if x["type"] == "Material"]
        lab_items = [x for x in app.live_bom_data if x["type"] == "Labor"]

        # ── Materials ──
        ws.cell(row, 3, "A. MATERIALS").font = Font(bold=True)
        row += 1

        mat_start_row = 6
        mat_end_row = mat_start_row + len(mat_items) - 1
        for i, item in enumerate(mat_items, 1):
            ws.append([
                i, item["code"], item["name"],
                round(item["qty"], 3), item["unit"],
                round(item["rate"], 2), f'=ROUND(D{row}*F{row}, 2)'
            ])
            ws.cell(row, 4).number_format = '0.000'
            ws.cell(row, 6).number_format = '0.00'
            ws.cell(row, 7).number_format = '0.00'
            row += 1

        # Calculate mat_base for further calculations, but write formula to Excel
        mat_base = sum(x["amt"] for x in mat_items)
        ws.append(["", "", "Material Base Total", "", "", "", f'=ROUND(SUM(G{mat_start_row}:G{mat_end_row}), 2)'])
        ws.cell(row, 7).number_format = '0.00'
        row += 1


        # Escalation rows (formulas)
        esc_rows = []
        mat_base_cell = f'G{row-1}'
        subtotal_formula = mat_base_cell
        for i, (fy, esc) in enumerate(app.escalations):
            # Each escalation is 5% of (mat_base + all previous escalations)
            if i == 0:
                esc_formula = f'=ROUND(({mat_base_cell})*0.05, 2)'
            else:
                prev_esc_cells = '+'.join(esc_rows)
                esc_formula = f'=ROUND(({mat_base_cell}+{prev_esc_cells})*0.05, 2)'
            ws.append([
                "", "", f"Add: Escalation @ 5% for FY {fy}", "", "", "", esc_formula
            ])
            ws.cell(row, 7).number_format = '0.00'
            row += 1
            esc_cell = f'G{row-1}'
            esc_rows.append(esc_cell)

        # Sundries (formula) - 5% of (mat_base + all escalations)
        if esc_rows:
            subtotal_formula = f'{mat_base_cell}+' + '+'.join(esc_rows)
        else:
            subtotal_formula = mat_base_cell
        sun_formula = f'=ROUND(({subtotal_formula})*0.05, 2)'
        ws.append(["", "", "Add: Sundries @ 5%", "", "", "", sun_formula])
        ws.cell(row, 7).number_format = '0.00'
        row += 1
        sun_row = row-1

        # TOTAL MATERIAL COST (A) (formula)
        # Grand total = mat_base + all escalations + sundries
        if esc_rows:
            grand_total_formula = f'=ROUND({mat_base_cell}+' + '+'.join(esc_rows) + f'+G{sun_row}, 2)'
        else:
            grand_total_formula = f'=ROUND({mat_base_cell}+G{sun_row}, 2)'
        ws.append(["", "", "TOTAL MATERIAL COST (A)", "", "", "", grand_total_formula])
        ws.cell(row, 3).font = Font(bold=True)
        ws.cell(row, 7).font = Font(bold=True)
        ws.cell(row, 7).number_format = '0.00'
        mat_total_row = row  # Track the row where TOTAL MATERIAL COST (A) is written
        row += 2

        # ── Labor ──
        ws.cell(row, 3, "B. ERECTION / LABOR").font = Font(bold=True)
        row += 1

        lab_start_row = row
        lab_end_row = lab_start_row + len(lab_items) - 1
        for i, item in enumerate(lab_items, 1):
            ws.append([
                i, "", item["name"],
                round(item["qty"], 3), item["unit"],
                round(item["rate"], 2), f'=ROUND(D{row}*F{row}, 2)'
            ])
            ws.cell(row, 4).number_format = '0.000'
            ws.cell(row, 6).number_format = '0.00'
            ws.cell(row, 7).number_format = '0.00'
            row += 1


        # Formula for labor total
        ws.append(["", "", "TOTAL LABOR COST (B)", "", "", "", f'=ROUND(SUM(G{lab_start_row}:G{lab_end_row}), 2)'])
        ws.cell(row, 3).font = Font(bold=True)
        ws.cell(row, 7).font = Font(bold=True)
        ws.cell(row, 7).number_format = '0.00'
        lab_total_row = row  # Track the row where TOTAL LABOR COST (B) is written
        row += 2

        # ── Taxes ──

        # Use the exact rows where totals were written
        mat_total_cell = f'G{mat_total_row}'
        lab_total_cell = f'G{lab_total_row}'

        # Supervision on (A+B)
        ws.cell(row, 3, "C. OVERHEADS & TAXES").font = Font(bold=True)
        row += 1

        # Supervision
        sup_formula = f'=ROUND(({mat_total_cell}+G{lab_total_row})*{sup_rate}, 2)'
        ws.append(["", "", f"Supervision @ {sup_pct}% on (A+B)", "", "", "", sup_formula])
        ws.cell(row, 7).number_format = '0.00'
        sup_row = row
        sup_cell = f'G{sup_row}'
        row += 1

        # GST on labor only
        gst_formula = f'=ROUND(G{lab_total_row}*0.18, 2)'
        ws.append(["", "", "GST @ 18% on Labour only", "", "", "", gst_formula])
        ws.cell(row, 7).number_format = '0.00'
        gst_row = row
        gst_cell = f'G{gst_row}'
        row += 1

        # Sub-Total (A+B+Supervision+GST)
        sub_total_formula = f'=ROUND({mat_total_cell}+G{lab_total_row}+{sup_cell}+{gst_cell}, 2)'
        ws.append(["", "", "Sub-Total", "", "", "", sub_total_formula])
        ws.cell(row, 7).number_format = '0.00'
        sub_total_row = row
        sub_total_cell = f'G{sub_total_row}'
        row += 1

        # Cess on (A+B+Supervision)
        cess_formula = f'=ROUND(({mat_total_cell}+G{lab_total_row}+{sup_cell})*0.01, 2)'
        ws.append(["", "", "Add: Cess @ 1% on (Mat+Lab+Sup)", "", "", "", cess_formula])
        ws.cell(row, 7).number_format = '0.00'
        cess_row = row
        cess_cell = f'G{cess_row}'
        row += 1

        # GRAND TOTAL (Sub-Total + Cess)
        grand_total_formula = f'=ROUND({sub_total_cell}+{cess_cell}, 2)'
        ws.append(["", "", "GRAND TOTAL", "", "", "", grand_total_formula])
        ws.cell(row, 3).font = Font(bold=True, size=12)
        ws.cell(row, 7).font = Font(bold=True, size=12, color="FF0000")
        ws.cell(row, 7).number_format = '0.00'

    # ── Iron breakup sheet ───────────────────────────────────────────────────

    def _compute_canvas_counts(self) -> dict:
        from canvas import SmartPole, SmartStructure, SmartSpan

        scene_items = self._app.scene.items()
        poles    = [i for i in scene_items if isinstance(i, SmartPole)]
        structs  = [i for i in scene_items if isinstance(i, SmartStructure)]
        spans    = [i for i in scene_items if isinstance(i, SmartSpan)]

        new_lt_poles = [p for p in poles if not p.is_existing and p.pole_type == "LT"]
        new_ht_poles = [p for p in poles if not p.is_existing and p.pole_type == "HT"]

        return {
            "lt_pole_count":    len(new_lt_poles),
            "ht_pole_count":    len(new_ht_poles),
            "dp_count":         len([s for s in structs if s.structure_type == "DP"]),
            "tp_count":         len([s for s in structs if s.structure_type == "TP"]),
            "4p_count":         len([s for s in structs if s.structure_type == "4P"]),
            "dtr_count":        len([s for s in structs if s.structure_type == "DTR"]),
            "cg_pole_count":    len([p for p in new_lt_poles if any(
                                    getattr(s, "has_cg", False)
                                    for s in getattr(p, "connected_spans", []))]),
            "pole_ext_count":   len([p for p in poles if getattr(p, "has_extension", False)]),
            "ht_ext_count":     len([p for p in new_ht_poles if getattr(p, "has_extension", False)]),
            "lt_acsr_count":    len([p for p in new_lt_poles if any(
                                    getattr(s, "conductor", "") == "ACSR"
                                    for s in getattr(p, "connected_spans", []))]),
            "ab_cable_count":   len([sp for sp in spans
                                    if getattr(sp, "conductor", "") == "AB Cable"
                                    and not getattr(sp, "is_existing_span", False)]),
        }

    def _write_iron_breakup_sheet(self, wb: Any) -> None:
        """
        Generates a premium object-group centric Iron Breakup sheet showing per-source metre/kg rows.
        """
        openpyxl, Font, Alignment, PatternFill, Border, Side = _xl()
        ws = wb.create_sheet("Iron Breakup")
        
        # Column setup
        ws.column_dimensions["A"].width = 5
        ws.column_dimensions["B"].width = 44
        ws.column_dimensions["C"].width = 8
        ws.column_dimensions["D"].width = 14
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 12
        ws.column_dimensions["G"].width = 5
        
        SECTION_TO_ITEM_CODE = {
            "CH_75X40":   "0102010611",
            "CH_100X50":  "0102010911",
            "ANG_65X65X6":"0101011311",
            "ANG_50X50X6":"0101011011",
            "FLAT_65X6":  "0103011511",
            "FLAT_50X6":  "0103011211",
        }
        
        KG_PER_METRE = {
            "CH_75X40":    6.8,
            "CH_100X50":   9.8,
            "ANG_65X65X6": 5.8,
            "ANG_50X50X6": 4.5,
            "FLAT_65X6":   3.1,
            "FLAT_50X6":   2.5,
        }
        
        # Get dynamic recipes and sections from DB
        try:
            from core import db_gateway as _dbg
            recipes_list = _dbg.get_recipes()
            sections_dict = _dbg.get_sections()
        except Exception as e:
            recipes_list = []
            sections_dict = {}
            print(f"Error loading recipes/sections: {e}")
            
        def find_recipe(rkey):
            return next((r for r in recipes_list if r["recipe_key"] == rkey), None)
            
        def get_section_category(section_code):
            if "CH" in section_code:
                return "Channel"
            elif "ANG" in section_code:
                return "Angle"
            elif "FLAT" in section_code:
                return "Flat"
            return "Other"
            
        thin = Side(border_style="thin", color="D3D3D3")
        thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)

        def style_row(row_idx, fill_color=None, bold=False, color="000000", size=11, align_center_cols=[]):
            for col in range(1, 8):
                cell = ws.cell(row_idx, col)
                cell.border = thin_border
                if fill_color:
                    cell.fill = PatternFill("solid", fgColor=fill_color)
                if bold or color != "000000" or size != 11:
                    cell.font = Font(name="Segoe UI", size=size, bold=bold, color=color)
                if col in align_center_cols:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

        # 1. Compute canvas counts
        counts = self._compute_canvas_counts()
        
        # Scan poles for LT and HT extension height calculations
        scene_items = self._app.scene.items()
        from canvas import SmartPole
        poles = [i for i in scene_items if isinstance(i, SmartPole)]
        new_lt_poles = [p for p in poles if not p.is_existing and p.pole_type == "LT"]
        
        lt_recipe_counts = {}
        for p in new_lt_poles:
            rkey = getattr(p, "iron_recipe", "POLE_LT_IRON")
            if not rkey or rkey == "None":
                rkey = "POLE_LT_IRON"
            lt_recipe_counts[rkey] = lt_recipe_counts.get(rkey, 0) + 1

        def get_recipe_items(recipe_key, canvas_count):
            rec = find_recipe(recipe_key)
            if not rec:
                return []
            items = []
            for item in rec.get("items", []):
                items.append({
                    "description": item.get("description", ""),
                    "section": item.get("section", ""),
                    "length_per_piece": float(item.get("length_per_piece") or item.get("length") or 0.0),
                    "qty_per_object": int(item.get("qty_per_object") or item.get("qty") or 1),
                    "length_formula": item.get("length_formula") or str(item.get("length") or 0.0),
                    "canvas_count": canvas_count
                })
            return items

        # Build all group structures dynamically
        all_groups = []
        
        # 1. DTR Substation Iron
        if counts["dtr_count"] > 0:
            items = get_recipe_items("DTR_IRON", counts["dtr_count"])
            if items:
                all_groups.append({
                    "title": f"DTR Substation Iron ({counts['dtr_count']} nos on canvas)",
                    "subgroups": [{"items": items}]
                })
                
        # 2. DP Structure Iron
        if counts["dp_count"] > 0:
            items = get_recipe_items("DP_IRON", counts["dp_count"])
            if items:
                all_groups.append({
                    "title": f"DP Structure Iron ({counts['dp_count']} nos on canvas)",
                    "subgroups": [{"items": items}]
                })
                
        # 3. TP Structure Iron
        if counts["tp_count"] > 0:
            items = get_recipe_items("TP_IRON", counts["tp_count"])
            if items:
                all_groups.append({
                    "title": f"TP Structure Iron ({counts['tp_count']} nos on canvas)",
                    "subgroups": [{"items": items}]
                })
                
        # 4. 4-Pole Structure Iron
        if counts["4p_count"] > 0:
            items = get_recipe_items("4P_IRON", counts["4p_count"])
            if items:
                all_groups.append({
                    "title": f"4-Pole Structure Iron ({counts['4p_count']} nos on canvas)",
                    "subgroups": [{"items": items}]
                })
                
        # 5. LT Pole Iron
        if counts["lt_pole_count"] > 0:
            lt_subgroups = []
            for rkey, cnt in lt_recipe_counts.items():
                if cnt > 0:
                    rec = find_recipe(rkey)
                    if rec:
                        items = get_recipe_items(rkey, cnt)
                        if items:
                            lt_subgroups.append({
                                "title": f"{rec['name']} ({cnt} nos)",
                                "items": items
                            })
            if lt_subgroups:
                all_groups.append({
                    "title": f"LT Pole Iron ({counts['lt_pole_count']} nos on canvas)",
                    "subgroups": lt_subgroups
                })
                
        # 6. HT Pole Iron
        if counts["ht_pole_count"] > 0:
            items = get_recipe_items("POLE_HT_IRON", counts["ht_pole_count"])
            if items:
                all_groups.append({
                    "title": f"HT Pole Iron ({counts['ht_pole_count']} nos on canvas)",
                    "subgroups": [{"items": items}]
                })
                
        # 7. Pole Extensions
        ext_subgroups = []
        
        # HT Extensions
        if counts["ht_ext_count"] > 0:
            ext_poles_ht = [p for p in poles if not p.is_existing and p.pole_type == "HT" and getattr(p, "has_extension", False)]
            avg_ext_ht = (sum(float(getattr(p, "extension_height", 3.0) or 3.0) for p in ext_poles_ht) / len(ext_poles_ht)
                          if ext_poles_ht else 3.0)
            
            ht_items = [
                {
                    "description": "HT Pole Extension (Channel)",
                    "section": "CH_75X40",
                    "length_per_piece": avg_ext_ht * 2,
                    "qty_per_object": 1,
                    "length_formula": f"={round(avg_ext_ht, 2)}*2",
                    "canvas_count": counts["ht_ext_count"]
                },
                {
                    "description": "HT Pole Extension (Flat)",
                    "section": "FLAT_65X6",
                    "length_per_piece": 3.0,
                    "qty_per_object": 1,
                    "length_formula": "=3",
                    "canvas_count": counts["ht_ext_count"]
                }
            ]
            ext_subgroups.append({
                "title": f"HT Pole Extension ({counts['ht_ext_count']} nos)",
                "items": ht_items
            })
            
        # LT Extensions
        ext_poles_lt = [p for p in poles if not p.is_existing and p.pole_type == "LT" and getattr(p, "has_extension", False)]
        lt_ext_count = len(ext_poles_lt)
        
        if lt_ext_count > 0:
            avg_ext_lt = (sum(float(getattr(p, "extension_height", 1.5) or 1.5) for p in ext_poles_lt) / len(ext_poles_lt)
                          if ext_poles_lt else 1.5)
            
            lt_items = [
                {
                    "description": "LT Pole Extension (Angle)",
                    "section": "ANG_65X65X6",
                    "length_per_piece": avg_ext_lt,
                    "qty_per_object": 1,
                    "length_formula": f"={round(avg_ext_lt, 2)}",
                    "canvas_count": lt_ext_count
                }
            ]
            ext_subgroups.append({
                "title": f"LT Pole Extension ({lt_ext_count} nos)",
                "items": lt_items
            })
            
        if ext_subgroups:
            all_groups.append({
                "title": f"Pole Extensions ({counts['ht_ext_count'] + lt_ext_count} nos on canvas)",
                "subgroups": ext_subgroups
            })
            
        # 8. CG Bracket Iron
        if counts["cg_pole_count"] > 0:
            cg_items = [
                {
                    "description": "CG Cradle Guard Bracket (Angle)",
                    "section": "ANG_65X65X6",
                    "length_per_piece": 1.9,
                    "qty_per_object": 1,
                    "length_formula": "=1.9",
                    "canvas_count": counts["cg_pole_count"]
                },
                {
                    "description": "CG Cradle Guard Bracket (Flat)",
                    "section": "FLAT_65X6",
                    "length_per_piece": 0.5,
                    "qty_per_object": 1,
                    "length_formula": "=0.5",
                    "canvas_count": counts["cg_pole_count"]
                }
            ]
            all_groups.append({
                "title": f"CG Bracket Iron ({counts['cg_pole_count']} nos on canvas)",
                "subgroups": [{"items": cg_items}]
            })
            
        # 9. LT ACSR Bracket
        if counts["lt_acsr_count"] > 0:
            acsr_items = [
                {
                    "description": "LT ACSR Bracket (Angle)",
                    "section": "ANG_65X65X6",
                    "length_per_piece": 1.0,
                    "qty_per_object": 1,
                    "length_formula": "=1",
                    "canvas_count": counts["lt_acsr_count"]
                },
                {
                    "description": "LT ACSR Bracket (Flat)",
                    "section": "FLAT_65X6",
                    "length_per_piece": 1.0,
                    "qty_per_object": 1,
                    "length_formula": "=1",
                    "canvas_count": counts["lt_acsr_count"]
                }
            ]
            all_groups.append({
                "title": f"LT ACSR Bracket ({counts['lt_acsr_count']} nos on canvas)",
                "subgroups": [{"items": acsr_items}]
            })
            
        # 10. AB Cable Clamp Flat
        if counts["ab_cable_count"] > 0:
            ab_items = [
                {
                    "description": "AB Cable Clamp (Flat)",
                    "section": "FLAT_65X6",
                    "length_per_piece": 0.5,
                    "qty_per_object": 1,
                    "length_formula": "=0.5",
                    "canvas_count": counts["ab_cable_count"]
                }
            ]
            all_groups.append({
                "title": f"AB Cable Clamp Flat ({counts['ab_cable_count']} nos on canvas)",
                "subgroups": [{"items": ab_items}]
            })

        # Write to sheet
        cr = 1
        ws.cell(cr, 1, "IRON CALCULATION BREAKUP").font = Font(name="Segoe UI", bold=True, size=13)
        ws.merge_cells(start_row=cr, start_column=1, end_row=cr, end_column=7)
        ws.cell(cr, 1).fill = PatternFill("solid", fgColor="4472C4")
        ws.cell(cr, 1).font = Font(name="Segoe UI", bold=True, size=13, color="FFFFFF")
        ws.cell(cr, 1).alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[cr].height = 28
        cr += 2

        section_totals = {}  # {section_code: {"metres": 0.0, "kg": 0.0}}
        group_letter_idx = 0
        
        for g in all_groups:
            group_letter = chr(ord('A') + group_letter_idx)
            group_letter_idx += 1
            
            # Group Header Row
            ws.cell(cr, 1, group_letter)
            ws.cell(cr, 2, g["title"])
            ws.cell(cr, 3, "No")
            ws.cell(cr, 4, "Length (m)")
            ws.cell(cr, 5, "Total (m)")
            ws.cell(cr, 6, "Wt (kg)")
            ws.cell(cr, 7, "")
            
            style_row(cr, fill_color="4472C4", bold=True, color="FFFFFF", align_center_cols=[1, 3, 4, 5, 6])
            ws.row_dimensions[cr].height = 24
            cr += 1
            
            row_idx_within_group = 1
            
            for subgroup in g["subgroups"]:
                if subgroup.get("title") and len(g["subgroups"]) > 1:
                    # Subgroup header row
                    ws.cell(cr, 2, subgroup["title"])
                    style_row(cr, fill_color="F2F7FF", bold=True)
                    cr += 1
                
                # Group subgroup items by section type
                items_by_sec_type = {}
                for item in subgroup["items"]:
                    sec_type = get_section_category(item["section"])
                    items_by_sec_type.setdefault(sec_type, []).append(item)
                    
                has_multiple_types = (len(items_by_sec_type) > 1)
                
                for sec_type, type_items in items_by_sec_type.items():
                    type_start_row = cr
                    for item in type_items:
                        ws.cell(cr, 1, row_idx_within_group)
                        ws.cell(cr, 2, item["description"])
                        ws.cell(cr, 3, item["canvas_count"])
                        
                        length_formula = item["length_formula"]
                        if not str(length_formula).startswith("="):
                            length_formula = f"={length_formula}"
                        ws.cell(cr, 4, length_formula)
                        
                        ws.cell(cr, 5, f"=C{cr}*D{cr}")
                        
                        sec_code = item["section"]
                        kg_m = KG_PER_METRE.get(sec_code, 0.0)
                        if not kg_m and sections_dict and sec_code in sections_dict:
                            kg_m = sections_dict[sec_code].get("kg_per_metre", 0.0)
                            
                        wt_kg = item["length_per_piece"] * item["qty_per_object"] * item["canvas_count"] * kg_m
                        ws.cell(cr, 6, round(wt_kg, 2))
                        
                        # Alternating colors for data rows
                        fill_color = "FFFFFF" if row_idx_within_group % 2 != 0 else "F2F7FF"
                        style_row(cr, fill_color=fill_color, align_center_cols=[1, 3, 4, 5])
                        ws.row_dimensions[cr].height = 20
                        
                        # Accumulate section totals
                        total_m_val = item["length_per_piece"] * item["qty_per_object"] * item["canvas_count"]
                        if sec_code not in section_totals:
                            section_totals[sec_code] = {"metres": 0.0, "kg": 0.0}
                        section_totals[sec_code]["metres"] += total_m_val
                        section_totals[sec_code]["kg"] += wt_kg
                        
                        row_idx_within_group += 1
                        cr += 1
                        
                    if has_multiple_types:
                        type_end_row = cr - 1
                        ws.cell(cr, 2, f"{sec_type} subtotal")
                        ws.cell(cr, 5, f"=SUM(E{type_start_row}:E{type_end_row})")
                        ws.cell(cr, 6, f"=SUM(F{type_start_row}:F{type_end_row})")
                        style_row(cr, fill_color="E2EFDA", bold=True, align_center_cols=[5])
                        ws.row_dimensions[cr].height = 20
                        cr += 1
                        
            cr += 1  # space between blocks

        # 4. Section Summary Block
        ws.cell(cr, 2, "SECTION SUMMARY")
        style_row(cr, fill_color="D9E1F2", bold=True)
        ws.row_dimensions[cr].height = 22
        cr += 1
        
        SECTION_LABELS = {
            "CH_75X40":   "M.S. Channel 75x40mm",
            "CH_100X50":  "M.S. Channel 100x50mm",
            "ANG_65X65X6":"M.S. Angle 65x65x6mm",
            "ANG_50X50X6":"M.S. Angle 50x50x6mm",
            "FLAT_65X6":  "M.S. Flat 65x6mm",
            "FLAT_50X6":  "M.S. Flat 50x6mm",
        }
        
        summary_start_row = cr
        has_summary_items = False
        
        for sec_code in ["CH_100X50", "CH_75X40", "ANG_65X65X6", "ANG_50X50X6", "FLAT_65X6", "FLAT_50X6"]:
            if sec_code in section_totals and section_totals[sec_code]["metres"] > 0:
                has_summary_items = True
                info = section_totals[sec_code]
                label = SECTION_LABELS.get(sec_code, sec_code)
                kg_m = KG_PER_METRE.get(sec_code, 0.0)
                
                ws.cell(cr, 2, label)
                ws.cell(cr, 3, round(info["metres"], 2))
                ws.cell(cr, 4, "m")
                ws.cell(cr, 5, f"{kg_m} kg/m")
                ws.cell(cr, 6, round(info["kg"], 2))
                
                style_row(cr, align_center_cols=[3, 4, 5])
                ws.row_dimensions[cr].height = 20
                cr += 1
                
        for sec_code, info in section_totals.items():
            if sec_code not in ["CH_100X50", "CH_75X40", "ANG_65X65X6", "ANG_50X50X6", "FLAT_65X6", "FLAT_50X6"] and info["metres"] > 0:
                has_summary_items = True
                label = sections_dict.get(sec_code, {}).get("label", sec_code)
                kg_m = sections_dict.get(sec_code, {}).get("kg_per_metre", 0.0)
                
                ws.cell(cr, 2, label)
                ws.cell(cr, 3, round(info["metres"], 2))
                ws.cell(cr, 4, "m")
                ws.cell(cr, 5, f"{kg_m} kg/m")
                ws.cell(cr, 6, round(info["kg"], 2))
                
                style_row(cr, align_center_cols=[3, 4, 5])
                ws.row_dimensions[cr].height = 20
                cr += 1
                
        if not has_summary_items:
            ws.cell(cr, 2, "No iron items on canvas")
            style_row(cr)
            cr += 1
            
        cr += 1
        
        # Sub-total (all iron)
        subtotal_row = cr
        ws.cell(cr, 2, "Sub-total (all iron):")
        ws.cell(cr, 6, f"=SUM(F{summary_start_row}:F{subtotal_row-2})")
        style_row(cr, fill_color="E2EFDA", bold=True)
        ws.row_dimensions[cr].height = 20
        cr += 1
        
        # Add: Wastage + Sag @ 3%
        wastage_row = cr
        ws.cell(cr, 2, "Add: Wastage + Sag @ 3%:")
        ws.cell(cr, 6, f"=ROUND(F{subtotal_row}*0.03, 2)")
        style_row(cr, fill_color="E2EFDA", bold=True)
        ws.row_dimensions[cr].height = 20
        cr += 1
        
        # GRAND TOTAL
        grand_total_row = cr
        ws.cell(cr, 2, "GRAND TOTAL:")
        ws.cell(cr, 6, f"=F{subtotal_row}+F{wastage_row}")
        ws.cell(cr, 7, f'=CONCATENATE("=  ", FIXED(F{grand_total_row}/1000, 4), " MT")')
        style_row(cr, fill_color="FFF2CC", bold=True, size=12)
        ws.row_dimensions[cr].height = 24

