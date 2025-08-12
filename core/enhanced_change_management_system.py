# -*- coding: utf-8 -*-
"""
Enhanced change management system with tree-based smart cascade algorithm.

This module integrates the enhanced tree-based depth recalculation system
with the existing change management infrastructure, providing:
1. Comprehensive vertex movement handling (upstream and downstream)
2. Smart cascade logic that respects convergent vertex rules
3. Efficient processing that only recalculates when necessary
4. Full integration with elevation updates and network validation
"""

from typing import Dict, List, Optional
from qgis.core import QgsVectorLayer, QgsMapLayer
from ..utils import DebugLogger
from ..data import FieldMapper
from .geometry_change_detector import GeometryChangeDetector, VertexChange
from .elevation_updater import ElevationUpdater
from .depth_calculator import DepthCalculator
from .enhanced_depth_recalculator import EnhancedDepthRecalculator, SmartCascadeResult


class EnhancedChangeManagementSystem:
    """
    Enhanced change management system with smart cascade algorithm.
    
    This system provides comprehensive handling of all vertex movements:
    - Detects geometry changes in real-time
    - Updates elevations for moved vertices using DEM interpolation
    - Recalculates depths using tree-based smart cascade algorithm
    - Handles both upstream and downstream vertex movements correctly
    - Respects convergent vertex maximum depth rules
    - Only propagates changes when depths would increase significantly
    """
    
    def __init__(self, vector_layer: QgsVectorLayer, dem_layer: Optional[QgsMapLayer] = None):
        """
        Initialize enhanced change management system.
        
        Args:
            vector_layer: Sewerage network vector layer
            dem_layer: DEM raster layer for elevation interpolation
        """
        self.vector_layer = vector_layer
        self.dem_layer = dem_layer
        
        # Core components
        self.field_mapper = FieldMapper(vector_layer)
        self.geometry_detector = GeometryChangeDetector(vector_layer)
        self.elevation_updater = ElevationUpdater(vector_layer, dem_layer, self.field_mapper) if dem_layer else None
        self.depth_calculator = DepthCalculator()
        self.enhanced_recalculator = EnhancedDepthRecalculator(
            vector_layer, self.field_mapper, self.depth_calculator
        )
        
        # System state
        self._monitoring_active = False
        self._auto_update_enabled = True
        
        # Statistics and debugging
        self._change_stats = {
            'vertices_moved': 0,
            'elevations_updated': 0,
            'depths_recalculated': 0,
            'cascade_stops': 0,
            'convergent_updates': 0,
            'total_processing_time': 0.0
        }
        
        # Parameters
        self._depth_parameters = {
            'min_cover_m': 0.9,
            'diameter_m': 0.15,
            'slope_m_per_m': 0.005
        }
    
    def start_monitoring(self) -> bool:
        """
        Start automatic change monitoring with enhanced processing.
        
        Returns:
            True if monitoring started successfully
        """
        try:
            if self._monitoring_active:
                DebugLogger.log("Enhanced change monitoring already active")
                return True
            
            # Start geometry change detection
            self.geometry_detector.start_monitoring()
            
            # Connect to enhanced change handler
            self.geometry_detector._handle_vertex_changes = self._handle_enhanced_vertex_changes
            
            self._monitoring_active = True
            DebugLogger.log("Enhanced change monitoring started successfully")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to start enhanced change monitoring", e)
            return False
    
    def stop_monitoring(self) -> bool:
        """
        Stop automatic change monitoring.
        
        Returns:
            True if monitoring stopped successfully
        """
        try:
            if not self._monitoring_active:
                return True
            
            # Stop geometry change detection
            self.geometry_detector.stop_monitoring()
            
            # Disconnect change handler
            self.geometry_detector._handle_vertex_changes = lambda feature, changes: None
            
            self._monitoring_active = False
            DebugLogger.log("Enhanced change monitoring stopped")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to stop enhanced change monitoring", e)
            return False
    
    def update_depth_parameters(self, min_cover_m: float, diameter_m: float, slope_m_per_m: float) -> None:
        """
        Update depth calculation parameters.
        
        Args:
            min_cover_m: Minimum cover depth in meters
            diameter_m: Pipe diameter in meters
            slope_m_per_m: Pipe slope (dimensionless)
        """
        try:
            self._depth_parameters.update({
                'min_cover_m': min_cover_m,
                'diameter_m': diameter_m,
                'slope_m_per_m': slope_m_per_m
            })
            
            # Update depth calculator using correct method
            self.depth_calculator.update_parameters(
                min_cover_m=min_cover_m,
                diameter_m=diameter_m,
                slope_m_per_m=slope_m_per_m
            )
            
            DebugLogger.log(f"Updated depth parameters: cover={min_cover_m}m, "
                          f"diameter={diameter_m}m, slope={slope_m_per_m}")
            
            # Parameter changes should only affect new segments, not existing ones
            # Automatic recalculation disabled - parameters apply to future segments only
            DebugLogger.log("Parameter change complete - affects new segments only, no auto-recalculation")
                
        except Exception as e:
            DebugLogger.log_error("Error updating depth parameters", e)
    
    def update_dem_layer(self, new_dem_layer: QgsMapLayer) -> bool:
        """
        Update DEM layer for elevation interpolation.
        
        Args:
            new_dem_layer: New DEM raster layer
            
        Returns:
            True if update successful
        """
        try:
            self.dem_layer = new_dem_layer
            
            # Update elevation updater
            if self.elevation_updater:
                self.elevation_updater.update_dem_layer(new_dem_layer)
            else:
                self.elevation_updater = ElevationUpdater(self.vector_layer, new_dem_layer, self.field_mapper)
            
            DebugLogger.log("DEM layer updated successfully")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to update DEM layer", e)
            return False
    
    def force_full_recalculation(self, feature_ids: Optional[List[int]] = None) -> Dict:
        """
        Force full network recalculation using enhanced algorithm.
        
        Args:
            feature_ids: Optional list of feature IDs to limit recalculation
            
        Returns:
            Dictionary with recalculation statistics
        """
        try:
            DebugLogger.log("=== Starting Force Full Recalculation ===")
            
            # Use enhanced recalculator for full network validation and recalculation
            selected_only = feature_ids is not None
            if feature_ids:
                # Select specified features
                self.vector_layer.selectByIds(feature_ids)
            
            result = self.enhanced_recalculator.validate_network_and_recalculate_all(selected_only)
            summary = result.get_summary()
            
            # Update statistics
            self._change_stats['depths_recalculated'] += summary['total_recalculated']
            self._change_stats['cascade_stops'] += summary['cascade_stopped']
            self._change_stats['convergent_updates'] += summary['convergent_updates']
            
            DebugLogger.log(f"Force full recalculation complete: {summary}")
            return summary
            
        except Exception as e:
            DebugLogger.log_error("Error in force full recalculation", e)
            return {'error': str(e)}
    
    def manual_process_vertex_changes(self, vertex_changes: List[VertexChange]) -> Dict:
        """
        Manually process specific vertex changes.
        
        Args:
            vertex_changes: List of vertex changes to process
            
        Returns:
            Dictionary with processing statistics
        """
        try:
            DebugLogger.log(f"=== Manual Processing {len(vertex_changes)} Vertex Changes ===")
            
            # Process using enhanced algorithm
            result = self._process_vertex_changes_enhanced(vertex_changes)
            summary = result.get_summary()
            
            DebugLogger.log(f"Manual vertex change processing complete: {summary}")
            return summary
            
        except Exception as e:
            DebugLogger.log_error("Error in manual vertex change processing", e)
            return {'error': str(e)}
    
    def _handle_enhanced_vertex_changes(self, feature, vertex_changes: List[VertexChange]) -> None:
        """
        Handle vertex changes using enhanced tree-based algorithm.
        
        Args:
            feature: The feature that changed
            vertex_changes: List of vertex changes detected
        """
        try:
            if not self._auto_update_enabled:
                DebugLogger.log("Auto-update disabled, skipping enhanced processing")
                return
            
            DebugLogger.log(f"=== Enhanced Processing {len(vertex_changes)} Vertex Changes ===")
            
            # Process using enhanced algorithm
            result = self._process_vertex_changes_enhanced(vertex_changes)
            
            # Update statistics
            summary = result.get_summary()
            self._change_stats['vertices_moved'] += len(vertex_changes)
            self._change_stats['elevations_updated'] += summary['elevation_updates']
            self._change_stats['depths_recalculated'] += summary['total_recalculated']
            self._change_stats['cascade_stops'] += summary['cascade_stopped']
            self._change_stats['convergent_updates'] += summary['convergent_updates']
            
            DebugLogger.log(f"Enhanced vertex change processing complete: {summary}")
            
        except Exception as e:
            DebugLogger.log_error("Error in enhanced vertex change handling", e)
    
    def _process_vertex_changes_enhanced(self, vertex_changes: List[VertexChange]) -> SmartCascadeResult:
        """
        Process vertex changes using the enhanced tree-based algorithm.
        
        Args:
            vertex_changes: List of vertex changes to process
            
        Returns:
            SmartCascadeResult with comprehensive processing results
        """
        try:
            # Step 1: Update elevations for moved vertices
            elevation_updates = {}
            if self.elevation_updater and self.elevation_updater.is_interpolation_available():
                elevation_updates = self.elevation_updater.update_vertex_elevations(vertex_changes)
                DebugLogger.log(f"Elevation updates: {len(elevation_updates)} features updated")
            else:
                DebugLogger.log("Elevation interpolation not available")
            
            # Step 2: Process using enhanced depth recalculator
            result = self.enhanced_recalculator.recalculate_depths_for_vertex_changes(
                vertex_changes, elevation_updates
            )
            
            # Step 3: Apply elevation updates to layer if not already applied
            if elevation_updates:
                self._apply_elevation_updates_to_layer(elevation_updates)
            
            return result
            
        except Exception as e:
            DebugLogger.log_error("Error in enhanced vertex change processing", e)
            return SmartCascadeResult()
    
    def _handle_parameter_change(self) -> None:
        """Handle depth parameter changes by recalculating affected segments."""
        try:
            DebugLogger.log("Processing parameter change - recalculating network")
            
            # For parameter changes, we need to recalculate the entire network
            result = self.enhanced_recalculator.recalculate_affected_by_parameter_change(
                self._depth_parameters
            )
            
            summary = result.get_summary()
            DebugLogger.log(f"Parameter change processing complete: {summary}")
            
        except Exception as e:
            DebugLogger.log_error("Error handling parameter change", e)
    
    def _apply_elevation_updates_to_layer(self, elevation_updates: Dict[int, Dict[str, float]]) -> None:
        """Apply elevation updates to the vector layer."""
        try:
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            
            if not self.vector_layer.isEditable():
                self.vector_layer.startEditing()
            
            for feature_id, updates in elevation_updates.items():
                for field_name, value in updates.items():
                    if field_name == 'p1_elev' and p1_elev_idx >= 0:
                        self.vector_layer.changeAttributeValue(feature_id, p1_elev_idx, round(value, 2))
                    elif field_name == 'p2_elev' and p2_elev_idx >= 0:
                        self.vector_layer.changeAttributeValue(feature_id, p2_elev_idx, round(value, 2))
            
            DebugLogger.log(f"Applied elevation updates to layer: {len(elevation_updates)} features")
            
        except Exception as e:
            DebugLogger.log_error("Error applying elevation updates to layer", e)
    
    def validate_network(self) -> Dict:
        """
        Validate network integrity and identify issues.
        
        Returns:
            Dictionary with validation results
        """
        try:
            DebugLogger.log("=== Starting Network Validation ===")
            
            issues = []
            
            # Check field mapping
            field_mapping = self.field_mapper.get_field_mapping()
            required_fields = ['p1_elev', 'p2_elev', 'p1_h', 'p2_h']
            missing_fields = [field for field in required_fields if field_mapping.get(field, -1) < 0]
            
            if missing_fields:
                issues.append({
                    'type': 'missing_fields',
                    'description': f"Missing required fields: {missing_fields}",
                    'severity': 'error'
                })
            
            # Check for missing elevations
            missing_elevations = self._check_missing_elevations()
            if missing_elevations:
                issues.append({
                    'type': 'missing_elevations',
                    'description': f"Features with missing elevations: {len(missing_elevations)}",
                    'feature_ids': missing_elevations,
                    'severity': 'warning'
                })
            
            # Check for invalid geometries
            invalid_geometries = self._check_invalid_geometries()
            if invalid_geometries:
                issues.append({
                    'type': 'invalid_geometries',
                    'description': f"Features with invalid geometries: {len(invalid_geometries)}",
                    'feature_ids': invalid_geometries,
                    'severity': 'error'
                })
            
            DebugLogger.log(f"Network validation complete: {len(issues)} issues found")
            return {'issues': issues, 'valid': len(issues) == 0}
            
        except Exception as e:
            DebugLogger.log_error("Error in network validation", e)
            return {'error': str(e)}
    
    def _check_missing_elevations(self) -> List[int]:
        """Check for features with missing elevation values."""
        missing = []
        try:
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            
            for feature in self.vector_layer.getFeatures():
                p1_elev = feature.attribute(p1_elev_idx) if p1_elev_idx >= 0 else None
                p2_elev = feature.attribute(p2_elev_idx) if p2_elev_idx >= 0 else None
                
                if p1_elev is None or p1_elev == '' or p2_elev is None or p2_elev == '':
                    missing.append(feature.id())
        
        except Exception as e:
            DebugLogger.log_error("Error checking missing elevations", e)
        
        return missing
    
    def _check_invalid_geometries(self) -> List[int]:
        """Check for features with invalid geometries."""
        invalid = []
        try:
            for feature in self.vector_layer.getFeatures():
                geom = feature.geometry()
                if geom.isEmpty() or not geom.isGeosValid():
                    invalid.append(feature.id())
        
        except Exception as e:
            DebugLogger.log_error("Error checking invalid geometries", e)
        
        return invalid
    
    def get_network_statistics(self) -> Dict:
        """Get comprehensive network statistics."""
        try:
            stats = {
                'monitoring_active': self._monitoring_active,
                'auto_update_enabled': self._auto_update_enabled,
                'change_stats': self._change_stats.copy(),
                'depth_parameters': self._depth_parameters.copy(),
                'processing_stats': self.enhanced_recalculator.get_processing_statistics(),
                'has_dem_layer': self.dem_layer is not None,
                'elevation_interpolation_available': (
                    self.elevation_updater is not None and 
                    self.elevation_updater.is_interpolation_available()
                )
            }
            
            # Add network topology stats
            topology_snapshot = self.enhanced_recalculator.tree_mapper.capture_topology_snapshot()
            stats['network_topology'] = {
                'total_nodes': len(topology_snapshot.get('nodes', {})),
                'total_segments': len(topology_snapshot.get('segments', {})),
                'convergent_nodes': len([n for n in topology_snapshot.get('nodes', {}).values() if n.is_convergent])
            }
            
            return stats
            
        except Exception as e:
            DebugLogger.log_error("Error getting network statistics", e)
            return {'error': str(e)}
    
    def set_auto_update_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic updates."""
        self._auto_update_enabled = enabled
        DebugLogger.log(f"Auto-update {'enabled' if enabled else 'disabled'}")
    
    def is_monitoring_active(self) -> bool:
        """Check if change monitoring is active."""
        return self._monitoring_active
    
    def is_auto_update_enabled(self) -> bool:
        """Check if auto-update is enabled."""
        return self._auto_update_enabled
    
    def get_change_statistics(self) -> Dict:
        """Get change processing statistics."""
        return self._change_stats.copy()
    
    def reset_statistics(self) -> None:
        """Reset all statistics."""
        self._change_stats = {
            'vertices_moved': 0,
            'elevations_updated': 0,
            'depths_recalculated': 0,
            'cascade_stops': 0,
            'convergent_updates': 0,
            'total_processing_time': 0.0
        }
        self.enhanced_recalculator.reset_statistics()
        DebugLogger.log("Statistics reset")
    
    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            self.stop_monitoring()
            DebugLogger.log("Enhanced change management system cleaned up")
        except Exception as e:
            DebugLogger.log_error("Error during cleanup", e)
