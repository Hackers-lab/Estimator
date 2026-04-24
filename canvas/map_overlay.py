import os
import math
from PyQt6.QtCore import Qt, QUrl, QRectF
from PyQt6.QtGui import QPixmap, QImage, QPainter
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

CACHE_DIR = ".map_cache"

class MapTileFetcher:
    """A map tile fetcher that downloads itself and caches locally, completely detached from the Qt Scene Graph."""
    def __init__(self, x: int, y: int, z: int, cx: int, cy: int, fraction_x: float, fraction_y: float, manager: QNetworkAccessManager, overlay=None):
        self.x_idx = x
        self.y_idx = y
        self.z = z
        self.overlay = overlay
        
        # Calculate strict world placement geometrically mapped to fraction offset
        self.draw_x = (x - cx - fraction_x) * 256.0
        self.draw_y = (y - cy - fraction_y) * 256.0
        self.pixmap = None
        self.reply = None
        
        if not os.path.exists(CACHE_DIR):
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
            except OSError:
                pass
        
        self.url = f"https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}"
        cache_key = f"google_m_{z}_{x}_{y}.png"
        self.cache_path = os.path.join(CACHE_DIR, cache_key)
        
        if os.path.exists(self.cache_path):
            try:
                self.pixmap = QPixmap(self.cache_path)
            except Exception:
                pass
        
        if self.pixmap is None:
            from app_config import APP_VERSION
            req = QNetworkRequest(QUrl(self.url))
            req.setRawHeader(b"User-Agent", f"Estimator_WBSEDCL/{APP_VERSION}".encode('utf-8'))
            self.reply = manager.get(req)
            self.reply.finished.connect(self._on_download_finished)

    def _on_download_finished(self):
        if not self.reply:
            return
        if self.reply.error() == QNetworkReply.NetworkError.NoError:
            data = self.reply.readAll()
            img = QImage.fromData(data)
            if not img.isNull():
                try:
                    img.save(self.cache_path, "PNG")
                except:
                    pass
                self.pixmap = QPixmap.fromImage(img)
                # Force the parent canvas overlay to redraw when cache is populated
                if self.overlay and self.overlay.scene():
                    self.overlay.update()
        self.reply.deleteLater()
        self.reply = None


class GPSBackgroundItem(QGraphicsItem):
    """
    Given an exact A4 page layout bounding box, dynamically fetches precisely the required map
    tiles and paints them into a strictly trimmed rectangular footprint matching the PDF scale.
    """
    def __init__(self, lat: float, lon: float, zoom: int = 19):
        super().__init__()
        self.setZValue(-100) # Deep background
        self.setOpacity(0.5)
        # Prevents capturing drags meant for the background grid
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self._clip_rect = QRectF()
        self.tiles = []
        
        self.lat = lat
        self.lon = lon
        self.zoom = zoom
        self.manager = QNetworkAccessManager()

    def set_clip_rect(self, scene_rect: QRectF):
        self.prepareGeometryChange()
        self._clip_rect = scene_rect
        self.tiles.clear()
            
        if scene_rect.isNull() or scene_rect.isEmpty():
            return
            
        n = 1 << self.zoom
        x_f = (self.lon + 180.0) / 360.0 * n
        lat_rad = math.radians(self.lat)
        y_f = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        
        cx = int(x_f)
        cy = int(y_f)
        
        fraction_x = x_f - cx
        fraction_y = y_f - cy
        
        self.setPos(0, 0)
        
        min_tx = math.floor(scene_rect.left() / 256.0 + cx + fraction_x)
        max_tx = math.ceil(scene_rect.right() / 256.0 + cx + fraction_x)
        
        min_ty = math.floor(scene_rect.top() / 256.0 + cy + fraction_y)
        max_ty = math.ceil(scene_rect.bottom() / 256.0 + cy + fraction_y)
        
        max_limit = 1500
        count = 0
        
        for tx in range(int(min_tx), int(max_tx)):
            for ty in range(int(min_ty), int(max_ty)):
                count += 1
                if count > max_limit:
                    return
                tile = MapTileFetcher(tx, ty, self.zoom, cx, cy, fraction_x, fraction_y, self.manager, overlay=self)
                self.tiles.append(tile)
        self.update()

    def boundingRect(self):
        return self._clip_rect
        
    def paint(self, painter, option, widget=None):
        if self._clip_rect.isEmpty() or self._clip_rect.isNull():
            return
            
        painter.save()
        # Strictly enforce boundaries with the Qt native painter logic so child textures don't bleed out
        painter.setClipRect(self._clip_rect)
        for tile in self.tiles:
            if tile.pixmap and not tile.pixmap.isNull():
                # Raw pixmap rendering ensures it can't trap clicks like standalone QGraphicsItems
                painter.drawPixmap(int(tile.draw_x), int(tile.draw_y), tile.pixmap)
        painter.restore()


