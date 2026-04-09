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
from typing import TYPE_CHECKING

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from canvas import SmartPole, SmartStructure, SmartSpan, SmartConsumer
from app_config import get_data_path

if TYPE_CHECKING:
    from app import EstimateApp


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

    # ── Estimate sheet ───────────────────────────────────────────────────────

    def _write_estimate_sheet(self, wb: openpyxl.Workbook, m: dict) -> None:
        app = self._app
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
        for i, item in enumerate(mat_items, 1):
            ws.append([
                i, item["code"], item["name"],
                round(item["qty"], 3), item["unit"],
                item["rate"], round(item["amt"], 2),
            ])
            row += 1

        mat_base = sum(x["amt"] for x in mat_items)
        ws.append(["", "", "Material Base Total", "", "", "", round(mat_base, 2)])
        row += 1

        cur = mat_base
        for fy, esc in app.escalations:
            ws.append([
                "", "", f"Add: Escalation @ 5% for FY {fy}",
                "", "", "", round(esc, 2),
            ])
            row += 1
            cur += esc

        sun     = cur * 0.05
        mat_sub = cur + sun
        ws.append(["", "", "Add: Sundries @ 5%", "", "", "", round(sun, 2)])
        row += 1
        ws.append(["", "", "TOTAL MATERIAL COST (A)", "", "", "", round(mat_sub, 2)])
        ws.cell(row, 3).font = Font(bold=True)
        ws.cell(row, 7).font = Font(bold=True)
        row += 2

        # ── Labor ──
        ws.cell(row, 3, "B. ERECTION / LABOR").font = Font(bold=True)
        row += 1
        for i, item in enumerate(lab_items, 1):
            ws.append([
                i, "", item["name"],
                round(item["qty"], 3), item["unit"],
                item["rate"], round(item["amt"], 2),
            ])
            row += 1

        lab_sub = sum(x["amt"] for x in lab_items)
        ws.append(["", "", "TOTAL LABOR COST (B)", "", "", "", round(lab_sub, 2)])
        ws.cell(row, 3).font = Font(bold=True)
        ws.cell(row, 7).font = Font(bold=True)
        row += 2

        # ── Taxes ──
        sup   = (mat_sub + lab_sub) * sup_rate
        gst   = lab_sub * 0.18
        cess  = (mat_sub + lab_sub + sup) * 0.01
        sub_c = mat_sub + lab_sub + sup + gst
        g_tot = sub_c + cess

        ws.cell(row, 3, "C. OVERHEADS & TAXES").font = Font(bold=True)
        row += 1
        for label, val in [
            (f"Supervision @ {sup_pct}% on (A+B)", sup),
            ("GST @ 18% on Labour only",            gst),
            ("Sub-Total",                           sub_c),
            ("Add: Cess @ 1% on (Mat+Lab+Sup)",     cess),
            ("GRAND TOTAL",                         g_tot),
        ]:
            ws.append(["", "", label, "", "", "", round(val, 2)])
            row += 1
        ws.cell(row - 1, 3).font = Font(bold=True, size=12)
        ws.cell(row - 1, 7).font = Font(bold=True, size=12, color="FF0000")

    # ── Iron breakup sheet ───────────────────────────────────────────────────

    def _write_iron_breakup_sheet(self, wb: openpyxl.Workbook) -> None:
        """
        Generates a detailed Iron Breakup sheet showing per-source metre/kg rows,
        plus 3% wastage + sag.
        """
        ws = wb.create_sheet("Iron Breakup")
        wastage_sag_pct = 0.03

        sections = [
            ("B",  "M.S. Channel (75X40mm)",   "0102010611", 6.8),
            ("B2", "M.S. Channel (100X50mm)",  "0102010911", 9.8),
            ("C",  "M.S. Angle (65X65X6mm)",   "0101011311", 5.8),
            ("D",  "M.S. Angle (50X50X6mm)",   "0101011011", 4.5),
            ("E",  "M.S. Flat (65X6mm)",       "0103011511", 3.1),
            ("F",  "G.I. Wire 5 MM (6 SWG)",   "0503010811", 0),
            ("G",  "G.I. Wire 4 MM (8 SWG)",   "0503010711", 0),
        ]

        detail = self._collect_iron_detail()

        ws.column_dimensions["A"].width = 5
        ws.column_dimensions["B"].width = 42
        ws.column_dimensions["C"].width = 8
        ws.column_dimensions["D"].width = 10
        ws.column_dimensions["E"].width = 10
        ws.column_dimensions["F"].width = 12

        header_fill  = PatternFill("solid", fgColor="4F81BD")
        section_fill = PatternFill("solid", fgColor="D9E1F2")
        total_fill   = PatternFill("solid", fgColor="EBF1DE")
        thin   = Side(border_style="thin", color="AAAAAA")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        cr = 1
        ws.cell(cr, 1, "IRON CALCULATION BREAKUP").font = Font(bold=True, size=13)
        ws.merge_cells(start_row=cr, start_column=1, end_row=cr, end_column=6)
        ws.cell(cr, 1).fill      = header_fill
        ws.cell(cr, 1).font      = Font(bold=True, size=13, color="FFFFFF")
        ws.cell(cr, 1).alignment = Alignment(horizontal="center")
        cr += 1

        ws.merge_cells(start_row=cr, start_column=1, end_row=cr, end_column=6)
        ws.cell(cr, 1, "Steel quantities from rule-engine + 3% wastage & sag")
        ws.cell(cr, 1).alignment = Alignment(horizontal="center")
        ws.cell(cr, 1).font = Font(bold=True, color="2F5597")
        cr += 1

        for sec_key, sec_title, item_code, kg_m in sections:
            rows = detail.get(item_code, [])
            if not rows:
                continue

            # Section header
            ws.cell(cr, 1, sec_key).font  = Font(bold=True)
            ws.cell(cr, 2, sec_title).font = Font(bold=True)
            ws.cell(cr, 3, "No").font     = Font(bold=True)
            if kg_m:
                ws.cell(cr, 4, "Lgth(m)").font  = Font(bold=True)
                ws.cell(cr, 5, "Total(m)").font = Font(bold=True)
            else:
                ws.cell(cr, 4, ""); ws.cell(cr, 5, "")
            ws.cell(cr, 6, "Wt(kg)").font = Font(bold=True)
            for col in range(1, 7):
                ws.cell(cr, col).fill   = section_fill
                ws.cell(cr, col).border = border
            cr += 1

            is_wire     = (kg_m == 0)
            subtotal_m  = 0.0
            subtotal_kg = 0.0

            for i, (desc, count, length_each, total_m, wt_kg) in enumerate(rows, 1):
                ws.cell(cr, 1, i)
                ws.cell(cr, 2, desc)
                ws.cell(cr, 3, count if count else "")
                if is_wire:
                    ws.cell(cr, 4, "")
                    ws.cell(cr, 5, "")
                else:
                    ws.cell(cr, 4, round(length_each, 2) if length_each else "")
                    ws.cell(cr, 5, round(total_m, 3))
                ws.cell(cr, 6, round(wt_kg, 2))
                for col in range(1, 7):
                    ws.cell(cr, col).border = border
                subtotal_m  += total_m
                subtotal_kg += wt_kg
                cr += 1

            if is_wire:
                extra_kg = subtotal_kg * wastage_sag_pct
                ws.cell(cr, 1, len(rows) + 1)
                ws.cell(cr, 2, "Add: Wastage + Sag @ 3%")
                ws.cell(cr, 3, ""); ws.cell(cr, 4, ""); ws.cell(cr, 5, "")
                ws.cell(cr, 6, round(extra_kg, 2))
                for col in range(1, 7):
                    ws.cell(cr, col).border = border
                cr += 1
                ws.cell(cr, 2, "Total (incl. 3% wastage & sag)").font = Font(bold=True)
                ws.cell(cr, 5, "")
                ws.cell(cr, 6, round(subtotal_kg + extra_kg, 2)).font = Font(bold=True)
            else:
                base_kg  = subtotal_m * kg_m
                extra_m  = subtotal_m * wastage_sag_pct
                extra_kg = base_kg * wastage_sag_pct
                ws.cell(cr, 1, len(rows) + 1)
                ws.cell(cr, 2, "Add: Wastage + Sag @ 3%")
                ws.cell(cr, 3, ""); ws.cell(cr, 4, "")
                ws.cell(cr, 5, round(extra_m, 3))
                ws.cell(cr, 6, round(extra_kg, 2))
                for col in range(1, 7):
                    ws.cell(cr, col).border = border
                cr += 1
                ws.cell(cr, 2, "Total (incl. 3% wastage & sag)").font = Font(bold=True)
                ws.cell(cr, 5, round(subtotal_m + extra_m, 3)).font = Font(bold=True)
                ws.cell(cr, 6, round(base_kg + extra_kg, 2)).font   = Font(bold=True)

            for col in range(1, 7):
                ws.cell(cr, col).border = border
                ws.cell(cr, col).fill   = total_fill
            cr += 2

    # ── Iron detail collector ────────────────────────────────────────────────

    def _collect_iron_detail(self) -> dict[str, list]:
        """
        Re-evaluate each steel rule per canvas item and return a
        per-item_code list of (description, count, length_each, total_m, wt_kg)
        rows suitable for the detailed Iron Breakup sheet.

        Returns
        -------
        dict  { item_code: [(desc, count, len_each, tot_m, wt_kg), ...] }
        """
        app = self._app
        UW  = self._IRON_UNIT_WEIGHTS

        try:
            with open(get_data_path("rules.json"), "r") as f:
                rules = _json.load(f)
        except (FileNotFoundError, _json.JSONDecodeError):
            rules = []

        steel_rules = [
            r for r in rules
            if r.get("type") == "Material" and r.get("item_code") in UW
        ]

        use_uh       = app.project_meta.get("use_uh", False)
        project_type = app.project_meta.get("project_type", "NSC")

        accum: dict[str, dict[tuple, list]] = {code: {} for code in UW}

        for item in app.scene.items():
            if isinstance(item, SmartPole):
                ctx = app.rule_engine._build_pole_context(item, use_uh, project_type)
            elif isinstance(item, SmartStructure):
                ctx = app.rule_engine._build_structure_context(item, use_uh, project_type)
            elif isinstance(item, SmartSpan):
                ctx = app.rule_engine._build_span_context(item, use_uh, project_type)
            elif isinstance(item, SmartConsumer):
                ctx = app.rule_engine._build_consumer_context(item, use_uh, project_type)
            else:
                continue

            obj_type = ctx.get("object_type", "")

            for rule in steel_rules:
                target = rule.get("object", "")
                if target == "SmartHome" and obj_type == "SmartConsumer":
                    pass
                elif target != obj_type:
                    continue

                if not app.rule_engine.evaluate_rule(ctx, rule.get("condition", "")):
                    continue

                qty_mt = app.rule_engine.calculate_qty(ctx, rule.get("formula", "1"))
                if qty_mt <= 0:
                    continue

                code  = rule["item_code"]
                kg_m  = UW[code]
                wt_kg = qty_mt * 1000.0
                tot_m = wt_kg / kg_m if kg_m else 0.0

                label, len_each = self._iron_source_label(ctx, rule, tot_m)
                key = (label, len_each)
                if key not in accum[code]:
                    accum[code][key] = [0, 0.0, 0.0]
                accum[code][key][0] += 1
                accum[code][key][1] += tot_m
                accum[code][key][2] += wt_kg

        result: dict[str, list] = {}
        for code, entries in accum.items():
            rows = []
            for (label, len_each), (cnt, tot_m, wt_kg) in sorted(entries.items()):
                rows.append((label, cnt, len_each, round(tot_m, 4), round(wt_kg, 4)))
            if rows:
                result[code] = rows
        return result

    @staticmethod
    def _iron_source_label(ctx: dict, rule: dict, total_m: float) -> tuple[str, float]:
        """Return (description_string, length_per_unit) for an iron breakup row."""
        obj   = ctx.get("object_type", "")
        cond  = rule.get("condition", "")
        formula = rule.get("formula", "")

        if obj == "SmartPole":
            pole_type   = ctx.get("pole_type", "")
            is_existing = ctx.get("is_existing", False)
            prefix      = "Existing" if is_existing else "New"

            if "has_extension" in cond:
                ext_h = ctx.get("extension_height", 3.0)
                if "FLAT" in formula:
                    return (f"{prefix} {pole_type} Pole Extension Flat ({ext_h}m)", round(total_m, 2))
                return (f"{prefix} {pole_type} Pole Extension ({ext_h}m)", round(total_m, 2))
            elif "has_cg" in cond:
                return ("Cradle Guard (CG) Bracket on Pole",
                        1.9 if "ANG" in formula else 0.5)
            elif "lt_acsr_count" in cond:
                return (f"LT Bracket on {prefix} LT Pole", 1.0)
            elif "ht_spans_count" in cond:
                return (f"Tee-off Bracket on {prefix} HT Pole", round(total_m, 2))
            elif "earth_count" in cond:
                ec = ctx.get("earth_count", 1)
                return (f"Earthing on {prefix} {pole_type} Pole ({ec} nos)", round(total_m, 2))
            else:
                return (f"{prefix} {pole_type} Pole Iron", round(total_m, 2))

        elif obj == "SmartStructure":
            st = ctx.get("structure_type", "")
            if "earth_count" in cond:
                ec = ctx.get("earth_count", 1)
                return (f"Earthing on {st} Structure ({ec} nos)", round(total_m, 2))
            if st == "DTR":
                if "CH_75X40" in formula or "CH_100X50" in formula:
                    return ("DTR Sub-Stn (Channel — Top + Isolator + Base + Bolt)", round(total_m, 2))
                elif "ANG_65X65X6" in formula:
                    return ("DTR Sub-Stn (Angle — Fuse + Switch + Support + FootRest)", round(total_m, 2))
                elif "ANG_50X50X6" in formula:
                    return ("DTR Sub-Stn (Angle 50 — Main Switch)", round(total_m, 2))
                elif "FLAT_65X6" in formula:
                    return ("DTR Sub-Stn (Flat — HT Clamp)", round(total_m, 2))
                return ("DTR Sub-Stn Iron", round(total_m, 2))
            elif st == "DP":
                if "CH_75X40" in formula:
                    return ("DP Structure (Channel)", round(total_m, 2))
                return ("DP Structure (Flat)", round(total_m, 2))
            elif st == "TP":
                if "CH_75X40" in formula:
                    return ("TP Structure (Channel)", round(total_m, 2))
                elif "ANG_65X65X6" in formula:
                    return ("TP Structure (Angle)", round(total_m, 2))
                return ("TP Structure (Flat)", round(total_m, 2))
            elif st == "4P":
                if "CH_75X40" in formula:
                    return ("4P Structure (Channel)", round(total_m, 2))
                elif "ANG_65X65X6" in formula:
                    return ("4P Structure (Angle)", round(total_m, 2))
                return ("4P Structure (Flat)", round(total_m, 2))
            return (f"{st} Structure Iron", round(total_m, 2))

        elif obj == "SmartSpan":
            item_code = rule.get("item_code", "")
            if item_code in ("0503010811", "0503010711"):
                length = ctx.get("length", 0)
                return (f"CG Earthing Wire on Span ({length}m)", round(total_m, 2))
            return ("AB Cable Span (Flat)", 0.5)

        return ("Other Iron", round(total_m, 2))
