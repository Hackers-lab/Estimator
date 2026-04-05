"""
ui_components.py
================
Custom reusable Qt widgets for ERP Estimate Generator v5.0.

Classes
-------
InteractiveView
    A QGraphicsView subclass that handles:
      • Mouse-wheel zooming anchored under the cursor
      • Middle-mouse-button panning (drag to scroll)
      • Forwarding left/right click events to app.handle_canvas_click()
      • Ctrl+Scroll for fine zoom steps
      • Keyboard shortcuts: Space = pan mode, Escape = select mode

DraggableLabel
    A QGraphicsTextItem subclass used for all on-canvas text labels
    (pole labels, span labels). Features:
      • Movable and selectable independently of its parent item
      • White pill-shaped background behind each line for legibility
      • Double-click to edit text inline
      • Automatic Z-ordering above all other items (Z=20)
      • Compact 7pt Arial font by default
"""

from PyQt6.QtWidgets import QGraphicsView, QGraphicsTextItem
from PyQt6.QtGui import (
    QColor, QPainter, QTextOption, QFont, QPen, QBrush,
    QWheelEvent, QMouseEvent, QKeyEvent
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QEvent


# ─────────────────────────────────────────────────────────────────────────────
#  InteractiveView
# ─────────────────────────────────────────────────────────────────────────────

class InteractiveView(QGraphicsView):
    """
    Enhanced QGraphicsView for the drawing canvas.

    Zoom
    ----
    Mouse wheel          — zoom in / out (×1.15 per step)
    Ctrl + mouse wheel   — fine zoom (×1.05 per step)
    Middle-mouse drag    — pan the canvas

    Tool integration
    ----------------
    Left click           → forwarded to app.handle_canvas_click()
    Right click          → forwarded to app.handle_canvas_click()
                           (app uses this to revert to SELECT tool)
    Space bar (hold)     → temporarily switch to scroll-hand drag
    Escape               → call app.set_tool("SELECT")
    """

    _ZOOM_NORMAL = 1.15
    _ZOOM_FINE   = 1.05

    _CURSOR_EMPTY_PAN = Qt.CursorShape.OpenHandCursor
    _CURSOR_HOVER_SELECT = Qt.CursorShape.PointingHandCursor
    _CURSOR_SELECTED_DRAG = Qt.CursorShape.DragMoveCursor

    def __init__(self, scene, parent_app):
        super().__init__(scene)
        self.parent_app   = parent_app
        self._panning     = False          # middle-mouse pan state
        self._pan_start   = QPointF()
        self._space_held  = False
        self._last_mouse_pos = None
        self._hover_scene_pos = None
        self._rubber_band_selecting = False

        # Page grid overlay state — populated by app._refresh_page_grid()
        # List of dicts: {rect: QRectF, orient: 'L'|'P', page_num: int}
        self.grid_tiles      = []
        self.grid_show       = True    # master toggle
        self.grid_crosshatch = True    # crosshatch inside pages

        # Ctrl+Left-Click pan state
        self._ctrl_panning  = False
        self._ctrl_pan_start = QPointF()

        # Render quality
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )

        # Zoom anchors under the mouse cursor
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )

        # Allow the scene to grow as items are added
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        # Canvas background
        self.setBackgroundBrush(QBrush(QColor("#f9f9f9")))

        # Enable keyboard focus so key events reach this widget
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        sc = self.scene()
        if sc is not None:
            sc.selectionChanged.connect(self._on_scene_selection_changed)

        self.refresh_interaction_state()

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)

        if self._hover_scene_pos is None:
            return

        tool = self.parent_app.current_tool
        x = self._hover_scene_pos.x()
        y = self._hover_scene_pos.y()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if tool == "ADD_SPAN":
            start = getattr(self.parent_app, "span_start_pole", None)
            hover = self._hover_scene_pos
            if start is not None:
                p1 = start.pos()
                p2 = hover
                painter.setPen(QPen(QColor(46, 134, 222, 210), 1.8, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(p1.x(), p1.y()), QPointF(p2.x(), p2.y()))
                painter.setBrush(QBrush(QColor(46, 134, 222, 70)))
                painter.setPen(QPen(QColor(46, 134, 222, 220), 1.2))
                painter.drawEllipse(QPointF(p1.x(), p1.y()), 6, 6)
                painter.drawEllipse(QPointF(p2.x(), p2.y()), 4, 4)
            painter.restore()
            return

        if tool == "ADD_LT":
            painter.setPen(QPen(QColor(34, 101, 194, 220), 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(52, 152, 219, 70)))
            painter.drawEllipse(QPointF(x, y), 9, 9)
        elif tool == "ADD_HT":
            painter.setPen(QPen(QColor(168, 43, 36, 220), 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(231, 76, 60, 70)))
            painter.drawEllipse(QPointF(x, y), 9, 9)
        elif tool == "ADD_EXISTING":
            painter.setPen(QPen(QColor(110, 110, 110, 220), 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(170, 170, 170, 70)))
            painter.drawEllipse(QPointF(x, y), 9, 9)
        elif tool == "ADD_STRUCTURE":
            painter.setPen(QPen(QColor(47, 130, 76, 220), 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(46, 204, 113, 60)))
            painter.drawRect(QRectF(x - 11, y - 11, 22, 22))
        elif tool == "ADD_CONSUMER":
            painter.setPen(QPen(QColor(120, 80, 30, 220), 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(243, 156, 18, 60)))
            painter.drawRect(QRectF(x - 8, y - 8, 16, 16))

        painter.restore()

    def _on_scene_selection_changed(self):
        self.refresh_interaction_state()

    def refresh_interaction_state(self, mouse_pos=None):
        """
        Update drag mode + cursor based on current canvas interaction state.

        SELECT mode states requested by UX:
        - Empty space + no selection -> OpenHand + ScrollHandDrag (page drag)
        - Hovering over object      -> Pointer cursor + RubberBandDrag
        - Any selected object       -> DragMove cursor + RubberBandDrag
        """
        if mouse_pos is not None:
            self._last_mouse_pos = mouse_pos

        # While explicit pan gestures are active, do not override cursor state.
        if self._panning or self._ctrl_panning or self._rubber_band_selecting:
            return

        if self.parent_app.current_tool != "SELECT":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if self._space_held:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        scene_obj = self.scene()
        selected_items = scene_obj.selectedItems() if scene_obj is not None else []

        hover_item = None
        if self._last_mouse_pos is not None:
            hover_item = self.itemAt(self._last_mouse_pos.toPoint())

        if selected_items:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(self._CURSOR_SELECTED_DRAG)
            return

        if hover_item is not None:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(self._CURSOR_HOVER_SELECT)
            return

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(self._CURSOR_EMPTY_PAN)

    # ── Page grid overlay ─────────────────────────────────────────────────────

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Draw the white canvas background then the A4 page grid overlay."""
        # White canvas fill
        painter.fillRect(rect, QColor("#f0f0f0"))

        if not self.grid_show or not self.grid_tiles:
            # Show navigation hints when there is nothing drawn yet
            painter.save()
            painter.resetTransform()
            vp_widget = self.viewport()
            assert vp_widget is not None
            vp = vp_widget.rect()
            painter.setFont(QFont("Arial", 11))
            painter.setPen(QColor(190, 195, 210))
            painter.drawText(
                vp,
                Qt.AlignmentFlag.AlignCenter,
                "Select a placement tool above, then click the canvas to place poles\n"
                "Middle-click drag  ·  Ctrl+drag  ·  Space+drag  →  Pan\n"
                "Scroll  →  Zoom  ·  F  →  Fit view  ·  Esc  →  Select mode"
            )
            painter.restore()
            return

        painter.save()

        # ── Page fill (white paper) ────────────────────────────────────────
        page_fill = QColor(255, 255, 255, 220)
        page_shadow = QColor(0, 0, 0, 18)

        for tile in self.grid_tiles:
            tr = tile["rect"]
            # Drop shadow (offset 3px in scene units — tiny, looks good)
            shadow_r = tr.adjusted(3, 3, 3, 3)
            painter.fillRect(shadow_r, page_shadow)
            # White page background
            painter.fillRect(tr, page_fill)

        # ── Crosshatch inside each page ───────────────────────────────────
        if self.grid_crosshatch:
            # Determine crosshatch spacing: ~5mm on paper in scene units
            # We'll pick a spacing that matches roughly 200 scene units
            # (about 11m real-world at 17.5 units/m)  — adapts to zoom
            hatch_pen = QPen(QColor(200, 210, 220, 100), 0.3)
            hatch_pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(hatch_pen)

            # Use the first tile's size to calibrate spacing
            if self.grid_tiles:
                tile_w = self.grid_tiles[0]["rect"].width()
                # ~20 vertical lines per page looks good
                spacing = max(50, tile_w / 20)
                for tile in self.grid_tiles:
                    tr = tile["rect"]
                    # Vertical lines
                    x = tr.left() + spacing
                    while x < tr.right():
                        painter.drawLine(QPointF(x, tr.top()), QPointF(x, tr.bottom()))
                        x += spacing
                    # Horizontal lines
                    y = tr.top() + spacing
                    while y < tr.bottom():
                        painter.drawLine(QPointF(tr.left(), y), QPointF(tr.right(), y))
                        y += spacing

        # ── Page boundary lines ───────────────────────────────────────────
        border_pen = QPen(QColor(150, 170, 200, 180), 1.5)
        border_pen.setCosmetic(True)   # always 1.5 screen-px regardless of zoom
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for tile in self.grid_tiles:
            painter.drawRect(tile["rect"])

        # ── Page label (orientation + page number) ────────────────────────
        # We paint these in a font that stays readable at all zoom levels.
        # Use a cosmetic transform: translate to scene position, then draw
        # in device coordinates to keep font size constant.
        label_color = QColor(160, 175, 195, 200)

        for tile in self.grid_tiles:
            tr  = tile["rect"]
            num = tile["page_num"]
            tot = tile["total"]
            ori = tile["orient"]
            mark = "*" if tile.get("is_override") else ""
            label = f"Page {num}/{tot}  [{ori}{mark}]"

            # Map top-left corner to viewport coordinates
            top_left_view = self.mapFromScene(tr.topLeft())

            painter.save()
            painter.resetTransform()   # paint in device (pixel) space

            font = QFont("Arial", 9)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(label_color)

            # Draw label 4px inside the top-left of the page tile
            painter.drawText(
                int(top_left_view.x()) + 6,
                int(top_left_view.y()) + 16,
                label
            )
            painter.restore()

        painter.restore()



    # ── Zoom ─────────────────────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        modifiers = event.modifiers()
        factor = (
            self._ZOOM_FINE
            if modifiers & Qt.KeyboardModifier.ControlModifier
            else self._ZOOM_NORMAL
        )
        if event.angleDelta().y() < 0:
            factor = 1.0 / factor

        # Clamp zoom so the user cannot zoom beyond useful extremes
        cur = self.transform().m11()
        if factor < 1.0 and cur < 0.04:   # too far zoomed out — stop
            event.accept()
            return
        if factor > 1.0 and cur > 25.0:   # too far zoomed in — stop
            event.accept()
            return

        self.scale(factor, factor)
        self.parent_app.update_view_drag_mode()

    # ── Middle-mouse pan ──────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        self._hover_scene_pos = self.mapToScene(event.position().toPoint())

        # Middle-mouse pan (unchanged)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning   = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # SELECT mode: allow Shift+drag rubber-band multi-select even when
        # default empty-space drag is page pan.
        if (
            self.parent_app.current_tool == "SELECT"
            and event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._rubber_band_selecting = True
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            super().mousePressEvent(event)
            return

        # Ctrl+Left-Click: pan canvas even when over a drawing item
        if (event.button() == Qt.MouseButton.LeftButton and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._ctrl_panning   = True
            self._ctrl_pan_start = event.position()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return

        self.refresh_interaction_state(event.position())

        # Forward left / right clicks to the application tool handler
        self.parent_app.handle_canvas_click(event, self)
        # Only invoke Qt's base handler in SELECT mode (needed for rubber-band drag).
        # In drawing-tool modes, calling super() can micro-shift the viewport via
        # AnchorUnderMouse — causing placed items to land at a slightly wrong position.
        if self.parent_app.current_tool == "SELECT":
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        self._hover_scene_pos = self.mapToScene(event.position().toPoint())

        if self._rubber_band_selecting:
            super().mouseMoveEvent(event)
            return

        # Middle-mouse pan
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            assert hs is not None and vs is not None
            hs.setValue(hs.value() - int(delta.x()))
            vs.setValue(vs.value() - int(delta.y()))
            event.accept()
            return
        # Ctrl+Left pan
        if self._ctrl_panning:
            delta = event.position() - self._ctrl_pan_start
            self._ctrl_pan_start = event.position()
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            assert hs is not None and vs is not None
            hs.setValue(hs.value() - int(delta.x()))
            vs.setValue(vs.value() - int(delta.y()))
            event.accept()
            return
        self.refresh_interaction_state(event.position())
        vp = self.viewport()
        assert vp is not None
        vp.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._hover_scene_pos = self.mapToScene(event.position().toPoint())

        if event.button() == Qt.MouseButton.LeftButton and self._rubber_band_selecting:
            self._rubber_band_selecting = False
            super().mouseReleaseEvent(event)
            self.refresh_interaction_state(event.position())
            vp = self.viewport()
            assert vp is not None
            vp.update()
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.refresh_interaction_state(event.position())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._ctrl_panning:
            self._ctrl_panning = False
            self.refresh_interaction_state(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.refresh_interaction_state(event.position())
        vp = self.viewport()
        assert vp is not None
        vp.update()

    def leaveEvent(self, event: QEvent):
        self._last_mouse_pos = None
        self._hover_scene_pos = None
        self._rubber_band_selecting = False
        self.refresh_interaction_state()
        vp = self.viewport()
        assert vp is not None
        vp.update()
        super().leaveEvent(event)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Shift:
            self.parent_app.set_tool("SELECT")
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and not self._space_held:
            self._space_held = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.parent_app.set_tool("SELECT")
            event.accept()
            return
        # F or Ctrl+0 — Fit all drawing content in view
        if event.key() == Qt.Key.Key_F or (
            event.key() == Qt.Key.Key_0 and
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            sc = self.scene()
            if sc is None:
                event.accept()
                return
            bounds = sc.itemsBoundingRect()
            if not bounds.isNull():
                self.fitInView(
                    bounds.adjusted(-60, -60, 60, 60),
                    Qt.AspectRatioMode.KeepAspectRatio
                )
            event.accept()
            return
        # Ctrl+A — delegate to scene select-all
        if (event.key() == Qt.Key.Key_A and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            sc = self.scene()
            if sc is None:
                event.accept()
                return
            sc.clearSelection()
            for item in sc.items():
                item.setSelected(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space:
            self._space_held = False
            self.parent_app.update_view_drag_mode()
            event.accept()
            return
        super().keyReleaseEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  DraggableLabel
# ─────────────────────────────────────────────────────────────────────────────

class DraggableLabel(QGraphicsTextItem):
    """
    An on-canvas text label that can be dragged independently of its
    parent item (pole, span, structure, consumer).

    Background rendering
    --------------------
    Each line of text gets a white rounded-rectangle background drawn
    behind it so the text remains legible over lines, symbols, and
    other canvas elements.  The background pill is sized to the
    natural width of each line plus 4 px horizontal padding.

    Editing
    -------
    Double-clicking the label enters inline text-edit mode.
    Clicking elsewhere (focusOut) locks the text again.
    """

    # Pill background colour — white with slight transparency feel
    _BG_COLOR   = QColor(255, 255, 255, 230)
    _FONT       = QFont("Arial", 7)
    _H_PADDING  = 4     # horizontal px added each side of text
    _CORNER_R   = 2     # corner radius for background pill

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        doc = self.document()
        assert doc is not None
        doc.setDefaultTextOption(
            QTextOption(Qt.AlignmentFlag.AlignCenter)
        )
        self.setZValue(20)
        self.setFont(self._FONT)

    # ── Inline editing ────────────────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event):
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
        )
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        super().focusOutEvent(event)

    # ── Paint override — white pill backgrounds ───────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        """
        Draw a white pill-shaped background behind each line of text,
        then delegate to the default QGraphicsTextItem paint for the
        actual text rendering.
        """
        painter.save()
        painter.setBrush(QBrush(self._BG_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)

        doc = self.document()
        assert doc is not None
        layout = doc.documentLayout()
        assert layout is not None

        for block_idx in range(doc.blockCount()):
            block = doc.findBlockByNumber(block_idx)
            if not block.isValid():
                continue

            text_layout = block.layout()
            if not text_layout:
                continue

            block_rect = layout.blockBoundingRect(block)

            # Iterate lines within the block (usually 1 per block for
            # short labels, but respects text-wrapping correctly)
            for line_idx in range(text_layout.lineCount()):
                line = text_layout.lineAt(line_idx)
                if not line.isValid():
                    continue

                used_w  = line.naturalTextWidth()
                line_r  = line.rect()

                # Centre the pill horizontally within the block width
                offset_x = (block_rect.width() - used_w) / 2

                pill = QRectF(
                    block_rect.left() + offset_x - self._H_PADDING,
                    block_rect.top() + line_r.top(),
                    used_w + self._H_PADDING * 2,
                    line_r.height(),
                )
                painter.drawRoundedRect(pill, self._CORNER_R, self._CORNER_R)

        painter.restore()

        # Render the actual text on top
        super().paint(painter, option, widget)
