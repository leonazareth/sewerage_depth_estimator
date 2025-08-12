# -*- coding: utf-8 -*-
"""
Lightweight elevation floater controller.

Shows an interpolated value from a selected raster DEM near the mouse cursor
while the checkbox in the dock widget is enabled. It does NOT take over the
active map tool; it listens to canvas cursor movement.
"""

import math
from typing import Optional, Tuple

from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.PyQt.QtCore import Qt, QEvent, QPoint

from qgis.core import (
    QgsProject,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsCoordinateReferenceSystem,
    QgsPointXY,
    QgsMapLayer,
    QgsRaster,
    QgsRectangle,
    QgsVectorLayer,
    QgsFeatureRequest,
    QgsWkbTypes,
)


# ---- Style knobs --------------------------------------------------------------
BUBBLE_BG_RGBA = (240, 240, 240, 170)
BUBBLE_BORDER_RGBA = (0, 0, 0, 100)
BUBBLE_RADIUS = 8
LABEL_FONT_FAMILY = "Calibri"
LABEL_FONT_FALLBACK = "Arial"
LABEL_FONT_SIZE_PT = 9
LABEL_HPAD = 6
LABEL_VPAD = 2
OFFSET_DX = 14
OFFSET_DY = 10
SHADOW_BLUR = 12
SHADOW_COLOR = QtGui.QColor(0, 0, 0, 60)


class _FloaterWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        self.label = QtWidgets.QLabel("—", self)
        font = QtGui.QFont()
        fam_ok = QtGui.QFontInfo(QtGui.QFont(LABEL_FONT_FAMILY)).family() != ""
        font.setFamily(LABEL_FONT_FAMILY if fam_ok else LABEL_FONT_FALLBACK)
        font.setPointSize(LABEL_FONT_SIZE_PT)
        self.label.setFont(font)
        # Enable rich text formatting for HTML content
        self.label.setTextFormat(Qt.RichText)
        self._text_color = QtGui.QColor(34, 34, 34)
        self._bg_color = QtGui.QColor(*BUBBLE_BG_RGBA)
        self.label.setStyleSheet("QLabel { color: #222; }")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(LABEL_HPAD, LABEL_VPAD, LABEL_HPAD, LABEL_VPAD)
        layout.setSpacing(0)
        layout.addWidget(self.label)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(SHADOW_BLUR)
        shadow.setOffset(0, 0)
        shadow.setColor(SHADOW_COLOR)
        self.setGraphicsEffect(shadow)

        self.adjustSize()

    def set_text(self, text: str):
        self.label.setText(text)
        self.adjustSize()
        self.update()

    def move_near_global(self, global_pos: QtCore.QPoint, dx=OFFSET_DX, dy=OFFSET_DY):
        if self.parent():
            local = self.parent().mapFromGlobal(global_pos)
            self.move(local + QPoint(dx, dy))
        else:
            self.move(global_pos + QPoint(dx, dy))

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setBrush(self._bg_color)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(rect, getattr(self, '_corner_radius', BUBBLE_RADIUS), getattr(self, '_corner_radius', BUBBLE_RADIUS))
        pen = QtGui.QPen(QtGui.QColor(*BUBBLE_BORDER_RGBA))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(rect, getattr(self, '_corner_radius', BUBBLE_RADIUS), getattr(self, '_corner_radius', BUBBLE_RADIUS))

    def apply_style(self, font: QtGui.QFont, point_size: int, text_color: QtGui.QColor, bg_color: QtGui.QColor):
        font_to_set = QtGui.QFont(font)
        font_to_set.setPointSize(point_size)
        self.label.setFont(font_to_set)
        self._text_color = QtGui.QColor(text_color)
        self._bg_color = QtGui.QColor(bg_color)
        self.label.setStyleSheet(f"QLabel {{ color: {self._text_color.name()}; }}")
        self.adjustSize()
        self.update()


class _CanvasInOutWatcher(QtCore.QObject):
    def __init__(self, floater, parent=None):
        super().__init__(parent)
        self._floater = floater

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Enter, QEvent.HoverEnter, QEvent.FocusIn):
            self._floater.show()
        elif t in (QEvent.Leave, QEvent.HoverLeave, QEvent.FocusOut, QEvent.WindowDeactivate):
            self._floater.hide()
        return False


class RasterInterpolator:
    def __init__(self, raster_layer, band=1):
        self.layer = raster_layer
        self.dp = raster_layer.dataProvider()
        self.band = int(band)

        try:
            self.nodata = self.dp.sourceNoDataValue(self.band) if self.dp.sourceHasNoDataValue(self.band) else None
        except Exception:
            self.nodata = None

        self.extent = self.dp.extent()
        self.width = self.dp.xSize()
        self.height = self.dp.ySize()

        try:
            self.xres = self.extent.width() / self.width
            self.yres = self.extent.height() / self.height
        except Exception:
            try:
                self.xres = self.layer.rasterUnitsPerPixelX()
                self.yres = self.layer.rasterUnitsPerPixelY()
            except Exception:
                self.xres = 1.0
                self.yres = 1.0

    def _is_nodata(self, v):
        if v is None:
            return True
        try:
            fv = float(v)
            if math.isnan(fv):
                return True
            if self.nodata is not None and fv == self.nodata:
                return True
            return False
        except Exception:
            return False

    def nearest(self, pt_layer_crs: QgsPointXY):
        try:
            val, ok = self.dp.sample(pt_layer_crs, self.band)
        except Exception:
            return None
        if not ok or self._is_nodata(val):
            return None
        try:
            return float(val)
        except Exception:
            return None

    def bilinear(self, pt_layer_crs: QgsPointXY):
        x = pt_layer_crs.x()
        y = pt_layer_crs.y()

        try:
            col = int(round((x - self.extent.xMinimum()) / self.xres))
            row = int(round((self.extent.yMaximum() - y) / self.yres))
        except Exception:
            return self.nearest(pt_layer_crs)

        xMin = self.extent.xMinimum() + (col - 1) * self.xres
        xMax = xMin + 2 * self.xres
        yMax = self.extent.yMaximum() - (row - 1) * self.yres
        yMin = yMax - 2 * self.yres

        if (xMin < self.extent.xMinimum() or xMax > self.extent.xMaximum() or
                yMin < self.extent.yMinimum() or yMax > self.extent.yMaximum()):
            return self.nearest(pt_layer_crs)

        pixel_extent = QgsRectangle(xMin, yMin, xMax, yMax)
        block = self.dp.block(self.band, pixel_extent, 2, 2)
        if block is None or block.width() != 2 or block.height() != 2:
            return self.nearest(pt_layer_crs)

        v12 = block.value(0, 0)
        v22 = block.value(0, 1)
        v11 = block.value(1, 0)
        v21 = block.value(1, 1)

        if any(self._is_nodata(v) for v in (v11, v12, v21, v22)):
            return self.nearest(pt_layer_crs)

        x1 = xMin + self.xres / 2.0
        x2 = xMax - self.xres / 2.0
        y1 = yMin + self.yres / 2.0
        y2 = yMax - self.yres / 2.0

        denom = (x2 - x1) * (y2 - y1)
        if denom == 0:
            return self.nearest(pt_layer_crs)

        val = (
            v11 * (x2 - x) * (y2 - y)
            + v21 * (x - x1) * (y2 - y)
            + v12 * (x2 - x) * (y - y1)
            + v22 * (x - x1) * (y - y1)
        ) / denom

        try:
            fv = float(val)
            if self._is_nodata(fv):
                return None
            return fv
        except Exception:
            return None


class ElevationFloaterController(QtCore.QObject):
    """Attaches to the canvas and shows an interpolated DEM value near cursor."""

    def __init__(self, iface):
        super().__init__(iface.mainWindow() if iface else None)
        self.iface = iface
        self.canvas = self.iface.mapCanvas() if self.iface else None
        # Snap utilities for getting snapped coordinates
        self.snapper = self.canvas.snappingUtils() if self.canvas else None
        self._floater: Optional[_FloaterWidget] = None
        self._watcher: Optional[_CanvasInOutWatcher] = None
        self._interp: Optional[RasterInterpolator] = None
        self._to_raster: Optional[QgsCoordinateTransform] = None
        self._band: int = 1
        self._format: str = "{value:.3f}"
        self._nodata_text: str = "NoData"
        self._connected = False
        # User-configurable display toggles
        self.show_extension: bool = True
        self.show_elevation: bool = True
        self.show_depth: bool = True
        # Parameters for depth preview
        self.minimum_cover_m: float = 0.9
        self.diameter_m: float = 0.150
        self.slope_m_per_m: float = 0.005
        self.initial_depth_m: float = 0.0
        # State for click sequence
        self._have_upstream: bool = False
        self._upstream_map_point: Optional[QgsPointXY] = None
        self._upstream_ground_elev: Optional[float] = None
        self._upstream_bottom_elev: Optional[float] = None
        # Track when we inherit depth from existing segment
        self._inherited_depth: Optional[float] = None
        # Track depth from current snap match (for hover preview)
        self._current_snap_depth: Optional[float] = None
        # Optional dedicated measure CRS
        self._measure_crs: Optional[QgsCoordinateReferenceSystem] = None
        # Style
        self._font = QtGui.QFont(LABEL_FONT_FAMILY)
        self._font_size = LABEL_FONT_SIZE_PT
        self._bold_labels = True
        self._text_color = QtGui.QColor(34, 34, 34)
        self._bg_color = QtGui.QColor(*BUBBLE_BG_RGBA)
        # Gating: only show when editing on selected line layer
        self._gate_layer_id: Optional[str] = None
        # Click storage for segment attribute writing
        self._stored_clicks = []  # List of {map_point, ground_elev, bottom_elev, timestamp}
        # Track features in buffer at session start to identify truly new ones
        self._buffer_features_at_session_start = set()

    def start(self, raster_layer, band=1, number_format="{value:.3f}", nodata_text="NoData"):
        if not self.canvas or not raster_layer:
            raise RuntimeError("Canvas or raster layer not available")

        self._band = int(band)
        self._format = number_format
        self._nodata_text = nodata_text

        ctxt: QgsCoordinateTransformContext = QgsProject.instance().transformContext()
        self._to_raster = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(), raster_layer.crs(), ctxt
        )

        self._interp = RasterInterpolator(raster_layer, band=self._band)

        parent_for_overlay = self.canvas.viewport() or self.canvas
        if self._floater is None:
            self._floater = _FloaterWidget(parent=parent_for_overlay)
        self._floater.hide()
        # Apply current style
        self._floater.apply_style(self._font, self._font_size, self._text_color, self._bg_color)
        # Corner radius
        try:
            self._floater._corner_radius = getattr(self, '_corner_radius', BUBBLE_RADIUS)
        except Exception:
            pass

        if self._watcher is None:
            self._watcher = _CanvasInOutWatcher(self._floater, parent=self.canvas)
        self.canvas.installEventFilter(self._watcher)
        if self.canvas.viewport() is not None:
            self.canvas.viewport().installEventFilter(self._watcher)

        if not self._connected:
            self.canvas.xyCoordinates.connect(self._on_xy_raw)
            # Install low-level event filter for press events on viewport
            self.canvas.viewport().installEventFilter(self)
            self._connected = True

    def stop(self):
        if not self.canvas:
            return
        if self._connected:
            try:
                self.canvas.xyCoordinates.disconnect(self._on_xy_raw)
            except Exception:
                pass
            self._connected = False
        # Remove viewport press filter
        try:
            if self.canvas.viewport() is not None:
                self.canvas.viewport().removeEventFilter(self)
        except Exception:
            pass
        if self._watcher:
            try:
                self.canvas.removeEventFilter(self._watcher)
            except Exception:
                pass
            try:
                if self.canvas.viewport() is not None:
                    self.canvas.viewport().removeEventFilter(self._watcher)
            except Exception:
                pass
        if self._floater:
            self._floater.hide()

    # ------------------------------------------------------------------
    def _on_xy_raw(self, map_pt: QgsPointXY):
        """Handle raw xyCoordinates signal and check for snapped coordinates"""
        try:
            # Convert map coordinates back to screen coordinates to check for snapping
            screen_pt = self.canvas.getCoordinateTransform().transform(map_pt)
            screen_pos = QtCore.QPoint(int(screen_pt.x()), int(screen_pt.y()))
            
            # Check if snapping occurred and get snap results
            snapped_pt = map_pt  # Default to original
            snap_depth = None
            
            if self.snapper:
                snap_match = self.snapper.snapToMap(screen_pos)
                if snap_match.isValid():
                    snapped_pt = snap_match.point()
                    # If we snapped, compute max coincident depth at snapped coord (before first click)
                    if not self._have_upstream:
                        snap_depth = self._find_existing_depth_at_point(snapped_pt, None)
            
            # Store snap depth for use in _compose_text
            self._current_snap_depth = snap_depth
            self._on_xy(snapped_pt)
        except Exception:
            # Fallback to original coordinates
            self._current_snap_depth = None
            self._on_xy(map_pt)

    def _on_xy(self, map_pt: QgsPointXY):
        # Guard against removed raster providers
        if not self._interp or not self._to_raster or not self._floater:
            return
        # Gate: show only when editing on selected line layer
        if not self._passes_gate():
            self._floater.hide()
            return
        try:
            # touch provider to see if valid
            _ = self._interp.dp
        except Exception:
            return
        try:
            lyr_pt = self._to_raster.transform(QgsPointXY(map_pt))
        except Exception:
            self._floater.set_text("CRS xform error")
            self._floater.move_near_global(QtGui.QCursor.pos())
            return

        try:
            elev = self._interp.bilinear(lyr_pt)
        except Exception:
            return
        text = self._compose_text(map_pt, elev)
        self._floater.set_text(text)
        self._floater.move_near_global(QtGui.QCursor.pos(), dx=getattr(self, '_offset_x', OFFSET_DX), dy=getattr(self, '_offset_y', OFFSET_DY))
        if not self._floater.isVisible():
            self._floater.show()

    # Build display text
    def _compose_text(self, map_pt: QgsPointXY, elev: Optional[float]) -> str:
        lines = []
        # Extension (distance)
        if self.show_extension and self._have_upstream and self._upstream_map_point is not None:
            try:
                dist = self._distance_m(self._upstream_map_point, map_pt)
                lines.append(f"ext={dist:.2f}")
            except Exception:
                pass
        # Elevation
        if self.show_elevation:
            if elev is None:
                lines.append(f"elev={self._nodata_text}")
            else:
                lines.append(f"elev={float(elev):.2f}")
        
        # Depth preview - different logic for before vs after first click
        if self.show_depth:
            if self._have_upstream and self._upstream_bottom_elev is not None:
                # Normal depth calculation when we have upstream point
                try:
                    dist = self._distance_m(self._upstream_map_point, map_pt)
                    downstream_candidate = self._upstream_bottom_elev - dist * max(0.0, float(self.slope_m_per_m))
                    # If current elev known, enforce minimum cover
                    if elev is not None:
                        # Use integer math to avoid floating-point precision issues
                        min_cover_mm = int(round(float(self.minimum_cover_m) * 1000))
                        diameter_mm = int(round(float(self.diameter_m) * 1000))
                        total_depth = (min_cover_mm + diameter_mm) / 1000.0
                        min_bottom = float(elev) - total_depth
                        downstream_bottom = min(downstream_candidate, min_bottom)
                        depth_val = float(elev) - downstream_bottom
                    else:
                        depth_val = float('nan')
                    
                    # Show if this is first point and depth was inherited
                    if dist < 0.01 and self._inherited_depth is not None:  # Within 1cm = first click
                        lines.append(f"<b><i><font color=\"#aa0000\">depth={depth_val:.2f}</font></i></b>")
                    else:
                        lines.append(f"depth={depth_val:.2f}")
                except Exception:
                    pass
            else:
                # Before first click: show depth from snap match if available
                if self._current_snap_depth is not None:
                    # Use consistent bold+italic red formatting for inherited depth
                    lines.append(f'<b><i><font color="#aa0000">depth={self._current_snap_depth:.2f}</font></i></b>')
        if not lines:
            # Default to elevation text if nothing selected
            return self._nodata_text if elev is None else self._format.format(value=float(elev))
        # Layout mode: vertical vs horizontal
        if getattr(self, '_layout_mode', 'vertical') == 'horizontal':
            sep = "  "
        else:
            sep = "<br/>"
        if self._bold_labels:
            def bold_label(line: str) -> str:
                try:
                    # Skip HTML formatting for lines that already contain HTML tags
                    if '<' in line and '>' in line:
                        return line
                    key, val = line.split("=", 1)
                    return f"<b>{key}</b>={val}"
                except Exception:
                    return line
            parts = [bold_label(l) for l in lines]
        else:
            parts = lines
        html = sep.join(parts)
        # Use rich text rendering
        self._floater.label.setTextFormat(Qt.RichText)
        return html

    # Distance in meters using canvas mapSettings distances
    def _distance_m(self, a: QgsPointXY, b: QgsPointXY) -> float:
        # Prefer configured measure CRS; else canvas destination CRS; else raster CRS
        crs = self._measure_crs or self.canvas.mapSettings().destinationCrs()
        if not crs or not crs.isValid():
            crs = self.layer.crs() if hasattr(self, 'layer') else self.canvas.mapSettings().destinationCrs()
        if crs.isGeographic():
            # Transform to raster CRS (likely projected) for distance calc
            if self._to_raster is not None:
                pa = self._to_raster.transform(QgsPointXY(a))
                pb = self._to_raster.transform(QgsPointXY(b))
                dx = pb.x() - pa.x()
                dy = pb.y() - pa.y()
                return (dx * dx + dy * dy) ** 0.5
        # Projected CRS in meters typically
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        return (dx * dx + dy * dy) ** 0.5

    def _get_snapped_or_raw_point(self, screen_pos):
        """Get snapped coordinates if available, otherwise raw coordinates"""
        try:
            if self.snapper:
                snap_match = self.snapper.snapToMap(screen_pos)
                if snap_match.isValid():
                    # Return snapped point coordinates
                    return snap_match.point()
            
            # Fallback to raw coordinates
            return self.canvas.getCoordinateTransform().toMapCoordinates(screen_pos.x(), screen_pos.y())
        except Exception:
            # Emergency fallback
            return self.canvas.getCoordinateTransform().toMapCoordinates(screen_pos.x(), screen_pos.y())

    def _find_existing_depth_at_point(self, map_pt: QgsPointXY, tolerance: Optional[float] = None):
        """Find existing segment depth at the given coordinates
        
        Args:
            map_pt: Point coordinates to search for
            tolerance: Search tolerance in map units. If None, uses a small pixel-based tolerance.
            
        Returns:
            float or None: Maximum existing depth value if any coincident endpoints are found, None otherwise
        """
        if not self._current_layer:
            return None
            
        try:
            # Derive tolerance from pixels if not provided
            if tolerance is None and self.canvas is not None:
                # 5 pixels radius converted to map units
                tolerance = max(self.canvas.mapUnitsPerPixel() * 5.0, 1e-6)
            elif tolerance is None:
                tolerance = 0.001

            # Get field mappings for depth fields
            field_mapping = self._get_field_mapping()
            p1_h_idx = field_mapping.get('p1_h', -1)
            p2_h_idx = field_mapping.get('p2_h', -1)
            
            if p1_h_idx < 0 and p2_h_idx < 0:
                return None  # No depth fields available
            
            # Search for features with endpoints at or very near this coordinate
            search_rect = QgsRectangle(
                map_pt.x() - tolerance, map_pt.y() - tolerance,
                map_pt.x() + tolerance, map_pt.y() + tolerance
            )
            
            # Get all features in the search area
            request = QgsFeatureRequest().setFilterRect(search_rect)
            features = list(self._current_layer.getFeatures(request))

            # Also inspect edit buffer added features if present
            try:
                eb = self._current_layer.editBuffer()
                if eb:
                    for f in eb.addedFeatures().values():
                        try:
                            g = f.geometry()
                            if g and not g.isEmpty() and g.boundingBox().intersects(search_rect):
                                features.append(f)
                        except Exception:
                            pass
            except Exception:
                pass
            
            print(f"[SEWERAGE DEBUG] Searching for existing depth at {map_pt.x():.6f}, {map_pt.y():.6f}")
            print(f"[SEWERAGE DEBUG] Found {len(features)} features in search area")
            
            max_depth: Optional[float] = None
            for feature in features:
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                if geom.type() != QgsWkbTypes.LineGeometry:
                    continue
                
                # Resolve first and last points of the polyline
                try:
                    if geom.isMultipart():
                        lines = geom.asMultiPolyline()
                        if not lines:
                            continue
                        # Evaluate all parts to catch endpoints that coincide
                        parts = lines
                    else:
                        parts = [geom.asPolyline()]
                except Exception:
                    continue
                candidate_depths = []
                for pts in parts:
                    if len(pts) < 2:
                        continue
                    p1 = QgsPointXY(pts[0])
                    p2 = QgsPointXY(pts[-1])
                    # Check proximity to start/end
                    d1 = ((p1.x() - map_pt.x()) ** 2 + (p1.y() - map_pt.y()) ** 2) ** 0.5
                    d2 = ((p2.x() - map_pt.x()) ** 2 + (p2.y() - map_pt.y()) ** 2) ** 0.5
                    if d1 <= tolerance and p1_h_idx >= 0:
                        candidate_depths.append(feature.attribute(p1_h_idx))
                    if d2 <= tolerance and p2_h_idx >= 0:
                        candidate_depths.append(feature.attribute(p2_h_idx))
                
                for val in candidate_depths:
                    if val is None or val == '':
                        continue
                    try:
                        depth_float = float(val)
                        print(f"[SEWERAGE DEBUG] Candidate depth {depth_float:.3f}m on feature {feature.id()}")
                        if max_depth is None or depth_float > max_depth:
                            max_depth = depth_float
                    except (ValueError, TypeError):
                        continue
            
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error searching for existing depth: {e}")
            
        if max_depth is not None:
            print(f"[SEWERAGE DEBUG] Selected maximum coincident depth: {max_depth:.3f}m")
        return max_depth

    def _get_depth_from_snap_match(self, snap_match):
        """Extract depth value from a snap match result"""
        try:
            # Get the feature and vertex index from snap match
            if hasattr(snap_match, 'layer') and hasattr(snap_match, 'featureId'):
                layer = snap_match.layer()
                if layer != self._current_layer:
                    return None  # Only check our current layer
                    
                feature_id = snap_match.featureId()
                vertex_index = getattr(snap_match, 'vertexIndex', lambda: -1)()
                
                # Get the feature
                feature = layer.getFeature(feature_id)
                if not feature.isValid():
                    return None
                
                # Get field mappings
                field_mapping = self._get_field_mapping()
                p1_h_idx = field_mapping.get('p1_h', -1)
                p2_h_idx = field_mapping.get('p2_h', -1)
                
                # Determine if this is start (p1) or end (p2) vertex
                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    if geom.type() == QgsWkbTypes.LineGeometry:
                        # For linestring, vertex 0 = p1, last vertex = p2
                        vertex_count = geom.constGet().numPoints() if hasattr(geom.constGet(), 'numPoints') else 0
                        
                        if vertex_index == 0 and p1_h_idx >= 0:
                            # First vertex = p1
                            depth_value = feature.attribute(p1_h_idx)
                        elif vertex_index == vertex_count - 1 and p2_h_idx >= 0:
                            # Last vertex = p2
                            depth_value = feature.attribute(p2_h_idx)
                        else:
                            return None  # Middle vertex, no depth info
                        
                        if depth_value is not None and depth_value != '':
                            try:
                                return float(depth_value)
                            except (ValueError, TypeError):
                                pass
                                
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error getting depth from snap match: {e}")
            
        return None

    # Event filter to catch clicks without stealing the active tool
    def eventFilter(self, obj, ev):
        if self.canvas and obj is self.canvas.viewport():
            t = ev.type()
            if t == QtCore.QEvent.MouseButtonPress:
                btn = ev.button()
                pos = ev.pos()
                # Use snapped coordinates if available, otherwise raw coordinates
                map_pt = self._get_snapped_or_raw_point(pos)
                # Gate check
                if not self._passes_gate():
                    return super().eventFilter(obj, ev)
                if btn == QtCore.Qt.LeftButton:
                    self._handle_left_click(map_pt)
                elif btn == QtCore.Qt.RightButton:
                    # Reset and allow native context menu to proceed
                    self._reset_sequence()

        return super().eventFilter(obj, ev)

    def _handle_left_click(self, map_pt: QgsPointXY):
        # Bail if raster was removed
        if not self._interp or not self._to_raster:
            return
        try:
            _ = self._interp.dp
        except Exception:
            return
        try:
            lyr_pt = self._to_raster.transform(QgsPointXY(map_pt))
        except Exception:
            return
        try:
            elev = self._interp.bilinear(lyr_pt) if self._interp else None
        except Exception:
            return
        
        import time
        current_time = time.time()
        
        if not self._have_upstream:
            # First click: clear any old stored clicks from previous drawing session
            if self._stored_clicks:
                print(f"[SEWERAGE DEBUG] Clearing {len(self._stored_clicks)} old stored clicks before new drawing")
                self._stored_clicks = []
            
            # Capture current buffer state at start of new drawing session
            try:
                if self._current_layer and self._current_layer.editBuffer():
                    current_buffer_features = set(self._current_layer.editBuffer().addedFeatures().keys())
                    self._buffer_features_at_session_start = current_buffer_features
                    print(f"[SEWERAGE DEBUG] Session start - buffer contains: {sorted(current_buffer_features)}")
                else:
                    self._buffer_features_at_session_start = set()
            except Exception as e:
                print(f"[SEWERAGE DEBUG] Error capturing buffer state: {e}")
                self._buffer_features_at_session_start = set()
            
            # First click: set upstream point and upstream bottom by rule
            self._upstream_map_point = QgsPointXY(map_pt)
            self._upstream_ground_elev = float(elev) if elev is not None else None
            
            # Check for existing depth at this coordinate (with preference over initial_depth_m)
            existing_depth = self._find_existing_depth_at_point(map_pt, None)
            effective_initial_depth = self.initial_depth_m
            
            if existing_depth is not None:
                # Use existing depth instead of initial_depth_m parameter
                effective_initial_depth = existing_depth
                self._inherited_depth = existing_depth
                print(f"[SEWERAGE DEBUG] Using existing depth {existing_depth:.3f}m instead of initial depth {self.initial_depth_m:.3f}m")
            else:
                self._inherited_depth = None
            
            if effective_initial_depth > 0.0:
                upstream_bottom = (self._upstream_ground_elev if self._upstream_ground_elev is not None else 0.0) - float(effective_initial_depth)
            else:
                # Minimum cover + diameter (use integer math to avoid floating-point precision issues)
                if self._upstream_ground_elev is not None:
                    # Convert to mm, add as integers, convert back to meters  
                    min_cover_mm = int(round(float(self.minimum_cover_m) * 1000))
                    diameter_mm = int(round(float(self.diameter_m) * 1000))
                    total_depth = (min_cover_mm + diameter_mm) / 1000.0
                    upstream_bottom = self._upstream_ground_elev - total_depth
                else:
                    upstream_bottom = None
            self._upstream_bottom_elev = upstream_bottom
            self._have_upstream = True
            
            # Store first click
            upstream_depth = (self._upstream_ground_elev - upstream_bottom) if (self._upstream_ground_elev is not None and upstream_bottom is not None) else None
            click_data = {
                'map_point': QgsPointXY(map_pt),
                'ground_elev': self._upstream_ground_elev,
                'bottom_elev': upstream_bottom,
                'depth': upstream_depth,
                'timestamp': current_time
            }
            self._stored_clicks.append(click_data)
            print(f"[SEWERAGE DEBUG] Stored first click: {map_pt.x():.2f}, {map_pt.y():.2f}, elev={self._upstream_ground_elev}, depth={upstream_depth}")
        else:
            # Second and subsequent clicks: finalize current downstream as new upstream
            if self._upstream_bottom_elev is None:
                return
            # Compute downstream bottom at clicked point
            try:
                dist = self._distance_m(self._upstream_map_point, map_pt)
                candidate = self._upstream_bottom_elev - dist * max(0.0, float(self.slope_m_per_m))
                if elev is not None:
                    # Use integer math to avoid floating-point precision issues
                    min_cover_mm = int(round(float(self.minimum_cover_m) * 1000))
                    diameter_mm = int(round(float(self.diameter_m) * 1000))
                    total_depth = (min_cover_mm + diameter_mm) / 1000.0
                    min_bottom = float(elev) - total_depth
                    downstream_bottom = min(candidate, min_bottom)
                else:
                    downstream_bottom = candidate
                
                # Store this click 
                downstream_depth = (float(elev) - downstream_bottom) if (elev is not None and downstream_bottom is not None) else None
                click_data = {
                    'map_point': QgsPointXY(map_pt),
                    'ground_elev': float(elev) if elev is not None else None,
                    'bottom_elev': downstream_bottom,
                    'depth': downstream_depth,
                    'timestamp': current_time
                }
                self._stored_clicks.append(click_data)
                print(f"[SEWERAGE DEBUG] Stored click {len(self._stored_clicks)}: {map_pt.x():.2f}, {map_pt.y():.2f}, elev={elev}, depth={downstream_depth}")
                
                # Now set new upstream for next segment
                self._upstream_map_point = QgsPointXY(map_pt)
                self._upstream_ground_elev = float(elev) if elev is not None else None
                self._upstream_bottom_elev = downstream_bottom
            except Exception:
                pass

    def _reset_sequence(self):
        self._have_upstream = False
        self._upstream_map_point = None
        self._upstream_ground_elev = None
        self._upstream_bottom_elev = None
        self._inherited_depth = None
        self._current_snap_depth = None
        # DON'T clear stored clicks here - let red_basica workflow complete first
        print("[SEWERAGE DEBUG] Reset sequence (right-click) but keeping stored clicks for red_basica workflow")

    # External API --------------------------------------------------------------
    def set_measure_crs(self, crs: QgsCoordinateReferenceSystem):
        self._measure_crs = crs

    def set_style(self, font: QtGui.QFont, size_pt: int, text_color: QtGui.QColor, bg_color: QtGui.QColor, bold_labels: bool):
        self._font = QtGui.QFont(font)
        self._font_size = int(size_pt)
        self._text_color = QtGui.QColor(text_color)
        self._bg_color = QtGui.QColor(bg_color)
        self._bold_labels = bool(bold_labels)
        if self._floater:
            self._floater.apply_style(self._font, self._font_size, self._text_color, self._bg_color)

    def set_layout_mode(self, mode: str):
        # 'vertical' or 'horizontal'
        self._layout_mode = mode if mode in ('vertical', 'horizontal') else 'vertical'

    def set_bubble_style(self, corner_radius: float, offset_x: int, offset_y: int):
        try:
            self._corner_radius = float(corner_radius)
            self._offset_x = int(offset_x)
            self._offset_y = int(offset_y)
            if self._floater:
                self._floater._corner_radius = self._corner_radius
        except Exception:
            pass

    def set_gate_line_layer(self, layer):
        try:
            # Disconnect from previous layer if any
            if hasattr(self, '_current_layer') and self._current_layer is not None:
                try:
                    self._current_layer.featureAdded.disconnect(self._on_feature_added)
                    self._current_layer.featuresDeleted.disconnect(self._on_features_deleted)
                except Exception:
                    pass
            
            self._gate_layer_id = layer.id() if layer is not None else None
            self._current_layer = layer
            
            # Connect to new layer signals if valid
            if layer is not None:
                try:
                    layer.featureAdded.connect(self._on_feature_added)
                    layer.featuresDeleted.connect(self._on_features_deleted)
                    # Track recent feature operations for red_basica detection
                    self._recent_deletions = []
                    self._pending_additions = []
                    print(f"[SEWERAGE DEBUG] Connected signals to layer: {layer.name()} (ID: {layer.id()})")
                except Exception as e:
                    print(f"[SEWERAGE DEBUG] Failed to connect signals: {e}")
                    pass
            else:
                print("[SEWERAGE DEBUG] No layer provided for signal connection")
        except Exception:
            self._gate_layer_id = None
            self._current_layer = None

    def _passes_gate(self) -> bool:
        if self._gate_layer_id is None:
            return False
        try:
            from qgis.core import QgsProject
            from qgis.gui import QgsMapToolDigitizeFeature
            
            lyr = QgsProject.instance().mapLayer(self._gate_layer_id)
            if lyr is None:
                return False
            # Active layer must be the gated one
            active = self.iface.activeLayer() if self.iface else None
            if active is None or active.id() != lyr.id():
                return False
            # If layer is editable, show; if not, hide
            if not lyr.isEditable():
                return False
            
            # NEW: Only work when using "Add Line Feature" tool (digitizing tool)
            if self.canvas and self.canvas.mapTool():
                current_tool = self.canvas.mapTool()
                # Check if it's a digitizing tool (Add Feature tool)
                if not isinstance(current_tool, QgsMapToolDigitizeFeature):
                    return False
                    
            return True
        except Exception:
            return False

    # Layer signal handlers for red_basica integration -------------------------
    def _on_features_deleted(self, fids):
        """Track deletions - red_basica deletes multi-vertex then adds 2-vertex segments"""
        import time
        try:
            print(f"[SEWERAGE DEBUG] Features deleted: {list(fids)}")
            self._recent_deletions.append({
                'fids': list(fids),
                'timestamp': time.time()
            })
            # Keep only recent deletions (last 5 seconds)
            current_time = time.time()
            self._recent_deletions = [d for d in self._recent_deletions if current_time - d['timestamp'] < 5.0]
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in _on_features_deleted: {e}")
            pass

    def _on_feature_added(self, fid):
        """Track additions - detect red_basica pattern and match to stored clicks"""
        import time
        try:
            current_time = time.time()
            print(f"[SEWERAGE DEBUG] Feature added: {fid}")
            print(f"[SEWERAGE DEBUG] Stored clicks count: {len(self._stored_clicks)}")
            print(f"[SEWERAGE DEBUG] Recent deletions: {len(self._recent_deletions)}")
            
            # Simplified detection: if we have stored clicks and this is a negative ID, process it
            # The key insight: red_basica always creates negative IDs, so any negative ID + stored clicks = process
            should_process = self._stored_clicks and fid < 0
            print(f"[SEWERAGE DEBUG] Should process: stored_clicks={len(self._stored_clicks)}, negative_id={fid < 0}")
            
            if should_process:
                print(f"[SEWERAGE DEBUG] Triggering segment processing for fid: {fid}")
                # Add to pending list and wait for more features to be added
                if not hasattr(self, '_pending_fids'):
                    self._pending_fids = []
                self._pending_fids.append(fid)
                
                # Delay processing longer to allow all segments to be added
                QtCore.QTimer.singleShot(500, lambda: self._process_pending_segments())
            else:
                if not self._stored_clicks:
                    print("[SEWERAGE DEBUG] No stored clicks - skipping processing")
                elif fid >= 0:
                    print("[SEWERAGE DEBUG] Positive feature ID - likely not red_basica - skipping processing")
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in _on_feature_added: {e}")
            pass

    def _process_pending_segments(self):
        """Process all pending segments after collecting multiple feature additions"""
        if hasattr(self, '_pending_fids'):
            print(f"[SEWERAGE DEBUG] Processing {len(self._pending_fids)} pending segments")
            self._process_new_segments(self._pending_fids)
            self._pending_fids = []  # Clear pending list
        else:
            print("[SEWERAGE DEBUG] No pending segments to process")

    def _process_new_segments(self, recent_fids):
        """Match newly added 2-vertex segments to stored clicks and write attributes"""
        print(f"[SEWERAGE DEBUG] Processing new segments, recent_fids: {recent_fids}")
        print(f"[SEWERAGE DEBUG] Has stored clicks: {bool(self._stored_clicks)}")
        print(f"[SEWERAGE DEBUG] Has current layer: {bool(self._current_layer)}")
        
        if not self._stored_clicks or not self._current_layer:
            print("[SEWERAGE DEBUG] Early return - missing clicks or layer")
            return
        
        # Keep a copy of current clicks for downstream recalculation
        stored_clicks_copy = list(self._stored_clicks)

        try:
            print(f"[SEWERAGE DEBUG] Layer is editable: {self._current_layer.isEditable()}")
            print(f"[SEWERAGE DEBUG] Layer feature count: {self._current_layer.featureCount()}")
            
            # Get features from edit buffer (for newly added features with negative IDs)
            edit_buffer = self._current_layer.editBuffer()
            if edit_buffer:
                added_features = edit_buffer.addedFeatures()
                print(f"[SEWERAGE DEBUG] Edit buffer has {len(added_features)} added features")
                print(f"[SEWERAGE DEBUG] Added feature IDs: {list(added_features.keys())}")
                
                # Filter to only NEW features (not in buffer at session start)
                new_feature_ids = set(added_features.keys()) - self._buffer_features_at_session_start
                print(f"[SEWERAGE DEBUG] Buffer at session start: {sorted(self._buffer_features_at_session_start)}")
                print(f"[SEWERAGE DEBUG] NEW features for this session: {sorted(new_feature_ids)}")
                
                # Use only new features from edit buffer
                candidate_features = []
                for feat_id in new_feature_ids:
                    if feat_id not in added_features:
                        continue
                    feat = added_features[feat_id]
                    try:
                        geom = feat.geometry()
                        if geom.isEmpty():
                            continue
                        
                        # Handle multipart geometry
                        if geom.isMultipart():
                            lines = geom.asMultiPolyline()
                            if lines and len(lines[0]) == 2:
                                candidate_features.append((feat, lines[0]))
                                print(f"[SEWERAGE DEBUG] Added NEW multipart 2-vertex feature: {feat.id()}")
                        else:
                            line = geom.asPolyline()
                            if len(line) == 2:
                                candidate_features.append((feat, line))
                                print(f"[SEWERAGE DEBUG] Added NEW single 2-vertex feature: {feat.id()}, coords: {[(p.x(), p.y()) for p in line]}")
                    except Exception as e:
                        print(f"[SEWERAGE DEBUG] Error processing NEW buffer feature {feat.id()}: {e}")
                        continue
            else:
                print("[SEWERAGE DEBUG] No edit buffer available, falling back to layer features")
                # Fallback to regular layer features
                all_features = list(self._current_layer.getFeatures())
                print(f"[SEWERAGE DEBUG] Retrieved {len(all_features)} features from layer")
                
                candidate_features = []
                for feat in all_features:
                    try:
                        geom = feat.geometry()
                        if geom.isEmpty():
                            continue
                        
                        # Handle multipart geometry
                        if geom.isMultipart():
                            lines = geom.asMultiPolyline()
                            if lines and len(lines[0]) == 2:
                                candidate_features.append((feat, lines[0]))
                                print(f"[SEWERAGE DEBUG] Added multipart 2-vertex feature: {feat.id()}")
                        else:
                            line = geom.asPolyline()
                            if len(line) == 2:
                                candidate_features.append((feat, line))
                                print(f"[SEWERAGE DEBUG] Added single 2-vertex feature: {feat.id()}, coords: {[(p.x(), p.y()) for p in line]}")
                    except Exception as e:
                        print(f"[SEWERAGE DEBUG] Error processing feature {feat.id()}: {e}")
                        continue
            
            print(f"[SEWERAGE DEBUG] Found {len(candidate_features)} NEW candidate 2-vertex features")
            
            if not candidate_features:
                print("[SEWERAGE DEBUG] No 2-vertex candidate features found")
                return
            
            # Match segments to click pairs
            matches_found = self._match_and_write_attributes(candidate_features)

            # If we wrote attributes, attempt downstream recalculation based on last click
            try:
                if matches_found > 0 and stored_clicks_copy:
                    end_click = stored_clicks_copy[-1]
                    end_point = end_click.get('map_point')
                    end_depth = end_click.get('depth')
                    if end_point is not None and end_depth is not None:
                        print(f"[SEWERAGE DEBUG] Trigger downstream recalculation from end point ({end_point.x():.3f}, {end_point.y():.3f}) with depth {end_depth:.3f}")
                        # Exclude new features from traversal (use non-negative IDs if available)
                        exclude_ids = set([feat.id() for feat, _ in candidate_features])
                        self._recalculate_downstream_from_connection(end_point, float(end_depth), exclude_ids)
                else:
                    print("[SEWERAGE DEBUG] Skipping downstream recalculation: no matches found or no end point/depth")
            except Exception as e:
                print(f"[SEWERAGE DEBUG] Downstream recalculation error: {e}")
            
            print(f"[SEWERAGE DEBUG] Total matches found: {matches_found}")
            
            # Always clear stored clicks at end of processing cycle
            self._stored_clicks = []
            print("[SEWERAGE DEBUG] Cleared stored clicks after processing cycle")
            
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in _process_new_segments: {e}")
            pass

    def _match_and_write_attributes(self, candidate_features):
        """Match segments to stored clicks and write elevation/depth attributes"""
        print(f"[SEWERAGE DEBUG] Matching attributes, stored clicks: {len(self._stored_clicks)}")
        
        if not self._stored_clicks or len(self._stored_clicks) < 2:
            print(f"[SEWERAGE DEBUG] Not enough stored clicks: {len(self._stored_clicks)}")
            return 0
        
        # Debug: Print stored clicks
        for i, click in enumerate(self._stored_clicks):
            print(f"[SEWERAGE DEBUG] Click {i}: {click['map_point'].x():.2f}, {click['map_point'].y():.2f}, elev={click['ground_elev']}, depth={click['depth']}")
        
        # Get attribute field mapping from dock widget
        field_mapping = self._get_field_mapping()
        print(f"[SEWERAGE DEBUG] Field mapping: {field_mapping}")
        
        if not field_mapping:
            print("[SEWERAGE DEBUG] No field mapping available")
            return 0
        
        try:
            # Sort features by ID (most negative first, which corresponds to creation order)
            # Features are created in order: -10, -11, -12, -13, -14...
            # We want them in reverse order of ID (creation order)
            sorted_features = sorted(candidate_features, key=lambda x: x[0].id(), reverse=True)
            print(f"[SEWERAGE DEBUG] Sorted features by creation order: {[f[0].id() for f in sorted_features]}")
            
            matches_found = 0
            expected_segments = len(self._stored_clicks) - 1
            
            print(f"[SEWERAGE DEBUG] Expected {expected_segments} segments from {len(self._stored_clicks)} clicks")
            
            # Match by sequential order: Feature 0 gets clicks 0-1, Feature 1 gets clicks 1-2, etc.
            for segment_index, (feat, line_coords) in enumerate(sorted_features):
                if segment_index >= expected_segments:
                    print(f"[SEWERAGE DEBUG] Segment {segment_index} exceeds expected segments ({expected_segments})")
                    break
                
                p1, p2 = line_coords[0], line_coords[1]
                click1 = self._stored_clicks[segment_index]
                click2 = self._stored_clicks[segment_index + 1]
                
                print(f"[SEWERAGE DEBUG] Sequential match - Feature {feat.id()} (segment {segment_index}): clicks {segment_index}-{segment_index+1}")
                print(f"[SEWERAGE DEBUG] Feature coords: p1=({p1.x():.2f}, {p1.y():.2f}), p2=({p2.x():.2f}, {p2.y():.2f})")
                print(f"[SEWERAGE DEBUG] Click coords: c1=({click1['map_point'].x():.2f}, {click1['map_point'].y():.2f}), c2=({click2['map_point'].x():.2f}, {click2['map_point'].y():.2f})")
                
                # Determine orientation by checking which click is closer to which endpoint
                d1_to_c1 = self._point_distance(p1, click1['map_point'])
                d1_to_c2 = self._point_distance(p1, click2['map_point'])
                
                if d1_to_c1 <= d1_to_c2:
                    # p1 closer to click1, so normal order
                    p1_data, p2_data = click1, click2
                    order_desc = "normal"
                else:
                    # p1 closer to click2, so reversed order
                    p1_data, p2_data = click2, click1
                    order_desc = "reversed"
                
                print(f"[SEWERAGE DEBUG] Orientation: {order_desc} (p1-to-c1: {d1_to_c1:.2f}, p1-to-c2: {d1_to_c2:.2f})")
                
                # Write attributes
                success = self._write_segment_attributes(feat, p1_data, p2_data, field_mapping)
                if success:
                    matches_found += 1
                    print(f"[SEWERAGE DEBUG] Successfully wrote attributes for feature {feat.id()}")
                else:
                    print(f"[SEWERAGE DEBUG] Failed to write attributes for feature {feat.id()}")
            
            print(f"[SEWERAGE DEBUG] Total matches found: {matches_found}")
            return matches_found
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in _match_and_write_attributes: {e}")
            return 0

    # --- Downstream recalculation ---------------------------------------------
    def _recalculate_downstream_from_connection(self, connection_point: QgsPointXY, new_upstream_depth: float, exclude_ids: set):
        """If connection_point is the upstream of an existing segment, update p1 depth and
        propagate downstream depths along connected chain using current parameters.

        exclude_ids: feature IDs to ignore (e.g., the just-added new features)
        """
        try:
            if not self._current_layer:
                return
            field_mapping = self._get_field_mapping()
            p1e = field_mapping.get('p1_elev', -1)
            p2e = field_mapping.get('p2_elev', -1)
            p1h = field_mapping.get('p1_h', -1)
            p2h = field_mapping.get('p2_h', -1)
            if min(p1e, p2e, p1h, p2h) < 0:
                print("[SEWERAGE DEBUG] Missing required fields for downstream recalc")
                return

            # Build index of features by their upstream (p1) coordinate
            def key_from_point(pt: QgsPointXY) -> str:
                return f"{pt.x():.6f},{pt.y():.6f}"

            p1_index = {}
            features = list(self._current_layer.getFeatures())
            for f in features:
                try:
                    if f.id() in exclude_ids:
                        continue
                    g = f.geometry()
                    if not g or g.isEmpty():
                        continue
                    if g.isMultipart():
                        lines = g.asMultiPolyline()
                        if not lines:
                            continue
                        pts = lines[0]
                    else:
                        pts = g.asPolyline()
                    if len(pts) < 2:
                        continue
                    k = key_from_point(QgsPointXY(pts[0]))
                    p1_index.setdefault(k, []).append((f, pts))
                except Exception:
                    continue

            start_key = key_from_point(connection_point)
            if start_key not in p1_index:
                print("[SEWERAGE DEBUG] No existing segment with this point as upstream (p1); skipping recalc")
                return

            # Use first matching segment (if multiple, choose smallest ID)
            candidate_list = p1_index[start_key]
            candidate_list.sort(key=lambda tup: tup[0].id())
            current_feature, current_pts = candidate_list[0]

            # Ensure layer is editable
            if not self._current_layer.isEditable():
                self._current_layer.startEditing()

            visited = set()
            upstream_depth = float(new_upstream_depth)
            current_upstream_point = QgsPointXY(current_pts[0])

            while current_feature and current_feature.id() not in visited:
                visited.add(current_feature.id())
                # Read ground elevations
                p1_ground = current_feature.attribute(p1e)
                p2_ground = current_feature.attribute(p2e)
                try:
                    p1_ground = float(p1_ground) if p1_ground is not None else None
                    p2_ground = float(p2_ground) if p2_ground is not None else None
                except Exception:
                    p1_ground = p2_ground = None

                # Interpolate missing elevations from DEM
                p1_interpolated = False
                p2_interpolated = False
                if p1_ground is None:
                    p1_ground = self._interpolate_elevation_from_dem(QgsPointXY(current_pts[0]))
                    if p1_ground is not None:
                        p1_interpolated = True
                        print(f"[SEWERAGE DEBUG] Interpolated P1 elevation: {p1_ground:.3f}m for feature {current_feature.id()}")
                        # Write interpolated value back to feature
                        self._current_layer.changeAttributeValue(current_feature.id(), p1e, round(p1_ground, 3))

                if p2_ground is None:
                    p2_ground = self._interpolate_elevation_from_dem(QgsPointXY(current_pts[-1]))
                    if p2_ground is not None:
                        p2_interpolated = True
                        print(f"[SEWERAGE DEBUG] Interpolated P2 elevation: {p2_ground:.3f}m for feature {current_feature.id()}")
                        # Write interpolated value back to feature
                        self._current_layer.changeAttributeValue(current_feature.id(), p2e, round(p2_ground, 3))

                # Update p1_h if needed (adopt the larger new upstream depth)
                try:
                    existing_p1_h_val = current_feature.attribute(p1h)
                    existing_p1_h = float(existing_p1_h_val) if existing_p1_h_val not in (None, '') else None
                except Exception:
                    existing_p1_h = None

                effective_p1_depth = upstream_depth
                if existing_p1_h is not None and existing_p1_h > effective_p1_depth:
                    effective_p1_depth = existing_p1_h

                # Write p1_h if changed
                if existing_p1_h is None or abs(existing_p1_h - effective_p1_depth) > 1e-3:
                    self._current_layer.changeAttributeValue(current_feature.id(), p1h, round(effective_p1_depth, 2))

                # Compute downstream bottom and depth
                if p1_ground is None or p2_ground is None:
                    print(f"[SEWERAGE DEBUG] Unable to get ground elevation on feature {current_feature.id()} - neither stored nor interpolatable from DEM, stopping")
                    break

                upstream_bottom = p1_ground - effective_p1_depth
                # Distance between endpoints in meters
                seg_len = self._distance_m(QgsPointXY(current_pts[0]), QgsPointXY(current_pts[-1]))
                bottom_candidate = upstream_bottom - seg_len * max(0.0, float(self.slope_m_per_m))

                # Enforce minimum cover at downstream
                min_cover_mm = int(round(float(self.minimum_cover_m) * 1000))
                diameter_mm = int(round(float(self.diameter_m) * 1000))
                total_depth = (min_cover_mm + diameter_mm) / 1000.0
                min_bottom = float(p2_ground) - total_depth
                downstream_bottom = min(bottom_candidate, min_bottom)
                downstream_depth = float(p2_ground) - downstream_bottom

                # Write p2_h
                self._current_layer.changeAttributeValue(current_feature.id(), p2h, round(downstream_depth, 2))

                # Advance to next feature where its p1 equals current p2
                next_key = key_from_point(QgsPointXY(current_pts[-1]))
                next_candidates = p1_index.get(next_key, [])
                # Remove already visited
                next_candidates = [(f, pts) for (f, pts) in next_candidates if f.id() not in visited]
                if not next_candidates:
                    break
                next_candidates.sort(key=lambda tup: tup[0].id())
                current_feature, current_pts = next_candidates[0]
                upstream_depth = downstream_depth

            print("[SEWERAGE DEBUG] Downstream recalculation complete")
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in downstream recalculation: {e}")

    def _interpolate_elevation_from_dem(self, point: QgsPointXY) -> Optional[float]:
        """Interpolate elevation from DEM at given point. Returns None if unavailable."""
        try:
            # Guard against removed raster providers
            if not self._interp or not self._to_raster:
                print("[SEWERAGE DEBUG] No DEM interpolator available for elevation interpolation")
                return None
            
            # Check if provider is still valid
            try:
                _ = self._interp.dp
            except Exception:
                print("[SEWERAGE DEBUG] DEM provider has been removed, cannot interpolate")
                return None
            
            # Transform point to raster CRS
            try:
                lyr_pt = self._to_raster.transform(point)
            except Exception as e:
                print(f"[SEWERAGE DEBUG] CRS transform error during elevation interpolation: {e}")
                return None
            
            # Interpolate elevation
            try:
                elev = self._interp.bilinear(lyr_pt)
                if elev is not None:
                    return float(elev)
                else:
                    print(f"[SEWERAGE DEBUG] DEM interpolation returned no data at point ({point.x():.3f}, {point.y():.3f})")
                    return None
            except Exception as e:
                print(f"[SEWERAGE DEBUG] DEM interpolation error: {e}")
                return None
                
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in _interpolate_elevation_from_dem: {e}")
            return None

    def _get_field_mapping(self):
        """Get field mapping from dock widget"""
        try:
            # Access the dock widget through the parent controller
            if hasattr(self, 'iface') and self.iface:
                # Find the sewerage depth estimator dock widget
                for widget in self.iface.mainWindow().findChildren(QtWidgets.QDockWidget):
                    if hasattr(widget, '_current_line_layer'):
                        p1e_idx = widget._resolve_field_index(self._current_layer, 'cmbP1Elev', 'p1_elev') if hasattr(widget, '_resolve_field_index') else self._current_layer.fields().indexOf('p1_elev')
                        p2e_idx = widget._resolve_field_index(self._current_layer, 'cmbP2Elev', 'p2_elev') if hasattr(widget, '_resolve_field_index') else self._current_layer.fields().indexOf('p2_elev')
                        p1h_idx = widget._resolve_field_index(self._current_layer, 'cmbP1H', 'p1_h') if hasattr(widget, '_resolve_field_index') else self._current_layer.fields().indexOf('p1_h')
                        p2h_idx = widget._resolve_field_index(self._current_layer, 'cmbP2H', 'p2_h') if hasattr(widget, '_resolve_field_index') else self._current_layer.fields().indexOf('p2_h')
                        return {
                            'p1_elev': p1e_idx,
                            'p2_elev': p2e_idx,
                            'p1_h': p1h_idx,
                            'p2_h': p2h_idx
                        }
        except Exception:
            pass
        
        # Fallback to default field names
        return {
            'p1_elev': self._current_layer.fields().indexOf('p1_elev'),
            'p2_elev': self._current_layer.fields().indexOf('p2_elev'),
            'p1_h': self._current_layer.fields().indexOf('p1_h'),
            'p2_h': self._current_layer.fields().indexOf('p2_h')
        }

    def _write_segment_attributes(self, feature, p1_data, p2_data, field_mapping):
        """Write elevation and depth values to segment attributes"""
        try:
            print(f"[SEWERAGE DEBUG] Writing attributes to feature {feature.id()}")
            print(f"[SEWERAGE DEBUG] Layer editable: {self._current_layer.isEditable()}")
            print(f"[SEWERAGE DEBUG] p1_data: elev={p1_data['ground_elev']}, depth={p1_data['depth']}")
            print(f"[SEWERAGE DEBUG] p2_data: elev={p2_data['ground_elev']}, depth={p2_data['depth']}")
            
            if not self._current_layer.isEditable():
                print("[SEWERAGE DEBUG] Starting edit session")
                self._current_layer.startEditing()
            
            changes_made = 0
            
            # Write p1 values (rounded to 2 decimals)
            if field_mapping['p1_elev'] >= 0 and p1_data['ground_elev'] is not None:
                rounded_elev = round(float(p1_data['ground_elev']), 2)
                success = self._current_layer.changeAttributeValue(feature.id(), field_mapping['p1_elev'], rounded_elev)
                print(f"[SEWERAGE DEBUG] p1_elev write success: {success} (field index: {field_mapping['p1_elev']}, value: {rounded_elev})")
                if success:
                    changes_made += 1
            else:
                print(f"[SEWERAGE DEBUG] Skipping p1_elev: field_index={field_mapping['p1_elev']}, value={p1_data['ground_elev']}")
                
            if field_mapping['p1_h'] >= 0 and p1_data['depth'] is not None:
                rounded_depth = round(float(p1_data['depth']), 2)
                success = self._current_layer.changeAttributeValue(feature.id(), field_mapping['p1_h'], rounded_depth)
                print(f"[SEWERAGE DEBUG] p1_h write success: {success} (field index: {field_mapping['p1_h']}, value: {rounded_depth})")
                if success:
                    changes_made += 1
            else:
                print(f"[SEWERAGE DEBUG] Skipping p1_h: field_index={field_mapping['p1_h']}, value={p1_data['depth']}")
            
            # Write p2 values (rounded to 2 decimals)  
            if field_mapping['p2_elev'] >= 0 and p2_data['ground_elev'] is not None:
                rounded_elev = round(float(p2_data['ground_elev']), 2)
                success = self._current_layer.changeAttributeValue(feature.id(), field_mapping['p2_elev'], rounded_elev)
                print(f"[SEWERAGE DEBUG] p2_elev write success: {success} (field index: {field_mapping['p2_elev']}, value: {rounded_elev})")
                if success:
                    changes_made += 1
            else:
                print(f"[SEWERAGE DEBUG] Skipping p2_elev: field_index={field_mapping['p2_elev']}, value={p2_data['ground_elev']}")
                
            if field_mapping['p2_h'] >= 0 and p2_data['depth'] is not None:
                rounded_depth = round(float(p2_data['depth']), 2)
                success = self._current_layer.changeAttributeValue(feature.id(), field_mapping['p2_h'], rounded_depth)
                print(f"[SEWERAGE DEBUG] p2_h write success: {success} (field index: {field_mapping['p2_h']}, value: {rounded_depth})")
                if success:
                    changes_made += 1
            else:
                print(f"[SEWERAGE DEBUG] Skipping p2_h: field_index={field_mapping['p2_h']}, value={p2_data['depth']}")
            
            print(f"[SEWERAGE DEBUG] Total changes made: {changes_made}")
            return changes_made > 0
                
        except Exception as e:
            print(f"[SEWERAGE DEBUG] Error in _write_segment_attributes: {e}")
            return False

    def _point_distance(self, qgs_point, qgs_point2):
        """Calculate distance between two QgsPointXY objects"""
        try:
            dx = qgs_point.x() - qgs_point2.x()
            dy = qgs_point.y() - qgs_point2.y()
            return (dx * dx + dy * dy) ** 0.5
        except Exception:
            return float('inf')

    # Access methods for stored clicks ------------------------------------------
    def get_stored_clicks(self):
        """Return copy of stored clicks for debugging/inspection"""
        return list(self._stored_clicks)
    
    def clear_stored_clicks(self):
        """Clear stored clicks manually"""
        self._stored_clicks = []
        print("[SEWERAGE DEBUG] Manually cleared stored clicks")
    
    def force_clear_on_new_drawing(self):
        """Clear stored clicks when starting a completely new drawing session"""
        if self._stored_clicks:
            print(f"[SEWERAGE DEBUG] Force clearing {len(self._stored_clicks)} stored clicks for new drawing")
            self._stored_clicks = []


