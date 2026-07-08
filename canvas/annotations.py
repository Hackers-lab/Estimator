from __future__ import annotations
import math
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QWidget, QStyleOptionGraphicsItem,
    QColorDialog, QMenu,
)
from PyQt6.QtGui import (
    QPainterPath, QPainterPathStroker, QBrush, QColor, QPen, QFont, QPainter,
)
from PyQt6.QtCore import Qt, QRectF, QPointF


# ─────────────────────────────────────────────────────────────────────────────
#  Cursor helpers
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
    # 0/180 = horizontal, 90 = vertical, 45 = FDiag (\), 135 = BDiag (/)
    if angle <= 22.5 or angle >= 157.5:
        return Qt.CursorShape.SizeHorCursor
    elif 22.5 < angle <= 67.5:
        return Qt.CursorShape.SizeFDiagCursor
    elif 67.5 < angle <= 112.5:
        return Qt.CursorShape.SizeVerCursor
    else:
        return Qt.CursorShape.SizeBDiagCursor


_CUR_DEFAULT  = Qt.CursorShape.ArrowCursor
_CUR_MOVE     = Qt.CursorShape.SizeAllCursor
_CUR_ROTATE   = Qt.CursorShape.CrossCursor


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS SYMBOL
# ─────────────────────────────────────────────────────────────────────────────

class CanvasSymbol(QGraphicsItem):
    """
    Resizable (all sides), rotatable annotation shape.

    Interaction uses invisible zones on edges/corners. The mouse cursor
    auto-rotates to match the visual orientation of the shape on screen.
    """

    MIN_DIM  = 10.0
    EDGE_TOL = 12.0   # px from edge that triggers resize cursor
    ROT_ZONE = 24.0   # px above shape top that is the rotation zone

    SHAPES = ("circle", "square", "arrow", "line", "dashed_line")

    def __init__(self, shape: str = "circle",
                 x: float = 0, y: float = 0,
                 width: float = 60.0,
                 height: float = 60.0,
                 color: str = "#222222",
                 rotation: float = 0.0) -> None:
        super().__init__()
        self.shape   = shape
        self._width  = max(width,  self.MIN_DIM)
        self._height = max(height, self.MIN_DIM)
        self._color  = color
        self.setPos(x, y)
        self.setRotation(rotation)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(-1)

        self._action: str | None = None
        self._drag_start_local   = QPointF()
        self._drag_start_w       = self._width
        self._drag_start_h       = self._height

    def _hw(self) -> float: return self._width  / 2.0
    def _hh(self) -> float: return self._height / 2.0

    def _body_rect(self) -> QRectF:
        return QRectF(-self._hw(), -self._hh(), self._width, self._height)

    def _rot_zone_rect(self) -> QRectF:
        return QRectF(-20, -self._hh() - self.ROT_ZONE, 40, self.ROT_ZONE)

    def _zone_of(self, lp: QPointF) -> str | None:
        if self._rot_zone_rect().contains(lp):
            return "rotate"
        
        hw = self._hw()
        hh = self._hh()
        e  = self.EDGE_TOL

        at_left   = (lp.x() < -hw + e)
        at_right  = (lp.x() > hw - e)
        at_top    = (lp.y() < -hh + e)
        at_bottom = (lp.y() > hh - e)

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
        hw  = self._hw()
        hh  = self._hh()
        pad = 8
        top = -hh - self.ROT_ZONE - pad
        return QRectF(-hw - pad, top,
                      self._width + pad * 2,
                      hh - top + pad)

    def shape(self) -> QPainterPath:    # type: ignore[override]
        raw = self._build_shape_path()
        stroker = QPainterPathStroker()
        stroker.setWidth(8.0)  # Thicker stroke to make edges easier to grab
        hit = stroker.createStroke(raw)

        if self.shape in ("circle", "square", "arrow"):
            hit = hit.united(raw)

        # Add all 4 edge bands to hit area (so we can grab them even if empty inside)
        e  = self.EDGE_TOL
        hw = self._hw()
        hh = self._hh()
        bands = QPainterPath()
        bands.addRect(QRectF(-hw, -hh, self._width, e))             # Top
        bands.addRect(QRectF(-hw, hh - e, self._width, e))          # Bottom
        bands.addRect(QRectF(-hw, -hh, e, self._height))            # Left
        bands.addRect(QRectF(hw - e, -hh, e, self._height))         # Right
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
            shaft_h   = hh * 0.45
            head_h    = hh
            shaft_end = hw * 0.55
            path.moveTo(-hw,       -shaft_h)
            path.lineTo(shaft_end, -shaft_h)
            path.lineTo(shaft_end, -head_h)
            path.lineTo( hw,        0)
            path.lineTo(shaft_end,  head_h)
            path.lineTo(shaft_end,  shaft_h)
            path.lineTo(-hw,        shaft_h)
            path.closeSubpath()
        elif self.shape in ("line", "dashed_line"):
            path.moveTo(-hw, 0)
            path.lineTo( hw, 0)

        return path

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        color = QColor(self._color)
        pen   = QPen(color, 1.8)
        if self.shape == "dashed_line":
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._build_shape_path())

        if self.isSelected():
            painter.setPen(QPen(QColor("#2980b9"), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._body_rect())

            painter.save()
            painter.setPen(QPen(QColor("#e74c3c"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cy   = -self._hh() - 12
            r    = 7
            painter.drawArc(QRectF(-r, cy - r, r * 2, r * 2), 30 * 16, 300 * 16)
            painter.drawLine(QPointF(r * 0.5,  cy - r), QPointF(r + 4, cy - r + 3))
            painter.drawLine(QPointF(r * 0.5,  cy - r), QPointF(r - 3, cy - r - 4))
            painter.setPen(QPen(QColor("#e74c3c"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(0, -self._hh()), QPointF(0, cy + r))
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

        from PyQt6.QtGui import QTransform
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
            dw = -dx
            if self._drag_start_w + dw >= self.MIN_DIM:
                new_w = self._drag_start_w + dw
                shift_x = dx / 2.0
        elif "r" in self._action:
            dw = dx
            if self._drag_start_w + dw >= self.MIN_DIM:
                new_w = self._drag_start_w + dw
                shift_x = dx / 2.0

        if "t" in self._action:
            dh = -dy
            if self._drag_start_h + dh >= self.MIN_DIM:
                new_h = self._drag_start_h + dh
                shift_y = dy / 2.0
        elif "b" in self._action:
            dh = dy
            if self._drag_start_h + dh >= self.MIN_DIM:
                new_h = self._drag_start_h + dh
                shift_y = dy / 2.0

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
        if self.scene():
            for item in self.scene().items():
                if hasattr(item, "refresh_signal"):
                    item.refresh_signal.emit()
                    break

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
        menu.addSeparator()
        menu.addAction("⬆  Bring to Front", lambda: self.setZValue(self.zValue() + 1))
        menu.addAction("⬇  Send to Back",   lambda: self.setZValue(self.zValue() - 1))
        menu.exec(event.screenPos())
        event.accept()

    def _pick_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._color), None, "Choose Symbol Colour")
        if col.isValid():
            self._color = col.name()
            self.update()

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
        )


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS TEXT BOX
# ─────────────────────────────────────────────────────────────────────────────

class CanvasTextBox(QGraphicsTextItem):
    """
    A freely-positionable text annotation with rotation support.
    """

    MIN_FONT          = 6.0
    MAX_FONT          = 144.0
    DEFAULT_FONT_SIZE = 10.0
    EDGE_TOL          = 12.0
    ROT_ZONE          = 24.0

    def __init__(self, text: str = "Text", x: float = 0, y: float = 0,
                 font_size: float = DEFAULT_FONT_SIZE,
                 color: str = "#111111",
                 rotation: float = 0.0) -> None:
        super().__init__(text)
        self._font_size = max(self.MIN_FONT, min(self.MAX_FONT, font_size))
        self._color     = color
        self.setPos(x, y)
        self.setRotation(rotation)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(-1)
        self._apply_font()
        self._action           = None
        self._drag_start_local = QPointF()
        self._drag_start_fsize = self._font_size
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    def _apply_font(self) -> None:
        f = QFont("Arial")
        f.setPointSizeF(self._font_size)
        self.setFont(f)
        self.setDefaultTextColor(QColor(self._color))
        self.setTransformOriginPoint(self._text_br().center())

    def _text_br(self) -> QRectF:
        return super().boundingRect()

    def _rot_zone_rect(self) -> QRectF:
        tbr = self._text_br()
        return QRectF(tbr.left(), tbr.top() - self.ROT_ZONE,
                      tbr.width(), self.ROT_ZONE)

    def _zone_of(self, lp: QPointF) -> str | None:
        if self._rot_zone_rect().contains(lp):
            return "rotate"
        
        tbr = self._text_br()
        e   = self.EDGE_TOL
        
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

        return None

    def boundingRect(self) -> QRectF:
        tbr = self._text_br()
        top = tbr.top() - self.ROT_ZONE - 4
        return QRectF(tbr.left(), top, tbr.width(), tbr.bottom() - top)

    def shape(self) -> QPainterPath:    # type: ignore[override]
        """
        MUST override shape() so QGraphicsTextItem allows clicking in 
        the rotation area above the text!
        """
        path = super().shape()
        rot_zone = QPainterPath()
        rot_zone.addRect(self._rot_zone_rect())
        path.addPath(rot_zone)
        return path

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        if self.isSelected():
            tbr = self._text_br()
            painter.save()
            painter.setPen(QPen(QColor("#2980b9"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor("#eaf4fc")))
            painter.drawRect(tbr)

            painter.setPen(QPen(QColor("#e74c3c"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cy = tbr.top() - 12
            cx = tbr.center().x()
            r  = 6
            painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 30 * 16, 300 * 16)
            painter.drawLine(QPointF(cx + r * 0.5, cy - r), QPointF(cx + r + 3, cy - r + 3))
            painter.drawLine(QPointF(cx + r * 0.5, cy - r), QPointF(cx + r - 2, cy - r - 3))
            painter.setPen(QPen(QColor("#e74c3c"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(cx, tbr.top()), QPointF(cx, cy + r))
            painter.restore()

        super().paint(painter, option, widget)

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
        self.setTransformOriginPoint(self._text_br().center())
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
            super().mousePressEvent(event)
            return

        zone = self._zone_of(event.pos())
        if self.isSelected() and zone:
            self._action           = zone
            self._drag_start_local = event.pos()
            self._drag_start_fsize = self._font_size
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
            centre = self.mapToScene(self._text_br().center())
            dx = event.scenePos().x() - centre.x()
            dy = event.scenePos().y() - centre.y()
            self.setRotation(math.degrees(math.atan2(dy, dx)) + 90)
            event.accept()
            return

        # It's a resize action
        delta = event.pos() - self._drag_start_local
        
        # Determine base magnitude of drag (outward from center)
        # Using simple sum of absolute deltas for scale is usually safe enough for text font scaling
        mag = 0.0
        if "l" in self._action: mag += -delta.x()
        elif "r" in self._action: mag += delta.x()
        
        if "t" in self._action: mag += -delta.y()
        elif "b" in self._action: mag += delta.y()

        change = mag / 5.0
        new_fs = max(self.MIN_FONT, min(self.MAX_FONT, self._drag_start_fsize + change))
        self._font_size = new_fs
        self._apply_font()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._action:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._action = None
        super().mouseReleaseEvent(event)
        if self.scene():
            for item in self.scene().items():
                if hasattr(item, "refresh_signal"):
                    item.refresh_signal.emit()
                    break

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
        menu.addSeparator()
        menu.addAction("⬆  Bring to Front", lambda: self.setZValue(self.zValue() + 1))
        menu.addAction("⬇  Send to Back",   lambda: self.setZValue(self.zValue() - 1))
        menu.exec(event.screenPos())
        event.accept()

    def _pick_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._color), None, "Choose Text Colour")
        if col.isValid():
            self._color = col.name()
            self._apply_font()
            self.update()

    def to_dict(self) -> dict:
        return {
            "kind":      "textbox",
            "text":      self.toPlainText(),
            "x":         self.x(),
            "y":         self.y(),
            "font_size": self._font_size,
            "color":     self._color,
            "rotation":  self.rotation(),
        }

    @staticmethod
    def from_dict(d: dict) -> "CanvasTextBox":
        return CanvasTextBox(
            d.get("text", "Text"),
            d["x"], d["y"],
            d.get("font_size", CanvasTextBox.DEFAULT_FONT_SIZE),
            d.get("color", "#111111"),
            d.get("rotation", 0.0),
        )
