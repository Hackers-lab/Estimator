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
from core import option_colors
from ui.components import DraggableLabel

if TYPE_CHECKING:
    _NodeBase = QGraphicsPathItem
else:
    _NodeBase = object
from canvas._base import _NodeMixin, _earth_path, _stay_path, _STAY_LENGTH, _ARROW_LEN, SmartPole

class SmartStructure(_NodeMixin, QGraphicsPathItem):
    """
    An HT multi-pole structure on the canvas.

    Structure types and their canvas symbols
    ----------------------------------------
    DP  — 2 circles side by side  (like old DTR symbol)
    TP  — 3 circles in triangle
    4P  — 4 circles in square (2×2)
    DTR — 2 circles + horizontal transformer body between them

    Earth defaults: DP=2, TP=3, 4P=4, DTR=5
    Stay default  : 4 for all types
    """

    _COLORS = {
        "DP":  QColor("#27ae60"),   # green
        "TP":  QColor("#1abc9c"),   # teal
        "4P":  QColor("#16a085"),   # dark teal
        "DTR": QColor("#e67e22"),   # orange
    }
    _RADIUS: int = 8
    _GAP: int = 6

    # ── Sequential label counters (per structure type) ────────────────────────
    _type_seq: dict = {"DP": 0, "TP": 0, "4P": 0, "DTR": 0}

    @classmethod
    def _next_seq(cls, st: str) -> int:
        cls._type_seq[st] = cls._type_seq.get(st, 0) + 1
        return cls._type_seq[st]

    @classmethod
    def reset_counters(cls) -> None:
        cls._type_seq = {"DP": 0, "TP": 0, "4P": 0, "DTR": 0}

    def __init__(self, x: float, y: float, refresh_signal: Any, detail_view: bool = True) -> None:
        QGraphicsPathItem.__init__(self)
        self._init_node(x, y, refresh_signal, detail_view)

        _d = defaults.current

        self.structure_type   = "DP"
        self.pole_type2       = _d["struct_pole_type2"]
        self.height           = _d["struct_height"]
        self.orientation      = _d.get("struct_orientation", "Horizontal")
        self.has_extension    = False
        self.extension_height = _d["extension_height"]
        self.earth_count      = _d.get("earth_default_dp", 2)
        self.stay_count       = _d["struct_stay_count"]
        self.dtr_size         = "None"
        self.kiosk_required   = bool(_d.get("dtr_kiosk_required", True))

        # seq_id starts at 0; assigned lazily on first update_visuals call
        # (because structure_type may be changed after __init__)
        self.seq_id    = 0
        self._seq_type = None   # tracks which type the seq_id was assigned for

        self.label = DraggableLabel(self)

        self.update_visuals()

    # ── Visual update ─────────────────────────────────────────────────────────

    def update_visuals(self) -> None:
        # Lazy-assign (or re-assign on type change) the sequential label number
        if not self.seq_id or self._seq_type != self.structure_type:
            self.seq_id    = SmartStructure._next_seq(self.structure_type)
            self._seq_type = self.structure_type

        path = QPainterPath()
        r    = self._RADIUS
        gap  = self._GAP

        st = self.structure_type

        def _draw_connecting_lines(path, offsets, radius):
            for i in range(len(offsets)):
                p1 = offsets[i]
                p2 = offsets[(i + 1) % len(offsets)]
                
                # Vector from p1 to p2
                vx, vy = p2[0] - p1[0], p2[1] - p1[1]
                dist = math.hypot(vx, vy)
                
                if dist == 0:
                    continue
                
                # Normalized vector
                nx, ny = vx / dist, vy / dist
                
                # Points on the circumference
                start_x, start_y = p1[0] + nx * radius, p1[1] + ny * radius
                end_x, end_y = p2[0] - nx * radius, p2[1] - ny * radius
                
                path.moveTo(start_x, start_y)
                path.lineTo(end_x, end_y)

        if st == "DP":
            # Two circles side by side
            cx = r + gap // 2
            path.addEllipse(-cx - r, -r, r * 2, r * 2)
            path.addEllipse( cx - r, -r, r * 2, r * 2)
            # Connecting bar
            path.moveTo(-cx + r, 0)
            path.lineTo( cx - r, 0)

        elif st == "TP":
            # Triangle: top + bottom-left + bottom-right
            offsets = [
                (0,           -(r + gap // 2)),          # top
                (-(r + gap),   (r + gap // 2)),           # bottom-left
                ( (r + gap),   (r + gap // 2)),           # bottom-right
            ]
            for ox, oy in offsets:
                path.addEllipse(ox - r, oy - r, r * 2, r * 2)
            # Connecting lines
            _draw_connecting_lines(path, offsets, r)

        elif st == "4P":
            # 2×2 square grid
            d = r + gap // 2
            offsets = [(-d, -d), (d, -d), (d, d), (-d, d)]
            for ox, oy in offsets:
                path.addEllipse(ox - r, oy - r, r * 2, r * 2)
            # Connecting lines
            _draw_connecting_lines(path, offsets, r)

        elif st == "DTR":
            # Two circles with transformer body between
            cx = r + gap // 2 + 4
            path.addEllipse(-cx - r, -r, r * 2, r * 2)
            path.addEllipse( cx - r, -r, r * 2, r * 2)
            # Transformer body — rectangle
            path.addRect(-gap // 2 - 2, -r // 2, gap + 4, r)
            # HV/LV winding hint lines
            path.moveTo(-gap // 2 - 2, 0)
            path.lineTo( gap // 2 + 2, 0)

        # Extension indicator
        if self.has_extension:
            path.addRect(-4, -(r * 2 + 14), 8, 8)

        # Earth symbols below structure
        if self.detail_view and self.earth_count > 0:
            bottom_y = r + 2 if st in ("DP", "DTR") else r + gap // 2 + r + 2
            for i in range(min(self.earth_count, 5)):
                x_off = (i - (min(self.earth_count, 5) - 1) / 2) * 14
                path.addPath(_earth_path(x_off, bottom_y))

        # Stay wire symbols
        if self.detail_view and self.stay_count > 0:
            stay_angles = [225, 315, 180, 0, 270, 90]
            for i in range(min(self.stay_count, 6)):
                path.addPath(_stay_path(stay_angles[i % 6]))

        if str(getattr(self, "orientation", "Horizontal")).lower().startswith("v"):
            path = QTransform().rotate(90).map(path)

        self.setPath(path)

        # Colour
        _struct_color_keys = {
            "DP":  "canvas_dp",
            "TP":  "canvas_tp",
            "4P":  "canvas_4p",
            "DTR": "canvas_dtr",
        }
        _default_col = defaults.current.get(_struct_color_keys.get(st, "canvas_dp"), "#27ae60")
        _user_col = option_colors.resolve_user_only("SmartStructure", "structure_type", str(st))
        _color_hex = _user_col if _user_col else _default_col
        
        for k, v in getattr(self, "dynamic_props", {}).items():
            _c_override = option_colors.resolve_user_only("SmartStructure", k, str(v))
            if _c_override: _color_hex = _c_override
            
        self.setBrush(QBrush(QColor(_color_hex)))
        self.setPen(QPen(Qt.GlobalColor.black, 1.5))

        # Label
        _pfx_d = defaults.current
        _lbl_keys = {"DP": "label_dp", "TP": "label_tp", "4P": "label_4p", "DTR": "label_dtr"}
        _pfx = _pfx_d.get(_lbl_keys.get(st, "label_dp"), st)
        txt  = f"{_pfx}{self.seq_id}"
        if st == "DTR" and self.dtr_size != "None":
            txt += f"\n{self.dtr_size} DTR"
        aug_required = bool(getattr(self, "dynamic_props", {}).get("dtr_aug_required", False))
        if st == "DTR" and aug_required:
            target = str(getattr(self, "dynamic_props", {}).get("dtr_new_size", "") or "")
            if target:
                txt += f"\nEx {self.dtr_size} S/STN to {target} S/STN"
            else:
                txt += "\nDTR Augmentation"
        if self.has_extension:
            txt += f"\n+Ext {self.extension_height:.1f}m"
        if (not self.detail_view) and self.earth_count > 0:
            txt += f"\n⏚ {self.earth_count} Earth"
        if (not self.detail_view) and self.stay_count > 0:
            txt += f"\nS×{self.stay_count} Stay"
        if self.custom_note:
            txt += f"\n📝 {self.custom_note}"

        self.label.setPlainText(txt)
        if not getattr(self.label, "user_moved", False):
            self.label.set_auto_pos(-(self.label.boundingRect().width() / 2), 26)

    # ── Qt overrides ──────────────────────────────────────────────────────────
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        super().paint(painter, option, widget)
        if painter is None:
            return
        if self.has_extension:
            r = self._RADIUS
            badge = QRectF(-5, -(r * 2 + 22), 10, 10)
            painter.save()
            painter.setPen(QPen(QColor("#1a5276"), 1))
            painter.setBrush(QBrush(QColor("#d6eaf8")))
            painter.drawRoundedRect(badge, 2, 2)
            painter.setPen(QPen(QColor("#1a5276"), 1))
            painter.setFont(QFont("Arial", 5, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "E")
            painter.restore()
        if (
            self.structure_type == "DTR"
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
#  SmartConsumer
# ─────────────────────────────────────────────────────────────────────────────

class SmartConsumer(_NodeMixin, QGraphicsPathItem):
    """
    A consumer service point on the canvas (replaces SmartHome).

    Symbol: house shape (same as before) — yellow fill.
    Agency supply shown as 'A' badge on the symbol when True.

    Properties
    ----------
    phase         : "1 Phase" | "3 Phase"
    cable_size    : e.g. "10 SQMM"
    agency_supply : bool  — True = agency supplied, False = WBSEDCL
    """

    # ── Sequential label counter ──────────────────────────────────────────────
    _con_seq: int = 0

    @classmethod
    def _next_seq(cls) -> int:
        cls._con_seq += 1
        return cls._con_seq

    @classmethod
    def reset_counters(cls) -> None:
        cls._con_seq = 0

    def __init__(self, x: float, y: float, refresh_signal: Any, detail_view: bool = True) -> None:
        QGraphicsPathItem.__init__(self)
        self._init_node(x, y, refresh_signal, detail_view)

        _d = defaults.current
        self.phase          = _d.get("sd_phase", "3 Phase")
        self.cable_size     = _d.get("sd_conductor_size", "10 SQMM")
        self.agency_supply  = False
        self.consider_cable = False

        self.seq_id = SmartConsumer._next_seq()

        # Build house path (static — does not change)
        house = QPainterPath()
        house.addRect(-10, 0, 20, 18)       # walls
        house.moveTo(-14, 0)
        house.lineTo(0, -14)                 # roof left
        house.lineTo(14, 0)                  # roof right
        self.setPath(house)
        self.setBrush(QBrush(QColor(defaults.current.get("canvas_consumer", "#f1c40f"))))
        self.setPen(QPen(Qt.GlobalColor.black, 1))

        self.label = DraggableLabel(self)
        self.label.setPos(0, 20)

        self.update_visuals()

    # ── Visual update ─────────────────────────────────────────────────────────

    def update_visuals(self) -> None:
        _pfx = defaults.current.get("label_consumer", "SC")
        phase_short = "1φ" if self.phase == "1 Phase" else "3φ"
        supply_tag  = " [A]" if self.agency_supply else ""
        txt = f"{_pfx}{self.seq_id}\n{phase_short}{supply_tag}"
        if self.custom_note:
            txt += f"\n📝 {self.custom_note}"

        if bool(getattr(self, "dynamic_props", {}).get("conductor_aug_required", False)):
            from_cfg = str(getattr(self, "dynamic_props", {}).get("aug_from_config", "") or "")
            to_cfg = str(getattr(self, "dynamic_props", {}).get("aug_to_config", "") or "")
            to_cond = str(getattr(self, "dynamic_props", {}).get("aug_to_conductor", "") or "")
            aug_txt = "AUG"
            if from_cfg and to_cfg:
                aug_txt = f"AUG {from_cfg}->{to_cfg}"
            elif to_cfg:
                aug_txt = f"AUG TO {to_cfg}"
            if to_cond:
                aug_txt += f" ({to_cond})"
            txt += f"\n{aug_txt}"
        self.label.setPlainText(txt)
        if not getattr(self.label, "user_moved", False):
            self.label.set_auto_pos(-(self.label.boundingRect().width() / 2), 20)

        # Colour hint for agency vs WBSEDCL
        _color_hex = "#f1c40f"
        if self.agency_supply:
            _default_col = defaults.current.get("canvas_consumer_agency", "#f39c12")
            _user_col = option_colors.resolve_user_only("SmartConsumer", "agency_supply", "True")
            _color_hex = _user_col if _user_col else _default_col
        else:
            _default_col = defaults.current.get("canvas_consumer", "#f1c40f")
            _user_col = option_colors.resolve_user_only("SmartConsumer", "agency_supply", "False")
            _color_hex = _user_col if _user_col else _default_col

        for k, v in getattr(self, "dynamic_props", {}).items():
            _c_override = option_colors.resolve_user_only("SmartConsumer", k, str(v))
            if _c_override: _color_hex = _c_override

        self.setBrush(QBrush(QColor(_color_hex)))

    # ── Qt overrides ──────────────────────────────────────────────────────────

    def itemChange(self, change: QGraphicsPathItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsPathItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_position_changed()
        return super().itemChange(change, value)


# ─────────────────────────────────────────────────────────────────────────────
#  SmartSpan
# ─────────────────────────────────────────────────────────────────────────────

