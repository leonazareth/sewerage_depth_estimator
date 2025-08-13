# -*- coding: utf-8 -*-
"""
Elevation updater for automatically interpolating elevations at moved vertices.
"""

from typing import List, Optional, Dict
from qgis.core import QgsPointXY, QgsVectorLayer, QgsCoordinateTransform, QgsProject
from ..utils import DebugLogger, CoordinateUtils
from ..data import RasterInterpolator, FieldMapper
from .geometry_change_detector import VertexChange


class ElevationUpdater:
    """Handles automatic elevation updates for moved vertices."""
    
    def __init__(self, layer: QgsVectorLayer, dem_layer, field_mapper: FieldMapper, dem_band: int = 1):
        """
        Initialize elevation updater.
        
        Args:
            layer: Vector layer containing network segments
            dem_layer: DEM raster layer for elevation interpolation
            field_mapper: Field mapping utility
            dem_band: DEM band to use for interpolation
        """
        self.layer = layer
        self.dem_layer = dem_layer
        self.field_mapper = field_mapper
        self.dem_band = dem_band
        
        # Initialize interpolator and coordinate transform
        self._interpolator: Optional[RasterInterpolator] = None
        self._coord_transform: Optional[QgsCoordinateTransform] = None
        self._initialize_interpolation()
    
    def _initialize_interpolation(self) -> bool:
        """Initialize DEM interpolator and coordinate transform."""
        try:
            if not self.dem_layer:
                DebugLogger.log_error("No DEM layer provided for elevation updates")
                return False
            
            # Create interpolator
            self._interpolator = RasterInterpolator(self.dem_layer, band=self.dem_band)
            
            # Create coordinate transform
            transform_context = QgsProject.instance().transformContext()
            self._coord_transform = QgsCoordinateTransform(
                self.layer.crs(), 
                self.dem_layer.crs(), 
                transform_context
            )
            
            DebugLogger.log("Elevation interpolation initialized successfully")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to initialize elevation interpolation", e)
            self._interpolator = None
            self._coord_transform = None
            return False
    
    def update_dem_layer(self, new_dem_layer, dem_band: int = 1) -> bool:
        """Update DEM layer and reinitialize interpolation."""
        self.dem_layer = new_dem_layer
        self.dem_band = dem_band
        return self._initialize_interpolation()
    
    def interpolate_elevation_at_point(self, point: QgsPointXY) -> Optional[float]:
        """
        Interpolate elevation at given point using DEM.
        
        Args:
            point: Point coordinates in layer CRS
            
        Returns:
            Interpolated elevation or None if unavailable
        """
        if not self._interpolator or not self._coord_transform:
            DebugLogger.log_error("Interpolation not properly initialized")
            return None
        
        try:
            # Check if interpolator is still valid
            if not self._interpolator.is_valid():
                DebugLogger.log_error("DEM interpolator is no longer valid")
                return None
            
            # Transform point to DEM CRS
            dem_point = CoordinateUtils.transform_point(point, self._coord_transform)
            if not dem_point:
                DebugLogger.log_error(f"Failed to transform point {point.x():.6f}, {point.y():.6f}")
                return None
            
            # Interpolate elevation
            elevation = self._interpolator.bilinear(dem_point)
            if elevation is not None:
                DebugLogger.log(f"Interpolated elevation {elevation:.3f}m at ({point.x():.6f}, {point.y():.6f})")
                return float(elevation)
            else:
                DebugLogger.log(f"No elevation data at point ({point.x():.6f}, {point.y():.6f})")
                return None
                
        except Exception as e:
            DebugLogger.log_error(f"Error interpolating elevation at ({point.x():.6f}, {point.y():.6f})", e)
            return None
    
    def update_vertex_elevations(self, vertex_changes: List[VertexChange]) -> Dict[int, Dict[str, float]]:
        """
        Update elevations for moved vertices.
        
        Args:
            vertex_changes: List of vertex changes to process
            
        Returns:
            Dictionary mapping feature_id to vertex elevations that were updated
        """
        updated_elevations = {}
        
        if not self._interpolator or not self._coord_transform:
            DebugLogger.log_error("Cannot update elevations: interpolation not initialized")
            return updated_elevations
        
        # Ensure layer is editable
        if not self.layer.isEditable():
            self.layer.startEditing()
        
        field_mapping = self.field_mapper.get_field_mapping()
        p1_elev_idx = field_mapping.get('p1_elev', -1)
        p2_elev_idx = field_mapping.get('p2_elev', -1)
        
        for change in vertex_changes:
            try:
                DebugLogger.log(f"Updating elevation for feature {change.feature_id}, vertex {change.vertex_type}")
                
                # Interpolate new elevation
                new_elevation = self.interpolate_elevation_at_point(change.new_coord)
                if new_elevation is None:
                    DebugLogger.log(f"Skipping elevation update: no DEM data at new position")
                    continue
                
                # Determine field index to update
                field_idx = p1_elev_idx if change.vertex_type == 'p1' else p2_elev_idx
                if field_idx < 0:
                    DebugLogger.log_error(f"Field index not found for {change.vertex_type}_elev")
                    continue
                
                # Update attribute value
                rounded_elevation = round(new_elevation, 2)
                success = self.layer.changeAttributeValue(change.feature_id, field_idx, rounded_elevation)
                
                if success:
                    # Track successful update
                    if change.feature_id not in updated_elevations:
                        updated_elevations[change.feature_id] = {}
                    updated_elevations[change.feature_id][change.vertex_type] = rounded_elevation
                    
                    DebugLogger.log(f"Updated {change.vertex_type}_elev = {rounded_elevation:.2f}m for feature {change.feature_id}")
                else:
                    DebugLogger.log_error(f"Failed to update {change.vertex_type}_elev for feature {change.feature_id}")
                
            except Exception as e:
                DebugLogger.log_error(f"Error updating elevation for feature {change.feature_id}", e)
        
        if updated_elevations:
            DebugLogger.log(f"Successfully updated elevations for {len(updated_elevations)} features")
        
        return updated_elevations
    
    def update_single_vertex_elevation(self, feature_id: int, vertex_type: str, new_coord: QgsPointXY) -> Optional[float]:
        """
        Update elevation for a single vertex.
        
        Args:
            feature_id: Feature ID
            vertex_type: 'p1' or 'p2'
            new_coord: New vertex coordinates
            
        Returns:
            Updated elevation value or None if failed
        """
        try:
            # Create a vertex change object
            change = VertexChange(
                feature_id=feature_id,
                vertex_type=vertex_type,
                old_coord=new_coord,  # We don't need old coord for this operation
                new_coord=new_coord,
                distance_moved=0.0
            )
            
            # Update elevation
            updated = self.update_vertex_elevations([change])
            
            if feature_id in updated and vertex_type in updated[feature_id]:
                return updated[feature_id][vertex_type]
            
            return None
            
        except Exception as e:
            DebugLogger.log_error(f"Error updating single vertex elevation", e)
            return None
    
    def batch_update_missing_elevations(self, feature_ids: Optional[List[int]] = None) -> Dict[int, Dict[str, float]]:
        """
        Batch update missing elevations for features.
        
        Args:
            feature_ids: List of feature IDs to process, or None for all features
            
        Returns:
            Dictionary of updated elevations
        """
        updated_elevations = {}
        
        try:
            # Get features to process
            if feature_ids is not None:
                features = [self.layer.getFeature(fid) for fid in feature_ids]
                features = [f for f in features if f.isValid()]
            else:
                features = list(self.layer.getFeatures())
            
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            
            if p1_elev_idx < 0 or p2_elev_idx < 0:
                DebugLogger.log_error("Missing elevation field indices")
                return updated_elevations
            
            # Ensure layer is editable
            if not self.layer.isEditable():
                self.layer.startEditing()
            
            for feature in features:
                try:
                    # Extract endpoints
                    geom = feature.geometry()
                    if geom.isEmpty():
                        continue
                    
                    if geom.isMultipart():
                        lines = geom.asMultiPolyline()
                        if not lines or len(lines[0]) < 2:
                            continue
                        pts = lines[0]
                    else:
                        pts = geom.asPolyline()
                        if len(pts) < 2:
                            continue
                    
                    p1, p2 = QgsPointXY(pts[0]), QgsPointXY(pts[-1])
                    
                    # Check and update P1 elevation if missing
                    p1_elev = feature.attribute(p1_elev_idx)
                    if p1_elev is None or p1_elev == '':
                        new_elev = self.interpolate_elevation_at_point(p1)
                        if new_elev is not None:
                            rounded_elev = round(new_elev, 2)
                            success = self.layer.changeAttributeValue(feature.id(), p1_elev_idx, rounded_elev)
                            if success:
                                if feature.id() not in updated_elevations:
                                    updated_elevations[feature.id()] = {}
                                updated_elevations[feature.id()]['p1'] = rounded_elev
                                DebugLogger.log(f"Updated missing P1 elevation: {rounded_elev:.2f}m for feature {feature.id()}")
                    
                    # Check and update P2 elevation if missing
                    p2_elev = feature.attribute(p2_elev_idx)
                    if p2_elev is None or p2_elev == '':
                        new_elev = self.interpolate_elevation_at_point(p2)
                        if new_elev is not None:
                            rounded_elev = round(new_elev, 2)
                            success = self.layer.changeAttributeValue(feature.id(), p2_elev_idx, rounded_elev)
                            if success:
                                if feature.id() not in updated_elevations:
                                    updated_elevations[feature.id()] = {}
                                updated_elevations[feature.id()]['p2'] = rounded_elev
                                DebugLogger.log(f"Updated missing P2 elevation: {rounded_elev:.2f}m for feature {feature.id()}")
                
                except Exception as e:
                    DebugLogger.log_error(f"Error processing feature {feature.id()} for missing elevations", e)
            
            if updated_elevations:
                DebugLogger.log(f"Batch updated missing elevations for {len(updated_elevations)} features")
        
        except Exception as e:
            DebugLogger.log_error("Error in batch elevation update", e)
        
        return updated_elevations
    
    def is_interpolation_available(self) -> bool:
        """Check if elevation interpolation is available."""
        return (self._interpolator is not None and 
                self._coord_transform is not None and 
                self._interpolator.is_valid())