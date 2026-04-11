from __future__ import annotations
import math
from typing import TYPE_CHECKING, Any
from PyQt6.QtWidgets import (
    QGraphicsPathItem, QGraphicsItemGroup, QWidget, QStyleOptionGraphicsItem,
    QGraphicsItem, QGraphicsTextItem,
)
from PyQt6.QtGui import (
    QPainterPath, QPainterPathStroker, QBrush, QColor, QPen, QFont, QPainter,
    QTransform, QFontMetricsF,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QLineF, QSizeF
from core import defaults
from ui.components import DraggableLabel

if TYPE_CHECKING:
    _NodeBase = QGraphicsPathItem
else:
    _NodeBase = object
from canvas._base import _cg_rail_path, _earth_path, SmartPole
from canvas.nodes import SmartStructure, SmartConsumer

class SmartSpan(QGraphicsPathItem):
    """
    A conductor span between two canvas endpoints
    (SmartPole, SmartStructure, or SmartConsumer).

    Voltage auto-detection
    ----------------------
    is_lt_span = True  when at least one endpoint is a SmartPole with
                       pole_type == "LT", or when either endpoint is a
                       SmartConsumer. HT structures always produce HT spans.

    Conductor defaults
    ------------------
    Service drop (Consumer endpoint) → "Service Drop" / 20 m
    LT span                          → "AB Cable" / 40 m
    HT span                          → "ACSR" / 40 m

    Visual style
    ------------
    ACSR new       — dashed black line
    ACSR existing  — solid black line
    AB Cable new   — wavy dark-blue line
    AB Cable exist — solid dark-blue line
    PVC Cable      — wavy dark-green line
    Service Drop   — wavy orange line
    CG symbol      — small crosshatch bracket below span midpoint
                     (only when detail_view=True and has_cg=True)
    """

    # Pen colours per conductor type
    _PEN_COLORS = {
        "ACSR":         QColor("#222222"),
        "AB Cable":     QColor("#1a5276"),   # dark blue
        "PVC Cable":    QColor("#107C41"),   # dark green
        "Service Drop": QColor("#d35400"),   # orange
    }
    _WAVY_AMPLITUDE: float = 4.0
    _WAVY_FREQUENCY_DIV: int = 15
    _MIN_WAVY_STEPS: int = 20

    def __init__(self, pole1: Any, pole2: Any, detail_view: bool = True) -> None:
        super().__init__()
        self.p1          = pole1
        self.p2          = pole2
        self.detail_view = detail_view
        self.setZValue(0)
        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable)

        self.is_existing_span = False
        self.custom_note      = ""
        self.dynamic_props    = {}

        # ── Auto-detect service drop ───────────────────────────────────────
        self.is_service_drop = (
            isinstance(self.p1, SmartConsumer) or
            isinstance(self.p2, SmartConsumer)
        )

        # ── Auto-detect voltage level ──────────────────────────────────────
        self.is_lt_span = self._detect_lt()

        # ── Set defaults ——————————————————————————————————————————
        _d = defaults.current
        if self.is_service_drop:
            self.conductor      = "Service Drop"
            self.conductor_size = _d["sd_conductor_size"]
            self.length         = _d["sd_length"]
            self.consider_cable = False
            self.phase          = _d["sd_phase"]
            self.has_cg         = False
            self.aug_type       = "New"
            self.wire_count     = "3"
        else:
            _pfx = "lt_" if self.is_lt_span else "ht_"
            self.conductor      = _d[_pfx + "conductor"]
            self.conductor_size = _d[_pfx + "conductor_size"]
            self.length         = _d[_pfx + "span_length"]
            self.aug_type       = "New"
            self.wire_count     = _d[_pfx + "wire_count"]
            # CG: for HT spans, follow the ht_cg_required default
            self.has_cg         = bool(_d.get("ht_cg_required", True)) if not self.is_lt_span else False
            self.consider_cable = False
            self.phase          = "3 Phase"

        # Label is a standalone item (not a child) so it can be
        # added separately to the scene and remain independent.
        self.label = DraggableLabel()

        self.update_position()
        self.update_visuals()

    # ── Voltage detection ─────────────────────────────────────────────────────

    def _detect_lt(self) -> bool:
        """
        Returns True (LT span) when either endpoint is:
          - a SmartPole whose effective type is "LT"  (uses existing_subtype when is_existing)
          - a SmartConsumer
        Returns False (HT span) when both endpoints are HT poles or structures.
        """
        for ep in (self.p1, self.p2):
            if isinstance(ep, SmartConsumer):
                return True
            if isinstance(ep, SmartPole):
                eff = ep.existing_subtype if ep.is_existing else ep.pole_type
                if eff == "LT":
                    return True
        return False

    # ── Position update ───────────────────────────────────────────────────────

    def update_position(self) -> None:
        """Redraws the span path and repositions the label."""
        self.is_lt_span = self._detect_lt()

        p1_pos = self.p1.pos()
        p2_pos = self.p2.pos()

        def _get_line_rect_intersection(line, rect) -> QPointF | None:
            
            # Check for intersection with each of the 4 lines of the rectangle
            rect_lines = [
                QLineF(rect.topLeft(), rect.topRight()),
                QLineF(rect.topRight(), rect.bottomRight()),
                QLineF(rect.bottomRight(), rect.bottomLeft()),
                QLineF(rect.bottomLeft(), rect.topLeft())
            ]
            
            for rect_line in rect_lines:
                # Use QLineF.intersects() which returns a tuple (IntersectionType, QPointF)
                intersection_type, intersect_pt = line.intersects(rect_line)
                if intersection_type == QLineF.IntersectionType.BoundedIntersection:
                    return intersect_pt

            return None

        def get_connection_point(item, other_item_pos) -> QPointF:
            item_pos = item.pos()
            line = QLineF(other_item_pos, item_pos)
            
            if isinstance(item, SmartPole):
                # For SmartPole, connect to the edge of the circle
                direction = line.unitVector()
                return item_pos - QPointF(direction.dx() * 9, direction.dy() * 9)
            
            if isinstance(item, SmartStructure):
                st = getattr(item, 'structure_type', None)
                r   = SmartStructure._RADIUS
                gap = SmartStructure._GAP

                if st == "TP":
                    # 3 circles: top, bottom-left, bottom-right
                    top = (0,           -(r + gap // 2))
                    bl  = (-(r + gap),   (r + gap // 2))
                    br  = ( (r + gap),   (r + gap // 2))
                    # midpoints of the three connecting edges
                    edge_mids = [
                        ((top[0] + bl[0]) / 2, (top[1] + bl[1]) / 2),   # top — BL (left edge)
                        ((top[0] + br[0]) / 2, (top[1] + br[1]) / 2),   # top — BR (right edge)
                        ((bl[0]  + br[0]) / 2, (bl[1]  + br[1]) / 2),   # BL — BR  (bottom edge)
                    ]
                elif st == "4P":
                    # 4 circles in 2×2 grid; edge midpoints are at cardinal directions
                    d = r + gap // 2
                    edge_mids = [
                        ( 0, -d),   # top edge
                        ( d,  0),   # right edge
                        ( 0,  d),   # bottom edge
                        (-d,  0),   # left edge
                    ]
                else:
                    edge_mids = None

                if edge_mids is not None:
                    # Pick the edge midpoint whose direction best matches other_item_pos
                    rel = other_item_pos - item_pos   # vector from structure to other pole
                    ox, oy = rel.x(), rel.y()
                    best = min(edge_mids,
                               key=lambda m: (m[0] - ox) ** 2 + (m[1] - oy) ** 2)
                    return item_pos + QPointF(best[0], best[1])
                else:
                    # For DP/DTR, use only core body bounds (exclude stay/earth symbols)
                    if st == "DTR":
                        cx = r + gap // 2 + 4
                    else:  # DP
                        cx = r + gap // 2
                    core = QRectF(
                        item_pos.x() - (cx + r),
                        item_pos.y() - r,
                        (cx + r) * 2,
                        r * 2,
                    )
                    intersection = _get_line_rect_intersection(line, core)
                    if intersection is not None:
                        return intersection
            
            return item_pos

        x1, y1 = get_connection_point(self.p1, p2_pos).x(), get_connection_point(self.p1, p2_pos).y()
        x2, y2 = get_connection_point(self.p2, p1_pos).x(), get_connection_point(self.p2, p1_pos).y()

        path = QPainterPath()
        path.moveTo(x1, y1)

        dx, dy = x2 - x1, y2 - y1
        px_len = math.hypot(dx, dy)

        wavy_conductors = {"AB Cable", "PVC Cable", "Service Drop"}
        if self.conductor in wavy_conductors and px_len > 0:
            steps     = max(self._MIN_WAVY_STEPS, int(px_len / 2))
            nx        = -dy / px_len
            ny        =  dx / px_len
            frequency = px_len / self._WAVY_FREQUENCY_DIV
            amplitude = self._WAVY_AMPLITUDE

            for i in range(1, steps + 1):
                t          = i / float(steps)
                cx_        = x1 + dx * t
                cy_        = y1 + dy * t
                sine_off   = math.sin(t * frequency * 2 * math.pi) * amplitude
                path.lineTo(cx_ + nx * sine_off, cy_ + ny * sine_off)
        else:
            path.lineTo(x2, y2)

        self.setPath(path)

        if px_len > 0:
            nx_n   = -dy / px_len
            ny_n   =  dx / px_len
            mid_x  = (x1 + x2) / 2
            mid_y  = (y1 + y2) / 2
            lw     = self.label.boundingRect().width()
            lh     = self.label.boundingRect().height()

            if not getattr(self.label, "user_moved", False):
                # Always offset perpendicularly from midpoint so diagonal
                # spans keep the label centred, not drifted toward a pole.
                # Pick the perpendicular direction that goes upward (–y in screen).
                perp_x = nx_n
                perp_y = ny_n
                if perp_y > 0:           # pointing down — flip to go up
                    perp_x, perp_y = -perp_x, -perp_y
                offset = 20              # px gap from span line to label edge
                self.label.set_auto_pos(
                    mid_x + perp_x * offset - lw / 2,
                    mid_y + perp_y * offset - lh / 2,
                )

    # ── Hit-test shape (wide corridor for easy clicking) ──────────────────────

    _HIT_WIDTH: float = 26.0   # total hit corridor width (~13 px each side)

    def shape(self) -> QPainterPath:
        """Return a wide stroked hit area so clicking anywhere between
        the two poles selects the span, not just clicking the 1 px line."""
        stroker = QPainterPathStroker()
        stroker.setWidth(self._HIT_WIDTH)
        stroker.setCapStyle(Qt.PenCapStyle.FlatCap)    # don't spill past endpoints
        stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:
        """Pad the base bounding rect by the hit corridor half-width so Qt's
        coarse culling never rejects a click that is within the hit shape.
        This is critical for augmented spans whose pen is NoPen (zero default padding)."""
        base = super().boundingRect()
        pad  = self._HIT_WIDTH / 2.0
        return base.adjusted(-pad, -pad, pad, pad)

    # ── Visual update ─────────────────────────────────────────────────────────

    def update_visuals(self) -> None:
        # ── Pen style ─────────────────────────────────────────────────────
        _span_color_keys = {
            "ACSR":         "canvas_acsr",
            "AB Cable":     "canvas_ab_cable",
            "PVC Cable":    "canvas_pvc_cable",
            "Service Drop": "canvas_svc_drop",
        }
        _ck  = _span_color_keys.get(self.conductor, "canvas_acsr")
        color = QColor(defaults.current.get(_ck, self._PEN_COLORS.get(self.conductor, QColor("#222222"))))
        pen   = QPen(color, 1.8)
        aug_overlay_pair = (
            bool(getattr(self, "dynamic_props", {}).get("conductor_aug_required", False))
            and self.conductor == "ACSR"
            and self.is_existing_span
        )

        if aug_overlay_pair:
            # The pair (existing + projected) is drawn manually in paint().
            pen = QPen(Qt.PenStyle.NoPen)
        elif self.is_existing_span:
            pen.setStyle(Qt.PenStyle.SolidLine)
            pen.setWidthF(1.2)
        elif self.conductor == "ACSR":
            pen.setStyle(Qt.PenStyle.DashLine)

        self.setPen(pen)

        # ── Label text ────────────────────────────────────────────────────
        if self.is_existing_span:
            if self.conductor == "ACSR":
                txt = f"{self.length}m"
            elif self.conductor == "AB Cable":
                txt = f"{self.length}m"
            else:
                txt = f"Existing\n{self.conductor}"
        elif self.is_service_drop:
            phase_s = "1φ" if self.phase == "1 Phase" else "3φ"
            txt = f"Service {self.length}m\n{phase_s}"
            if self.consider_cable:
                txt += f"\n{self.conductor_size}"
        else:
            if self.conductor == "ACSR":
                txt = f"{self.length}m"
            elif self.conductor == "AB Cable":
                txt = f"{self.length}m"
            else:
                txt = f"{self.length}m PVC"
            if self.aug_type != "New":
                txt += f"\n({self.aug_type})"
            if self.has_cg and (not self.detail_view):
                txt += "\n+CG"

        if self.custom_note:
            txt += f"\n📝 {self.custom_note}"

        self.label.setPlainText(txt)
        self.update_position()

        # Ensure label is in scene
        if not self.label.scene():
            sc = self.scene()
            if sc is not None:
                sc.addItem(self.label)

    # ── Custom paint for CG symbol ────────────────────────────────────────────

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        # Draw the span line itself
        super().paint(painter, option, widget)

        x1, y1 = self.p1.x(), self.p1.y()
        x2, y2 = self.p2.x(), self.p2.y()
        dx, dy  = x2 - x1, y2 - y1
        px_len  = math.hypot(dx, dy)
        if px_len == 0:
            return

        # Along-span unit vector
        ux = dx / px_len
        uy = dy / px_len

        # Perpendicular unit vector — stable: down for horizontal, right for vertical
        nx = -dy / px_len
        ny =  dx / px_len
        if abs(dx) >= abs(dy):   # horizontal-ish: ensure ny > 0 (downward)
            if ny < 0:
                nx, ny = -nx, -ny
        else:                    # vertical-ish: ensure nx > 0 (rightward)
            if nx < 0:
                nx, ny = -nx, -ny

        # ── Wire-count tick marks for ACSR spans ──────────────────────────
        if self.conductor == "ACSR" and self.detail_view:
            try:
                n_wires = int(self.wire_count)
            except (ValueError, TypeError):
                n_wires = 3
            tick_h  = 5.0          # half-height of each tick (px)
            spacing = 4.0          # gap between ticks (px)
            tilt    = 0.35         # along-span lean (fraction of tick_h)
            total_w = (n_wires - 1) * spacing
            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            tick_color = QColor(defaults.current.get("canvas_acsr", "#222222"))
            painter.save()
            painter.setPen(QPen(tick_color, 0.8))
            for k in range(n_wires):
                along = -total_w / 2 + k * spacing
                cx_ = mx + ux * along
                cy_ = my + uy * along
                painter.drawLine(
                    QPointF(cx_ - nx * tick_h - ux * tick_h * tilt,
                            cy_ - ny * tick_h - uy * tick_h * tilt),
                    QPointF(cx_ + nx * tick_h + ux * tick_h * tilt,
                            cy_ + ny * tick_h + uy * tick_h * tilt),
                )
            painter.restore()

        # Draw CG rail symbol at midpoint if enabled.
        if self.detail_view and self.has_cg and not self.is_existing_span:
            cg_half  = 0.30 * px_len   # half of 60% span length
            offset   = 9               # px gap from span line to rail centre
            rail_sep = 2.6             # px half-gap between the two rails

            # Centre of CG rail band (offset perpendicularly from span midpoint)
            cx = (x1 + x2) / 2 + nx * offset
            cy = (y1 + y2) / 2 + ny * offset

            painter.save()
            painter.translate(cx, cy)
            painter.setPen(QPen(QColor("#9ec5e8"), 1.0))   # light blue rail
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(_cg_rail_path(ux, uy, nx, ny, cg_half, rail_sep))
            painter.restore()

        if bool(getattr(self, "dynamic_props", {}).get("conductor_aug_required", False)):
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            # Draw projected augmentation line parallel to existing span.
            gap_total = 10.0
            half_gap = gap_total / 2.0

            # Keep the two lines centered around the true pole-to-pole center line.
            exx1 = x1 - nx * half_gap
            exy1 = y1 - ny * half_gap
            exx2 = x2 - nx * half_gap
            exy2 = y2 - ny * half_gap
            px1 = x1 + nx * half_gap
            py1 = y1 + ny * half_gap
            px2 = x2 + nx * half_gap
            py2 = y2 + ny * half_gap
            aug_to = str(getattr(self, "dynamic_props", {}).get("aug_to_config", "") or "")

            painter.save()
            # Existing line in pair.
            painter.setPen(QPen(QColor("#222222"), 1.3, Qt.PenStyle.SolidLine))
            painter.drawLine(QLineF(exx1, exy1, exx2, exy2))

            if aug_to == "ABC":
                # Wavy projected line for ABC conversion.
                wavy = QPainterPath()
                wavy.moveTo(px1, py1)
                steps = max(self._MIN_WAVY_STEPS, int(px_len / 2))
                amp = 2.8
                freq = px_len / self._WAVY_FREQUENCY_DIV
                for i in range(1, steps + 1):
                    t = i / float(steps)
                    lx = px1 + (px2 - px1) * t
                    ly = py1 + (py2 - py1) * t
                    off = math.sin(t * freq * 2 * math.pi) * amp
                    wavy.lineTo(lx + nx * off, ly + ny * off)
                painter.setPen(QPen(QColor("#1a5276"), 1.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(wavy)
            else:
                # Dashed projected line for 3/4/5 wire ACSR projection.
                dash_pen = QPen(QColor("#4a4a4a"), 1.4, Qt.PenStyle.DashLine)
                painter.setPen(dash_pen)
                painter.drawLine(QLineF(px1, py1, px2, py2))
            painter.restore()

            if aug_to == "ABC":
                badge_text = "AUG ABC"
            elif aug_to:
                badge_text = f"AUG {aug_to}W"
            else:
                badge_text = "AUG"

            painter.save()
            # Keep the badge around the span center but pull it toward the projected/new line.
            mx = (px1 + px2) / 2 + nx * 3.0
            my = (py1 + py2) / 2 + ny * 3.0
            badge = QRectF(mx - 17, my - 5, 34, 10)
            painter.setPen(QPen(QColor("#7a4000"), 1))
            painter.setBrush(QBrush(QColor("#fff3df")))
            painter.drawRoundedRect(badge, 2, 2)
            painter.setFont(QFont("Arial", 5, QFont.Weight.Bold))
            painter.setPen(QPen(QColor("#7a4000"), 1))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, badge_text)
            painter.restore()


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS SYMBOL  — resizable annotation shape (circle, square, arrow, line)
# ─────────────────────────────────────────────────────────────────────────────

