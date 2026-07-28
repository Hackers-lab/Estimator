from __future__ import annotations
import math
from typing import TYPE_CHECKING, Any
from PyQt6.QtWidgets import (
    QGraphicsPathItem, QWidget, QStyleOptionGraphicsItem,
)
from PyQt6.QtGui import (
    QPainterPath, QBrush, QColor, QPen, QFont, QPainter, QPolygonF,
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from core import defaults
from core import option_colors
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
    QGraphicsPathItem, QWidget, QStyleOptionGraphicsItem,
)
from PyQt6.QtGui import (
    QPainterPath, QBrush, QColor, QPen, QFont, QPainter,
)
from PyQt6.QtCore import Qt, QRectF, QPointF


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


def _diamond_path(r: float = 10.0) -> QPainterPath:
    path = QPainterPath()
    poly = QPolygonF([
        QPointF(0, -r * 1.3),
        QPointF(r * 1.3, 0),
        QPointF(0, r * 1.3),
        QPointF(-r * 1.3, 0),
        QPointF(0, -r * 1.3)
    ])
    path.addPolygon(poly)
    path.closeSubpath()
    return path


def _get_2char_pole_badge(pole) -> str:
    """Concise 2-character material/height badge code inside pole symbol."""
    pt2 = str(getattr(pole, "pole_type2", "")).upper().strip()
    if pt2 in ("STP", "ST", "ST_POLE"): return "ST"
    if pt2 in ("H-BEAM", "H_BEAM", "HB", "HBEAM"): return "HB"
    if pt2 in ("GI_PIPE", "GI", "GI_POLE"): return "GI"

    h = str(getattr(pole, "height", "")).strip().lower()
    if "8" in h: return "8M"
    if "9" in h: return "9M"
    if "11" in h: return "11"

    if getattr(pole, "voltage_level", None) == "33kV" or getattr(pole, "existing_subtype", None) == "33":
        return "33"

    if getattr(pole, "is_existing", False):
        sub = getattr(pole, "existing_subtype", "LT")
        return "HT" if sub in ("HT", "DP", "TP", "4P") else "LT"
    return "LT" if getattr(pole, "pole_type", "LT") == "LT" else "HT"


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

    def to_dict(self) -> dict:
        """Serialize common node properties to a dictionary."""
        return {
            "x": self.x(),
            "y": self.y(),
            "label_x": self.label.pos().x(),
            "label_y": self.label.pos().y(),
            "label_text": self.label.toPlainText(),
            "custom_note": self.custom_note,
            "dynamic_props": self.dynamic_props,
        }

    def apply_state(self, state: dict) -> None:
        """Apply serialized state back to the node."""
        self.setPos(state["x"], state["y"])
        self.label.setPos(state["label_x"], state["label_y"])
        self.label.setPlainText(state["label_text"])
        self.custom_note = state.get("custom_note", "")
        self.dynamic_props = dict(state.get("dynamic_props", {}))

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

    # ── Sequential label counters (per category) ──────────────────────────
    _lt_seq: int = 0   # new LT poles
    _ht_seq: int = 0   # new HT 11kV poles
    _33_seq: int = 0   # new HT 33kV poles
    
    # Existing pole counters (partitioned by subtype)
    _ex_type_seq: dict = {"LT": 0, "HT": 0, "33": 0, "DP": 0, "TP": 0, "4P": 0, "DTR": 0}

    @classmethod
    def _next_seq(cls, category: str, subtype: str = "LT") -> int:
        if category == "lt":
            cls._lt_seq += 1
            return cls._lt_seq
        elif category == "ht":
            cls._ht_seq += 1
            return cls._ht_seq
        elif category == "33":
            cls._33_seq += 1
            return cls._33_seq
        else: # ex
            cur = cls._ex_type_seq.get(subtype, 0) + 1
            cls._ex_type_seq[subtype] = cur
            return cur

    @classmethod
    def reset_counters(cls) -> None:
        cls._lt_seq = 0
        cls._ht_seq = 0
        cls._33_seq = 0
        cls._ex_type_seq = {"LT": 0, "HT": 0, "33": 0, "DP": 0, "TP": 0, "4P": 0, "DTR": 0}

    def __init__(
        self, x: float, y: float, refresh_signal: Any,
        pole_type: str = "LT", is_existing: bool = False,
        detail_view: bool = True, existing_subtype: str = "LT"
    ) -> None:
        QGraphicsPathItem.__init__(self)
        self._init_node(x, y, refresh_signal, detail_view)

        _d   = defaults.current
        _pfx = "lt_" if pole_type == "LT" else "ht_"

        self.pole_type          = pole_type
        self.pole_type2         = _d[_pfx + "pole_type2"] if not is_existing else "PCC"
        self.is_existing        = is_existing
        self.existing_subtype   = existing_subtype if is_existing else pole_type   # LT | HT | DP | TP | 4P | DTR
        self.existing_dtr_size  = "None"
        self.height             = _d[_pfx + "height"] if not is_existing else ("8MTR" if pole_type == "LT" else "9MTR")
        self.has_extension      = False
        self.extension_height   = _d["extension_height"]
        self.override_auto_stay = False
        self.iron_recipe        = "None"

        # Sequential label counter assigned lazily on update_visuals call
        self.seq_id    = 0
        self._seq_type = None

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

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "type": "Pole",
            "seq_id": self.seq_id,
            "pole_type": self.pole_type,
            "pole_type2": self.pole_type2,
            "is_existing": self.is_existing,
            "existing_subtype": self.existing_subtype,
            "existing_dtr_size": getattr(self, "existing_dtr_size", "None"),
            "height": self.height,
            "has_extension": self.has_extension,
            "extension_height": self.extension_height,
            "earth_count": self.earth_count,
            "stay_count": self.stay_count,
            "override_auto_stay": self.override_auto_stay,
            "stay_angle_override": self.stay_angle_override,
            "earth_angle_override": self.earth_angle_override,
            "voltage_level": getattr(self, "voltage_level", "11kV" if self.pole_type == "HT" else "LT"),
            "dist_box_required": self.dist_box_required,
            "iron_recipe": getattr(self, "iron_recipe", "None"),
        })
        return d

    def apply_state(self, state: dict) -> None:
        super().apply_state(state)
        self.pole_type = state.get("pole_type", "LT")
        self.pole_type2 = state.get("pole_type2", "PCC")
        self.is_existing = state.get("is_existing", False)
        self.existing_subtype = state.get("existing_subtype", self.pole_type)
        self.voltage_level = state.get("voltage_level", "33kV" if self.existing_subtype == "33" else ("11kV" if self.pole_type == "HT" else "LT"))
        self.existing_dtr_size = state.get("existing_dtr_size", "None")
        self.height = state.get("height", "8MTR")
        self.has_extension = state.get("has_extension", False)
        self.extension_height = state.get("extension_height", 3.0)
        self.earth_count = state.get("earth_count", 0)
        self.stay_count = state.get("stay_count", 0)
        self.override_auto_stay = state.get("override_auto_stay", False)
        self.stay_angle_override = state.get("stay_angle_override", None)
        self.earth_angle_override = state.get("earth_angle_override", None)
        self.dist_box_required = state.get("dist_box_required", False)
        self.iron_recipe = state.get("iron_recipe", "None")
        self.seq_id = state.get("seq_id", self.seq_id)
        if self.seq_id:
            self._seq_type = ("ex", self.existing_subtype) if self.is_existing else ("pole", self.pole_type)

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
            # Lazy-assign (or re-assign on subtype change) the sequential label number
            v_level = getattr(self, "voltage_level", "11kV")
            ex_sub = getattr(self, "existing_subtype", "")
            current_cat = ("ex", ex_sub) if self.is_existing else ("pole", v_level if v_level == "33kV" else self.pole_type)
            if not self.seq_id or getattr(self, "_seq_type", None) != current_cat:
                if self.is_existing:
                    self.seq_id = SmartPole._next_seq("ex", ex_sub)
                elif v_level == "33kV":
                    self.seq_id = SmartPole._next_seq("33")
                elif self.pole_type == "LT":
                    self.seq_id = SmartPole._next_seq("lt")
                else:
                    self.seq_id = SmartPole._next_seq("ht")
                self._seq_type = current_cat

            path = QPainterPath()

            # Main pole symbol shape according to type/condition
            r = self._RADIUS
            if self.is_existing and ex_sub in ("DP", "TP", "4P", "DTR"):
                path.addPath(_existing_struct_path(ex_sub))
            elif v_level == "33kV" or (self.is_existing and ex_sub == "33"):
                path.addPath(_diamond_path(r))
            elif self.pole_type == "LT" and not (self.is_existing and ex_sub == "HT"):
                # LT Pole: Circle
                path.addEllipse(-r, -r, r * 2, r * 2)
            else:
                # HT Pole: Perfect Square with sharp corners
                path.addRect(-r, -r, r * 2, r * 2)

            self.setPath(path)

            # Colours
            black_pen = QPen(Qt.GlobalColor.black, 1)
            _c = defaults.current
            if self.is_existing:
                is_aug_dtr = (
                    self.existing_subtype == "DTR"
                    and bool(getattr(self, "dynamic_props", {}).get("dtr_aug_required", False))
                )
                if is_aug_dtr:
                    self.setBrush(QBrush(QColor(_c.get("canvas_ex_aug_dtr", "#f7b267"))))
                    self.setPen(QPen(QColor("#7a4000"), 1.6, Qt.PenStyle.SolidLine))
                else:
                    self.setBrush(QBrush(QColor(255, 255, 255, 255)))
                    self.setPen(QPen(QColor("#222222"), 1.5, Qt.PenStyle.SolidLine))
            elif v_level == "33kV":
                self.setBrush(QBrush(QColor("#7e22ce")))
                self.setPen(black_pen)
            elif self.pole_type == "LT":
                _hk = "canvas_lt_pole_" + self.height.lower().replace(".", "_")
                _default_col = _c.get(_hk, _c.get("canvas_lt_pole", "#2980b9"))
                _ctx = {"pole_type": "LT", "pole_type2": str(self.pole_type2)}
                _user_col = option_colors.resolve_user_only("SmartPole", "height", str(self.height), _ctx)
                _col = _user_col if _user_col else _default_col
                
                # Check for custom properties that might override the color
                for k, v in getattr(self, "dynamic_props", {}).items():
                    _c_override = option_colors.resolve_user_only("SmartPole", k, str(v))
                    if _c_override: _col = _c_override
                    
                self.setBrush(QBrush(QColor(_col)))
                self.setPen(black_pen)
            else:  # HT
                _hk = "canvas_ht_pole_" + self.height.lower().replace(".", "_")
                _default_col = _c.get(_hk, _c.get("canvas_ht_pole", "#c0392b"))
                _ctx = {"pole_type": "HT", "pole_type2": str(self.pole_type2)}
                _user_col = option_colors.resolve_user_only("SmartPole", "height", str(self.height), _ctx)
                _col = _user_col if _user_col else _default_col
                
                # Check for custom properties that might override the color
                for k, v in getattr(self, "dynamic_props", {}).items():
                    _c_override = option_colors.resolve_user_only("SmartPole", k, str(v))
                    if _c_override: _col = _c_override
                    
                self.setBrush(QBrush(QColor(_col)))
                self.setPen(black_pen)

            # Label text
            _pfx_d = defaults.current
            if self.is_existing:
                _sub = self.existing_subtype
                if _sub == "33":
                    _lbl = _pfx_d.get("label_ex_33", "E33")
                else:
                    _lbl_key = "label_ex_pole" if _sub == "LT" else f"label_ex_{_sub.lower()}"
                    _lbl = _pfx_d.get(_lbl_key, _pfx_d.get("label_ex_pole", "ELT"))
                txt = f"{_lbl}{self.seq_id}"
                
                _sin = getattr(self, "dynamic_props", {}).get("sin", "")
                if _sin:
                    txt += f"\nSIN: {_sin}"
                
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
                    pass   # no extra line for plain existing poles
            else:
                if getattr(self, "voltage_level", "11kV") == "33kV":
                    _lbl = _pfx_d.get("label_new_33", "P33")
                elif self.pole_type == "LT":
                    _lbl = _pfx_d.get("label_new_lt", "PLT")
                else:
                    _lbl = _pfx_d.get("label_new_ht", "PHT")
                txt  = f"{_lbl}{self.seq_id}"
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
            show_lbl = getattr(getattr(self.scene(), "parent_app", None), "show_pole_labels", True)
            self.label.setVisible(show_lbl)

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
                        stay_angle = self.stay_angle_override % 360 if self.stay_angle_override is not None else self._calc_stay_angle()
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
        if painter is None:
            return

        r = self._RADIUS

        # ── 1. Draw stays and earthing BEHIND main pole body ───────────────────
        if self.detail_view:
            if self.stay_angle_override is not None:
                stay_angle = self.stay_angle_override % 360
            else:
                stay_angle = self._calc_stay_angle()

            if self.earth_angle_override is not None:
                earth_angle = self.earth_angle_override % 360
            else:
                earth_angle = self._calc_earth_angle(stay_angle)

            # Earthing symbols
            if self.earth_count > 0:
                n        = min(self.earth_count, 3)
                erad     = math.radians(earth_angle)
                perp_rad = math.radians(earth_angle + 90)
                att_x    = math.cos(erad) * (r + 2)
                att_y    = math.sin(erad) * (r + 2)
                painter.save()
                for i in range(n):
                    offset = (i - (n - 1) / 2) * 10
                    ex = att_x + math.cos(perp_rad) * offset
                    ey = att_y + math.sin(perp_rad) * offset
                    painter.drawPath(_earth_path(ex, ey, earth_angle))
                painter.restore()

            # Stay wire symbols
            if self.stay_count > 0:
                spread = [0, -25, 25, -50]
                painter.save()
                painter.setPen(QPen(QColor("#222222"), 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for i in range(min(self.stay_count, 4)):
                    ang = (stay_angle + spread[i]) % 360
                    painter.drawPath(_stay_path(ang))
                painter.restore()

        # ── 2. Draw main pole body (circle/square) ON TOP of stays/earthing ─────
        super().paint(painter, option, widget)

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

        # Inner symbol badge text inside pole (max 2 characters)
        r = self._RADIUS
        symbol_rect = QRectF(-r, -r, r * 2, r * 2)
        badge_text = _get_2char_pole_badge(self)
        if self.is_existing and self.existing_subtype in ("DP", "TP", "4P", "DTR"):
            badge_text = ""

        if badge_text:
            painter.save()
            if self.is_existing:
                text_col = QColor("#222222")
            else:
                text_col = QColor("#ffffff")
            painter.setPen(QPen(text_col))
            font = QFont("Arial", 5, QFont.Weight.Bold)
            font.setPixelSize(7)
            painter.setFont(font)
            painter.drawText(symbol_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
            painter.restore()
    def itemChange(self, change: QGraphicsPathItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsPathItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_position_changed()
        return super().itemChange(change, value)


# ─────────────────────────────────────────────────────────────────────────────
#  SmartStructure
# ─────────────────────────────────────────────────────────────────────────────

