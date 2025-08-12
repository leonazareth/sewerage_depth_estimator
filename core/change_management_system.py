# -*- coding: utf-8 -*-
"""
Integrated change management system that coordinates geometry detection, 
elevation updates, and depth recalculation.
"""

from typing import Optional, Dict, List
from qgis.core import QgsVectorLayer, QgsMapLayer
from ..utils import DebugLogger
from ..data import FieldMapper, RasterInterpolator
from .geometry_change_detector import GeometryChangeDetector, VertexChange
from .elevation_updater import ElevationUpdater
from .network_connectivity import NetworkConnectivityAnalyzer
from .depth_calculator import DepthCalculator
from .depth_recalculator import DepthRecalculator


class ChangeManagementSystem:
    """
    Integrated system for managing geometry changes and their effects on elevation and depth.
    
    This system:
    1. Monitors geometry changes in real-time
    2. Updates elevations for moved vertices
    3. Recalculates depths for affected segments
    4. Cascades changes through the network
    """
    
    def __init__(self, vector_layer: QgsVectorLayer, dem_layer: Optional[QgsMapLayer] = None):
        """
        Initialize the change management system.
        
        Args:
            vector_layer: Sewerage network vector layer
            dem_layer: DEM raster layer for elevation interpolation
        """
        self.vector_layer = vector_layer
        self.dem_layer = dem_layer
        
        # Initialize modular components
        self.field_mapper = FieldMapper(vector_layer)
        self.depth_calculator = DepthCalculator()
        self.connectivity_analyzer = NetworkConnectivityAnalyzer(vector_layer, self.field_mapper)
        
        # Initialize optional components that require DEM
        self.elevation_updater: Optional[ElevationUpdater] = None
        if dem_layer:
            self.elevation_updater = ElevationUpdater(vector_layer, dem_layer, self.field_mapper)
        
        self.depth_recalculator = DepthRecalculator(
            vector_layer, self.field_mapper, self.depth_calculator, self.connectivity_analyzer
        )
        
        # Initialize change detector
        self.change_detector = GeometryChangeDetector(vector_layer)
        
        # State tracking
        self._monitoring_active = False
        self._auto_update_enabled = True
        
        # Statistics
        self._change_stats = {
            'vertices_moved': 0,
            'elevations_updated': 0,
            'depths_recalculated': 0,
            'cascade_updates': 0
        }
    
    def start_monitoring(self) -> bool:
        """
        Start monitoring geometry changes.
        
        Returns:
            True if monitoring started successfully
        """
        try:
            if self._monitoring_active:
                DebugLogger.log("Change monitoring already active")
                return True
            
            # Connect change detector to our handler
            self._connect_change_signals()
            
            # Start change detection
            self.change_detector.start_monitoring()
            
            # Build initial connectivity map
            self.connectivity_analyzer.build_connectivity_map()
            
            self._monitoring_active = True
            DebugLogger.log("Change management system monitoring started")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to start change monitoring", e)
            return False
    
    def stop_monitoring(self) -> bool:
        """
        Stop monitoring geometry changes.
        
        Returns:
            True if monitoring stopped successfully
        """
        try:
            if not self._monitoring_active:
                return True
            
            # Stop change detection
            self.change_detector.stop_monitoring()
            
            # Disconnect signals
            self._disconnect_change_signals()
            
            self._monitoring_active = False
            DebugLogger.log("Change management system monitoring stopped")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to stop change monitoring", e)
            return False
    
    def _connect_change_signals(self) -> None:
        """Connect to geometry change signals."""
        # Override the change detector's handler to use our integrated approach
        self.change_detector._handle_vertex_changes = self._handle_integrated_vertex_changes
    
    def _disconnect_change_signals(self) -> None:
        """Disconnect from geometry change signals."""
        # Restore original handler
        self.change_detector._handle_vertex_changes = lambda feature, changes: None
    
    def _handle_integrated_vertex_changes(self, feature, vertex_changes: List[VertexChange]) -> None:
        """
        Handle vertex changes with integrated elevation and depth updates.
        
        Args:
            feature: The feature that changed
            vertex_changes: List of vertex changes detected
        """
        try:
            if not self._auto_update_enabled:
                DebugLogger.log("Auto-update disabled, skipping integrated processing")
                return
            
            DebugLogger.log(f"Processing {len(vertex_changes)} vertex changes for feature {feature.id()}")
            
            # Step 1: Update elevations for moved vertices
            updated_elevations = {}
            if self.elevation_updater and self.elevation_updater.is_interpolation_available():
                updated_elevations = self.elevation_updater.update_vertex_elevations(vertex_changes)
                if updated_elevations:
                    self._change_stats['elevations_updated'] += sum(len(elev_dict) for elev_dict in updated_elevations.values())
            else:
                DebugLogger.log("Elevation interpolation not available, skipping elevation updates")
            
            # Step 2: Recalculate depths for affected segments
            recalculated = self.depth_recalculator.recalculate_depths_for_changes(vertex_changes, updated_elevations)
            
            # Update statistics
            self._change_stats['vertices_moved'] += len(vertex_changes)
            self._change_stats['depths_recalculated'] += len(recalculated.get('directly_recalculated', []))
            self._change_stats['cascade_updates'] += len(recalculated.get('cascade_recalculated', []))
            
            DebugLogger.log(f"Change processing complete: "
                          f"{len(updated_elevations)} features elevation updates, "
                          f"{len(recalculated.get('directly_recalculated', []))} direct depth updates, "
                          f"{len(recalculated.get('cascade_recalculated', []))} cascade updates")
            
        except Exception as e:
            DebugLogger.log_error("Error in integrated vertex change handling", e)
    
    def manual_process_changes(self) -> Dict[str, int]:
        """
        Manually detect and process all geometry changes.
        
        Returns:
            Dictionary with processing statistics
        """
        try:
            DebugLogger.log("Starting manual change processing")
            
            # Detect all changes since last check
            all_changes = self.change_detector.detect_changes_manually()
            
            if not all_changes:
                DebugLogger.log("No geometry changes detected")
                return {'vertices_moved': 0, 'features_processed': 0}
            
            # Process changes for each feature
            total_vertex_changes = []
            for feature_id, vertex_changes in all_changes.items():
                feature = self.vector_layer.getFeature(feature_id)
                if feature.isValid():
                    self._handle_integrated_vertex_changes(feature, vertex_changes)
                    total_vertex_changes.extend(vertex_changes)
            
            return {
                'vertices_moved': len(total_vertex_changes),
                'features_processed': len(all_changes)
            }
            
        except Exception as e:
            DebugLogger.log_error("Error in manual change processing", e)
            return {'vertices_moved': 0, 'features_processed': 0}
    
    def update_dem_layer(self, new_dem_layer: QgsMapLayer, dem_band: int = 1) -> bool:
        """
        Update DEM layer for elevation interpolation.
        
        Args:
            new_dem_layer: New DEM raster layer
            dem_band: DEM band to use
            
        Returns:
            True if update successful
        """
        try:
            self.dem_layer = new_dem_layer
            
            if self.elevation_updater:
                return self.elevation_updater.update_dem_layer(new_dem_layer, dem_band)
            else:
                # Create elevation updater if it didn't exist
                self.elevation_updater = ElevationUpdater(
                    self.vector_layer, new_dem_layer, self.field_mapper, dem_band
                )
                return True
                
        except Exception as e:
            DebugLogger.log_error("Error updating DEM layer", e)
            return False
    
    def update_depth_parameters(self, min_cover_m: Optional[float] = None,
                              diameter_m: Optional[float] = None,
                              slope_m_per_m: Optional[float] = None) -> None:
        """Update depth calculation parameters."""
        self.depth_calculator.update_parameters(min_cover_m, diameter_m, slope_m_per_m)
        DebugLogger.log("Depth calculation parameters updated")
    
    def force_full_recalculation(self, feature_ids: Optional[List[int]] = None) -> Dict[str, int]:
        """
        Force full recalculation of elevations and depths.
        
        Args:
            feature_ids: List of feature IDs to process, or None for all
            
        Returns:
            Statistics dictionary
        """
        try:
            DebugLogger.log("Starting force full recalculation")
            stats = {'elevations_updated': 0, 'depths_recalculated': 0, 'failed': 0}
            
            # Update missing elevations
            if self.elevation_updater and self.elevation_updater.is_interpolation_available():
                elevation_updates = self.elevation_updater.batch_update_missing_elevations(feature_ids)
                stats['elevations_updated'] = sum(len(elev_dict) for elev_dict in elevation_updates.values())
            
            # Force depth recalculation
            depth_stats = self.depth_recalculator.force_recalculate_network(feature_ids)
            stats.update(depth_stats)
            
            DebugLogger.log(f"Force recalculation complete: {stats}")
            return stats
            
        except Exception as e:
            DebugLogger.log_error("Error in force full recalculation", e)
            return {'elevations_updated': 0, 'depths_recalculated': 0, 'failed': 1}
    
    def set_auto_update_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic updates on geometry changes."""
        self._auto_update_enabled = enabled
        DebugLogger.log(f"Auto-update {'enabled' if enabled else 'disabled'}")
    
    def get_network_statistics(self) -> Dict[str, any]:
        """Get comprehensive network and change statistics."""
        try:
            # Get connectivity statistics
            connectivity_stats = self.connectivity_analyzer.get_network_statistics()
            
            # Get field mapping status
            field_status = {
                'has_required_fields': self.field_mapper.has_required_fields(),
                'missing_fields': self.field_mapper.get_missing_fields()
            }
            
            # Get system status
            system_status = {
                'monitoring_active': self._monitoring_active,
                'auto_update_enabled': self._auto_update_enabled,
                'elevation_interpolation_available': (
                    self.elevation_updater is not None and 
                    self.elevation_updater.is_interpolation_available()
                )
            }
            
            return {
                'connectivity': connectivity_stats,
                'fields': field_status,
                'system': system_status,
                'change_stats': self._change_stats.copy()
            }
            
        except Exception as e:
            DebugLogger.log_error("Error getting network statistics", e)
            return {}
    
    def validate_network(self) -> Dict[str, List[str]]:
        """Validate network connectivity and data integrity."""
        try:
            # Rebuild connectivity map
            self.connectivity_analyzer.build_connectivity_map()
            
            # Validate connectivity
            connectivity_issues = self.connectivity_analyzer.validate_network_connectivity()
            
            # Validate field requirements
            field_issues = []
            if not self.field_mapper.has_required_fields():
                missing = self.field_mapper.get_missing_fields()
                field_issues.append(f"Missing required fields: {', '.join(missing)}")
            
            # Combine all issues
            all_issues = connectivity_issues.copy()
            if field_issues:
                all_issues['field_issues'] = field_issues
            
            return all_issues
            
        except Exception as e:
            DebugLogger.log_error("Error validating network", e)
            return {'validation_errors': [str(e)]}
    
    def create_missing_fields(self) -> bool:
        """Create missing required fields in the layer."""
        try:
            return self.field_mapper.create_missing_fields()
        except Exception as e:
            DebugLogger.log_error("Error creating missing fields", e)
            return False
    
    def reset_change_statistics(self) -> None:
        """Reset change tracking statistics."""
        self._change_stats = {
            'vertices_moved': 0,
            'elevations_updated': 0,
            'depths_recalculated': 0,
            'cascade_updates': 0
        }
        DebugLogger.log("Change statistics reset")
    
    def is_monitoring_active(self) -> bool:
        """Check if change monitoring is active."""
        return self._monitoring_active
    
    def is_auto_update_enabled(self) -> bool:
        """Check if auto-update is enabled."""
        return self._auto_update_enabled