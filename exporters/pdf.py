"""
pdf_exporter.py
===============
PDFExporter class — all PDF generation logic extracted from app.py.

Usage::

    from pdf_exporter import PDFExporter
    PDFExporter(app_instance).export()
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QRectF, QPointF, QLineF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath,
    QPageLayout, QPageSize, QFont,
)
from PyQt6.QtCore import QMarginsF
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from app_config import APP_DISPLAY_NAME, APP_VERSION
from canvas import SmartPole, SmartStructure, SmartSpan, SmartConsumer

if TYPE_CHECKING:
    from app import EstimateApp


class PDFExporter:
    """Handles all PDF export logic for the ERP Estimate Generator."""

    # ── PDF layout constants ──────────────────────────────────────────────────
    MARG_T = MARG_B = MARG_L = MARG_R = 10
    PAGE_EDGE_GAP  = 20
    TITLE_H_MIN   = 20   # minimum title strip height (device px) when text fits on one line
    FOOTER_H       = 16   # footer strip height
    LEGEND_RESERVE = 140  # px reserved at bottom of last page for the legend box

    def __init__(self, app: "EstimateApp") -> None:
        self._app = app

    # ── Static page geometry helpers ─────────────────────────────────────────

    @staticmethod
    def _layout_for(orient: str) -> QPageLayout:
        qt_orient = (
            QPageLayout.Orientation.Portrait
            if orient == "P"
            else QPageLayout.Orientation.Landscape
        )
        return QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            qt_orient,
            QMarginsF(0, 0, 0, 0),
        )

    @staticmethod
    def _span_pen_for_export(span: SmartSpan) -> QPen:
        color = span._PEN_COLORS.get(span.conductor, QColor("#222222"))
        pen = QPen(color, 1.8)
        if span.is_existing_span:
            pen.setStyle(Qt.PenStyle.SolidLine)
            pen.setWidthF(1.2)
        elif span.conductor == "ACSR":
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    @staticmethod
    def _scene_to_page_pt(
        scene_pt: QPointF,
        render_rect: QRectF,
        src_rect: QRectF,
    ) -> QPointF:
        if src_rect.width() <= 0 or src_rect.height() <= 0:
            return QPointF(render_rect.left(), render_rect.top())
        sx = render_rect.width()  / src_rect.width()
        sy = render_rect.height() / src_rect.height()
        return QPointF(
            render_rect.left() + (scene_pt.x() - src_rect.left()) * sx,
            render_rect.top()  + (scene_pt.y() - src_rect.top())  * sy,
        )

    @staticmethod
    def _anchor_scene_for_mark(
        span: SmartSpan,
        marker_scene: QPointF,
        src_rect: QRectF,
    ) -> QPointF:
        p1 = span.p1.pos()
        p2 = span.p2.pos()
        p1_in = src_rect.contains(p1)
        p2_in = src_rect.contains(p2)

        if p1_in and not p2_in:
            return p1
        if p2_in and not p1_in:
            return p2

        if not p1_in and not p2_in:
            line = QLineF(p1, p2)
            edges = [
                QLineF(src_rect.topLeft(),    src_rect.topRight()),
                QLineF(src_rect.topRight(),   src_rect.bottomRight()),
                QLineF(src_rect.bottomRight(),src_rect.bottomLeft()),
                QLineF(src_rect.bottomLeft(), src_rect.topLeft()),
            ]
            hits: list[QPointF] = []
            for e in edges:
                inter_type, pt = line.intersects(e)
                if inter_type == QLineF.IntersectionType.BoundedIntersection and pt is not None:
                    hits.append(pt)
            if hits:
                return max(
                    hits,
                    key=lambda p: (p.x() - marker_scene.x()) ** 2
                                + (p.y() - marker_scene.y()) ** 2,
                )

        d1 = (p1.x() - marker_scene.x()) ** 2 + (p1.y() - marker_scene.y()) ** 2
        d2 = (p2.x() - marker_scene.x()) ** 2 + (p2.y() - marker_scene.y()) ** 2
        return p1 if d1 <= d2 else p2

    # ── Continuation mark helpers ─────────────────────────────────────────────

    def _build_continuation_marks_for_tiles(
        self,
        tiles: list[dict],
        inset_scene: float = 20.0,
    ) -> dict[int, list[dict]]:
        """Build O---A / A---O continuation marks for neighbouring tiles."""
        if not tiles:
            return {}

        spans = [i for i in self._app.scene.items() if isinstance(i, SmartSpan)]
        tile_lookup = {(t.get("row", 0), t.get("col", 0)): t for t in tiles}

        def _continuation_label(idx: int) -> str:
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if idx < len(alphabet):
                return alphabet[idx]
            return f"{alphabet[idx % len(alphabet)]}{idx // len(alphabet) + 1}"

        def _inset_point(hit_pt: QPointF, side: str) -> QPointF:
            pt = QPointF(hit_pt)
            if side == "right":
                pt.setX(pt.x() - inset_scene)
            elif side == "left":
                pt.setX(pt.x() + inset_scene)
            elif side == "bottom":
                pt.setY(pt.y() - inset_scene)
            else:  # top
                pt.setY(pt.y() + inset_scene)
            return pt

        def _anchor_on_rect(
            span: SmartSpan, rect: QRectF, marker_pt: QPointF
        ) -> QPointF:
            p1 = span.p1.pos()
            p2 = span.p2.pos()
            p1_in = rect.contains(p1)
            p2_in = rect.contains(p2)

            if p1_in and not p2_in:
                return p1
            if p2_in and not p1_in:
                return p2

            if not p1_in and not p2_in:
                line = QLineF(p1, p2)
                edges = [
                    QLineF(rect.topLeft(),    rect.topRight()),
                    QLineF(rect.topRight(),   rect.bottomRight()),
                    QLineF(rect.bottomRight(),rect.bottomLeft()),
                    QLineF(rect.bottomLeft(), rect.topLeft()),
                ]
                hits: list[QPointF] = []
                for edge in edges:
                    inter_type, pt = line.intersects(edge)
                    if inter_type == QLineF.IntersectionType.BoundedIntersection and pt is not None:
                        hits.append(pt)
                if hits:
                    return max(
                        hits,
                        key=lambda p: (p.x() - marker_pt.x()) ** 2
                                    + (p.y() - marker_pt.y()) ** 2,
                    )

            d1 = (p1.x() - marker_pt.x()) ** 2 + (p1.y() - marker_pt.y()) ** 2
            d2 = (p2.x() - marker_pt.x()) ** 2 + (p2.y() - marker_pt.y()) ** 2
            return p1 if d1 <= d2 else p2

        marks: dict[int, list[dict]] = {t.get("page_num", 0): [] for t in tiles}
        marker_idx = 0

        for tile in tiles:
            row  = tile.get("row", 0)
            col  = tile.get("col", 0)
            rect = tile["rect"]

            neighbors = [
                ("right",  tile_lookup.get((row, col + 1))),
                ("bottom", tile_lookup.get((row + 1, col))),
            ]
            for edge_kind, neighbor in neighbors:
                if neighbor is None:
                    continue

                if edge_kind == "right":
                    boundary    = QLineF(rect.topRight(), rect.bottomRight())
                    source_side = "right"
                    target_side = "left"
                else:
                    boundary    = QLineF(rect.bottomLeft(), rect.bottomRight())
                    source_side = "bottom"
                    target_side = "top"

                for span in spans:
                    span_rect = span.sceneBoundingRect()
                    if not rect.intersects(span_rect):
                        continue
                    if not neighbor["rect"].intersects(span_rect):
                        continue

                    line = QLineF(span.p1.pos(), span.p2.pos())
                    intersection_type, hit_pt = line.intersects(boundary)
                    if intersection_type != QLineF.IntersectionType.BoundedIntersection:
                        continue
                    if hit_pt is None:
                        continue

                    label = _continuation_label(marker_idx)
                    marker_idx += 1

                    marks.setdefault(tile["page_num"], []).append({
                        "page_num":            tile["page_num"],
                        "label":               label,
                        "scene_point":         hit_pt,
                        "marker_scene_point":  _inset_point(hit_pt, source_side),
                        "anchor_scene_point":  _anchor_on_rect(
                            span, rect, _inset_point(hit_pt, source_side)
                        ),
                        "side":        source_side,
                        "target_page": neighbor["page_num"],
                        "span":        span,
                    })
                    marks.setdefault(neighbor["page_num"], []).append({
                        "page_num":           neighbor["page_num"],
                        "label":              label,
                        "scene_point":        hit_pt,
                        "marker_scene_point": _inset_point(hit_pt, target_side),
                        "anchor_scene_point": _anchor_on_rect(
                            span, neighbor["rect"], _inset_point(hit_pt, target_side)
                        ),
                        "side":        target_side,
                        "target_page": tile["page_num"],
                        "span":        span,
                    })

        return marks

    def _position_split_span_labels(self, continuation_marks: dict[int, list[dict]]) -> None:
        """Place each split span's real label on the incoming A---O segment once."""
        incoming_by_span: dict[int, dict] = {}
        for marks in continuation_marks.values():
            for mark in marks:
                span = mark.get("span")
                if span is None:
                    continue
                if mark.get("target_page", 0) < mark.get("page_num", 0):
                    incoming_by_span[id(span)] = mark

        for mark in incoming_by_span.values():
            span = mark.get("span")
            if span is None or not hasattr(span, "label"):
                continue
            lbl = span.label
            if getattr(lbl, "user_moved", False):
                continue

            marker = mark.get("marker_scene_point")
            anchor = mark.get("anchor_scene_point")
            if marker is None or anchor is None:
                continue

            p1 = span.p1.pos()
            p2 = span.p2.pos()
            default_mid  = QPointF((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0)
            label_center = lbl.sceneBoundingRect().center()
            if (
                abs(label_center.x() - default_mid.x()) > 35.0
                or abs(label_center.y() - default_mid.y()) > 35.0
            ):
                lbl.user_moved = True
                continue

            mid_x = (marker.x() + anchor.x()) / 2.0
            mid_y = (marker.y() + anchor.y()) / 2.0
            lw = lbl.boundingRect().width()
            lbl.set_auto_pos(mid_x - lw / 2.0, mid_y - 12.0)

    # ── Stub renderer ────────────────────────────────────────────────────────

    def _draw_continuation_stub(
        self,
        painter: QPainter,
        draw_rect: QRectF,
        render_rect: QRectF,
        src_rect: QRectF,
        mark: dict,
    ) -> None:
        span = mark.get("span")
        if span is None:
            return

        marker_scene = mark.get("marker_scene_point", mark["scene_point"])
        marker_page  = self._scene_to_page_pt(marker_scene, render_rect, src_rect)
        radius = 10.0
        marker_page.setX(max(draw_rect.left() + radius + 2.0,
                             min(draw_rect.right() - radius - 2.0, marker_page.x())))
        marker_page.setY(max(draw_rect.top() + radius + 2.0,
                             min(draw_rect.bottom() - radius - 2.0, marker_page.y())))

        anchor_scene = mark.get("anchor_scene_point")
        if anchor_scene is None:
            anchor_scene = self._anchor_scene_for_mark(span, marker_scene, src_rect)
        anchor_page = self._scene_to_page_pt(anchor_scene, render_rect, src_rect)

        painter.save()
        painter.setClipRect(draw_rect)

        # Draw visible stub segment inside the page: O---A or A---O
        painter.setPen(self._span_pen_for_export(span))
        painter.drawLine(anchor_page, marker_page)

        # Draw circled marker label
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.setPen(QPen(QColor(180, 60, 60), 1.2))
        painter.drawEllipse(marker_page, radius, radius)

        painter.setPen(QColor(180, 60, 60))
        painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(
                marker_page.x() - radius,
                marker_page.y() - radius - 1,
                radius * 2,
                radius * 2,
            ),
            Qt.AlignmentFlag.AlignCenter,
            mark["label"],
        )

        # Page reference near marker (e.g., "Pg 3")
        target_page = mark.get("target_page")
        if target_page is not None:
            painter.setPen(QColor(160, 55, 55))
            painter.setFont(QFont("Arial", 7))
            side = mark.get("side", "right")
            if side in ("left", "right"):
                # Horizontal page crossing → page ref above A
                txt_rect = QRectF(marker_page.x() - 21, marker_page.y() - 26, 42, 14)
                align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
            else:
                # Vertical page crossing → page ref to the right of A
                txt_rect = QRectF(marker_page.x() + 14, marker_page.y() - 7, 42, 14)
                align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(txt_rect, align, f"Pg {target_page}")

        painter.restore()

    # ── Legend renderer ──────────────────────────────────────────────────────

    @staticmethod
    def _draw_legend_symbol(painter: QPainter, rect: QRectF, kind: str) -> None:
        """Paint a mini canonical symbol matching the canvas colours/shapes.

        Colours are pulled live from defaults.current so any user customisation
        in the Property Editor is reflected here too.
        """
        from core import defaults
        d = defaults.current
        cx, cy = rect.center().x(), rect.center().y()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        def _circle(color_hex, r=3.0, ox=0.0, oy=0.0, border="#333333", bw=0.5):
            painter.setBrush(QBrush(QColor(color_hex)))
            painter.setPen(QPen(QColor(border), bw))
            painter.drawEllipse(QPointF(cx + ox, cy + oy), r, r)

        def _square(color_hex, r=2.2, ox=0.0, oy=0.0, border="#333333", bw=0.5):
            painter.setBrush(QBrush(QColor(color_hex)))
            painter.setPen(QPen(QColor(border), bw))
            painter.drawRect(QRectF(cx + ox - r, cy + oy - r, r * 2, r * 2))

        if kind == "lt_pole":
            painter.setBrush(QBrush(QColor(d.get("canvas_lt_pole", "#2980b9"))))
            painter.setPen(QPen(QColor("#222222"), 0.5))
            painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
            painter.setPen(QPen(QColor("#ffffff")))
            font = QFont("Arial", 4, QFont.Weight.Bold)
            font.setPixelSize(5)
            painter.setFont(font)
            painter.drawText(QRectF(cx - 3.5, cy - 3.5, 7, 7), Qt.AlignmentFlag.AlignCenter, "LT")
        elif kind == "ht_pole":
            painter.setBrush(QBrush(QColor(d.get("canvas_ht_pole", "#c0392b"))))
            painter.setPen(QPen(QColor("#222222"), 0.5))
            painter.drawRect(QRectF(cx - 3.5, cy - 3.5, 7, 7))
            painter.setPen(QPen(QColor("#ffffff")))
            font = QFont("Arial", 4, QFont.Weight.Bold)
            font.setPixelSize(5)
            painter.setFont(font)
            painter.drawText(QRectF(cx - 3.5, cy - 3.5, 7, 7), Qt.AlignmentFlag.AlignCenter, "HT")
        elif kind == "ex_lt_pole":
            painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
            painter.setPen(QPen(QColor("#222222"), 0.8))
            painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
            painter.setPen(QPen(QColor("#222222")))
            font = QFont("Arial", 4, QFont.Weight.Bold)
            font.setPixelSize(5)
            painter.setFont(font)
            painter.drawText(QRectF(cx - 3.5, cy - 3.5, 7, 7), Qt.AlignmentFlag.AlignCenter, "LT")
        elif kind == "ex_ht_pole":
            painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
            painter.setPen(QPen(QColor("#222222"), 0.8))
            painter.drawRect(QRectF(cx - 3.5, cy - 3.5, 7, 7))
            painter.setPen(QPen(QColor("#222222")))
            font = QFont("Arial", 4, QFont.Weight.Bold)
            font.setPixelSize(5)
            painter.setFont(font)
            painter.drawText(QRectF(cx - 3.5, cy - 3.5, 7, 7), Qt.AlignmentFlag.AlignCenter, "HT")
        elif kind == "ex_pole":
            _circle(d.get("canvas_ex_pole", "#cccccc"), border="#777777", bw=0.6)

        elif kind == "dp":
            col = d.get("canvas_dp", "#27ae60")
            _circle(col, 2.2, -2.6); _circle(col, 2.2, 2.6)
        elif kind == "tp":
            col = d.get("canvas_tp", "#1abc9c")
            _circle(col, 2.0, 0.0, -2.2); _circle(col, 2.0, -2.4, 1.8); _circle(col, 2.0, 2.4, 1.8)
        elif kind == "4p":
            col = d.get("canvas_4p", "#16a085")
            for ox in (-2.4, 2.4):
                for oy in (-2.4, 2.4):
                    _circle(col, 1.9, ox, oy)
        elif kind == "dtr":
            col = d.get("canvas_dtr", "#e67e22")
            painter.setBrush(QBrush(QColor(col)))
            painter.setPen(QPen(QColor("#333333"), 0.4))
            painter.drawRect(QRectF(cx - 2.0, cy - 1.6, 4.0, 3.2))
            _circle(col, 2.0, -3.2); _circle(col, 2.0, 3.2)
        elif kind == "consumer":
            painter.setBrush(QBrush(QColor(d.get("canvas_consumer", "#f1c40f"))))
            painter.setPen(QPen(QColor("#7a5a00"), 0.5))
            painter.drawRect(QRectF(cx - 3, cy - 2.4, 6, 4.8))
        elif kind == "earth":
            painter.setPen(QPen(QColor("#333333"), 0.7))
            painter.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy))
            painter.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
            painter.drawLine(QPointF(cx - 2, cy + 1.4), QPointF(cx + 2, cy + 1.4))
            painter.drawLine(QPointF(cx - 1, cy + 2.6), QPointF(cx + 1, cy + 2.6))
        elif kind == "stay":
            painter.setPen(QPen(QColor("#444444"), 0.7))
            painter.drawLine(QPointF(cx - 4, cy + 3), QPointF(cx + 3, cy - 3))
            painter.setBrush(QBrush(QColor("#444444")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx - 4, cy + 3), 0.9, 0.9)
        elif kind in ("span_acsr", "span_ab", "span_pvc", "span_existing", "span_svc"):
            colors = {
                "span_acsr":     d.get("canvas_acsr",      "#222222"),
                "span_ab":       d.get("canvas_ab_cable",  "#1a5276"),
                "span_pvc":      d.get("canvas_pvc_cable", "#107C41"),
                "span_existing": d.get("canvas_acsr",      "#222222"),
                "span_svc":      d.get("canvas_svc_drop",  "#d35400"),
            }
            color = QColor(colors[kind])
            x0 = rect.left() + 2
            x1 = rect.right() - 2
            if kind in ("span_ab", "span_pvc", "span_svc"):
                # Wavy line — AB Cable, PVC Cable and Service Drop are drawn as
                # sine waves on the canvas (see SmartSpan.update_visuals).
                painter.setPen(QPen(color, 1.1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath()
                path.moveTo(x0, cy)
                steps, cycles, amp = 26, 3.0, 1.8
                for i in range(1, steps + 1):
                    t = i / steps
                    off = math.sin(t * cycles * 2 * math.pi) * amp
                    path.lineTo(x0 + (x1 - x0) * t, cy + off)
                painter.drawPath(path)
            else:
                # ACSR dashed-straight, existing span thin-solid (matches canvas).
                pen = QPen(color, 1.3)
                if kind == "span_acsr":
                    pen.setStyle(Qt.PenStyle.DashLine)
                else:
                    pen.setWidthF(0.7)
                painter.setPen(pen)
                painter.drawLine(QPointF(x0, cy), QPointF(x1, cy))

        painter.restore()

    def _draw_pdf_legend(self, painter: QPainter, border: QRectF) -> None:
        app = self._app
        # Each entry carries a "draw" kind so the legend paints the SAME shapes
        # and colours the canvas uses (not emoji/ASCII, which never matched).
        legend_data = {
            "New LT Pole":      {"s": None, "draw": "lt_pole",    "q": 0},
            "New HT Pole":      {"s": None, "draw": "ht_pole",    "q": 0},
            "Existing LT Pole": {"s": None, "draw": "ex_lt_pole", "q": 0},
            "Existing HT Pole": {"s": None, "draw": "ex_ht_pole", "q": 0},
            "DP Structure":     {"s": None, "draw": "dp",         "q": 0},
            "TP Structure":     {"s": None, "draw": "tp",         "q": 0},
            "4P Structure":     {"s": None, "draw": "4p",         "q": 0},
            "DTR":              {"s": None, "draw": "dtr",        "q": 0},
            "Extension":        {"s": "[E]",                      "q": 0},
            "Consumer":         {"s": None, "draw": "consumer",   "q": 0},
            "Earthing":         {"s": None, "draw": "earth",      "q": 0},
            "Stay":             {"s": None, "draw": "stay",       "q": 0},
            "CG (SP)":          {"s": None, "draw": "cg",         "q": 0},
            "CG (DP)":          {"s": None, "draw": "cg",         "q": 0},
            "New ACSR":         {"s": None, "draw": "span_acsr",     "l": 0},
            "New AB Cable":     {"s": None, "draw": "span_ab",       "l": 0},
            "New PVC Cable":    {"s": None, "draw": "span_pvc",      "l": 0},
            "Existing Span":    {"s": None, "draw": "span_existing", "l": 0},
            "Service Drop":     {"s": None, "draw": "span_svc",      "l": 0},
        }

        for item in app.scene.items():
            if isinstance(item, SmartPole):
                legend_data["Earthing"]["q"] += item.earth_count
                legend_data["Stay"]["q"]     += item.stay_count
                if item.has_extension:
                    legend_data["Extension"]["q"] += 1
                if item.is_existing:
                    if item.existing_subtype == "HT":
                        legend_data["Existing HT Pole"]["q"] += 1
                    elif item.existing_subtype in ("DP", "TP", "4P", "DTR"):
                        st_key = item.existing_subtype if item.existing_subtype == "DTR" else f"{item.existing_subtype} Structure"
                        if st_key in legend_data:
                            legend_data[st_key]["q"] += 1
                    else:
                        legend_data["Existing LT Pole"]["q"] += 1
                elif item.pole_type == "LT":
                    legend_data["New LT Pole"]["q"] += 1
                else:
                    legend_data["New HT Pole"]["q"] += 1
            elif isinstance(item, SmartStructure):
                st_key = (
                    item.structure_type
                    if item.structure_type == "DTR"
                    else f"{item.structure_type} Structure"
                )
                if st_key in legend_data:
                    legend_data[st_key]["q"] += 1
                legend_data["Earthing"]["q"] += item.earth_count
                legend_data["Stay"]["q"]     += item.stay_count
                if item.has_extension:
                    legend_data["Extension"]["q"] += 1
            elif isinstance(item, SmartConsumer):
                legend_data["Consumer"]["q"] += 1
            elif isinstance(item, SmartSpan):
                if item.has_cg:
                    is_dp = isinstance(item.p1, SmartStructure) or isinstance(item.p2, SmartStructure)
                    legend_data["CG (DP)" if is_dp else "CG (SP)"]["q"] += 1
                key = (
                    "Service Drop"  if item.is_service_drop    else
                    "Existing Span" if item.is_existing_span   else
                    f"New {item.conductor}"
                )
                if key in legend_data:
                    if "l" in legend_data[key]:
                        legend_data[key]["l"] += item.length
                    else:
                        legend_data[key]["q"] = legend_data[key].get("q", 0) + 1

        used = []
        for desc, d in legend_data.items():
            q = d.get("q", 0)
            l = d.get("l", 0)
            if q > 0 or l > 0:
                val = str(q) if "q" in d else f"{int(l)}m"
                used.append({"desc": desc, "sym": d["s"], "draw": d.get("draw"), "val": val})

        if not used:
            return

        # Two side-by-side mini-tables to halve the vertical footprint.
        cw     = {"sl": 18, "sym": 22, "desc": 90, "qty": 34}
        ckeys  = list(cw.keys())
        half_w = sum(cw.values())
        gap    = 6
        total_w = half_w * 2 + gap

        row_h  = 14
        hdr_h  = 15
        ll_h   = 16

        mid       = (len(used) + 1) // 2
        left_col  = used[:mid]
        right_col = used[mid:]
        rows      = max(len(left_col), len(right_col))
        total_h   = hdr_h + rows * row_h + ll_h

        # Default anchor: bottom-right inside the provided border rect.
        leg_left = border.right()  - total_w - 5
        leg_top  = border.bottom() - total_h - 5
        leg_rect = QRectF(leg_left, leg_top, total_w, total_h)

        painter.save()
        painter.setOpacity(1.0)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(leg_rect)

        grid_pen   = QPen(QColor(170, 170, 170), 0.4)
        border_pen = QPen(Qt.GlobalColor.black, 0.7)

        def _sub_table(entries: list, left_x: float, number_offset: int) -> None:
            cy = leg_top
            painter.setBrush(QBrush(QColor(200, 200, 200, 200)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(left_x, cy, half_w, hdr_h))
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.setFont(QFont("Arial", 6, QFont.Weight.Bold))
            cx = left_x
            for k in ckeys:
                lbl = {"sl": "#", "sym": "Sym", "desc": "Description", "qty": "Qty"}[k]
                painter.drawText(QRectF(cx, cy, cw[k], hdr_h), Qt.AlignmentFlag.AlignCenter, lbl)
                cx += cw[k]
            cy += hdr_h

            painter.setPen(border_pen)
            painter.drawLine(QPointF(left_x, cy), QPointF(left_x + half_w, cy))

            painter.setPen(grid_pen)
            sx = left_x
            for k in ckeys[:-1]:
                sx += cw[k]
                painter.drawLine(QPointF(sx, leg_top), QPointF(sx, leg_top + total_h - ll_h))

            painter.setFont(QFont("Arial", 6))
            for i, entry in enumerate(entries):
                bg = QColor(248, 248, 248, 200) if i % 2 == 0 else QColor(255, 255, 255, 180)
                painter.setBrush(QBrush(bg))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(QRectF(left_x, cy, half_w, row_h))
                painter.setPen(QPen(Qt.GlobalColor.black))
                cx = left_x
                painter.drawText(QRectF(cx, cy, cw["sl"], row_h),
                                 Qt.AlignmentFlag.AlignCenter, str(i + 1 + number_offset))
                cx += cw["sl"]
                # Symbol — draw CG rail graphic or plain text
                sym_rect = QRectF(cx, cy, cw["sym"], row_h)
                if entry.get("draw") == "cg":
                    painter.save()
                    rail_cx = sym_rect.center().x()
                    rail_cy = sym_rect.center().y()
                    rail_hw = 6.8   # half-length of rail (subtle)
                    rail_sep = 2.0  # half-gap between the two rails
                    ext = rail_sep + 1.2  # sleepers poke slightly past rails
                    painter.setPen(QPen(QColor("#9ec5e8"), 0.8))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    # Rail A
                    painter.drawLine(QPointF(rail_cx - rail_hw, rail_cy - rail_sep),
                                     QPointF(rail_cx + rail_hw, rail_cy - rail_sep))
                    # Rail B
                    painter.drawLine(QPointF(rail_cx - rail_hw, rail_cy + rail_sep),
                                     QPointF(rail_cx + rail_hw, rail_cy + rail_sep))
                    # Sleepers (3, skip ends)
                    for si in range(1, 4):
                        sx = rail_cx - rail_hw + rail_hw * 2 * si / 4
                        painter.drawLine(QPointF(sx, rail_cy - ext),
                                         QPointF(sx, rail_cy + ext))
                    painter.restore()
                elif entry.get("draw"):
                    self._draw_legend_symbol(painter, sym_rect, entry["draw"])
                else:
                    painter.drawText(sym_rect, Qt.AlignmentFlag.AlignCenter, entry["sym"] or "")
                cx += cw["sym"]
                painter.drawText(QRectF(cx + 2, cy, cw["desc"] - 2, row_h),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                                 entry["desc"])
                cx += cw["desc"]
                painter.drawText(QRectF(cx, cy, cw["qty"], row_h),
                                 Qt.AlignmentFlag.AlignCenter, entry["val"])
                cy += row_h
                painter.setPen(grid_pen)
                painter.drawLine(QPointF(left_x, cy), QPointF(left_x + half_w, cy))

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(border_pen)
            painter.drawRect(QRectF(left_x, leg_top, half_w, total_h - ll_h))

        _sub_table(left_col,  leg_left,                  0)
        _sub_table(right_col, leg_left + half_w + gap, len(left_col))

        # Footer (coordinates) — full-width
        cy = leg_top + total_h - ll_h
        painter.setBrush(QBrush(QColor(220, 220, 220, 200)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(leg_left, cy, total_w, ll_h))
        painter.setPen(QPen(Qt.GlobalColor.black))
        painter.setFont(QFont("Arial", 6, QFont.Weight.Normal, True))
        painter.drawText(
            QRectF(leg_left, cy, total_w, ll_h),
            Qt.AlignmentFlag.AlignCenter,
            f"Lat: {app.project_meta.get('lat', '')}   Long: {app.project_meta.get('long', '')}",
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(border_pen)
        painter.drawRect(leg_rect)

        # Draw Signature Block if active profile exists
        from core import db_gateway as _dbg
        from PyQt6.QtGui import QImage
        import os
        profile = _dbg.get_active_profile()
        if profile and profile.get("signature_path"):
            sig_path = profile["signature_path"]
            if os.path.exists(sig_path):
                sig_img = QImage(sig_path)
                if not sig_img.isNull():
                    sig_w = 80
                    sig_h = 35
                    sig_left = leg_left - sig_w - 10
                    sig_top = border.bottom() - sig_h - 5
                    painter.save()
                    # Border
                    painter.setPen(QPen(QColor(180, 180, 180), 0.5))
                    painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
                    painter.drawRect(QRectF(sig_left, sig_top - 12, sig_w, sig_h + 12))
                    # Image
                    painter.drawImage(QRectF(sig_left, sig_top, sig_w, sig_h), sig_img)
                    # Text label
                    painter.setFont(QFont("Arial", 5, QFont.Weight.Bold))
                    painter.setPen(Qt.GlobalColor.black)
                    painter.drawText(QRectF(sig_left, sig_top - 12, sig_w, 12), Qt.AlignmentFlag.AlignCenter, "Signature")
                    painter.restore()

        painter.restore()


    # ── Main export entry point ──────────────────────────────────────────────

    def export(
        self,
        output_path: str | None = None,
        initial_dir: str | None = None,
        show_success: bool = True,
    ) -> str | None:
        """
        Export a multi-page PDF whose page layout matches the canvas page grid.
        Each tile visible in the grid becomes one page in the PDF.
        """
        app = self._app
        m   = app.project_meta

        subject = m.get("subject", "Project_Drawing")
        safe    = "".join(c for c in subject if c not in r'\/*?:"<>|')
        default = f"{safe}.pdf" if safe else "Project_Drawing.pdf"

        filename = output_path
        if not filename:
            start_path = default
            if initial_dir:
                start_path = os.path.join(initial_dir.rstrip('/\\'), default)
            filename, _ = QFileDialog.getSaveFileName(
                app, "Export PDF Drawing", start_path, "PDF Files (*.pdf)"
            )
            if not filename:
                return None

        if app.scene.itemsBoundingRect().isNull():
            QMessageBox.warning(app, "Empty Canvas", "Nothing to export.")
            return None

        app._refresh_page_grid()
        tiles = app.view.grid_tiles
        if not tiles:
            QMessageBox.warning(app, "Empty Canvas", "Nothing to export.")
            return None

        total_pages = tiles[0]["total"]

        MARG_T, MARG_B = self.MARG_T, self.MARG_B
        MARG_L, MARG_R = self.MARG_L, self.MARG_R
        PAGE_EDGE_GAP  = self.PAGE_EDGE_GAP
        TITLE_H_MIN    = self.TITLE_H_MIN
        FOOTER_H       = self.FOOTER_H

        printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(filename)
        printer.setFullPage(True)

        drawable_items = [
            i for i in app.scene.items()
            if isinstance(i, (SmartPole, SmartStructure, SmartConsumer, SmartSpan))
        ]
        continuation_marks = self._build_continuation_marks_for_tiles(tiles, inset_scene=20.0)

        painter: QPainter | None = None

        for page_idx, tile in enumerate(tiles):
            src_rect = tile["rect"]
            page_num = tile["page_num"]
            is_last  = (page_idx == len(tiles) - 1)
            orient   = tile.get("orient", "L")

            if painter is None:
                printer.setPageLayout(self._layout_for(orient))
                painter = QPainter(printer)
            else:
                printer.setPageLayout(self._layout_for(orient))
                printer.newPage()

            paper  = printer.paperRect(QPrinter.Unit.DevicePixel)
            page_w = paper.width()  - MARG_L - MARG_R
            page_h = paper.height() - MARG_T  - MARG_B
            ox, oy = MARG_L, MARG_T

            # ── Dynamic title height based on actual text content ─────────────
            title_text = (m.get("subject") or "ERP PROJECT DRAWING") if app.pdf_show_project_name else ""
            if title_text:
                from PyQt6.QtGui import QTextDocument
                _doc = QTextDocument()
                _doc.setDefaultFont(QFont("Arial", 9, QFont.Weight.Bold))
                _doc.setTextWidth(page_w * 0.70 - 8)
                _doc.setPlainText(title_text)
                TITLE_H = max(TITLE_H_MIN, int(_doc.size().height()) + 10)
            else:
                TITLE_H = TITLE_H_MIN
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(180, 180, 180), 0.8))
            painter.drawRect(QRectF(ox, oy, page_w, page_h))

            # ── Title strip ───────────────────────────────────────────────
            painter.fillRect(QRectF(ox, oy, page_w, TITLE_H), QColor(240, 244, 250))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            if title_text:
                painter.drawText(
                    QRectF(ox + 4, oy + 4, page_w * 0.70 - 8, TITLE_H - 4),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                    | Qt.TextFlag.TextWordWrap,
                    title_text,
                )
            painter.setFont(QFont("Arial", 8))
            painter.drawText(
                QRectF(ox + page_w * 0.70, oy, page_w * 0.30 - 4, TITLE_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"Page {page_num} / {total_pages}   [Scale 1:{app.pdf_scale}]",
            )
            painter.setPen(QPen(QColor(180, 180, 180), 0.5))
            painter.drawLine(
                QPointF(ox, oy + TITLE_H), QPointF(ox + page_w, oy + TITLE_H)
            )

            # ── Footer strip ──────────────────────────────────────────────
            footer_y = oy + page_h - FOOTER_H
            painter.fillRect(QRectF(ox, footer_y, page_w, FOOTER_H), QColor(240, 244, 250))
            painter.setPen(QPen(QColor(180, 180, 180), 0.5))
            painter.drawLine(QPointF(ox, footer_y), QPointF(ox + page_w, footer_y))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(QFont("Arial", 7))
            
            from core import db_gateway as _dbg
            active_profile = _dbg.get_active_profile()
            profile_txt = f"{active_profile['firm_name']}  |  " if active_profile else ""
            
            date_str   = datetime.now().strftime("%d-%m-%Y")
            footer_txt = (
                f"{m.get('project_type','')}  |  "
                f"{date_str}  |  "
                f"Lat: {m.get('lat', '')}   Long: {m.get('long', '')}  |  "
                f"{profile_txt}"
                f"{APP_DISPLAY_NAME} v{APP_VERSION}"
            )
            painter.drawText(
                QRectF(ox + 4, footer_y, page_w - 8, FOOTER_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                footer_txt,
            )

            # ── Drawing area ──────────────────────────────────────────────
            draw_top  = oy + TITLE_H + 2
            draw_h    = page_h - TITLE_H - FOOTER_H - 4
            draw_rect = QRectF(
                ox + PAGE_EDGE_GAP,
                draw_top + PAGE_EDGE_GAP,
                max(1.0, page_w - 2 * PAGE_EDGE_GAP),
                max(1.0, draw_h  - 2 * PAGE_EDGE_GAP),
            )

            # Reserve legend strip only when last-page bottom-right has content.
            # This keeps full drawing scale when the corner is already empty.
            if is_last and app.pdf_show_legend:
                probe_scene = QRectF(
                    src_rect.left() + src_rect.width() * 0.58,
                    src_rect.top() + src_rect.height() * 0.62,
                    src_rect.width() * 0.42,
                    src_rect.height() * 0.38,
                )
                reserve_legend_strip = any(
                    item.scene() is not None
                    and item.isVisible()
                    and src_rect.intersects(item.sceneBoundingRect())
                    and probe_scene.intersects(item.sceneBoundingRect())
                    for item in drawable_items
                )
            else:
                reserve_legend_strip = False

            if reserve_legend_strip:
                content_rect = QRectF(
                    draw_rect.left(), draw_rect.top(),
                    draw_rect.width(),
                    max(1.0, draw_rect.height() - self.LEGEND_RESERVE),
                )
                legend_strip = QRectF(
                    draw_rect.left(), content_rect.bottom(),
                    draw_rect.width(), self.LEGEND_RESERVE,
                )
            else:
                content_rect = draw_rect
                legend_strip = draw_rect if (is_last and app.pdf_show_legend) else None

            page_marks = continuation_marks.get(page_num, [])

            # Hide crossing spans before rendering this tile
            hidden_spans: list[SmartSpan] = []
            for mark in page_marks:
                span = mark.get("span")
                if span is None or span in hidden_spans:
                    continue
                if span.isVisible():
                    hidden_spans.append(span)
                    span.setVisible(False)

            # Preserve aspect ratio: compute uniform scale and centre inside content_rect
            scene_w = src_rect.width()
            scene_h = src_rect.height()
            if scene_w > 0 and scene_h > 0:
                s = min(content_rect.width() / scene_w, content_rect.height() / scene_h)
                rw = scene_w * s
                rh = scene_h * s
                render_rect = QRectF(
                    content_rect.left() + (content_rect.width()  - rw) / 2.0,
                    content_rect.top()  + (content_rect.height() - rh) / 2.0,
                    rw, rh,
                )
            else:
                render_rect = QRectF(content_rect)
            painter.save()
            painter.setClipRect(content_rect)
            # Deselect all items before rendering to avoid selection highlight / handles in PDF
            app.scene.clearSelection()
            app.scene.render(
                painter, render_rect, src_rect,
                Qt.AspectRatioMode.IgnoreAspectRatio,
            )
            painter.restore()

            for span in hidden_spans:
                span.setVisible(True)

            if legend_strip is not None:
                self._draw_pdf_legend(painter, legend_strip)

            for mark in page_marks:
                self._draw_continuation_stub(painter, draw_rect, render_rect, src_rect, mark)

        if painter:
            painter.end()

        l_count = sum(1 for t in tiles if t.get("orient") == "L")
        p_count = sum(1 for t in tiles if t.get("orient") == "P")
        override_count = sum(1 for t in tiles if t.get("is_override"))
        orient_summary = f"L:{l_count}  P:{p_count}"
        if override_count:
            orient_summary += f"  |  Overrides:{override_count}"

        if show_success:
            msg = QMessageBox(app)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("PDF Exported")
            msg.setText(
                f"Saved {total_pages} page(s) to:\n{filename}\n\n"
                f"Scale: 1:{app.pdf_scale}  |  "
                f"Orientation: {app.pdf_orientation_mode} ({orient_summary})"
            )
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

    def export_to_painter(self, printer: QPrinter, painter: QPainter) -> None:
        """
        Render the drawing pages onto an active QPainter and QPrinter.
        This appends pages to the existing document.
        """
        app = self._app
        m   = app.project_meta
        app._refresh_page_grid()
        tiles = app.view.grid_tiles
        if not tiles:
            return

        total_pages = tiles[0]["total"]

        MARG_T, MARG_B = self.MARG_T, self.MARG_B
        MARG_L, MARG_R = self.MARG_L, self.MARG_R
        PAGE_EDGE_GAP  = self.PAGE_EDGE_GAP
        TITLE_H_MIN    = self.TITLE_H_MIN
        FOOTER_H       = self.FOOTER_H

        drawable_items = [
            i for i in app.scene.items()
            if isinstance(i, (SmartPole, SmartStructure, SmartConsumer, SmartSpan))
        ]
        continuation_marks = self._build_continuation_marks_for_tiles(tiles, inset_scene=20.0)

        for page_idx, tile in enumerate(tiles):
            src_rect = tile["rect"]
            page_num = tile["page_num"]
            is_last  = (page_idx == len(tiles) - 1)
            orient   = tile.get("orient", "L")

            printer.setPageLayout(self._layout_for(orient))
            printer.newPage()

            paper  = printer.paperRect(QPrinter.Unit.DevicePixel)
            page_w = paper.width()  - MARG_L - MARG_R
            page_h = paper.height() - MARG_T  - MARG_B
            ox, oy = MARG_L, MARG_T

            # Title text
            title_text = (m.get("subject") or "ERP PROJECT DRAWING") if app.pdf_show_project_name else ""
            if title_text:
                from PyQt6.QtGui import QTextDocument
                _doc = QTextDocument()
                _doc.setDefaultFont(QFont("Arial", 9, QFont.Weight.Bold))
                _doc.setTextWidth(page_w * 0.70 - 8)
                _doc.setPlainText(title_text)
                TITLE_H = max(TITLE_H_MIN, int(_doc.size().height()) + 10)
            else:
                TITLE_H = TITLE_H_MIN
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(180, 180, 180), 0.8))
            painter.drawRect(QRectF(ox, oy, page_w, page_h))

            # Title strip
            painter.fillRect(QRectF(ox, oy, page_w, TITLE_H), QColor(240, 244, 250))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            if title_text:
                painter.drawText(
                    QRectF(ox + 4, oy + 4, page_w * 0.70 - 8, TITLE_H - 4),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                    | Qt.TextFlag.TextWordWrap,
                    title_text,
                )
            painter.setFont(QFont("Arial", 8))
            painter.drawText(
                QRectF(ox + page_w * 0.70, oy, page_w * 0.30 - 4, TITLE_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"Page {page_num} / {total_pages}   [Scale 1:{app.pdf_scale}]",
            )
            painter.setPen(QPen(QColor(180, 180, 180), 0.5))
            painter.drawLine(
                QPointF(ox, oy + TITLE_H), QPointF(ox + page_w, oy + TITLE_H)
            )

            # Footer strip
            footer_y = oy + page_h - FOOTER_H
            painter.fillRect(QRectF(ox, footer_y, page_w, FOOTER_H), QColor(240, 244, 250))
            painter.setPen(QPen(QColor(180, 180, 180), 0.5))
            painter.drawLine(QPointF(ox, footer_y), QPointF(ox + page_w, footer_y))
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(QFont("Arial", 7))

            from core import db_gateway as _dbg
            active_profile = _dbg.get_active_profile()
            profile_txt = f"{active_profile['firm_name']}  |  " if active_profile else ""

            date_str   = datetime.now().strftime("%d-%m-%Y")
            footer_txt = (
                f"{m.get('project_type','')}  |  "
                f"{date_str}  |  "
                f"Lat: {m.get('lat', '')}   Long: {m.get('long', '')}  |  "
                f"{profile_txt}"
                f"{APP_DISPLAY_NAME} v{APP_VERSION}"
            )
            painter.drawText(
                QRectF(ox + 4, footer_y, page_w - 8, FOOTER_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                footer_txt,
            )

            # Drawing area
            draw_top  = oy + TITLE_H + 2
            draw_h    = page_h - TITLE_H - FOOTER_H - 4
            draw_rect = QRectF(
                ox + PAGE_EDGE_GAP,
                draw_top + PAGE_EDGE_GAP,
                max(1.0, page_w - 2 * PAGE_EDGE_GAP),
                max(1.0, draw_h  - 2 * PAGE_EDGE_GAP),
            )

            if is_last and app.pdf_show_legend:
                probe_scene = QRectF(
                    src_rect.left() + src_rect.width() * 0.58,
                    src_rect.top() + src_rect.height() * 0.62,
                    src_rect.width() * 0.42,
                    src_rect.height() * 0.38,
                )
                reserve_legend_strip = any(
                    item.scene() is not None
                    and item.isVisible()
                    and src_rect.intersects(item.sceneBoundingRect())
                    and probe_scene.intersects(item.sceneBoundingRect())
                    for item in drawable_items
                )
            else:
                reserve_legend_strip = False

            if reserve_legend_strip:
                content_rect = QRectF(
                    draw_rect.left(), draw_rect.top(),
                    draw_rect.width(),
                    max(1.0, draw_rect.height() - self.LEGEND_RESERVE),
                )
                legend_strip = QRectF(
                    draw_rect.left(), content_rect.bottom(),
                    draw_rect.width(), self.LEGEND_RESERVE,
                )
            else:
                content_rect = draw_rect
                legend_strip = draw_rect if (is_last and app.pdf_show_legend) else None

            page_marks = continuation_marks.get(page_num, [])

            hidden_spans: list[SmartSpan] = []
            for mark in page_marks:
                span = mark.get("span")
                if span is None or span in hidden_spans:
                    continue
                if span.isVisible():
                    hidden_spans.append(span)
                    span.setVisible(False)

            scene_w = src_rect.width()
            scene_h = src_rect.height()
            if scene_w > 0 and scene_h > 0:
                s = min(content_rect.width() / scene_w, content_rect.height() / scene_h)
                rw = scene_w * s
                rh = scene_h * s
                render_rect = QRectF(
                    content_rect.left() + (content_rect.width()  - rw) / 2.0,
                    content_rect.top()  + (content_rect.height() - rh) / 2.0,
                    rw, rh,
                )
            else:
                render_rect = QRectF(content_rect)
            painter.save()
            painter.setClipRect(content_rect)
            app.scene.clearSelection()
            app.scene.render(
                painter, render_rect, src_rect,
                Qt.AspectRatioMode.IgnoreAspectRatio,
            )
            painter.restore()

            for span in hidden_spans:
                span.setVisible(True)

            if legend_strip is not None:
                self._draw_pdf_legend(painter, legend_strip)

            for mark in page_marks:
                self._draw_continuation_stub(painter, draw_rect, render_rect, src_rect, mark)

