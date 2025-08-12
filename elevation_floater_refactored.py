# -*- coding: utf-8 -*-
"""
Refactored elevation floater controller using modular architecture.

This is a compatibility layer that uses the new modular components while
maintaining the same API as the original elevation_floater.py.
"""

import time
from typing import Optional
from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.PyQt.QtCore import Qt, QEvent, QPoint
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, QgsPointXY, QgsMapLayer, QgsVectorLayer
)

# Import modular components
from .utils import DebugLogger, CoordinateUtils
from .data import RasterInterpolator, FieldMapper
from .core import DepthCalculator

# Import UI components from original file (keeping existing UI for now)
from .elevation_floater import _FloaterWidget, _CanvasInOutWatcher

# Re-export RasterInterpolator for backward compatibility
from .data.raster_interpolator import RasterInterpolator


class ElevationFloaterController(QtCore.QObject):
    """Refactored elevation floater using modular architecture."""

    def __init__(self, iface):
        super().__init__(iface.mainWindow() if iface else None)
        self.iface = iface
        self.canvas = self.iface.mapCanvas() if self.iface else None
        self.snapper = self.canvas.snappingUtils() if self.canvas else None
        
        # UI components
        self._floater: Optional[_FloaterWidget] = None
        self._watcher: Optional[_CanvasInOutWatcher] = None
        self._connected = False

        # Modular components
        self._interpolator: Optional[RasterInterpolator] = None
        self._field_mapper: Optional[FieldMapper] = None
        self._depth_calculator = DepthCalculator()
        
        # Coordinate transformation
        self._to_raster: Optional[CoordinateUtils] = None
        self._measure_crs: Optional[QgsCoordinateReferenceSystem] = None
        
        # Configuration
        self._band: int = 1
        self._format: str = "{value:.3f}"
        self._nodata_text: str = "NoData"
        
        # Display toggles
        self.show_extension: bool = True
        self.show_elevation: bool = True
        self.show_depth: bool = True
        
        # Click sequence state
        self._have_upstream: bool = False
        self._upstream_map_point: Optional[QgsPointXY] = None
        self._upstream_ground_elev: Optional[float] = None
        self._upstream_bottom_elev: Optional[float] = None
        self._inherited_depth: Optional[float] = None
        self._current_snap_depth: Optional[float] = None
        
        # Style settings
        self._font = QtGui.QFont("Calibri")
        self._font_size = 9
        self._bold_labels = True
        self._text_color = QtGui.QColor(34, 34, 34)
        self._bg_color = QtGui.QColor(240, 240, 240, 170)
        self._layout_mode = 'vertical'
        self._corner_radius = 8
        self._offset_x = 14
        self._offset_y = 10
        
        # Layer gating
        self._gate_layer_id: Optional[str] = None
        self._current_layer: Optional[QgsVectorLayer] = None
        
        # Click storage
        self._stored_clicks = []
        self._buffer_features_at_session_start = set()

    # --- Properties for backward compatibility ---
    @property
    def minimum_cover_m(self) -> float:
        return self._depth_calculator.min_cover_m
    
    @minimum_cover_m.setter
    def minimum_cover_m(self, value: float):
        self._depth_calculator.min_cover_m = value
    
    @property
    def diameter_m(self) -> float:
        return self._depth_calculator.diameter_m
    
    @diameter_m.setter
    def diameter_m(self, value: float):
        self._depth_calculator.diameter_m = value
    
    @property
    def slope_m_per_m(self) -> float:
        return self._depth_calculator.slope_m_per_m
    
    @slope_m_per_m.setter
    def slope_m_per_m(self, value: float):
        self._depth_calculator.slope_m_per_m = value
    
    @property
    def initial_depth_m(self) -> float:
        return getattr(self, '_initial_depth_m', 0.0)
    
    @initial_depth_m.setter
    def initial_depth_m(self, value: float):
        self._initial_depth_m = value

    def start(self, raster_layer: QgsMapLayer, band: int = 1, 
              number_format: str = "{value:.3f}", nodata_text: str = "NoData"):
        """Start the elevation floater with given raster layer."""
        if not self.canvas or not raster_layer:
            raise RuntimeError("Canvas or raster layer not available")

        self._band = int(band)
        self._format = number_format
        self._nodata_text = nodata_text

        # Initialize interpolator
        self._interpolator = RasterInterpolator(raster_layer, band=self._band)
        
        # Setup coordinate transform
        from qgis.core import QgsCoordinateTransform
        ctxt = QgsProject.instance().transformContext()
        self._to_raster = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(), raster_layer.crs(), ctxt
        )

        # Setup UI
        parent_for_overlay = self.canvas.viewport() or self.canvas
        if self._floater is None:
            self._floater = _FloaterWidget(parent=parent_for_overlay)
        self._floater.hide()
        self._floater.apply_style(self._font, self._font_size, self._text_color, self._bg_color)
        
        # Apply style settings
        try:
            self._floater._corner_radius = self._corner_radius
        except Exception:
            pass

        # Setup event handling
        if self._watcher is None:
            self._watcher = _CanvasInOutWatcher(self._floater, parent=self.canvas)
        self.canvas.installEventFilter(self._watcher)
        if self.canvas.viewport() is not None:
            self.canvas.viewport().installEventFilter(self._watcher)

        if not self._connected:
            self.canvas.xyCoordinates.connect(self._on_xy_raw)
            self.canvas.viewport().installEventFilter(self)
            self._connected = True

        DebugLogger.log("Elevation floater started successfully")

    def stop(self):
        """Stop the elevation floater."""
        if not self.canvas:
            return
            
        if self._connected:
            try:
                self.canvas.xyCoordinates.disconnect(self._on_xy_raw)
            except Exception:
                pass
            self._connected = False
            
        # Remove event filters
        try:
            if self.canvas.viewport() is not None:
                self.canvas.viewport().removeEventFilter(self)
        except Exception:
            pass
            
        if self._watcher:
            try:
                self.canvas.removeEventFilter(self._watcher)
                if self.canvas.viewport() is not None:
                    self.canvas.viewport().removeEventFilter(self._watcher)
            except Exception:
                pass
                
        if self._floater:
            self._floater.hide()
            
        DebugLogger.log("Elevation floater stopped")

    def set_gate_line_layer(self, layer: Optional[QgsVectorLayer]):
        """Set the gate layer for controlling when floater is active."""
        try:
            # Disconnect from previous layer
            if self._current_layer is not None:
                try:
                    self._current_layer.featureAdded.disconnect(self._on_feature_added)
                    self._current_layer.featuresDeleted.disconnect(self._on_features_deleted)
                except Exception:
                    pass
            
            self._gate_layer_id = layer.id() if layer is not None else None
            self._current_layer = layer
            
            # Initialize field mapper for new layer
            if layer is not None:
                self._field_mapper = FieldMapper(layer)
                
                # Connect to layer signals
                try:
                    layer.featureAdded.connect(self._on_feature_added)
                    layer.featuresDeleted.connect(self._on_features_deleted)
                    DebugLogger.log(f"Connected to layer: {layer.name()}")
                except Exception as e:
                    DebugLogger.log_error("Failed to connect layer signals", e)
            else:
                self._field_mapper = None
                
        except Exception as e:
            DebugLogger.log_error("Error setting gate layer", e)
            self._gate_layer_id = None
            self._current_layer = None
            self._field_mapper = None

    def set_measure_crs(self, crs: QgsCoordinateReferenceSystem):
        """Set the CRS for distance measurements."""
        self._measure_crs = crs

    def set_style(self, font: QtGui.QFont, size_pt: int, text_color: QtGui.QColor, 
                  bg_color: QtGui.QColor, bold_labels: bool):
        """Set display style."""
        self._font = QtGui.QFont(font)
        self._font_size = int(size_pt)
        self._text_color = QtGui.QColor(text_color)
        self._bg_color = QtGui.QColor(bg_color)
        self._bold_labels = bool(bold_labels)
        if self._floater:
            self._floater.apply_style(self._font, self._font_size, self._text_color, self._bg_color)

    def set_layout_mode(self, mode: str):
        """Set layout mode (vertical/horizontal)."""
        self._layout_mode = mode if mode in ('vertical', 'horizontal') else 'vertical'

    def set_bubble_style(self, corner_radius: float, offset_x: int, offset_y: int):
        """Set bubble styling."""
        try:
            self._corner_radius = float(corner_radius)
            self._offset_x = int(offset_x)
            self._offset_y = int(offset_y)
            if self._floater:
                self._floater._corner_radius = self._corner_radius
        except Exception:
            pass

    # --- Event handling (simplified versions of original methods) ---
    
    def _on_xy_raw(self, map_pt: QgsPointXY):
        """Handle mouse movement with snapping."""
        try:
            # Get snapped coordinates if available
            if self.snapper:
                screen_pt = self.canvas.getCoordinateTransform().transform(map_pt)
                screen_pos = QtCore.QPoint(int(screen_pt.x()), int(screen_pt.y()))
                snap_match = self.snapper.snapToMap(screen_pos)
                if snap_match.isValid():
                    map_pt = snap_match.point()
                    # Store snap depth for display
                    if not self._have_upstream:
                        self._current_snap_depth = self._find_existing_depth_at_point(map_pt)
            
            self._on_xy(map_pt)
        except Exception:
            self._current_snap_depth = None
            self._on_xy(map_pt)

    def _on_xy(self, map_pt: QgsPointXY):
        """Handle coordinate display."""
        if not self._interpolator or not self._floater:
            return
            
        if not self._passes_gate():
            self._floater.hide()
            return
            
        # Check if interpolator is still valid
        if not self._interpolator.is_valid():
            return
            
        try:
            # Transform to raster coordinates
            lyr_pt = CoordinateUtils.transform_point(map_pt, self._to_raster)
            if not lyr_pt:
                self._floater.set_text("CRS transform error")
                self._floater.move_near_global(QtGui.QCursor.pos())
                return
                
            # Get elevation
            elev = self._interpolator.bilinear(lyr_pt)
        except Exception:
            return
            
        # Compose and display text
        text = self._compose_text(map_pt, elev)
        self._floater.set_text(text)
        self._floater.move_near_global(
            QtGui.QCursor.pos(), 
            dx=self._offset_x, 
            dy=self._offset_y
        )
        
        if not self._floater.isVisible():
            self._floater.show()

    def _compose_text(self, map_pt: QgsPointXY, elev: Optional[float]) -> str:
        """Compose display text using modular components."""
        lines = []
        
        # Extension (distance)
        if self.show_extension and self._have_upstream and self._upstream_map_point:
            try:
                dist = CoordinateUtils.distance_m(
                    self._upstream_map_point, map_pt, 
                    self._measure_crs, self._to_raster
                )
                lines.append(f"ext={dist:.2f}")
            except Exception:
                pass
        
        # Elevation
        if self.show_elevation:
            if elev is None:
                lines.append(f"elev={self._nodata_text}")
            else:
                lines.append(f"elev={float(elev):.2f}")
        
        # Depth preview
        if self.show_depth:
            depth_text = self._get_depth_text(map_pt, elev)
            if depth_text:
                lines.append(depth_text)
        
        if not lines:
            return self._nodata_text if elev is None else self._format.format(value=float(elev))
        
        # Format lines
        separator = "  " if self._layout_mode == 'horizontal' else "<br/>"
        
        if self._bold_labels:
            formatted_lines = []
            for line in lines:
                if '<' in line and '>' in line:  # Skip HTML-formatted lines
                    formatted_lines.append(line)
                else:
                    try:
                        key, val = line.split("=", 1)
                        formatted_lines.append(f"<b>{key}</b>={val}")
                    except Exception:
                        formatted_lines.append(line)
            lines = formatted_lines
        
        self._floater.label.setTextFormat(Qt.RichText)
        return separator.join(lines)

    def _get_depth_text(self, map_pt: QgsPointXY, elev: Optional[float]) -> Optional[str]:
        """Get depth text for display."""
        if self._have_upstream and self._upstream_bottom_elev is not None:
            # Normal depth calculation
            try:
                dist = CoordinateUtils.distance_m(
                    self._upstream_map_point, map_pt,
                    self._measure_crs, self._to_raster
                )
                downstream_candidate = self._upstream_bottom_elev - dist * max(0.0, self.slope_m_per_m)
                
                if elev is not None:
                    min_depth = self._depth_calculator.calculate_minimum_depth()
                    min_bottom = float(elev) - min_depth
                    downstream_bottom = min(downstream_candidate, min_bottom)
                    depth_val = float(elev) - downstream_bottom
                else:
                    depth_val = float('nan')
                
                # Format for inherited depth
                if dist < 0.01 and self._inherited_depth is not None:
                    return f"<b><i><font color=\"#aa0000\">depth={depth_val:.2f}</font></i></b>"
                else:
                    return f"depth={depth_val:.2f}"
            except Exception:
                pass
        else:
            # Before first click: show snap depth if available
            if self._current_snap_depth is not None:
                return f'<b><i><font color="#aa0000">depth={self._current_snap_depth:.2f}</font></i></b>'
        
        return None

    def _find_existing_depth_at_point(self, map_pt: QgsPointXY) -> Optional[float]:
        """Find existing depth at point using field mapper."""
        if not self._field_mapper or not self._current_layer:
            return None
            
        # Implementation using field mapper would go here
        # For now, return None to maintain compatibility
        return None

    def _passes_gate(self) -> bool:
        """Check if floater should be active."""
        if self._gate_layer_id is None:
            return False
            
        try:
            from qgis.gui import QgsMapToolDigitizeFeature
            
            layer = QgsProject.instance().mapLayer(self._gate_layer_id)
            if not layer:
                return False
                
            # Check active layer
            active = self.iface.activeLayer() if self.iface else None
            if not active or active.id() != layer.id():
                return False
                
            # Check editable
            if not layer.isEditable():
                return False
                
            # Check tool
            if self.canvas and self.canvas.mapTool():
                current_tool = self.canvas.mapTool()
                if not isinstance(current_tool, QgsMapToolDigitizeFeature):
                    return False
                    
            return True
        except Exception:
            return False

    # --- Placeholder methods for feature handling ---
    
    def _on_feature_added(self, fid):
        """Handle feature added event."""
        DebugLogger.log(f"Feature added: {fid}")
        # Implementation would use modular components
    
    def _on_features_deleted(self, fids):
        """Handle features deleted event."""
        DebugLogger.log(f"Features deleted: {list(fids)}")
        # Implementation would use modular components

    def eventFilter(self, obj, ev):
        """Handle canvas events."""
        if self.canvas and obj is self.canvas.viewport():
            if ev.type() == QtCore.QEvent.MouseButtonPress:
                btn = ev.button()
                if btn == QtCore.Qt.LeftButton:
                    # Handle left click for depth calculation
                    pos = ev.pos()
                    map_pt = self.canvas.getCoordinateTransform().toMapCoordinates(pos.x(), pos.y())
                    if self._passes_gate():
                        self._handle_left_click(map_pt)
                elif btn == QtCore.Qt.RightButton:
                    # Reset sequence
                    self._reset_sequence()
        
        return super().eventFilter(obj, ev)

    def _handle_left_click(self, map_pt: QgsPointXY):
        """Handle left click for depth calculation."""
        if not self._interpolator or not self._interpolator.is_valid():
            return
            
        try:
            lyr_pt = CoordinateUtils.transform_point(map_pt, self._to_raster)
            if not lyr_pt:
                return
                
            elev = self._interpolator.bilinear(lyr_pt)
            if elev is None:
                return
                
            current_time = time.time()
            
            if not self._have_upstream:
                # First click
                self._upstream_map_point = QgsPointXY(map_pt)
                self._upstream_ground_elev = float(elev)
                
                # Calculate initial depth
                initial_depth = self._depth_calculator.calculate_initial_depth(
                    self._upstream_ground_elev, self.initial_depth_m
                )
                
                self._upstream_bottom_elev = self._upstream_ground_elev - initial_depth
                self._have_upstream = True
                
                # Store click
                click_data = {
                    'map_point': QgsPointXY(map_pt),
                    'ground_elev': self._upstream_ground_elev,
                    'bottom_elev': self._upstream_bottom_elev,
                    'depth': initial_depth,
                    'timestamp': current_time
                }
                self._stored_clicks.append(click_data)
                
                DebugLogger.log(f"First click stored: depth={initial_depth:.2f}m")
            else:
                # Subsequent clicks
                if self._upstream_bottom_elev is None:
                    return
                    
                # Calculate downstream depth
                dist = CoordinateUtils.distance_m(
                    self._upstream_map_point, map_pt,
                    self._measure_crs, self._to_raster
                )
                
                upstream_depth, downstream_depth = self._depth_calculator.calculate_segment_depths(
                    self._upstream_ground_elev - self._upstream_bottom_elev,
                    self._upstream_ground_elev, float(elev), dist
                )
                
                # Store click
                click_data = {
                    'map_point': QgsPointXY(map_pt),
                    'ground_elev': float(elev),
                    'bottom_elev': float(elev) - downstream_depth,
                    'depth': downstream_depth,
                    'timestamp': current_time
                }
                self._stored_clicks.append(click_data)
                
                # Update for next segment
                self._upstream_map_point = QgsPointXY(map_pt)
                self._upstream_ground_elev = float(elev)
                self._upstream_bottom_elev = float(elev) - downstream_depth
                
                DebugLogger.log(f"Click {len(self._stored_clicks)} stored: depth={downstream_depth:.2f}m")
                
        except Exception as e:
            DebugLogger.log_error("Error handling left click", e)

    def _reset_sequence(self):
        """Reset click sequence."""
        self._have_upstream = False
        self._upstream_map_point = None
        self._upstream_ground_elev = None
        self._upstream_bottom_elev = None
        self._inherited_depth = None
        self._current_snap_depth = None
        DebugLogger.log("Click sequence reset")

    # --- Utility methods for backward compatibility ---
    
    def get_stored_clicks(self):
        """Get stored clicks for debugging."""
        return list(self._stored_clicks)
    
    def clear_stored_clicks(self):
        """Clear stored clicks."""
        self._stored_clicks = []
        DebugLogger.log("Stored clicks cleared")
    
    def force_clear_on_new_drawing(self):
        """Force clear on new drawing session."""
        if self._stored_clicks:
            DebugLogger.log(f"Force clearing {len(self._stored_clicks)} stored clicks")
            self._stored_clicks = []