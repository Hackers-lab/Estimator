"""
grid.py
=======
A4 page grid and orientation management for the canvas.
"""

import math
from PyQt6.QtCore import QRectF
from core.constants import A4_W_MM, A4_H_MM
from canvas import SmartPole, SmartStructure, SmartConsumer, SmartSpan

class GridManager:
    """
    Handles recomputing A4 page tiles and orientations based on canvas content.
    """
    
    def __init__(self, app):
        self.app = app
        # Constants from app
        self._SCENE_UNITS_PER_M = 17.5
        
    def refresh(self):
        """
        Recompute the A4 page tiles in scene coordinates and push them
        to the InteractiveView for background rendering.
        """
        scene = self.app.scene
        view = self.app.view
        
        items = [
            i for i in scene.items()
            if isinstance(i, (SmartPole, SmartStructure, SmartConsumer, SmartSpan))
        ]
        
        if not items:
            blank_orient = "P" if self.app.pdf_orientation_mode == "Portrait (All)" else "L"
            pw, ph = self._a4_scene_dims_oriented(self.app.pdf_scale, blank_orient)
            blank_rect = QRectF(-pw / 2.0, -ph / 2.0, pw, ph)
            view.grid_tiles = [{
                "rect": blank_rect,
                "orient": blank_orient,
                "auto_orient": blank_orient,
                "is_override": False,
                "items_count": 0,
                "row": 0, "col": 0, "page_num": 1, "total": 1,
            }]
            view.continuation_marks = {}
            margin = max(pw, ph)
            scene.setSceneRect(blank_rect.adjusted(-margin, -margin, margin, margin))
            
            if getattr(self.app, "gps_bg_item", None):
                try:
                    self.app.gps_bg_item.set_clip_rect(blank_rect)
                except Exception:
                    pass
            
            view.viewport().update()
            return

        PAD = 50
        bounds = items[0].sceneBoundingRect()
        for i in items[1:]:
            bounds = bounds.united(i.sceneBoundingRect())
        bounds = bounds.adjusted(-PAD, -PAD, PAD, PAD)

        if self.app.pdf_orientation_mode == "Landscape (All)":
            base_orient = "L"
        elif self.app.pdf_orientation_mode == "Portrait (All)":
            base_orient = "P"
        else:
            base_orient = self._auto_global_orientation(bounds)
            
        pw_L, ph_L = self._a4_scene_dims_oriented(self.app.pdf_scale, base_orient)
        EDGE_MARGIN = 30
        
        if (bounds.width() <= pw_L - 2 * EDGE_MARGIN and 
            bounds.height() <= ph_L - 2 * EDGE_MARGIN):
            single_rect = QRectF(-pw_L / 2.0, -ph_L / 2.0, pw_L, ph_L)
            
            if (bounds.left() >= single_rect.left() + EDGE_MARGIN and
                bounds.right() <= single_rect.right() - EDGE_MARGIN and
                bounds.top() >= single_rect.top() + EDGE_MARGIN and
                bounds.bottom() <= single_rect.bottom() - EDGE_MARGIN):
                
                view.grid_tiles = [{
                    "rect": single_rect,
                    "auto_orient": base_orient,
                    "orient": base_orient,
                    "is_override": False,
                    "items_count": len(items),
                    "row": 0, "col": 0, "page_num": 1, "total": 1,
                }]
                view.continuation_marks = {}
                margin = max(pw_L, ph_L)
                scene.setSceneRect(single_rect.adjusted(-margin, -margin, margin, margin))
                
                if getattr(self.app, "gps_bg_item", None):
                    try:
                        self.app.gps_bg_item.set_clip_rect(single_rect)
                    except Exception:
                        pass
                
                view.viewport().update()
                return

        def items_in(rect):
            return [i for i in items if rect.intersects(i.sceneBoundingRect())]

        eps = 1e-6
        cols = max(1, int(math.ceil(max(0.0, bounds.width() - eps) / pw_L)))
        rows = max(1, int(math.ceil(max(0.0, bounds.height() - eps) / ph_L)))
        base_left = bounds.left()
        base_top = bounds.top()

        occupied_tiles = []
        for r in range(rows):
            for c in range(cols):
                rect = QRectF(base_left + c * pw_L, base_top + r * ph_L, pw_L, ph_L)
                ins = items_in(rect)
                if not ins:
                    continue

                local_union = None
                for item in ins:
                    inter = rect.intersected(item.sceneBoundingRect())
                    if not (inter.isNull() or inter.isEmpty()):
                        local_union = inter if local_union is None else local_union.united(inter)

                occupied_tiles.append({
                    "rect": rect,
                    "auto_orient": self._auto_tile_orientation(local_union) if local_union else base_orient,
                    "items_count": len(ins),
                    "row": r, "col": c,
                })

        total = len(occupied_tiles)
        final_tiles = []
        for i, t in enumerate(occupied_tiles):
            page_num = i + 1
            orient, is_override = self._resolve_orientation(t["auto_orient"], page_num)
            
            if orient != base_orient:
                orient = base_orient
                is_override = False

            t.update({"page_num": page_num, "total": total, "orient": orient, "is_override": is_override})
            final_tiles.append(t)

        if self.app.pdf_page_overrides:
            self.app.pdf_page_overrides = {
                k: v for k, v in self.app.pdf_page_overrides.items() if 1 <= k <= total
            }

        view.grid_tiles = final_tiles
        from exporters.pdf import PDFExporter
        exporter = PDFExporter(self.app)
        view.continuation_marks = exporter._build_continuation_marks_for_tiles(final_tiles)
        exporter._position_split_span_labels(view.continuation_marks)

        if final_tiles:
            full_rect = final_tiles[0]["rect"]
            for t in final_tiles[1:]:
                full_rect = full_rect.united(t["rect"])
            
            if getattr(self.app, "gps_bg_item", None):
                try:
                    self.app.gps_bg_item.set_clip_rect(full_rect)
                except Exception:
                    pass

            w_l, h_l = self._a4_scene_dims_oriented(self.app.pdf_scale, "L")
            margin = max(w_l, h_l)
            scene.setSceneRect(full_rect.adjusted(-margin, -margin, margin, margin))
        
        view.viewport().update()

    def _a4_scene_dims(self, scale):
        m_per_mm = scale / 1000.0
        w = A4_W_MM * m_per_mm * self._SCENE_UNITS_PER_M
        h = A4_H_MM * m_per_mm * self._SCENE_UNITS_PER_M
        return w, h

    def _a4_scene_dims_oriented(self, scale, orient: str):
        w_l, h_l = self._a4_scene_dims(scale)
        return (h_l, w_l) if orient == "P" else (w_l, h_l)

    def _auto_tile_orientation(self, union_rect: QRectF, pad: float = 10.0) -> str:
        if union_rect is None or union_rect.isNull() or union_rect.isEmpty():
            return "L"
        cw, ch = max(1.0, union_rect.width()), max(1.0, union_rect.height())
        pw_l, ph_l = self._a4_scene_dims_oriented(self.app.pdf_scale, "L")
        pw_p, ph_p = self._a4_scene_dims_oriented(self.app.pdf_scale, "P")
        s_l = min((pw_l - 2 * pad) / cw, (ph_l - 2 * pad) / ch)
        s_p = min((pw_p - 2 * pad) / cw, (ph_p - 2 * pad) / ch)
        return "P" if s_p > s_l * self.app.pdf_auto_gain_threshold else "L"

    def _auto_global_orientation(self, bounds: QRectF) -> str:
        return self._auto_tile_orientation(bounds)

    def _resolve_orientation(self, auto_orient: str, page_num: int) -> tuple[str, bool]:
        mode = self.app.pdf_orientation_mode
        if mode == "Landscape (All)": return "L", False
        if mode == "Portrait (All)":  return "P", False
        if mode == "Auto + Overrides":
            ov = self.app.pdf_page_overrides.get(page_num)
            if ov in ("L", "P"): return ov, True
        return auto_orient, False
