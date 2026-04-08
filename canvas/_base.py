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

"""
canvas_objects.py
=================
Defines the four interactive canvas objects for ERP Estimate Generator:

    SmartPole      — LT or HT single pole (PCC / STP / H-BEAM)
    SmartStructure — Multi-pole HT structures (DP / TP / 4P / DTR sub-station)
    SmartSpan      — Conductor span between any two endpoints
    SmartConsumer  — Consumer service point (replaces SmartHome)

Visual improvements over v4
----------------------------
  • Stay wire — diagonal line + anchor drawn attached to pole/structure symbol
  • Earth symbol — standard ⏚ (3 decreasing horizontal bars) below pole base
  • CG symbol — small crosshatch bracket drawn at span midpoint below the line
  • TP symbol — 3 circles in triangular arrangement
  • 4P symbol — 4 circles in square arrangement
  • Detail-view toggle — stay/earth/CG symbols hidden when detail_view=False
  • Pole colour coding: LT=blue, HT=red, Existing=grey
  • Structure colour coding: DP/TP/4P=dark-green, DTR=orange
"""

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


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED DRAWING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _earth_path(x_off: float = 0, y_off: float = 0, angle_deg: float = 90) -> QPainterPath:
    """
    Draws the standard IEC earth / ground symbol (⏚) in any direction.
    (x_off, y_off) — attachment point at pole edge.
    angle_deg — direction away from pole (default 90° = downward in screen coords).
    Symbol is kept compact so it doesn't overlap the pole or label.
    """
    p = QPainterPath()
    rad      = math.radians(angle_deg)
    perp_rad = math.radians(angle_deg + 90)
    # Short stem in angle_deg direction
    p.moveTo(x_off, y_off)
    p.lineTo(x_off + math.cos(rad) * 3, y_off + math.sin(rad) * 3)
    # Three bars perpendicular to stem, decreasing width (compact)
    for dist, half_w in ((3, 4), (5, 3), (7, 2)):
        bx = x_off + math.cos(rad) * dist
        by = y_off + math.sin(rad) * dist
        px = math.cos(perp_rad) * half_w
        py = math.sin(perp_rad) * half_w
        p.moveTo(bx - px, by - py)
        p.lineTo(bx + px, by + py)
    return p


_STAY_LENGTH: int = 18
_ARROW_LEN: int = 6


def _stay_path(angle_deg: float = 225) -> QPainterPath:
    """
    Draws a stay-wire symbol: a diagonal line from pole centre outward,
    with an arrowhead at the far end pointing in the stay direction.
    angle_deg — direction of stay wire (default: lower-left = 225°)
    """
    length = _STAY_LENGTH
    rad    = math.radians(angle_deg)
    ex     = math.cos(rad) * length
    ey     = math.sin(rad) * length

    p = QPainterPath()
    p.moveTo(0, 0)
    p.lineTo(ex, ey)
    # Arrowhead — two wings going back from tip at ±140° from forward direction
    arrow_len = _ARROW_LEN
    for wing_offset in (+140, -140):
        wing_rad = math.radians(angle_deg + wing_offset)
        p.moveTo(ex, ey)
        p.lineTo(ex + math.cos(wing_rad) * arrow_len,
                 ey + math.sin(wing_rad) * arrow_len)
    return p


def _existing_struct_path(st: str) -> QPainterPath:
    """
    Returns the outline path for an existing structure symbol used on a SmartPole
    when existing_subtype is DP/TP/4P/DTR. Matches SmartStructure geometry.
    """
    p   = QPainterPath()
    r   = 8
    gap = 6

    def _cl(path, offsets, radius):
        for i in range(len(offsets)):
            p1 = offsets[i]
            p2 = offsets[(i + 1) % len(offsets)]
            vx, vy = p2[0] - p1[0], p2[1] - p1[1]
            dist = math.hypot(vx, vy)
            if dist == 0:
                continue
            nx, ny = vx / dist, vy / dist
            path.moveTo(p1[0] + nx * radius, p1[1] + ny * radius)
            path.lineTo(p2[0] - nx * radius, p2[1] - ny * radius)

    if st == "DP":
        cx = r + gap // 2
        p.addEllipse(-cx - r, -r, r * 2, r * 2)
        p.addEllipse( cx - r, -r, r * 2, r * 2)
        p.moveTo(-cx + r, 0)
        p.lineTo( cx - r, 0)
    elif st == "TP":
        offs = [(0, -(r + gap // 2)), (-(r + gap), r + gap // 2), (r + gap, r + gap // 2)]
        for ox, oy in offs:
            p.addEllipse(ox - r, oy - r, r * 2, r * 2)
        _cl(p, offs, r)
    elif st == "4P":
        d = r + gap // 2
        offs = [(-d, -d), (d, -d), (d, d), (-d, d)]
        for ox, oy in offs:
            p.addEllipse(ox - r, oy - r, r * 2, r * 2)
        _cl(p, offs, r)
    elif st == "DTR":
        cx = r + gap // 2 + 4
        p.addEllipse(-cx - r, -r, r * 2, r * 2)
        p.addEllipse( cx - r, -r, r * 2, r * 2)
        p.addRect(-gap // 2 - 2, -r // 2, gap + 4, r)
        p.moveTo(-gap // 2 - 2, 0)
        p.lineTo( gap // 2 + 2, 0)
    return p


def _cg_rail_path(ux: float, uy: float, nx: float, ny: float,
                  cg_half: float, rail_sep: float) -> QPainterPath:
    """
    Draws the CG (Cradle Guard) rail-line symbol centred at (0,0).
    Two parallel rails run along (ux,uy) for cg_half on each side,
    offset ±rail_sep in the perpendicular (nx,ny) direction.
    Evenly-spaced sleepers connect the two rails.
    """
    p = QPainterPath()
    # Rail A (far side)
    p.moveTo(-ux*cg_half + nx*rail_sep, -uy*cg_half + ny*rail_sep)
    p.lineTo( ux*cg_half + nx*rail_sep,  uy*cg_half + ny*rail_sep)
    # Rail B (near side)
    p.moveTo(-ux*cg_half - nx*rail_sep, -uy*cg_half - ny*rail_sep)
    p.lineTo( ux*cg_half - nx*rail_sep,  uy*cg_half - ny*rail_sep)
    # Sleepers — skip end positions (open ends), moderately dense
    n_sleepers = max(3, int(cg_half * 2 / 14))
    ext = rail_sep + 1.4
    for i in range(1, n_sleepers):
        t = -cg_half + cg_half * 2 * i / n_sleepers
        p.moveTo(ux*t + nx*ext, uy*t + ny*ext)
        p.lineTo(ux*t - nx*ext, uy*t - ny*ext)
    return p


# ─────────────────────────────────────────────────────────────────────────────
#  BASE MIXIN  — common flags + itemChange + detail_view propagation
# ─────────────────────────────────────────────────────────────────────────────

class _NodeMixin(_NodeBase):
    """
    Mixin providing shared setup for all node-type canvas items
    (SmartPole, SmartStructure, SmartConsumer).
    Call _init_node() from the subclass __init__ after super().__init__().
    """
    def _init_node(self, x: float, y: float, refresh_signal: Any, detail_view: bool = True) -> None:
        self.setPos(x, y)
        self.setZValue(10)
        F = QGraphicsPathItem.GraphicsItemFlag
        self.setFlag(F.ItemIsSelectable)
        self.setFlag(F.ItemIsMovable)
        self.setFlag(F.ItemSendsGeometryChanges)

        self.refresh_signal  = refresh_signal
        self.detail_view     = detail_view
        self.connected_spans = []
        self.custom_note     = ""
        self.dynamic_props   = {}

    def _on_position_changed(self) -> None:
        for span in self.connected_spans:
            span.update_position()
        if self.refresh_signal:
            self.refresh_signal.emit()


# ─────────────────────────────────────────────────────────────────────────────
#  SmartPole
# ─────────────────────────────────────────────────────────────────────────────

class SmartPole(_NodeMixin, QGraphicsPathItem):
    """
    A single LT or HT pole on the canvas.

    Properties
    ----------
    pole_type        : "LT" | "HT"
    pole_type2       : "PCC" | "STP" | "H-BEAM"
    height           : "8MTR" | "9MTR" | "9.5MTR" | "11MTR" | "13MTR"
    is_existing      : bool
    has_extension    : bool
    extension_height : float  (metres, only used when has_extension=True)
    earth_count      : int
    stay_count       : int
    override_auto_stay : bool
    detail_view      : bool   (show stay/earth symbols)
    """

    _RADIUS: int = 9
    _LABEL_MARGIN_X: int = 10
    _LABEL_MARGIN_Y: int = 8

    def __init__(
        self, x: float, y: float, refresh_signal: Any,
        pole_type: str = "LT", is_existing: bool = False,
        detail_view: bool = True
    ) -> None:
        QGraphicsPathItem.__init__(self)
        self._init_node(x, y, refresh_signal, detail_view)

        _d   = defaults.current
        _pfx = "lt_" if pole_type == "LT" else "ht_"

        self.pole_type          = pole_type
        self.pole_type2         = _d[_pfx + "pole_type2"] if not is_existing else "PCC"
        self.is_existing        = is_existing
        self.existing_subtype   = pole_type   # LT | HT | DP | TP | 4P | DTR
        self.existing_dtr_size  = "None"
        self.height             = _d[_pfx + "height"] if not is_existing else ("8MTR" if pole_type == "LT" else "9MTR")
        self.has_extension      = False
        self.extension_height   = _d["extension_height"]
        self.override_auto_stay = False

        if is_existing:
            self.earth_count = 0
            self.stay_count  = 0
        else:
            self.earth_count = _d[_pfx + "earth_count"]
            self.stay_count  = _d[_pfx + "stay_count"]

        # Distribution box flag — only meaningful on LT poles with AB Cable spans
        self.dist_box_required: bool = bool(
            _d.get("lt_dist_box_required", True)
        ) if pole_type == "LT" and not is_existing else False

        self._updating_visuals = False

        # Angle overrides for stay/earth symbols (None = auto-calculate from spans)
        self.stay_angle_override  = None   # float degrees, or None
        self.earth_angle_override = None   # float degrees, or None

        # Label — child of this item so it moves with the pole
        self.label = DraggableLabel(self)

        self.update_visuals()

    # ── Stay / Earth angle calculation ────────────────────────────────────────

    def _calc_stay_angle(self) -> float:
        """
        Returns the direction (degrees, screen coords) in which the stay wire
        should point, based on connected span tensions.

        For an end pole (1 active span):  stay points opposite to the span
        direction so the anchor resists the wire tension.
        For a turning pole (2+ spans):  stay points opposite to the resultant
        of all span unit-vectors (toward the net tension source).
        Default 225° when no spans are connected.
        """
        # New poles: follow NEW-work strain only (exclude existing spans).
        # Existing poles: use both existing + new non-service spans so the stay
        # aligns to the middle/resultant of EX+NEW pull directions.
        if self.is_existing:
            active_spans = [
                s for s in self.connected_spans
                if not s.is_service_drop
            ]
        else:
            active_spans = [
                s for s in self.connected_spans
                if not s.is_service_drop and not s.is_existing_span
            ]
        if not active_spans:
            return 225.0

        sum_x, sum_y = 0.0, 0.0
        my_x, my_y = self.x(), self.y()

        for span in active_spans:
            other = span.p1 if span.p2 is self else span.p2
            dx = other.x() - my_x
            dy = other.y() - my_y
            mag = math.hypot(dx, dy)
            if mag > 0:
                sum_x += dx / mag
                sum_y += dy / mag

        if math.hypot(sum_x, sum_y) < 0.01:
            return 225.0   # balanced / through pole — no net tension

        # Net tension direction (toward spans); stay opposes it → +180°
        tension_angle = math.degrees(math.atan2(sum_y, sum_x)) % 360
        return (tension_angle + 180) % 360

    def _calc_earth_angle(self, stay_angle: float) -> float:
        """
        Finds a "free" direction for the earth symbol that avoids all span
        directions and the stay direction.

        Priority order:
          1. Cardinal directions: left(180°), top(270°), bottom(90°), right(0°)
          2. Diagonals: lower-left(225°), lower-right(315°), upper-left(135°), upper-right(45°)
          3. Fallback: opposite of stay

        A direction is blocked if it is within 50° of any span or the stay.
        Only applies to new (non-existing) poles; existing poles use stay+180°.
        """
        if self.is_existing:
            return (stay_angle + 180) % 360

        # Collect all occupied angles (span directions + stay)
        occupied = []
        my_x, my_y = self.x(), self.y()
        for span in self.connected_spans:
            other = span.p1 if span.p2 is self else span.p2
            dx = other.x() - my_x
            dy = other.y() - my_y
            if math.hypot(dx, dy) > 0:
                occupied.append(math.degrees(math.atan2(dy, dx)) % 360)
        occupied.append(stay_angle % 360)

        def _is_free(angle: float) -> bool:
            for occ in occupied:
                diff = abs((angle - occ + 180) % 360 - 180)
                if diff < 50:
                    return False
            return True

        # 1. Try cardinal directions in preference order
        for candidate in (180.0, 270.0, 90.0, 0.0):
            if _is_free(candidate):
                return candidate
        # 2. Try 45° diagonals
        for candidate in (225.0, 315.0, 135.0, 45.0):
            if _is_free(candidate):
                return candidate
        # 3. Fallback
        return (stay_angle + 180) % 360

    def _label_pos_from_stay(self, r: float, lw: float, lh: float, stay_angle: float) -> QPointF:
        """Place label in the same quadrant as stay direction."""
        rad = math.radians(stay_angle % 360)
        vx = math.cos(rad)
        vy = math.sin(rad)

        sx = 1 if vx >= 0 else -1
        sy = 1 if vy >= 0 else -1

        margin_x = r + self._LABEL_MARGIN_X
        margin_y = r + self._LABEL_MARGIN_Y

        x = margin_x if sx > 0 else -(lw + margin_x)
        y = margin_y if sy > 0 else -(lh + margin_y)
        return QPointF(x, y)

    def _connected_span_layout(self) -> str:
        """Return 'vertical', 'horizontal', or 'mixed' for connected span directions."""
        has_vertical = False
        has_horizontal = False
        my_x, my_y = self.x(), self.y()

        for span in self.connected_spans:
            other = span.p1 if span.p2 is self else span.p2
            dx = abs(other.x() - my_x)
            dy = abs(other.y() - my_y)
            if dy >= dx:
                has_vertical = True
            if dx >= dy:
                has_horizontal = True

        if has_vertical and has_horizontal:
            return "mixed"
        if has_vertical:
            return "vertical"
        return "horizontal"

    # ── Visual update ─────────────────────────────────────────────────────────

    def update_visuals(self) -> None:
        if self._updating_visuals:
            return
        self._updating_visuals = True

        try:
            path = QPainterPath()

            # Main pole symbol
            r = self._RADIUS
            if self.is_existing and self.existing_subtype in ("DP", "TP", "4P", "DTR"):
                path.addPath(_existing_struct_path(self.existing_subtype))
            else:
                path.addEllipse(-r, -r, r * 2, r * 2)

            # ── Determine stay / earth angles ─────────────────────────────────
            if self.stay_angle_override is not None:
                stay_angle = self.stay_angle_override % 360
            else:
                stay_angle = self._calc_stay_angle()

            if self.earth_angle_override is not None:
                earth_angle = self.earth_angle_override % 360
            else:
                earth_angle = self._calc_earth_angle(stay_angle)

            # ── Earth symbol at pole edge in earth_angle direction ────────────
            if self.detail_view and self.earth_count > 0:
                n         = min(self.earth_count, 3)
                erad      = math.radians(earth_angle)
                perp_rad  = math.radians(earth_angle + 90)
                # attachment point on pole edge
                att_x = math.cos(erad) * (r + 2)
                att_y = math.sin(erad) * (r + 2)
                for i in range(n):
                    offset = (i - (n - 1) / 2) * 10   # tighter spacing for smaller symbol
                    ex = att_x + math.cos(perp_rad) * offset
                    ey = att_y + math.sin(perp_rad) * offset
                    path.addPath(_earth_path(ex, ey, earth_angle))

            # ── Stay wire symbols in stay_angle direction ─────────────────────
            if self.detail_view and self.stay_count > 0:
                # For multiple stays, fan them around the main stay angle
                spread = [0, -25, 25, -50]
                for i in range(min(self.stay_count, 4)):
                    ang = (stay_angle + spread[i]) % 360
                    path.addPath(_stay_path(ang))

            self.setPath(path)

            # Colours
            black_pen = QPen(Qt.GlobalColor.black, 1)
            if self.is_existing:
                is_aug_dtr = (
                    self.existing_subtype == "DTR"
                    and bool(getattr(self, "dynamic_props", {}).get("dtr_aug_required", False))
                )
                if is_aug_dtr:
                    self.setBrush(QBrush(QColor("#f7b267")))
                    self.setPen(QPen(QColor("#7a4000"), 1.6, Qt.PenStyle.DashLine))
                else:
                    self.setBrush(QBrush(QColor("#cccccc")))
                    self.setPen(QPen(Qt.GlobalColor.darkGray, 1, Qt.PenStyle.DashLine))
            elif self.pole_type == "LT":
                self.setBrush(QBrush(QColor("#2980b9")))   # blue
                self.setPen(black_pen)
            else:  # HT
                self.setBrush(QBrush(QColor("#c0392b")))   # red
                self.setPen(black_pen)

            # Label text
            if self.is_existing:
                _sub = self.existing_subtype
                _sfx = " Struct" if _sub in ("DP", "TP", "4P", "DTR") else " Pole"
                txt = f"Ex. {_sub}{_sfx}"
                if _sub == "DTR":
                    ex_kva = getattr(self, "existing_dtr_size", "None")
                    txt += f"\n{ex_kva}"
                    aug_required = bool(getattr(self, "dynamic_props", {}).get("dtr_aug_required", False))
                    if aug_required:
                        target = str(getattr(self, "dynamic_props", {}).get("dtr_new_size", "") or "")
                        if target:
                            txt += f"\nEx {ex_kva} S/STN to {target} S/STN"
                        else:
                            txt += "\nDTR Augmentation"
            else:
                ht_m = self.height.replace("MTR", "m")
                txt  = f"{self.pole_type2} {ht_m} ({self.pole_type})"
                if self.has_extension:
                    txt += f"\n+Ext {self.extension_height:.1f}m"

            if not self.is_existing:
                if (not self.detail_view) and self.earth_count > 0:
                    txt += f"\n⏚ {self.earth_count} Earth"
                if (not self.detail_view) and self.stay_count > 0:
                    txt += f"\nS×{self.stay_count} Stay"
            if self.custom_note:
                txt += f"\n📝 {self.custom_note}"

            self.label.setPlainText(txt)

            # ── Label position auto-placement ──────────────────────────────────
            # Preserve old behavior for pure vertical spans: label on right.
            # Preserve old behavior for pure horizontal spans: label below.
            # Only use stay-direction quadrant for mixed corner cases.
            if not getattr(self.label, "user_moved", False):
                lw = self.label.boundingRect().width()
                lh = self.label.boundingRect().height()
                if self.connected_spans:
                    layout = self._connected_span_layout()
                    if layout == "vertical":
                        self.label.set_auto_pos(r + 10, -lh / 2)
                    elif layout == "mixed":
                        p = self._label_pos_from_stay(r, lw, lh, stay_angle)
                        self.label.set_auto_pos(p.x(), p.y())
                    else:
                        lbl_y = r + 8
                        self.label.set_auto_pos(-lw / 2, lbl_y)
                else:
                    if self.is_existing and self.existing_subtype in ("TP", "4P"):
                        lbl_y = 27   # taller structure symbol
                    else:
                        lbl_y = r + 8
                    self.label.set_auto_pos(-lw / 2, lbl_y)
        finally:
            self._updating_visuals = False

    # ── Qt overrides ──────────────────────────────────────────────────────────
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        super().paint(painter, option, widget)
        if painter is None:
            return

        if (
            self.is_existing
            and self.existing_subtype == "DTR"
            and bool(getattr(self, "dynamic_props", {}).get("dtr_aug_required", False))
        ):
            # Emphasize augmented DTR with a larger shadow halo.
            painter.save()
            painter.translate(3.0, 3.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 80)))
            painter.drawPath(self.path())
            painter.restore()

            painter.save()
            painter.setPen(self.pen())
            painter.setBrush(self.brush())
            painter.drawPath(self.path())
            painter.restore()

        # Existing poles use dashed grey pen for body; redraw stay in dark stroke
        # so it remains as visible as new stays.
        if self.is_existing and self.detail_view and self.stay_count > 0:
            if self.stay_angle_override is not None:
                stay_angle = self.stay_angle_override % 360
            else:
                stay_angle = self._calc_stay_angle()
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.black, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            spread = [0, -25, 25, -50]
            for i in range(min(self.stay_count, 4)):
                ang = (stay_angle + spread[i]) % 360
                painter.drawPath(_stay_path(ang))
            painter.restore()

        if self.has_extension:
            r = self._RADIUS
            badge = QRectF(-5, -(r + 22), 10, 10)
            painter.save()
            painter.setPen(QPen(QColor("#1a5276"), 1))
            painter.setBrush(QBrush(QColor("#d6eaf8")))
            painter.drawRoundedRect(badge, 2, 2)
            painter.setPen(QPen(QColor("#1a5276"), 1))
            painter.setFont(QFont("Arial", 5, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "E")
            painter.restore()

        # Distribution Box marker on-canvas for quick visual verification.
        show_db = (
            not self.is_existing
            and self.pole_type == "LT"
            and getattr(self, "dist_box_required", False)
            and any(
                s.scene() is not None and s.conductor == "AB Cable" and not s.is_service_drop
                for s in self.connected_spans
            )
        )
        if show_db:
            r = self._RADIUS
            badge = QRectF(r + 2, -(r + 9), 15, 9)
            painter.save()
            painter.setPen(QPen(QColor("#7f6000"), 0.8))
            painter.setBrush(QBrush(QColor("#fff2cc")))
            painter.drawRoundedRect(badge, 2, 2)
            painter.setPen(QPen(QColor("#7f6000"), 1))
            painter.setFont(QFont("Arial", 5, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "DB")
            painter.restore()

        if (
            self.is_existing
            and self.existing_subtype == "DTR"
            and bool(getattr(self, "dynamic_props", {}).get("dtr_aug_required", False))
        ):
            r = self._RADIUS
            badge = QRectF(r + 4, -(r + 13), 18, 10)
            painter.save()
            painter.setPen(QPen(QColor("#7a4000"), 1))
            painter.setBrush(QBrush(QColor("#ffe5cc")))
            painter.drawRoundedRect(badge, 2, 2)
            painter.setPen(QPen(QColor("#7a4000"), 1))
            painter.setFont(QFont("Arial", 5, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "AUG")
            painter.restore()
    def itemChange(self, change: QGraphicsPathItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsPathItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_position_changed()
        return super().itemChange(change, value)


# ─────────────────────────────────────────────────────────────────────────────
#  SmartStructure
# ─────────────────────────────────────────────────────────────────────────────

