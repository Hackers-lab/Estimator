"""
excel_exporter.py
=================
ExcelExporter class — all Excel generation logic extracted from app.py.

Usage::

    from excel_exporter import ExcelExporter
    ExcelExporter(app_instance).generate()
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import QFileDialog, QMessageBox


if TYPE_CHECKING:
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
        safe    = "".join(c for c in subject if c not in r'\/*?:"<>|').strip()
        safe_stem = safe[:100].rstrip(" ._")
        default = f"{safe_stem}_Estimate.xlsx" if safe_stem else "ERP_Estimate.xlsx"

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
        ws = wb.active
        assert ws is not None
        ws.title = "Estimate"

        # ── Page Setup (Print strictly on 1 single page with minimum margins) ──
        ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_margins.left = 0.20
        ws.page_margins.right = 0.20
        ws.page_margins.top = 0.30
        ws.page_margins.bottom = 0.30
        ws.print_options.horizontalCentered = True
        ws.views.sheetView[0].showGridLines = True

        sup_rate = m.get("supervision_rate", 0.10)
        sup_pct  = int(sup_rate * 100)

        # ── Color Palette & Styles ──────────────────────────────────────────
        FONT_FAMILY = "Segoe UI"
        NAVY_HEADER = "1F4E79"
        TBL_HEADER  = "2E75B6"
        SEC_BG      = "D9E1F2"
        SEC_TXT     = "1F4E79"
        SUBTOTAL_BG = "F1F5F9"
        TOTAL_BG    = "E2EFDA"
        ZEBRA_EVEN  = "FFFFFF"
        ZEBRA_ODD   = "F9FBFD"
        META_BG     = "F2F4F7"

        thin_side = Side(border_style="thin", color="D9D9D9")
        thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        dark_side = Side(border_style="thin", color="808080")
        subtotal_border = Border(
            left=thin_side, right=thin_side,
            top=Side(border_style="thin", color="B0C4DE"),
            bottom=Side(border_style="thin", color="B0C4DE")
        )
        grand_total_border = Border(
            left=thin_side, right=thin_side,
            top=Side(border_style="thin", color="2E75B6"),
            bottom=Side(border_style="double", color="1F4E79")
        )

        def style_cells(row_idx: int, bg_color: str | None = None, font: Any = None,
                        align: Any = None, border: Any = thin_border, cols: range = range(1, 8)):
            for col_idx in cols:
                cell = ws.cell(row=row_idx, column=col_idx)
                if border:
                    cell.border = border
                if bg_color:
                    cell.fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
                if font:
                    cell.font = font
                if align:
                    cell.alignment = align

        # ── Title & Meta Header Block ───────────────────────────────────────
        ws.row_dimensions[1].height = 28
        ws.merge_cells("A1:G1")
        title_cell = ws["A1"]
        title_cell.value = "AUTOMATED ERP ESTIMATE"
        title_cell.font = Font(name=FONT_FAMILY, size=14, bold=True, color="FFFFFF")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        title_cell.fill = PatternFill(start_color=NAVY_HEADER, end_color=NAVY_HEADER, fill_type="solid")
        for col in range(1, 8):
            ws.cell(row=1, column=col).border = Border(bottom=dark_side)

        ws.row_dimensions[2].height = 18
        ws.merge_cells("A2:G2")
        meta1 = ws["A2"]
        meta1.value = f"Project: {m.get('subject','')}    |    Type: {m.get('project_type','')}    |    Date: {datetime.now().strftime('%d-%m-%Y')}"
        meta1.font = Font(name=FONT_FAMILY, size=9.5, bold=True, color="333333")
        meta1.alignment = Alignment(horizontal="center", vertical="center")
        meta1.fill = PatternFill(start_color=META_BG, end_color=META_BG, fill_type="solid")
        for col in range(1, 8):
            ws.cell(row=2, column=col).border = Border(left=thin_side, right=thin_side)

        ws.row_dimensions[3].height = 17
        ws.merge_cells("A3:G3")
        meta2 = ws["A3"]
        meta2.value = f"Coordinates: {m.get('lat','')} , {m.get('long','')}    |    Materials: {'UH (Readymade)' if m.get('use_uh') else 'Raw Steel'}"
        meta2.font = Font(name=FONT_FAMILY, size=9, color="555555")
        meta2.alignment = Alignment(horizontal="center", vertical="center")
        meta2.fill = PatternFill(start_color=META_BG, end_color=META_BG, fill_type="solid")
        for col in range(1, 8):
            ws.cell(row=3, column=col).border = Border(left=thin_side, right=thin_side)

        ws.row_dimensions[4].height = 18
        ws.merge_cells("A4:G4")
        meta3 = ws["A4"]
        from core import db_gateway as _dbg
        profile = _dbg.get_active_profile()
        if profile:
            meta3.value = f"Firm: {profile['firm_name']}   |   Address: {profile['address']}   |   GSTIN: {profile['gstin']}"
        else:
            meta3.value = "Firm Details: Not Configured"
        meta3.font = Font(name=FONT_FAMILY, size=9, italic=True, color="444444")
        meta3.alignment = Alignment(horizontal="center", vertical="center")
        meta3.fill = PatternFill(start_color=META_BG, end_color=META_BG, fill_type="solid")
        for col in range(1, 8):
            ws.cell(row=4, column=col).border = Border(left=thin_side, right=thin_side, bottom=dark_side)

        # ── Table Column Headers ────────────────────────────────────────────
        ws.row_dimensions[5].height = 22
        headers = ["Sl No.", "Code", "Description of Item", "Qty", "Unit", "Rate (₹)", "Amount (₹)"]
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=5, column=col_idx, value=h)
            cell.font = Font(name=FONT_FAMILY, size=10, bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.fill = PatternFill(start_color=TBL_HEADER, end_color=TBL_HEADER, fill_type="solid")
            cell.border = Border(left=thin_side, right=thin_side, top=dark_side, bottom=dark_side)

        ws.column_dimensions["A"].width = 7.5
        ws.column_dimensions["B"].width = 13.5
        ws.column_dimensions["D"].width = 10.0
        ws.column_dimensions["E"].width = 8.5
        ws.column_dimensions["F"].width = 13.0
        ws.column_dimensions["G"].width = 15.0

        mat_items = [x for x in app.live_bom_data if x["type"] == "Material"]
        lab_items = [x for x in app.live_bom_data if x["type"] == "Labor"]

        # Dynamically compute flexible width for Column C (Description of Item)
        # When an estimate has many rows (e.g. 35 to 60+ rows), Excel compresses the sheet
        # vertically to fit on 1 page. By expanding Column C's width proportionally,
        # the table width expands to fill 100% of the printed page margins instead of shrinking.
        total_data_rows = len(mat_items) + len(lab_items)
        max_desc_len = max(
            [len("Description of Item")] +
            [len(str(x.get("name", ""))) for x in mat_items + lab_items]
        )
        base_desc_w = max(46.0, float(max_desc_len + 4))

        if total_data_rows <= 20:
            flexible_desc_width = max(base_desc_w, 48.0)
        elif total_data_rows <= 32:
            flexible_desc_width = max(base_desc_w, 58.0)
        elif total_data_rows <= 45:
            flexible_desc_width = max(base_desc_w, 72.0)
        else:
            flexible_desc_width = max(base_desc_w, 88.0)

        ws.column_dimensions["C"].width = min(flexible_desc_width, 98.0)

        row = 6

        # ── Section A: Materials ────────────────────────────────────────────
        ws.row_dimensions[row].height = 20
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        sec_a = ws.cell(row=row, column=1, value="A. MATERIALS")
        sec_a.font = Font(name=FONT_FAMILY, size=10.5, bold=True, color=SEC_TXT)
        sec_a.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        style_cells(row, bg_color=SEC_BG, border=Border(left=thin_side, right=thin_side, top=dark_side, bottom=thin_side))
        row += 1

        mat_start_row = row
        for i, item in enumerate(mat_items, 1):
            qty_val = round(item["qty"], 3)
            qty_is_int = (qty_val == int(qty_val))
            ws.row_dimensions[row].height = 18
            bg = ZEBRA_EVEN if (i % 2 != 0) else ZEBRA_ODD

            c_sl   = ws.cell(row=row, column=1, value=i)
            c_code = ws.cell(row=row, column=2, value=item["code"])
            c_desc = ws.cell(row=row, column=3, value=item["name"])
            c_qty  = ws.cell(row=row, column=4, value=int(qty_val) if qty_is_int else qty_val)
            c_unit = ws.cell(row=row, column=5, value=item["unit"])
            c_rate = ws.cell(row=row, column=6, value=round(item["rate"], 2))
            c_amt  = ws.cell(row=row, column=7, value=f'=ROUND(D{row}*F{row}, 2)')

            c_sl.alignment   = Alignment(horizontal="center", vertical="center")
            c_code.alignment = Alignment(horizontal="center", vertical="center")
            c_desc.alignment = Alignment(horizontal="left", vertical="center")
            c_qty.alignment  = Alignment(horizontal="right", vertical="center")
            c_unit.alignment = Alignment(horizontal="center", vertical="center")
            c_rate.alignment = Alignment(horizontal="right", vertical="center")
            c_amt.alignment  = Alignment(horizontal="right", vertical="center")

            c_qty.number_format  = '#,##0' if qty_is_int else '#,##0.000'
            c_rate.number_format = '#,##0.00'
            c_amt.number_format  = '#,##0.00'

            for c_idx in range(1, 8):
                cell = ws.cell(row=row, column=c_idx)
                cell.font = Font(name=FONT_FAMILY, size=9.5)
                cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
                cell.border = thin_border
            row += 1

        mat_end_row = row - 1

        # Material Base Total
        ws.row_dimensions[row].height = 19
        ws.cell(row=row, column=3, value="Material Base Total").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=f'=ROUND(SUM(G{mat_start_row}:G{mat_end_row}), 2)').alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, bg_color=SUBTOTAL_BG, font=Font(name=FONT_FAMILY, size=9.5, bold=True, color="333333"), border=subtotal_border)
        mat_base_cell = f'G{row}'
        row += 1

        # Escalation rows
        esc_rows: list[str] = []
        for i, (fy, esc) in enumerate(getattr(app, 'escalations', [])):
            ws.row_dimensions[row].height = 18
            if i == 0:
                esc_formula = f'=ROUND(({mat_base_cell})*0.05, 2)'
            else:
                prev_esc_cells = '+'.join(esc_rows)
                esc_formula = f'=ROUND(({mat_base_cell}+{prev_esc_cells})*0.05, 2)'
            ws.cell(row=row, column=3, value=f"Add: Escalation @ 5% for FY {fy}").alignment = Alignment(horizontal="right", vertical="center")
            ws.cell(row=row, column=7, value=esc_formula).alignment = Alignment(horizontal="right", vertical="center")
            ws.cell(row=row, column=7).number_format = '#,##0.00'
            style_cells(row, font=Font(name=FONT_FAMILY, size=9, italic=True), border=thin_border)
            esc_rows.append(f'G{row}')
            row += 1

        # Sundries row
        ws.row_dimensions[row].height = 18
        if esc_rows:
            subtotal_formula = f'{mat_base_cell}+' + '+'.join(esc_rows)
        else:
            subtotal_formula = mat_base_cell
        sun_formula = f'=ROUND(({subtotal_formula})*0.05, 2)'
        ws.cell(row=row, column=3, value="Add: Sundries @ 5%").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=sun_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, font=Font(name=FONT_FAMILY, size=9, italic=True), border=thin_border)
        sun_cell = f'G{row}'
        row += 1

        # TOTAL MATERIAL COST (A)
        ws.row_dimensions[row].height = 20
        if esc_rows:
            grand_mat_formula = f'=ROUND({mat_base_cell}+' + '+'.join(esc_rows) + f'+{sun_cell}, 2)'
        else:
            grand_mat_formula = f'=ROUND({mat_base_cell}+{sun_cell}, 2)'
        ws.cell(row=row, column=3, value="TOTAL MATERIAL COST (A)").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=grand_mat_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, bg_color=SUBTOTAL_BG, font=Font(name=FONT_FAMILY, size=10, bold=True, color="1F4E79"), border=subtotal_border)
        mat_total_cell = f'G{row}'
        row += 1

        # ── Section B: Labor ────────────────────────────────────────────────
        ws.row_dimensions[row].height = 20
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        sec_b = ws.cell(row=row, column=1, value="B. ERECTION / LABOR")
        sec_b.font = Font(name=FONT_FAMILY, size=10.5, bold=True, color=SEC_TXT)
        sec_b.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        style_cells(row, bg_color=SEC_BG, border=Border(left=thin_side, right=thin_side, top=dark_side, bottom=thin_side))
        row += 1

        lab_start_row = row
        for i, item in enumerate(lab_items, 1):
            qty_val = round(item["qty"], 3)
            qty_is_int = (qty_val == int(qty_val))
            ws.row_dimensions[row].height = 18
            bg = ZEBRA_EVEN if (i % 2 != 0) else ZEBRA_ODD

            c_sl   = ws.cell(row=row, column=1, value=i)
            c_code = ws.cell(row=row, column=2, value="")
            c_desc = ws.cell(row=row, column=3, value=item["name"])
            c_qty  = ws.cell(row=row, column=4, value=int(qty_val) if qty_is_int else qty_val)
            c_unit = ws.cell(row=row, column=5, value=item["unit"])
            c_rate = ws.cell(row=row, column=6, value=round(item["rate"], 2))
            c_amt  = ws.cell(row=row, column=7, value=f'=ROUND(D{row}*F{row}, 2)')

            c_sl.alignment   = Alignment(horizontal="center", vertical="center")
            c_code.alignment = Alignment(horizontal="center", vertical="center")
            c_desc.alignment = Alignment(horizontal="left", vertical="center")
            c_qty.alignment  = Alignment(horizontal="right", vertical="center")
            c_unit.alignment = Alignment(horizontal="center", vertical="center")
            c_rate.alignment = Alignment(horizontal="right", vertical="center")
            c_amt.alignment  = Alignment(horizontal="right", vertical="center")

            c_qty.number_format  = '#,##0' if qty_is_int else '#,##0.000'
            c_rate.number_format = '#,##0.00'
            c_amt.number_format  = '#,##0.00'

            for c_idx in range(1, 8):
                cell = ws.cell(row=row, column=c_idx)
                cell.font = Font(name=FONT_FAMILY, size=9.5)
                cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
                cell.border = thin_border
            row += 1

        lab_end_row = row - 1

        # TOTAL LABOR COST (B)
        ws.row_dimensions[row].height = 20
        ws.cell(row=row, column=3, value="TOTAL LABOR COST (B)").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=f'=ROUND(SUM(G{lab_start_row}:G{lab_end_row}), 2)').alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, bg_color=SUBTOTAL_BG, font=Font(name=FONT_FAMILY, size=10, bold=True, color="1F4E79"), border=subtotal_border)
        lab_total_cell = f'G{row}'
        row += 1

        # ── Section C: Overheads & Taxes ────────────────────────────────────
        ws.row_dimensions[row].height = 20
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        sec_c = ws.cell(row=row, column=1, value="C. OVERHEADS & TAXES")
        sec_c.font = Font(name=FONT_FAMILY, size=10.5, bold=True, color=SEC_TXT)
        sec_c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        style_cells(row, bg_color=SEC_BG, border=Border(left=thin_side, right=thin_side, top=dark_side, bottom=thin_side))
        row += 1

        # Supervision
        ws.row_dimensions[row].height = 18
        sup_formula = f'=ROUND(({mat_total_cell}+{lab_total_cell})*{sup_rate}, 2)'
        ws.cell(row=row, column=3, value=f"Supervision @ {sup_pct}% on (A+B)").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=sup_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, font=Font(name=FONT_FAMILY, size=9.5), border=thin_border)
        sup_cell = f'G{row}'
        row += 1

        # GST on Labor
        ws.row_dimensions[row].height = 18
        gst_formula = f'=ROUND({lab_total_cell}*0.18, 2)'
        ws.cell(row=row, column=3, value="GST @ 18% on Labour only").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=gst_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, font=Font(name=FONT_FAMILY, size=9.5), border=thin_border)
        gst_cell = f'G{row}'
        row += 1

        # Sub-Total
        ws.row_dimensions[row].height = 19
        sub_total_formula = f'=ROUND({mat_total_cell}+{lab_total_cell}+{sup_cell}+{gst_cell}, 2)'
        ws.cell(row=row, column=3, value="Sub-Total").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=sub_total_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, bg_color=SUBTOTAL_BG, font=Font(name=FONT_FAMILY, size=9.5, bold=True, color="333333"), border=subtotal_border)
        sub_total_cell = f'G{row}'
        row += 1

        # Cess
        ws.row_dimensions[row].height = 18
        cess_formula = f'=ROUND(({mat_total_cell}+{lab_total_cell}+{sup_cell})*0.01, 2)'
        ws.cell(row=row, column=3, value="Add: Cess @ 1% on (Mat+Lab+Sup)").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=cess_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, font=Font(name=FONT_FAMILY, size=9.5), border=thin_border)
        cess_cell = f'G{row}'
        row += 1

        # GRAND TOTAL
        ws.row_dimensions[row].height = 24
        grand_total_formula = f'=ROUND({sub_total_cell}+{cess_cell}, 2)'
        ws.cell(row=row, column=3, value="GRAND TOTAL (₹)").alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7, value=grand_total_formula).alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=7).number_format = '#,##0.00'
        style_cells(row, bg_color=TOTAL_BG, font=Font(name=FONT_FAMILY, size=11, bold=True, color="1F4E79"), border=grand_total_border)

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
            "cg_pole_brackets": sum(
                sum(1 for s in getattr(p, "connected_spans", []) if getattr(s, "has_cg", False))
                for p in poles if not p.is_existing
            ),
            "cg_dp_brackets":   sum(
                sum(1 for s in getattr(st, "connected_spans", []) if getattr(s, "has_cg", False))
                for st in structs if getattr(st, "structure_type", "") in ("DP", "DTR")
            ),
            "pole_ext_count":   len([p for p in poles if getattr(p, "has_extension", False)]),
            "ht_ext_count":     len([p for p in new_ht_poles if getattr(p, "has_extension", False)]),
            "lt_acsr_count":    len([p for p in new_lt_poles if any(
                                    getattr(s, "conductor", "") == "ACSR"
                                    for s in getattr(p, "connected_spans", []))]) +
                                len([p for p in poles if getattr(p, "is_existing", False)
                                     and getattr(p, "pole_type", "") == "LT"
                                     and bool(getattr(p, "lt_extension_continuous", lambda: False)())]),
            "ab_cable_count":   len([sp for sp in spans
                                    if getattr(sp, "conductor", "") == "AB Cable"
                                    and not getattr(sp, "is_existing_span", False)]),
        }

    def _write_iron_breakup_sheet(self, wb: Any) -> None:
        """
        Iron Breakup sheet: grouped by Section Type → Object Type → Recipe Items.
        Column F shows Iron (MT) per description row matching the estimate exactly.
        Totals reconcile with the Estimate sheet.
        """
        _, Font, Alignment, PatternFill, Border, Side = _xl()
        ws = wb.create_sheet("Iron Breakup")

        # ── Page Setup (Print strictly on 1 single page with minimum margins) ──
        ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_margins.left = 0.20
        ws.page_margins.right = 0.20
        ws.page_margins.top = 0.30
        ws.page_margins.bottom = 0.30
        ws.print_options.horizontalCentered = True
        ws.views.sheetView[0].showGridLines = True

        ws.column_dimensions["A"].width = 6
        ws.column_dimensions["B"].width = 42
        ws.column_dimensions["C"].width = 8
        ws.column_dimensions["D"].width = 16
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 15

        KG_PER_METRE = {
            "CH_75X40":    6.8,
            "CH_100X50":   9.8,
            "ANG_65X65X6": 5.8,
            "ANG_50X50X6": 4.5,
            "FLAT_65X6":   3.1,
            "FLAT_50X6":   2.5,
        }
        SECTION_LABELS = {
            "CH_75X40":    "M.S. Channel (75X40mm)",
            "CH_100X50":   "M.S. Channel (100X50mm)",
            "ANG_65X65X6": "M.S. Angle (65X65X6mm)",
            "ANG_50X50X6": "M.S. Angle (50X50X6mm)",
            "FLAT_65X6":   "M.S. Flat (65X6mm)",
            "FLAT_50X6":   "M.S. Flat (50X6mm)",
        }
        SECTION_ORDER = ["CH_100X50", "CH_75X40", "ANG_65X65X6", "ANG_50X50X6", "FLAT_65X6", "FLAT_50X6"]

        try:
            from core import db_gateway as _dbg
            recipes_list = _dbg.get_recipes()
            sections_dict = _dbg.get_sections()
        except Exception as e:
            recipes_list = []
            sections_dict = {}
            print(f"[Excel] Error loading recipes/sections: {e}")

        def find_recipe(rkey):
            return next((r for r in recipes_list if r["recipe_key"] == rkey), None)

        thin = Side(border_style="thin", color="D3D3D3")
        thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)

        def style_row(row_idx, fill_color=None, bold=False, color="000000", size=10, center_cols=()):
            for col in range(1, 7):
                cell = ws.cell(row_idx, col)
                cell.border = thin_border
                if fill_color:
                    cell.fill = PatternFill("solid", fgColor=fill_color)
                cell.font = Font(name="Segoe UI", size=size, bold=bold, color=color)
                if col in center_cols:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

        # ── Canvas data ────────────────────────────────────────────────────────
        counts = self._compute_canvas_counts()
        scene_items = self._app.scene.items()
        from canvas import SmartPole
        poles = [i for i in scene_items if isinstance(i, SmartPole)]
        new_lt_poles = [p for p in poles if not p.is_existing and p.pole_type == "LT"]

        lt_recipe_counts: dict = {}
        for p in new_lt_poles:
            rkey = getattr(p, "iron_recipe", "None") or "None"
            if rkey == "None":
                rkey = "POLE_LT_IRON"
            lt_recipe_counts[rkey] = lt_recipe_counts.get(rkey, 0) + 1

        new_ht_poles = [p for p in poles if not p.is_existing and p.pole_type == "HT"]
        ht_recipe_counts: dict = {}
        for p in new_ht_poles:
            rkey = getattr(p, "iron_recipe", "None") or "None"
            if rkey == "None":
                rkey = "POLE_HT_IRON"
            ht_recipe_counts[rkey] = ht_recipe_counts.get(rkey, 0) + 1

        ext_lt = [p for p in poles if not p.is_existing and p.pole_type == "LT"
                  and getattr(p, "has_extension", False)]
        lt_ext_count = len(ext_lt)
        avg_ext_lt = round(
            sum(float(getattr(p, "extension_height", 1.5) or 1.5) for p in ext_lt) / lt_ext_count
            if lt_ext_count else 1.5, 2)

        ext_ht = [p for p in poles if not p.is_existing and p.pole_type == "HT"
                  and getattr(p, "has_extension", False)]
        avg_ext_ht = round(
            sum(float(getattr(p, "extension_height", 3.0) or 3.0) for p in ext_ht) / len(ext_ht)
            if ext_ht else 3.0, 2)

        def _lf(lpp, qpo, stored=""):
            if stored and str(stored).strip():
                s = str(stored).strip()
                return s if s.startswith("=") else f"={s}"
            return f"={qpo}*{lpp}" if qpo > 1 else str(lpp)

        # ── Build object list (title, canvas_count, items per object) ──────────
        # Each item: {description, section, lpp, qpo, lf}
        objects: list[dict] = []

        def add_recipe_obj(title, recipe_key, canvas_count):
            rec = find_recipe(recipe_key)
            if not rec or canvas_count <= 0:
                return
            items = []
            for ri in rec.get("items", []):
                lpp = float(ri.get("length_per_piece", ri.get("length", 0.0)))
                qpo = int(ri.get("qty_per_object", ri.get("qty", 1)))
                if lpp <= 0:
                    continue
                items.append({
                    "description": ri.get("description", ""),
                    "section": ri.get("section", ""),
                    "lpp": lpp, "qpo": qpo,
                    "lf": _lf(lpp, qpo, ri.get("length_formula", "")),
                })
            if items:
                objects.append({"title": title, "canvas_count": canvas_count, "items": items})

        def add_direct_obj(title, canvas_count, direct_items):
            if canvas_count <= 0:
                return
            items = [dict(it) for it in direct_items if it.get("lpp", 0) > 0]
            if items:
                objects.append({"title": title, "canvas_count": canvas_count, "items": items})

        # Build objects in logical order matching the estimate
        for rkey, cnt in lt_recipe_counts.items():
            rec = find_recipe(rkey)
            label = rec["name"] if rec else rkey
            add_recipe_obj(f"LT Pole Iron — {label}", rkey, cnt)

        add_direct_obj(f"LT Pole Extension ({lt_ext_count} nos)", lt_ext_count, [
            {"description": "Single Pole Extension (Angle)", "section": "ANG_65X65X6",
             "lpp": avg_ext_lt, "qpo": 1, "lf": f"={avg_ext_lt}"},
        ])

        add_recipe_obj(f"DP Structure Iron", "DP_IRON", counts["dp_count"])

        add_recipe_obj(f"CG Cradle Guard Bracket ({counts.get('cg_pole_brackets', 0)} sets)", "CG_BRACKET", counts.get("cg_pole_brackets", 0))
        add_recipe_obj(f"CG Cradle Guard Bracket DP ({counts.get('cg_dp_brackets', 0)} sets)", "CG_DP_BRACKET", counts.get("cg_dp_brackets", 0))

        add_recipe_obj(f"TP Structure Iron", "TP_IRON", counts["tp_count"])
        add_recipe_obj(f"4-Pole Structure Iron", "4P_IRON", counts["4p_count"])
        add_recipe_obj(f"DTR Substation Iron", "DTR_IRON", counts["dtr_count"])

        # Structure extensions — mirrors the STRUCT_HT_EXT_2P/3P/4P recipes used
        # by rules 232-234 (channel ×pole_count, flat ×pole_count). Without this
        # the exported breakup omitted iron the live estimate already counts.
        from canvas import SmartStructure as _SmartStructure
        _all_structs = [i for i in scene_items if isinstance(i, _SmartStructure)]
        for _slabel, _stypes, _ppc in (("DP/DTR", ("DP", "DTR"), 2), ("TP", ("TP",), 3), ("4P", ("4P",), 4)):
            _grp = [s for s in _all_structs
                    if getattr(s, "structure_type", "") in _stypes and getattr(s, "has_extension", False)]
            if not _grp:
                continue
            _cnt = len(_grp)
            _avg = round(sum(float(getattr(s, "extension_height", 3.0) or 3.0) for s in _grp) / _cnt, 2)
            add_direct_obj(f"{_slabel} Structure Extension ({_cnt} nos)", _cnt, [
                {"description": "Structure Extension (Channel)", "section": "CH_75X40",
                 "lpp": round(_avg * 2, 2), "qpo": _ppc, "lf": f"={_ppc}*{_avg}*2"},
                {"description": "Structure Extension (Flat)", "section": "FLAT_65X6",
                 "lpp": 3.0, "qpo": _ppc, "lf": f"={_ppc}*3"},
            ])

        for rkey, cnt in ht_recipe_counts.items():
            rec = find_recipe(rkey)
            label = rec["name"] if rec else rkey
            add_recipe_obj(f"HT Pole Iron — {label}", rkey, cnt)

        add_direct_obj(f"HT Pole Extension ({counts['ht_ext_count']} nos)", counts["ht_ext_count"], [
            {"description": "HT Pole Extension (Channel)", "section": "CH_75X40",
             "lpp": round(avg_ext_ht * 2, 2), "qpo": 1, "lf": f"={avg_ext_ht}*2"},
            {"description": "HT Pole Extension (Flat)", "section": "FLAT_65X6",
             "lpp": 3.0, "qpo": 1, "lf": "=3"},
        ])

        add_recipe_obj(f"LT ACSR Bracket ({counts['lt_acsr_count']} poles)", "LT_ACSR_BRACKET", counts["lt_acsr_count"])
        add_recipe_obj(f"AB Cable Clamp ({counts['ab_cable_count']} spans)", "AB_CABLE_CLAMP", counts["ab_cable_count"])

        # ── Build section → [objects with items for that section] ─────────────
        from collections import defaultdict
        extra_sections = []
        for obj in objects:
            for it in obj["items"]:
                if it["section"] not in SECTION_ORDER and it["section"] not in extra_sections:
                    extra_sections.append(it["section"])

        write_order = SECTION_ORDER + extra_sections
        section_map: dict = defaultdict(list)  # sec_code → [{title, canvas_count, sec_items}]
        for obj in objects:
            for sec_code in write_order:
                sec_items = [it for it in obj["items"] if it["section"] == sec_code]
                if sec_items:
                    section_map[sec_code].append({
                        "title": obj["title"],
                        "canvas_count": obj["canvas_count"],
                        "sec_items": sec_items,
                    })

        section_totals: dict[str, float] = {}  # sec_code → total MT (Python-side)

        # ── Write sheet ────────────────────────────────────────────────────────
        cr = 1
        ws.merge_cells(start_row=cr, start_column=1, end_row=cr, end_column=6)
        ws.cell(cr, 1, "IRON CALCULATION BREAKUP")
        ws.cell(cr, 1).fill = PatternFill("solid", fgColor="1F4E79")
        ws.cell(cr, 1).font = Font(name="Segoe UI", bold=True, size=13, color="FFFFFF")
        ws.cell(cr, 1).alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[cr].height = 30
        cr += 1

        # Column headers
        for col, hdr in enumerate(["No.", "Description", "No", "Length (m)", "Total (m)", "Iron (MT)"], 1):
            ws.cell(cr, col, hdr)
        style_row(cr, fill_color="2E75B6", bold=True, color="FFFFFF", center_cols=(1, 3, 4, 5, 6))
        ws.row_dimensions[cr].height = 18
        cr += 1

        section_letter_idx = ord('A')
        all_section_iron_f: list[str] = []  # section-total F-cell refs for grand total

        for sec_code in write_order:
            sec_objects = section_map.get(sec_code, [])
            if not sec_objects:
                continue

            kg_m = KG_PER_METRE.get(sec_code)
            if not kg_m and sec_code in sections_dict:
                kg_m = sections_dict[sec_code].get("kg_per_metre", 0.0)
            kg_m = kg_m or 0.0
            sec_label = SECTION_LABELS.get(sec_code, sec_code)
            letter = chr(section_letter_idx)
            section_letter_idx += 1

            # ── Section header ─────────────────────────────────────────────────
            ws.cell(cr, 1, letter)
            ws.cell(cr, 2, f"{sec_label}  —  {kg_m} kg/m")
            ws.cell(cr, 6, "Iron (MT)")
            style_row(cr, fill_color="4472C4", bold=True, color="FFFFFF", size=11,
                      center_cols=(1, 3, 4, 5, 6))
            ws.merge_cells(start_row=cr, start_column=2, end_row=cr, end_column=5)
            ws.row_dimensions[cr].height = 22
            cr += 1

            sec_obj_iron_f: list[str] = []  # object-total F-cell refs for this section

            for obj in sec_objects:
                # Object sub-header
                ws.cell(cr, 2, f"  ↳  {obj['title']}  ({obj['canvas_count']} nos on canvas)")
                style_row(cr, fill_color="BDD7EE", bold=True, size=10, center_cols=())
                ws.merge_cells(start_row=cr, start_column=2, end_row=cr, end_column=6)
                ws.row_dimensions[cr].height = 18
                cr += 1

                # Item rows
                item_f_start = cr
                for row_idx, it in enumerate(obj["sec_items"], 1):
                    ws.cell(cr, 1, row_idx)
                    ws.cell(cr, 2, it["description"])
                    ws.cell(cr, 3, obj["canvas_count"])
                    ws.cell(cr, 4, it["lf"])
                    ws.cell(cr, 5, f"=C{cr}*D{cr}")
                    ws.cell(cr, 6, f"=ROUND(E{cr}*{kg_m}/1000,6)")
                    ws.cell(cr, 6).number_format = '0.000'
                    ws.cell(cr, 5).number_format = '0.00'
                    fill = "FFFFFF" if row_idx % 2 != 0 else "EBF3FB"
                    style_row(cr, fill_color=fill, center_cols=(1, 3))
                    ws.row_dimensions[cr].height = 17
                    mt_val = (it["lpp"] * it["qpo"] * obj["canvas_count"] * kg_m) / 1000.0
                    section_totals[sec_code] = section_totals.get(sec_code, 0.0) + mt_val
                    cr += 1

                item_f_end = cr - 1

                # Object total row
                ws.cell(cr, 2, f"  Iron Total — {obj['title']}")
                ws.cell(cr, 5, f"=SUM(E{item_f_start}:E{item_f_end})")
                ws.cell(cr, 6, f"=SUM(F{item_f_start}:F{item_f_end})")
                ws.cell(cr, 5).number_format = '0.00'
                ws.cell(cr, 6).number_format = '0.000'
                style_row(cr, fill_color="E2EFDA", bold=True, center_cols=(5, 6))
                ws.row_dimensions[cr].height = 18
                sec_obj_iron_f.append(f"F{cr}")
                cr += 1

            # Section total (sum of all object totals for this section)
            sec_formula = "+".join(sec_obj_iron_f) if sec_obj_iron_f else "0"
            ws.cell(cr, 2, f"Section Total — {sec_label}")
            ws.cell(cr, 6, f"=ROUND({sec_formula},3)")
            ws.cell(cr, 6).number_format = '0.000'
            style_row(cr, fill_color="D9E1F2", bold=True, size=11, center_cols=(6,))
            ws.row_dimensions[cr].height = 20
            all_section_iron_f.append(f"F{cr}")
            cr += 2  # blank row between sections

        # ── Iron Summary + Grand Total ─────────────────────────────────────────
        if section_totals:
            cr += 1  # extra blank row before summary block

            # IRON SUMMARY header
            ws.merge_cells(start_row=cr, start_column=1, end_row=cr, end_column=6)
            ws.cell(cr, 1, "IRON SUMMARY")
            ws.cell(cr, 1).fill = PatternFill("solid", fgColor="1F4E79")
            ws.cell(cr, 1).font = Font(name="Segoe UI", bold=True, size=12, color="FFFFFF")
            ws.cell(cr, 1).alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[cr].height = 24
            cr += 1

            # One row per section type with MT > 0
            section_total_cells: list[str] = []
            for sec_code in SECTION_ORDER:
                if section_totals.get(sec_code, 0.0) <= 0:
                    continue
                sec_label = SECTION_LABELS.get(sec_code, sec_code)
                ws.cell(cr, 2, sec_label)
                ws.cell(cr, 6, round(section_totals[sec_code], 3))
                ws.cell(cr, 6).number_format = '0.000'
                style_row(cr, fill_color="D9E1F2", bold=False, center_cols=(6,))
                ws.row_dimensions[cr].height = 17
                section_total_cells.append(f"F{cr}")
                cr += 1

            cr += 1  # blank row before totals

            # Total iron (as per estimate)
            grand_formula = "+".join(section_total_cells) if section_total_cells else "0"
            ws.cell(cr, 2, "TOTAL IRON (as per Estimate):")
            ws.cell(cr, 6, f"=ROUND({grand_formula},3)")
            ws.cell(cr, 6).number_format = '0.000'
            style_row(cr, fill_color="FFF2CC", bold=True, size=11, center_cols=(6,))
            ws.row_dimensions[cr].height = 22
            grand_row = cr
            cr += 1

            # Wastage @ 3%
            ws.cell(cr, 2, "  Add: Fabrication Wastage @ 3%:")
            ws.cell(cr, 6, f"=ROUND(F{grand_row}*0.03,3)")
            ws.cell(cr, 6).number_format = '0.000'
            style_row(cr, fill_color="FFF2CC", bold=True, center_cols=(6,))
            ws.row_dimensions[cr].height = 18
            wastage_row = cr
            cr += 1

            # Final total — no "procurement" language
            ws.cell(cr, 2, "TOTAL IRON (incl. wastage):")
            ws.cell(cr, 6, f"=ROUND(F{grand_row}+F{wastage_row},3)")
            ws.cell(cr, 6).number_format = '0.000 "MT"'
            style_row(cr, fill_color="C6EFCE", bold=True, size=12, center_cols=(6,))
            ws.row_dimensions[cr].height = 26

