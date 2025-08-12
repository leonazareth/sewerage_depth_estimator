# -*- coding: utf-8 -*-
"""
Geometry change detection system for monitoring vertex movements and segment modifications.
"""

from typing import Dict, Set, List, Tuple, Optional, NamedTuple
from qgis.core import QgsPointXY, QgsVectorLayer, QgsFeature, QgsGeometry, QgsWkbTypes
from ..utils import DebugLogger, CoordinateUtils


class VertexChange(NamedTuple):
    """Represents a vertex coordinate change."""
    feature_id: int
    vertex_type: str  # 'p1' or 'p2' 
    old_coord: QgsPointXY
    new_coord: QgsPointXY
    distance_moved: float


class GeometrySnapshot:
    """Stores geometry state for change detection."""
    
    def __init__(self, feature: QgsFeature):
        self.feature_id = feature.id()
        self.p1, self.p2 = self._extract_endpoints(feature)
        self.geometry_wkt = feature.geometry().asWkt() if not feature.geometry().isEmpty() else ""
    
    def _extract_endpoints(self, feature: QgsFeature) -> Tuple[Optional[QgsPointXY], Optional[QgsPointXY]]:
        """Extract P1 and P2 endpoints from feature geometry."""
        try:
            geom = feature.geometry()
            if geom.isEmpty():
                return None, None
                
            if geom.type() != QgsWkbTypes.LineGeometry:
                return None, None
                
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                if not lines or len(lines[0]) < 2:
                    return None, None
                pts = lines[0]
            else:
                pts = geom.asPolyline()
                if len(pts) < 2:
                    return None, None
            
            return QgsPointXY(pts[0]), QgsPointXY(pts[-1])
        except Exception as e:
            DebugLogger.log_error(f"Failed to extract endpoints from feature {feature.id()}", e)
            return None, None
    
    def has_changed(self, current_feature: QgsFeature, tolerance: float = 1e-6) -> bool:
        """Check if geometry has changed since snapshot."""
        current_wkt = current_feature.geometry().asWkt() if not current_feature.geometry().isEmpty() else ""
        return self.geometry_wkt != current_wkt
    
    def get_vertex_changes(self, current_feature: QgsFeature, tolerance: float = 1e-3) -> List[VertexChange]:
        """Get list of vertex changes between snapshot and current state."""
        changes = []
        
        current_p1, current_p2 = self._extract_endpoints(current_feature)
        
        if self.p1 and current_p1:
            distance = CoordinateUtils.point_distance_2d(self.p1, current_p1)
            if distance > tolerance:
                changes.append(VertexChange(
                    feature_id=self.feature_id,
                    vertex_type='p1',
                    old_coord=self.p1,
                    new_coord=current_p1,
                    distance_moved=distance
                ))
        
        if self.p2 and current_p2:
            distance = CoordinateUtils.point_distance_2d(self.p2, current_p2)
            if distance > tolerance:
                changes.append(VertexChange(
                    feature_id=self.feature_id,
                    vertex_type='p2', 
                    old_coord=self.p2,
                    new_coord=current_p2,
                    distance_moved=distance
                ))
        
        return changes


class GeometryChangeDetector:
    """Detects and tracks geometry changes in vector layers."""
    
    def __init__(self, layer: QgsVectorLayer, movement_tolerance: float = 1e-3):
        """
        Initialize geometry change detector.
        
        Args:
            layer: Vector layer to monitor
            movement_tolerance: Minimum distance to consider as movement (in map units)
        """
        self.layer = layer
        self.movement_tolerance = movement_tolerance
        self._snapshots: Dict[int, GeometrySnapshot] = {}
        self._monitoring = False
        
    def start_monitoring(self) -> None:
        """Start monitoring geometry changes."""
        if self._monitoring:
            return
            
        try:
            # Take initial snapshots
            self._take_initial_snapshots()
            
            # Connect to layer signals
            self.layer.geometryChanged.connect(self._on_geometry_changed)
            self.layer.attributeValueChanged.connect(self._on_attribute_changed) 
            self.layer.featureAdded.connect(self._on_feature_added)
            self.layer.featuresDeleted.connect(self._on_features_deleted)
            
            self._monitoring = True
            DebugLogger.log(f"Started monitoring geometry changes for layer: {self.layer.name()}")
            
        except Exception as e:
            DebugLogger.log_error("Failed to start geometry monitoring", e)
    
    def stop_monitoring(self) -> None:
        """Stop monitoring geometry changes."""
        if not self._monitoring:
            return
            
        try:
            # Disconnect signals
            self.layer.geometryChanged.disconnect(self._on_geometry_changed)
            self.layer.attributeValueChanged.disconnect(self._on_attribute_changed)
            self.layer.featureAdded.disconnect(self._on_feature_added)
            self.layer.featuresDeleted.disconnect(self._on_features_deleted)
            
            self._monitoring = False
            self._snapshots.clear()
            DebugLogger.log(f"Stopped monitoring geometry changes for layer: {self.layer.name()}")
            
        except Exception as e:
            DebugLogger.log_error("Failed to stop geometry monitoring", e)
    
    def _take_initial_snapshots(self) -> None:
        """Take initial geometry snapshots of all features."""
        try:
            self._snapshots.clear()
            features = list(self.layer.getFeatures())
            
            for feature in features:
                if not feature.geometry().isEmpty():
                    self._snapshots[feature.id()] = GeometrySnapshot(feature)
            
            DebugLogger.log(f"Captured {len(self._snapshots)} initial geometry snapshots")
            
        except Exception as e:
            DebugLogger.log_error("Failed to take initial snapshots", e)
    
    def _on_geometry_changed(self, feature_id: int, geometry: QgsGeometry) -> None:
        """Handle geometry change event."""
        try:
            DebugLogger.log(f"Geometry changed for feature {feature_id}")
            
            # Get current feature
            feature = self.layer.getFeature(feature_id)
            if not feature.isValid():
                return
            
            # Check if we have a snapshot to compare against
            if feature_id in self._snapshots:
                old_snapshot = self._snapshots[feature_id]
                vertex_changes = old_snapshot.get_vertex_changes(feature, self.movement_tolerance)
                
                if vertex_changes:
                    DebugLogger.log(f"Detected {len(vertex_changes)} vertex movements:")
                    for change in vertex_changes:
                        DebugLogger.log(f"  {change.vertex_type}: moved {change.distance_moved:.3f}m")
                    
                    # Emit vertex change signal
                    self._handle_vertex_changes(feature, vertex_changes)
            
            # Update snapshot
            self._snapshots[feature_id] = GeometrySnapshot(feature)
            
        except Exception as e:
            DebugLogger.log_error(f"Error handling geometry change for feature {feature_id}", e)
    
    def _on_attribute_changed(self, feature_id: int, field_idx: int, value) -> None:
        """Handle attribute change event."""
        # This could be used to monitor elevation field changes
        pass
    
    def _on_feature_added(self, feature_id: int) -> None:
        """Handle feature addition."""
        try:
            feature = self.layer.getFeature(feature_id)
            if feature.isValid() and not feature.geometry().isEmpty():
                self._snapshots[feature_id] = GeometrySnapshot(feature)
                DebugLogger.log(f"Added geometry snapshot for new feature {feature_id}")
        except Exception as e:
            DebugLogger.log_error(f"Error handling feature addition {feature_id}", e)
    
    def _on_features_deleted(self, feature_ids: List[int]) -> None:
        """Handle feature deletion."""
        for feature_id in feature_ids:
            if feature_id in self._snapshots:
                del self._snapshots[feature_id]
                DebugLogger.log(f"Removed geometry snapshot for deleted feature {feature_id}")
    
    def _handle_vertex_changes(self, feature: QgsFeature, vertex_changes: List[VertexChange]) -> None:
        """Handle detected vertex changes."""
        # This will be connected to the elevation updater and depth recalculator
        # For now, just log the changes
        for change in vertex_changes:
            DebugLogger.log(f"Vertex change detected: Feature {change.feature_id}, "
                          f"{change.vertex_type} moved {change.distance_moved:.3f}m")
    
    def get_current_snapshot(self, feature_id: int) -> Optional[GeometrySnapshot]:
        """Get current geometry snapshot for feature."""
        return self._snapshots.get(feature_id)
    
    def force_snapshot_update(self, feature_id: int) -> bool:
        """Force update snapshot for specific feature."""
        try:
            feature = self.layer.getFeature(feature_id)
            if feature.isValid():
                self._snapshots[feature_id] = GeometrySnapshot(feature)
                DebugLogger.log(f"Force updated snapshot for feature {feature_id}")
                return True
        except Exception as e:
            DebugLogger.log_error(f"Failed to force update snapshot for feature {feature_id}", e)
        return False
    
    def detect_changes_manually(self) -> Dict[int, List[VertexChange]]:
        """Manually detect all geometry changes since last snapshot."""
        all_changes = {}
        
        try:
            features = list(self.layer.getFeatures())
            
            for feature in features:
                if feature.id() in self._snapshots:
                    old_snapshot = self._snapshots[feature.id()]
                    vertex_changes = old_snapshot.get_vertex_changes(feature, self.movement_tolerance)
                    
                    if vertex_changes:
                        all_changes[feature.id()] = vertex_changes
                        # Update snapshot
                        self._snapshots[feature.id()] = GeometrySnapshot(feature)
            
            if all_changes:
                DebugLogger.log(f"Manual detection found changes in {len(all_changes)} features")
            
        except Exception as e:
            DebugLogger.log_error("Error in manual change detection", e)
        
        return all_changes
    
    def is_monitoring(self) -> bool:
        """Check if currently monitoring changes."""
        return self._monitoring