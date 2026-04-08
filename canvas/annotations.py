from __future__ import annotations
from typing import Any
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QWidget, QStyleOptionGraphicsItem,
)
from PyQt6.QtGui import (
    QPainterPath, QBrush, QColor, QPen, QFont, QPainter,
)
from PyQt6.QtCore import Qt, QRectF, QPointF

class CanvasSymbol(QGraphicsItem):
    """
    A resizable annotation symbol for print decoration.

    Supported shapes: "circle", "square", "arrow", "line"

    Interaction
    -----------
    • Main body: drag to move (via ItemIsMovable)
    • Small resize handle at bottom-right corner: drag to resize
    """

    HANDLE_SIZE = 10.0
    MIN_SIZE    = 20.0

    SHAPES = ("circle", "square", "arrow", "line")

    def __init__(self, shape: str = "circle", x: float = 0, y: float = 0,
                 size: float = 40.0) -> None:
        super().__init__()
        self.shape = shape
        self._size = max(size, self.MIN_SIZE)
        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(-1)
        self._resizing = False
        self._resize_start_pos  = QPointF()
        self._resize_start_size = self._size

    @property
    def size(self) -> float:
        return self._size

    def _body_rect(self) -> QRectF:
        return QRectF(0, 0, self._size, self._size)

    def _handle_rect(self) -> QRectF:
        h = self.HANDLE_SIZE
        s = self._size
        return QRectF(s - h, s - h, h, h)

    def boundingRect(self) -> QRectF:
        h = self.HANDLE_SIZE
        return QRectF(-2, -2, self._size + h + 2, self._size + h + 2)

    def _build_shape_path(self) -> QPainterPath:
        s = self._size
        path = QPainterPath()
        if self.shape == "circle":
            path.addEllipse(QRectF(0, 0, s, s))
        elif self.shape == "square":
            path.addRect(QRectF(0, 0, s, s))
        elif self.shape == "arrow":
            # Right-pointing block arrow
            hw = s * 0.55   # horizontal shaft width
            hh = s * 0.25   # shaft half-height
            aw = s - hw     # arrowhead width
            ah = s * 0.45   # arrowhead half-height
            cx = s / 2
            cy = s / 2
            path.moveTo(0,        cy - hh)
            path.lineTo(hw,       cy - hh)
            path.lineTo(hw,       cy - ah)
            path.lineTo(s,        cy)
            path.lineTo(hw,       cy + ah)
            path.lineTo(hw,       cy + hh)
            path.lineTo(0,        cy + hh)
            path.closeSubpath()
        elif self.shape == "line":
            path.moveTo(0, s / 2)
            path.lineTo(s, s / 2)
        return path

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        pen = QPen(QColor("#222222"), 1.5)
        if self.isSelected():
            pen.setColor(QColor("#2980b9"))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._build_shape_path())

        # Resize handle — only visible when selected
        if self.isSelected():
            hp = self._handle_rect()
            painter.setPen(QPen(QColor("#2980b9"), 1))
            painter.setBrush(QBrush(QColor("#d5e8f7")))
            painter.drawRect(hp)

    def mousePressEvent(self, event) -> None:
        if self._handle_rect().contains(event.pos()):
            self._resizing = True
            self._resize_start_pos  = event.scenePos()
            self._resize_start_size = self._size
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
        else:
            self._resizing = False
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_start_pos
            new_size = max(self.MIN_SIZE,
                           self._resize_start_size + (delta.x() + delta.y()) / 2)
            self.prepareGeometryChange()
            self._size = new_size
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._resizing = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("Bring to Front", lambda: self.setZValue(self.zValue() + 1))
        menu.addAction("Send to Back",   lambda: self.setZValue(self.zValue() - 1))
        menu.exec(event.screenPos())
        event.accept()

    # ── Serialisation helpers ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "kind":  "symbol",
            "shape": self.shape,
            "x":     self.x(),
            "y":     self.y(),
            "size":  self._size,
        }

    @staticmethod
    def from_dict(d: dict) -> "CanvasSymbol":
        return CanvasSymbol(d["shape"], d["x"], d["y"], d.get("size", 40.0))


# ─────────────────────────────────────────────────────────────────────────────
#  CANVAS TEXT BOX  — inline-editable text annotation (QGraphicsTextItem)
# ─────────────────────────────────────────────────────────────────────────────

class CanvasTextBox(QGraphicsTextItem):
    """
    A freely-positionable text annotation.

    Interaction
    -----------
    • Single-click: select / drag to move
    • Double-click: enter inline edit mode (cursor appears, type away)
    • Bottom-right handle (visible when selected): drag to resize font
    • Right-click: context menu (Bring to Front / Send to Back)
    """

    HANDLE_SIZE       = 10.0
    MIN_FONT          = 6.0
    MAX_FONT          = 72.0
    DEFAULT_FONT_SIZE = 10.0

    def __init__(self, text: str = "Text", x: float = 0, y: float = 0,
                 font_size: float = DEFAULT_FONT_SIZE) -> None:
        super().__init__(text)
        self._font_size = max(self.MIN_FONT, min(self.MAX_FONT, font_size))
        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(-1)
        self._apply_font()
        self._resizing           = False
        self._resize_start_pos   = QPointF()
        self._resize_start_fsize = self._font_size
        # Editing is only active while the user double-clicks
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    def _apply_font(self) -> None:
        f = QFont("Arial")
        f.setPointSizeF(self._font_size)
        self.setFont(f)

    def _handle_rect(self) -> QRectF:
        br = self.boundingRect()
        h  = self.HANDLE_SIZE
        return QRectF(br.right() - h, br.bottom() - h, h, h)

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        # Draw dashed border only when selected
        if self.isSelected():
            br = self.boundingRect()
            painter.save()
            painter.setPen(QPen(QColor("#2980b9"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor("#eaf4fc")))
            painter.drawRect(br)
            # Resize handle (only when selected)
            hp = self._handle_rect()
            painter.setPen(QPen(QColor("#2980b9"), 1))
            painter.setBrush(QBrush(QColor("#d5e8f7")))
            painter.drawRect(hp)
            painter.restore()
        # Draw the text
        super().paint(painter, option, widget)

    def mouseDoubleClickEvent(self, event) -> None:
        # Enter inline text-edit mode
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event) -> None:
        # Exit edit mode when focus is lost
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        # If we are in edit mode, let QGraphicsTextItem handle it (cursor placement)
        if self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction:
            super().mousePressEvent(event)
            return
        if self.isSelected() and self._handle_rect().contains(event.pos()):
            self._resizing           = True
            self._resize_start_pos   = event.scenePos()
            self._resize_start_fsize = self._font_size
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
        else:
            self._resizing = False
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_start_pos
            change = (delta.x() + delta.y()) / 10.0
            new_fs = max(self.MIN_FONT, min(self.MAX_FONT,
                                            self._resize_start_fsize + change))
            self._font_size = new_fs
            self._apply_font()
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._resizing = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("Bring to Front", lambda: self.setZValue(self.zValue() + 1))
        menu.addAction("Send to Back",   lambda: self.setZValue(self.zValue() - 1))
        menu.exec(event.screenPos())
        event.accept()

    # ── Serialisation helpers ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "kind":      "textbox",
            "text":      self.toPlainText(),
            "x":         self.x(),
            "y":         self.y(),
            "font_size": self._font_size,
        }

    @staticmethod
    def from_dict(d: dict) -> "CanvasTextBox":
        return CanvasTextBox(d.get("text", "Text"), d["x"], d["y"],
                             d.get("font_size", CanvasTextBox.DEFAULT_FONT_SIZE))

