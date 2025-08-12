# -*- coding: utf-8 -*-
"""
Integration example showing how to use the change management system 
with the existing plugin architecture.
"""

from typing import Optional
from qgis.core import QgsVectorLayer, QgsMapLayer
from .core.enhanced_change_management_system import EnhancedChangeManagementSystem
from .utils import DebugLogger


class ChangeManagerIntegration:
    """
    Integration layer for the enhanced change management system with the existing plugin.
    
    This class integrates the enhanced tree-based depth recalculation system
    with automatic change detection into the existing plugin.
    """
    
    def __init__(self):
        """Initialize change manager integration."""
        self.enhanced_change_manager: Optional[EnhancedChangeManagementSystem] = None
        self._current_vector_layer: Optional[QgsVectorLayer] = None
        self._current_dem_layer: Optional[QgsMapLayer] = None
    
    def initialize_change_management(self, vector_layer: QgsVectorLayer, 
                                   dem_layer: Optional[QgsMapLayer] = None) -> bool:
        """
        Initialize the change management system for given layers.
        
        Args:
            vector_layer: Sewerage network vector layer
            dem_layer: DEM raster layer (optional)
            
        Returns:
            True if initialization successful
        """
        try:
            # Stop existing change manager if active
            if self.enhanced_change_manager:
                self.stop_change_monitoring()
            
            # Create enhanced change manager
            DebugLogger.log("Initializing Enhanced Change Management System...")
            self.enhanced_change_manager = EnhancedChangeManagementSystem(vector_layer, dem_layer)
            
            # Validate network
            validation_results = self.enhanced_change_manager.validate_network()
            if validation_results.get('issues'):
                DebugLogger.log(f"Network validation issues: {len(validation_results['issues'])}")
                for issue in validation_results['issues']:
                    DebugLogger.log(f"  - {issue['type']}: {issue['description']}")
            
            DebugLogger.log("Enhanced change management system initialized successfully")
            
            self._current_vector_layer = vector_layer
            self._current_dem_layer = dem_layer
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to initialize change management", e)
            return False
    
    def start_change_monitoring(self) -> bool:
        """
        Start automatic change monitoring and recalculation.
        
        Returns:
            True if monitoring started successfully
        """
        if not self.enhanced_change_manager:
            DebugLogger.log_error("Enhanced change manager not initialized")
            return False
        
        try:
            success = self.enhanced_change_manager.start_monitoring()
            if success:
                DebugLogger.log("Enhanced automatic change monitoring started")
            return success
        except Exception as e:
            DebugLogger.log_error("Failed to start change monitoring", e)
            return False
    
    def stop_change_monitoring(self) -> bool:
        """
        Stop automatic change monitoring.
        
        Returns:
            True if monitoring stopped successfully
        """
        if not self.enhanced_change_manager:
            return True
        
        try:
            success = self.enhanced_change_manager.stop_monitoring()
            if success:
                DebugLogger.log("Enhanced change monitoring stopped")
            return success
        except Exception as e:
            DebugLogger.log_error("Failed to stop change monitoring", e)
            return False
    
    def update_dem_layer(self, new_dem_layer: QgsMapLayer) -> bool:
        """
        Update the DEM layer used for elevation interpolation.
        
        Args:
            new_dem_layer: New DEM raster layer
            
        Returns:
            True if update successful
        """
        if not self.enhanced_change_manager:
            return False
        
        try:
            success = self.enhanced_change_manager.update_dem_layer(new_dem_layer)
            
            if success:
                self._current_dem_layer = new_dem_layer
                DebugLogger.log("DEM layer updated successfully")
            return success
        except Exception as e:
            DebugLogger.log_error("Failed to update DEM layer", e)
            return False
    
    def update_calculation_parameters(self, min_cover_m: float, diameter_m: float, 
                                    slope_m_per_m: float) -> None:
        """
        Update depth calculation parameters.
        
        Args:
            min_cover_m: Minimum cover depth in meters
            diameter_m: Pipe diameter in meters
            slope_m_per_m: Pipe slope (dimensionless)
        """
        if self.enhanced_change_manager:
            # Convert diameter from mm to m if needed (assuming UI provides mm)
            diameter_in_m = diameter_m / 1000.0 if diameter_m > 1.0 else diameter_m
            
            self.enhanced_change_manager.update_depth_parameters(
                min_cover_m=min_cover_m,
                diameter_m=diameter_in_m,
                slope_m_per_m=slope_m_per_m
            )
            
            DebugLogger.log(f"Updated parameters: cover={min_cover_m}m, "
                          f"diameter={diameter_in_m}m, slope={slope_m_per_m}")
    
    def manual_recalculate_network(self, selected_only: bool = False) -> dict:
        """
        Manually trigger network recalculation.
        
        Args:
            selected_only: If True, only recalculate selected features
            
        Returns:
            Dictionary with recalculation statistics
        """
        if not self.enhanced_change_manager:
            return {'error': 'Change manager not initialized'}
        
        try:
            feature_ids = None
            if selected_only and self._current_vector_layer:
                feature_ids = list(self._current_vector_layer.selectedFeatureIds())
                if not feature_ids:
                    return {'error': 'No features selected'}
            
            stats = self.enhanced_change_manager.force_full_recalculation(feature_ids)
            DebugLogger.log(f"Enhanced manual recalculation complete: {stats}")
            return stats
            
        except Exception as e:
            DebugLogger.log_error("Error in manual recalculation", e)
            return {'error': str(e)}
    
    def process_pending_changes(self) -> dict:
        """
        Manually process any pending geometry changes.
        
        Returns:
            Dictionary with processing statistics
        """
        if not self.enhanced_change_manager:
            return {'error': 'Change manager not initialized'}
        
        try:
            stats = self.enhanced_change_manager.manual_process_changes()
            DebugLogger.log(f"Processed pending changes: {stats}")
            return stats
        except Exception as e:
            DebugLogger.log_error("Error processing pending changes", e)
            return {'error': str(e)}
    
    def get_system_status(self) -> dict:
        """
        Get comprehensive system status and statistics.
        
        Returns:
            Dictionary with system status information
        """
        if not self.enhanced_change_manager:
            return {'initialized': False}
        
        try:
            stats = self.enhanced_change_manager.get_network_statistics()
            stats['initialized'] = True
            return stats
        except Exception as e:
            DebugLogger.log_error("Error getting system status", e)
            return {'initialized': True, 'error': str(e)}
    
    def set_auto_update_enabled(self, enabled: bool) -> None:
        """
        Enable or disable automatic updates on geometry changes.
        
        Args:
            enabled: True to enable auto-updates, False to disable
        """
        if self.enhanced_change_manager:
            self.enhanced_change_manager.set_auto_update_enabled(enabled)
            DebugLogger.log(f"Auto-update {'enabled' if enabled else 'disabled'}")
    
    def validate_network_integrity(self) -> dict:
        """
        Validate network connectivity and data integrity.
        
        Returns:
            Dictionary with validation results
        """
        if not self.enhanced_change_manager:
            return {'error': 'Change manager not initialized'}
        
        try:
            issues = self.enhanced_change_manager.validate_network()
            return {'issues': issues, 'valid': len(issues) == 0}
        except Exception as e:
            DebugLogger.log_error("Error validating network", e)
            return {'error': str(e)}
    
    def cleanup(self) -> None:
        """Clean up resources when plugin is unloaded."""
        try:
            if self.enhanced_change_manager:
                self.stop_change_monitoring()
                self.enhanced_change_manager = None
            
            self._current_vector_layer = None
            self._current_dem_layer = None
            
            DebugLogger.log("Change manager integration cleaned up")
            
        except Exception as e:
            DebugLogger.log_error("Error during cleanup", e)
    
    def is_monitoring_active(self) -> bool:
        """Check if change monitoring is currently active."""
        return (self.enhanced_change_manager is not None and 
                self.enhanced_change_manager.is_monitoring_active())
    
    def is_auto_update_enabled(self) -> bool:
        """Check if auto-update is enabled."""
        return (self.enhanced_change_manager is not None and 
                self.enhanced_change_manager.is_auto_update_enabled())


# Example usage for integration with dock widget
def integrate_with_dock_widget(dock_widget, vector_layer, dem_layer):
    """
    Example of how to integrate the enhanced change management system with the dock widget.
    
    Args:
        dock_widget: The sewerage depth estimator dock widget
        vector_layer: Current sewerage network layer
        dem_layer: Current DEM layer
    """
    # Create integration instance
    change_integration = ChangeManagerIntegration()
    
    # Initialize with current layers
    if change_integration.initialize_change_management(vector_layer, dem_layer):
        
        # Start monitoring if auto-mode is enabled
        if hasattr(dock_widget, 'chkAutoUpdateDepths') and dock_widget.chkAutoUpdateDepths.isChecked():
            change_integration.start_change_monitoring()
        
        # Connect to parameter changes
        def on_params_changed():
            if hasattr(dock_widget, 'spnMinCover') and hasattr(dock_widget, 'spnDiameter') and hasattr(dock_widget, 'spnSlope'):
                change_integration.update_calculation_parameters(
                    min_cover_m=dock_widget.spnMinCover.value(),
                    diameter_m=dock_widget.spnDiameter.value(),
                    slope_m_per_m=dock_widget.spnSlope.value()
                )
        
        # Connect parameter change signals
        if hasattr(dock_widget, 'spnMinCover'):
            dock_widget.spnMinCover.valueChanged.connect(on_params_changed)
        if hasattr(dock_widget, 'spnDiameter'):
            dock_widget.spnDiameter.valueChanged.connect(on_params_changed)
        if hasattr(dock_widget, 'spnSlope'):
            dock_widget.spnSlope.valueChanged.connect(on_params_changed)
        
        # Connect layer change signals
        def on_dem_layer_changed():
            if hasattr(dock_widget, '_current_dem_layer'):
                dem = dock_widget._current_dem_layer()
                if dem:
                    change_integration.update_dem_layer(dem)
        
        if hasattr(dock_widget, 'cmbDemLayer'):
            dock_widget.cmbDemLayer.currentIndexChanged.connect(on_dem_layer_changed)
        
        # Store integration instance in dock widget for later use
        dock_widget._change_integration = change_integration
        
        DebugLogger.log("Enhanced change management system integrated with dock widget")
        
        return change_integration
    
    return None