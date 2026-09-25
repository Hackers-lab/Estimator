from __future__ import annotations
import math
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QWidget, QStyleOptionGraphicsItem,
    QColorDialog, QMenu,
)
from PyQt6.QtGui import (
    QPainterPath, QPainterPathStroker, QBrush, QColor, QPen, QFont, QPainter,
    QTransform, QTextCursor,
)
from PyQt6.QtCore import Qt, QRectF, QPointF


# ─────────────────────────────────────────────────────────────────────────────
#  Cursor & notification helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_resize_cursor(local_action: str, rotation_deg: float) -> Qt.CursorShape:
    """
    Returns the visually correct Qt CursorShape for a resize handle,
    taking into account the item's current rotation on the screen.
    """
    angle = rotation_deg % 180
    if angle < 0:
        angle += 180

    if local_action in ("resize_l", "resize_r"):
        # Local X-axis (width)
        pass
    elif local_action in ("resize_t", "resize_b"):
        # Local Y-axis (height)
        angle = (angle + 90) % 180
    elif local_action in ("resize_tl", "resize_br"):
        # Top-Left to Bottom-Right diagonal (\)
        angle = (angle + 45) % 180
    elif local_action in ("resize_tr", "resize_bl"):
        # Top-Right to Bottom-Left diagonal (/)
        angle = (angle + 135) % 180
    else:
        return Qt.CursorShape.SizeAllCursor

    # Map the global screen angle back to standard Qt cursors
    # 0/180 = horizontal, 90 = vertical, 45 = BDiag (\), 135 = FDiag (/)
    if angle <= 22.5 or angle >= 157.5:
        return Qt.CursorShape.SizeHorCursor
    elif 22.5 < angle <= 67.5:
        return Qt.CursorShape.SizeBDiagCursor
    elif 67.5 < angle <= 112.5:
        return Qt.CursorShape.SizeVerCursor
    else:
        return Qt.CursorShape.SizeFDiagCursor


_CUR_DEFAULT  = Qt.CursorShape.ArrowCursor
_CUR_MOVE     = Qt.CursorShape.SizeAllCursor
_CUR_ROTATE   = Qt.CursorShape.CrossCursor


def _notify_canvas_changed(item: QGraphicsItem) -> None:
    """Notify the application that an annotation item changed (for undo & autosave)."""
    scene = item.scene()
    if not scene:
        return
    for view in scene.views():
        app = getattr(view, "parent_app", None)
        if app is not None:
            if hasattr(app, "refresh_live_estimate"):
                app.refresh_live_estimate()
            return
    for s_item in scene.items():
        sig = getattr(s_item, "refresh_signal", None)
        if sig is not None:
            sig.emit()
            break


def _delete_annotation_item(item: QGraphicsItem) -> None:
    """Safely delete an annotation item via the parent app if available."""
    scene = item.scene()
    if not scene:
        return
    for view in scene.views():
        app = getattr(view, "parent_app", None)
        if app is not None and hasattr(app, "delete_item"):
            app.delete_item(item)
            return
    scene.removeItem(item)
    _notify_canvas_changed(item)


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS SYMBOL
# ─────────────────────────────────────────────────────────────────────────────

class CanvasSymbol(QGraphicsItem):
    """
    Resizable, rotatable annotation shape.

    Interaction uses invisible zones on edges/corners. The mouse cursor
    auto-rotates to match the visual orientation of the shape on screen.
    """

    MIN_DIM  = 10.0
    EDGE_TOL = 12.0   # px from edge that triggers resize cursor
    ROT_ZONE = 24.0   # px above shape top that is the rotation zone

    SHAPES = ("circle", "square", "arrow", "line", "dashed_line", "road", "rail")

    def __init__(self, shape: str = "circle",
                 x: float = 0, y: float = 0,
                 width: float = 60.0,
                 height: float = 60.0,
                 color: str = "#222222",
                 rotation: float = 0.0,
                 z_value: float = -1.0) -> None:
        super().__init__()
        self.shape   = shape
        self._width  = max(width,  self.MIN_DIM)
        self._height = max(height, self.MIN_DIM)
        self._color  = color
        self.setPos(x, y)
        self.setRotation(rotation)
        self.setZValue(z_value)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self._action: str | None = None
        self._drag_start_scene   = QPointF()
        self._drag_start_w       = self._width
        self._drag_start_h       = self._height
        self._drag_start_pos     = QPointF()

    def _hw(self) -> float: return self._width  / 2.0
    def _hh(self) -> float: return self._height / 2.0

    def _is_line(self) -> bool:
        return self.shape in ("line", "dashed_line")

    def _body_rect(self) -> QRectF:
        if self._is_line():
            return QRectF(-self._hw(), -6.0, self._width, 12.0)
        return QRectF(-self._hw(), -self._hh(), self._width, self._height)

    def _rot_zone_rect(self) -> QRectF:
        hh = 6.0 if self._is_line() else self._hh()
        return QRectF(-20.0, -hh - self.ROT_ZONE, 40.0, self.ROT_ZONE)

    def _effective_edge_tol(self) -> tuple[float, float]:
        """Compute safe edge tolerance preventing inversion when shapes are small."""
        hw = self._hw()
        hh = 6.0 if self._is_line() else self._hh()
        ex = min(self.EDGE_TOL, hw * 0.45)
        ey = min(self.EDGE_TOL, hh * 0.45)
        return ex, ey

    def _zone_of(self, lp: QPointF) -> str | None:
        if self._rot_zone_rect().contains(lp):
            return "rotate"

        hw = self._hw()

        if self._is_line():
            if abs(lp.y()) <= 12.0:
                if lp.x() < -hw + self.EDGE_TOL:
                    return "resize_l"
                if lp.x() > hw - self.EDGE_TOL:
                    return "resize_r"
                return "move"
            return None

        hh = self._hh()
        ex, ey = self._effective_edge_tol()

        at_left   = (lp.x() < -hw + ex)
        at_right  = (lp.x() > hw - ex)
        at_top    = (lp.y() < -hh + ey)
        at_bottom = (lp.y() > hh - ey)

        # Corners
        if at_top and at_left:     return "resize_tl"
        if at_top and at_right:    return "resize_tr"
        if at_bottom and at_left:  return "resize_bl"
        if at_bottom and at_right: return "resize_br"

        # Edges
        if at_left:   return "resize_l"
        if at_right:  return "resize_r"
        if at_top:    return "resize_t"
        if at_bottom: return "resize_b"

        # Inside
        if self._body_rect().contains(lp):
            return "move"

        return None

    def boundingRect(self) -> QRectF:
        pad = 8.0
        hw = max(self._hw(), 24.0)
        hh = 6.0 if self._is_line() else self._hh()
        top = -hh - self.ROT_ZONE - pad
        height = (hh + pad) - top
        return QRectF(-hw - pad, top, (hw + pad) * 2.0, height)

    def shape(self) -> QPainterPath:    # type: ignore[override]
        raw = self._build_shape_path()
        stroker = QPainterPathStroker()
        stroker.setWidth(max(12.0, self.EDGE_TOL * 2.0))
        hit = stroker.createStroke(raw)

        if self.shape in ("circle", "square", "arrow", "road", "rail"):
            hit = hit.united(raw)
            hw = self._hw()
            hh = self._hh()
            ex, ey = self._effective_edge_tol()
            bands = QPainterPath()
            bands.addRect(QRectF(-hw, -hh, self._width, ey))
            bands.addRect(QRectF(-hw, hh - ey, self._width, ey))
            bands.addRect(QRectF(-hw, -hh, ex, self._height))
            bands.addRect(QRectF(hw - ex, -hh, ex, self._height))
            hit = hit.united(bands)

        rot_zone = QPainterPath()
        rot_zone.addRect(self._rot_zone_rect())
        hit = hit.united(rot_zone)

        return hit

    def _build_shape_path(self) -> QPainterPath:
        hw   = self._hw()
        hh   = self._hh()
        path = QPainterPath()

        if self.shape == "circle":
            path.addEllipse(self._body_rect())
        elif self.shape == "square":
            path.addRect(self._body_rect())
        elif self.shape == "arrow":
            shaft_h   = hh * 0.40
            head_h    = hh
            head_len  = min(hw * 0.9, max(12.0, hw * 0.45))
            shaft_end = hw - head_len
            path.moveTo(-hw,       -shaft_h)
            path.lineTo(shaft_end, -shaft_h)
            path.lineTo(shaft_end, -head_h)
            path.lineTo( hw,        0)
            path.lineTo(shaft_end,  head_h)
            path.lineTo(shaft_end,  shaft_h)
            path.lineTo(-hw,        shaft_h)
            path.closeSubpath()
        elif self.shape in ("road", "rail"):
            path.addRect(self._body_rect())
        elif self._is_line():
            path.moveTo(-hw, 0)
            path.lineTo( hw, 0)

        return path

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = QColor(self._color)

        if self.shape == "road":
            hw = self._hw()
            hh = self._hh()

            # Subtle asphalt background
            asphalt_col = QColor(color)
            asphalt_col.setAlpha(28)
            painter.setBrush(QBrush(asphalt_col))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(self._body_rect())

            # Two solid outer curb lines
            curb_pen = QPen(color, 2.0, Qt.PenStyle.SolidLine)
            curb_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(curb_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(-hw, -hh), QPointF(hw, -hh))
            painter.drawLine(QPointF(-hw,  hh), QPointF(hw,  hh))

            # Dashed center dividing lane
            div_pen = QPen(color, 1.4, Qt.PenStyle.CustomDashLine)
            div_pen.setDashPattern([6, 4])
            div_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(div_pen)
            painter.drawLine(QPointF(-hw, 0), QPointF(hw, 0))
        elif self.shape == "rail":
            hw = self._hw()
            hh = self._hh()

            # Cross-ties (railway sleepers) drawn regularly across track length
            tie_spacing = max(8.0, min(16.0, hh * 1.2))
            tie_pen = QPen(color, 1.5, Qt.PenStyle.SolidLine)
            tie_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(tie_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            x = -hw + (tie_spacing / 2.0)
            while x <= hw:
                painter.drawLine(QPointF(x, -hh), QPointF(x, hh))
                x += tie_spacing

            # Two continuous steel rail lines running parallel along track length
            rail_inset = max(1.0, hh * 0.25)
            rail_pen = QPen(color, 2.4, Qt.PenStyle.SolidLine)
            rail_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(rail_pen)
            painter.drawLine(QPointF(-hw, -hh + rail_inset), QPointF(hw, -hh + rail_inset))
            painter.drawLine(QPointF(-hw,  hh - rail_inset), QPointF(hw,  hh - rail_inset))
        else:
            pen = QPen(color, 1.8)
            if self.shape == "dashed_line":
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._build_shape_path())

        if self.isSelected():
            hw = self._hw()
            hh = 6.0 if self._is_line() else self._hh()

            if self._is_line():
                # Line specific selection: endpoint grips
                painter.setPen(QPen(QColor("#2980b9"), 1.0, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(-hw, 0), QPointF(hw, 0))
                grip_r = 3.5
                painter.setBrush(QBrush(QColor("#ffffff")))
                painter.setPen(QPen(QColor("#2980b9"), 1.2))
                painter.drawRect(QRectF(-hw - grip_r, -grip_r, grip_r * 2, grip_r * 2))
                painter.drawRect(QRectF(hw - grip_r, -grip_r, grip_r * 2, grip_r * 2))
            else:
                painter.setPen(QPen(QColor("#2980b9"), 1.0, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self._body_rect())

            # Rotation handle
            painter.setPen(QPen(QColor("#e74c3c"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cy = -hh - 12.0
            r  = 7.0
            painter.drawArc(QRectF(-r, cy - r, r * 2, r * 2), 30 * 16, 300 * 16)
            painter.drawLine(QPointF(r * 0.5, cy - r), QPointF(r + 4, cy - r + 3))
            painter.drawLine(QPointF(r * 0.5, cy - r), QPointF(r - 3, cy - r - 4))
            painter.setPen(QPen(QColor("#e74c3c"), 1.0, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(0, -hh), QPointF(0, cy + r))

        painter.restore()

    def hoverMoveEvent(self, event) -> None:
        if not self.isSelected():
            self.setCursor(_CUR_MOVE)
            return
        zone = self._zone_of(event.pos())
        if zone == "rotate":
            self.setCursor(_CUR_ROTATE)
        elif zone and zone.startswith("resize"):
            self.setCursor(_get_resize_cursor(zone, self.rotation()))
        else:
            self.setCursor(_CUR_MOVE)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setCursor(_CUR_DEFAULT)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self.isSelected():
            self._action = None
            super().mousePressEvent(event)
            return

        zone = self._zone_of(event.pos())
        if zone and zone != "move":
            self._action           = zone
            self._drag_start_scene = event.scenePos()
            self._drag_start_w     = self._width
            self._drag_start_h     = self._height
            self._drag_start_pos   = self.pos()
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
        else:
            self._action = None
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._action:
            super().mouseMoveEvent(event)
            return

        if self._action == "rotate":
            centre = self.mapToScene(QPointF(0, 0))
            sx = event.scenePos().x() - centre.x()
            sy = event.scenePos().y() - centre.y()
            self.setRotation(math.degrees(math.atan2(sy, sx)) + 90)
            event.accept()
            return

        scene_delta = event.scenePos() - self._drag_start_scene
        t_inv_rot = QTransform().rotate(-self.rotation())
        local_delta = t_inv_rot.map(scene_delta)
        dx = local_delta.x()
        dy = local_delta.y()

        new_w = self._drag_start_w
        new_h = self._drag_start_h
        shift_x = 0.0
        shift_y = 0.0

        if "l" in self._action:
            new_w = max(self.MIN_DIM, self._drag_start_w - dx)
            actual_dw = new_w - self._drag_start_w
            shift_x = -actual_dw / 2.0
        elif "r" in self._action:
            new_w = max(self.MIN_DIM, self._drag_start_w + dx)
            actual_dw = new_w - self._drag_start_w
            shift_x = actual_dw / 2.0

        if not self._is_line():
            if "t" in self._action:
                new_h = max(self.MIN_DIM, self._drag_start_h - dy)
                actual_dh = new_h - self._drag_start_h
                shift_y = -actual_dh / 2.0
            elif "b" in self._action:
                new_h = max(self.MIN_DIM, self._drag_start_h + dy)
                actual_dh = new_h - self._drag_start_h
                shift_y = actual_dh / 2.0

        if new_w != self._width or new_h != self._height:
            self.prepareGeometryChange()
            self._width  = new_w
            self._height = new_h
            
            t_rot = QTransform().rotate(self.rotation())
            scene_shift = t_rot.map(QPointF(shift_x, shift_y))
            self.setPos(self._drag_start_pos + scene_shift)

        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._action:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._action = None
        super().mouseReleaseEvent(event)
        _notify_canvas_changed(self)

    def contextMenuEvent(self, event) -> None:
        if self.scene() is not None:
            views = self.scene().views()
            if views:
                view = views[0]
                if hasattr(view, "parent_app") and getattr(view.parent_app, "project_locked", False):
                    event.accept()
                    return
        menu = QMenu()
        menu.addAction("🎨  Change Colour", self._pick_color)
        if self.rotation() != 0.0:
            menu.addAction("🔄  Reset Rotation", self._reset_rotation)
        menu.addSeparator()
        menu.addAction("📋  Duplicate",     self._duplicate)
        menu.addAction("⬆  Bring to Front", lambda: self._change_z(1))
        menu.addAction("⬇  Send to Back",   lambda: self._change_z(-1))
        menu.addSeparator()
        menu.addAction("🗑  Delete",        lambda: _delete_annotation_item(self))
        menu.exec(event.screenPos())
        event.accept()

    def _change_z(self, delta: int) -> None:
        self.setZValue(self.zValue() + delta)
        _notify_canvas_changed(self)

    def _reset_rotation(self) -> None:
        self.setRotation(0.0)
        self.update()
        _notify_canvas_changed(self)

    def _duplicate(self) -> None:
        if not self.scene():
            return
        clone = CanvasSymbol(
            shape=self.shape,
            x=self.x() + 20,
            y=self.y() + 20,
            width=self._width,
            height=self._height,
            color=self._color,
            rotation=self.rotation(),
            z_value=self.zValue(),
        )
        self.scene().addItem(clone)
        self.scene().clearSelection()
        clone.setSelected(True)
        _notify_canvas_changed(clone)

    def _pick_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._color), None, "Choose Symbol Colour")
        if col.isValid():
            self._color = col.name()
            self.update()
            _notify_canvas_changed(self)

    def to_dict(self) -> dict:
        return {
            "kind":     "symbol",
            "shape":    self.shape,
            "x":        self.x(),
            "y":        self.y(),
            "width":    self._width,
            "height":   self._height,
            "color":    self._color,
            "rotation": self.rotation(),
            "size":     self._width,
            "z_value":  self.zValue(),
        }

    @staticmethod
    def from_dict(d: dict) -> "CanvasSymbol":
        legacy = d.get("size", 60.0)
        return CanvasSymbol(
            d["shape"], d["x"], d["y"],
            d.get("width",  legacy),
            d.get("height", legacy),
            d.get("color",  "#222222"),
            d.get("rotation", 0.0),
            z_value=d.get("z_value", -1.0),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS TEXT BOX
# ─────────────────────────────────────────────────────────────────────────────

class CanvasTextBox(QGraphicsTextItem):
    """
    A freely-positionable text annotation with rotation and scaling support.
    """

    MIN_FONT          = 6.0
    MAX_FONT          = 144.0
    DEFAULT_FONT_SIZE = 10.0
    EDGE_TOL          = 10.0
    ROT_ZONE          = 24.0

    def __init__(self, text: str = "Text", x: float = 0, y: float = 0,
                 font_size: float = DEFAULT_FONT_SIZE,
                 color: str = "#111111",
                 rotation: float = 0.0,
                 z_value: float = -1.0) -> None:
        super().__init__(text)
        self._font_size = max(self.MIN_FONT, min(self.MAX_FONT, font_size))
        self._color     = color
        self.setPos(x, y)
        self.setRotation(rotation)
        self.setZValue(z_value)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        self._action           = None
        self._drag_start_scene = QPointF()
        self._drag_start_fsize = self._font_size
        self._drag_start_dist  = 1.0

        self._apply_font()

    def _text_br(self) -> QRectF:
        return super().boundingRect()

    def _apply_font(self) -> None:
        """Apply font size while preserving the item's visual center on canvas."""
        has_pos = hasattr(self, "pos") and self.scene() is not None
        old_center = self.mapToScene(self._text_br().center()) if has_pos else None

        self.prepareGeometryChange()
        f = QFont("Arial")
        f.setPointSizeF(self._font_size)
        self.setFont(f)
        self.setDefaultTextColor(QColor(self._color))
        self.setTransformOriginPoint(self._text_br().center())

        if old_center is not None:
            new_center = self.mapToScene(self._text_br().center())
            self.setPos(self.pos() + (old_center - new_center))

    def _rot_zone_rect(self) -> QRectF:
        tbr = self._text_br()
        cx = tbr.center().x()
        rot_w = max(tbr.width(), 40.0)
        return QRectF(cx - rot_w / 2.0, tbr.top() - self.ROT_ZONE, rot_w, self.ROT_ZONE)

    def _zone_of(self, lp: QPointF) -> str | None:
        if self._rot_zone_rect().contains(lp):
            return "rotate"
        
        tbr = self._text_br()
        e   = min(self.EDGE_TOL, tbr.width() * 0.35, tbr.height() * 0.35)
        
        at_left   = (lp.x() < tbr.left() + e)
        at_right  = (lp.x() > tbr.right() - e)
        at_top    = (lp.y() < tbr.top() + e)
        at_bottom = (lp.y() > tbr.bottom() - e)

        # Corners
        if at_top and at_left:     return "resize_tl"
        if at_top and at_right:    return "resize_tr"
        if at_bottom and at_left:  return "resize_bl"
        if at_bottom and at_right: return "resize_br"

        # Edges
        if at_left:   return "resize_l"
        if at_right:  return "resize_r"
        if at_top:    return "resize_t"
        if at_bottom: return "resize_b"

        if tbr.contains(lp):
            return "move"

        return None

    def boundingRect(self) -> QRectF:
        tbr = self._text_br()
        cx  = tbr.center().x()
        pad = 6.0
        min_x = min(tbr.left() - pad, cx - 22.0)
        max_x = max(tbr.right() + pad, cx + 22.0)
        top = tbr.top() - self.ROT_ZONE - pad
        bottom = tbr.bottom() + pad
        return QRectF(min_x, top, max_x - min_x, bottom - top)

    def shape(self) -> QPainterPath:    # type: ignore[override]
        path = QPainterPath()
        path.addRect(self._text_br())
        path.addRect(self._rot_zone_rect())
        return path

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        is_editing = bool(self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction)

        if self.isSelected() and not is_editing:
            tbr = self._text_br()
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Translucent selection background
            painter.setPen(QPen(QColor("#2980b9"), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(41, 128, 185, 25)))
            painter.drawRect(tbr)

            # Rotation widget
            painter.setPen(QPen(QColor("#e74c3c"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cy = tbr.top() - 12.0
            cx = tbr.center().x()
            r  = 6.0
            painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 30 * 16, 300 * 16)
            painter.drawLine(QPointF(cx + r * 0.5, cy - r), QPointF(cx + r + 3, cy - r + 3))
            painter.drawLine(QPointF(cx + r * 0.5, cy - r), QPointF(cx + r - 2, cy - r - 3))
            painter.setPen(QPen(QColor("#e74c3c"), 1.0, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(cx, tbr.top()), QPointF(cx, cy + r))
            painter.restore()

        super().paint(painter, option, widget)

    def hoverMoveEvent(self, event) -> None:
        is_editing = bool(self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction)
        if is_editing:
            self.setCursor(Qt.CursorShape.IBeamCursor)
            super().hoverMoveEvent(event)
            return

        if not self.isSelected():
            self.setCursor(Qt.CursorShape.IBeamCursor)
            return

        zone = self._zone_of(event.pos())
        if zone == "rotate":
            self.setCursor(_CUR_ROTATE)
        elif zone and zone.startswith("resize"):
            self.setCursor(_get_resize_cursor(zone, self.rotation()))
        else:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setCursor(_CUR_DEFAULT)
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.scene() is not None:
            views = self.scene().views()
            if views:
                view = views[0]
                if hasattr(view, "parent_app") and getattr(view.parent_app, "project_locked", False):
                    event.accept()
                    return
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event) -> None:
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)

        # Prevent empty invisible text box
        if not self.toPlainText().strip():
            self.setPlainText("Text")

        # Stable origin update
        old_center = self.mapToScene(self._text_br().center())
        self.prepareGeometryChange()
        self.setTransformOriginPoint(self._text_br().center())
        new_center = self.mapToScene(self._text_br().center())
        self.setPos(self.pos() + (old_center - new_center))

        super().focusOutEvent(event)
        _notify_canvas_changed(self)

    def mousePressEvent(self, event) -> None:
        if self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
            self.setCursor(Qt.CursorShape.IBeamCursor)
            super().mousePressEvent(event)
            return

        zone = self._zone_of(event.pos())
        if self.isSelected() and zone and zone != "move":
            self._action           = zone
            self._drag_start_scene = event.scenePos()
            self._drag_start_fsize = self._font_size
            center_scene = self.mapToScene(self._text_br().center())
            self._drag_start_dist  = max(10.0, (event.scenePos() - center_scene).manhattanLength())
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
        else:
            self._action = None
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
            self.setCursor(Qt.CursorShape.IBeamCursor)
            super().mouseMoveEvent(event)
            return

        if not self._action:
            super().mouseMoveEvent(event)
            return

        center_scene = self.mapToScene(self._text_br().center())

        if self._action == "rotate":
            dx = event.scenePos().x() - center_scene.x()
            dy = event.scenePos().y() - center_scene.y()
            self.setRotation(math.degrees(math.atan2(dy, dx)) + 90)
            event.accept()
            return

        # Resize / Font scaling proportional to distance from center
        curr_dist = (event.scenePos() - center_scene).manhattanLength()
        ratio = curr_dist / max(self._drag_start_dist, 1.0)
        new_fs = max(self.MIN_FONT, min(self.MAX_FONT, round(self._drag_start_fsize * ratio * 2) / 2))

        if new_fs != self._font_size:
            self._font_size = new_fs
            self._apply_font()
            self.update()

        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
            self.setCursor(Qt.CursorShape.IBeamCursor)
            super().mouseReleaseEvent(event)
            return

        if self._action:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._action = None
        super().mouseReleaseEvent(event)
        _notify_canvas_changed(self)

    def contextMenuEvent(self, event) -> None:
        if self.scene() is not None:
            views = self.scene().views()
            if views:
                view = views[0]
                if hasattr(view, "parent_app") and getattr(view.parent_app, "project_locked", False):
                    event.accept()
                    return
        menu = QMenu()
        menu.addAction("✏  Edit Text",      self._start_edit)
        menu.addAction("🎨  Change Colour", self._pick_color)
        if self.rotation() != 0.0:
            menu.addAction("🔄  Reset Rotation", self._reset_rotation)
        menu.addSeparator()
        menu.addAction("📋  Duplicate",     self._duplicate)
        menu.addAction("⬆  Bring to Front", lambda: self._change_z(1))
        menu.addAction("⬇  Send to Back",   lambda: self._change_z(-1))
        menu.addSeparator()
        menu.addAction("🗑  Delete",        lambda: _delete_annotation_item(self))
        menu.exec(event.screenPos())
        event.accept()

    def start_edit(self, select_all: bool = True) -> None:
        """Enter in-place text editing mode with keyboard focus and text selected."""
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if select_all:
            cursor = self.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            self.setTextCursor(cursor)

    def _start_edit(self) -> None:
        self.start_edit(select_all=True)

    def _change_z(self, delta: int) -> None:
        self.setZValue(self.zValue() + delta)
        _notify_canvas_changed(self)

    def _reset_rotation(self) -> None:
        old_center = self.mapToScene(self._text_br().center())
        self.prepareGeometryChange()
        self.setRotation(0.0)
        new_center = self.mapToScene(self._text_br().center())
        self.setPos(self.pos() + (old_center - new_center))
        self.update()
        _notify_canvas_changed(self)

    def _duplicate(self) -> None:
        if not self.scene():
            return
        clone = CanvasTextBox(
            text=self.toPlainText(),
            x=self.x() + 20,
            y=self.y() + 20,
            font_size=self._font_size,
            color=self._color,
            rotation=self.rotation(),
            z_value=self.zValue(),
        )
        self.scene().addItem(clone)
        self.scene().clearSelection()
        clone.setSelected(True)
        _notify_canvas_changed(clone)

    def _pick_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._color), None, "Choose Text Colour")
        if col.isValid():
            self._color = col.name()
            self._apply_font()
            self.update()
            _notify_canvas_changed(self)

    def to_dict(self) -> dict:
        return {
            "kind":      "textbox",
            "text":      self.toPlainText(),
            "x":         self.x(),
            "y":         self.y(),
            "font_size": self._font_size,
            "color":     self._color,
            "rotation":  self.rotation(),
            "z_value":   self.zValue(),
        }

    @staticmethod
    def from_dict(d: dict) -> "CanvasTextBox":
        return CanvasTextBox(
            d.get("text", "Text"),
            d["x"], d["y"],
            d.get("font_size", CanvasTextBox.DEFAULT_FONT_SIZE),
            d.get("color", "#111111"),
            d.get("rotation", 0.0),
            z_value=d.get("z_value", -1.0),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  LIVE CANVAS PDF LEGEND OVERLAY
# ─────────────────────────────────────────────────────────────────────────────

class CanvasLegendItem(QGraphicsItem):
    """
    Faded live preview of the PDF legend rendered directly on the last A4 canvas page.
    Informs the user of reserved/unutilised space so they don't place items over the legend.
    """

    def __init__(self, parent_app, target_rect: QRectF | None = None) -> None:
        super().__init__()
        self.parent_app = parent_app
        self._target_rect: QRectF = target_rect or QRectF()
        self.setZValue(-0.5)  # Under interactive nodes/spans, above page background
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def set_target_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self._target_rect = QRectF(rect)
        self.update()

    def boundingRect(self) -> QRectF:
        # Include top label tag (top - 14) and margins
        return self._target_rect.adjusted(-4, -16, 4, 4)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if not self._target_rect or self._target_rect.isNull() or self._target_rect.isEmpty():
            return
        if not getattr(self.parent_app, "pdf_show_legend", True):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Faded opacity so it serves as a soft, unobtrusive guide watermark
        painter.setOpacity(0.16)

        # Subtle dashed guide border
        guide_pen = QPen(QColor(140, 165, 195, 130), 0.8, Qt.PenStyle.DashLine)
        painter.setPen(guide_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._target_rect)

        # Scale coordinates so PDF exporter's font & element sizes fit scene space
        scale_factor = self._target_rect.width() / 340.0
        painter.save()
        painter.translate(self._target_rect.left(), self._target_rect.top())
        painter.scale(scale_factor, scale_factor)

        try:
            from exporters.pdf import PDFExporter
            exporter = PDFExporter(self.parent_app)
            # Give border rect with bottom pinned so _draw_pdf_legend aligns flush with bottom-right
            normalized_h = self._target_rect.height() / scale_factor
            normalized_rect = QRectF(0, 0, 340.0, normalized_h)
            exporter._draw_pdf_legend(painter, normalized_rect)
        except Exception:
            pass
        painter.restore()

        # Subtle watermark tag indicating reserved PDF legend area
        painter.setPen(QColor(100, 130, 165, 150))
        font = QFont("Arial", 6)
        font.setItalic(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(self._target_rect.left() + 4, self._target_rect.top() - 10, self._target_rect.width(), 9),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Reserved PDF Legend Area"
        )

        painter.restore()

