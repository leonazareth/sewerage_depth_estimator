# -*- coding: utf-8 -*-
"""
Depth recalculator with smart cascade logic.

This module implements the smart cascade algorithm for depth recalculation:
1. Uses tree-based network analysis
2. Only recalculates when depths would increase
3. Handles convergent vertices with maximum depth rule
4. Processes in proper upstream→downstream order
5. Stops cascade when no significant depth increase occurs
"""

from typing import List, Dict, Set, Optional, Tuple
from qgis.core import QgsVectorLayer
from ..utils import DebugLogger
from ..data import FieldMapper
from .depth_calculator import DepthCalculator
from .network_tree_mapper import NetworkTreeMapper
from .geometry_change_detector import VertexChange


class SmartCascadeResult:
    """Result of smart cascade depth recalculation."""
    
    def __init__(self):
        self.recalculated_segments: List[int] = []
        self.cascade_stopped_segments: List[int] = []
        self.convergent_updates: List[int] = []
        self.no_change_segments: List[int] = []
        self.elevation_updates: Dict[int, Dict[str, float]] = {}
        self.depth_updates: Dict[int, Dict[str, float]] = {}
        self.processing_stats: Dict[str, int] = {}
    
    def get_summary(self) -> Dict[str, int]:
        """Get summary statistics of the recalculation."""
        return {
            'total_recalculated': len(self.recalculated_segments),
            'cascade_stopped': len(self.cascade_stopped_segments),
            'convergent_updates': len(self.convergent_updates),
            'no_change_needed': len(self.no_change_segments),
            'elevation_updates': len(self.elevation_updates),
            'depth_updates': len(self.depth_updates)
        }


class DepthRecalculator:
    """
    Depth recalculator with smart cascade logic.
    
    This class implements the comprehensive tree-based algorithm for depth recalculation:
    - Analyzes complete network topology
    - Handles all types of vertex movements (upstream/downstream)
    - Implements smart cascade that stops when depths don't increase significantly
    - Respects convergent vertex maximum depth rule
    - Processes changes in proper network order
    """
    
    def __init__(self, layer: QgsVectorLayer, field_mapper: FieldMapper, 
                 depth_calculator: DepthCalculator, tolerance: float = 1e-6):
        """
        Initialize enhanced depth recalculator.
        
        Args:
            layer: Vector layer containing network segments
            field_mapper: Field mapping utility
            depth_calculator: Depth calculation utility
            tolerance: Coordinate tolerance for analysis
        """
        self.layer = layer
        self.field_mapper = field_mapper
        self.depth_calculator = depth_calculator
        self.tolerance = tolerance
        
        # Network tree mapper for topology analysis
        self.tree_mapper = NetworkTreeMapper(layer, field_mapper, tolerance)
        
        # Processing parameters
        self.depth_increase_threshold = 0.01  # 1cm threshold for cascade decisions
        self.minimum_depth_buffer = 0.05  # 5cm buffer for minimum depth calculations
        
        # Statistics tracking
        self.processing_stats = {
            'total_processed': 0,
            'cascade_stops': 0,
            'convergent_updates': 0,
            'topology_rebuilds': 0
        }
    
    def recalculate_depths_for_vertex_changes(self, vertex_changes: List[VertexChange], 
                                            elevation_updates: Dict[int, Dict[str, float]]) -> SmartCascadeResult:
        """
        Recalculate depths for vertex changes using smart cascade algorithm.
        
        Args:
            vertex_changes: List of vertex coordinate changes
            elevation_updates: Dictionary of updated elevation values
            
        Returns:
            SmartCascadeResult with comprehensive recalculation results
        """
        result = SmartCascadeResult()
        
        try:
            DebugLogger.log("=== Starting Enhanced Depth Recalculation ===")
            DebugLogger.log(f"Processing {len(vertex_changes)} vertex changes")
            
            # Phase 1: Comprehensive Impact Analysis
            DebugLogger.log("Phase 1: Analyzing comprehensive vertex movement impacts...")
            impacts = self.tree_mapper.analyze_vertex_movement_impacts_comprehensive(vertex_changes)
            
            if not impacts.get('processing_order'):
                DebugLogger.log("No segments to process")
                return result
            
            DebugLogger.log(f"Impact analysis complete: {len(impacts['processing_order'])} segments to process")
            
            # Phase 2: Update Elevations in Tree Order
            DebugLogger.log("Phase 2: Updating elevations in tree order...")
            comprehensive_elevation_updates = self._update_elevations_tree_order(
                impacts, vertex_changes, elevation_updates
            )
            result.elevation_updates = comprehensive_elevation_updates
            
            # Phase 3: Smart Cascade Depth Recalculation
            DebugLogger.log("Phase 3: Executing smart cascade depth recalculation...")
            cascade_result = self.tree_mapper.execute_smart_cascade_recalculation(
                impacts, self.depth_calculator, comprehensive_elevation_updates
            )
            
            # Phase 4: Post-process Results
            DebugLogger.log("Phase 4: Post-processing results...")
            self._post_process_cascade_results(cascade_result, result)
            
            # Update statistics
            self.processing_stats['total_processed'] += len(result.recalculated_segments)
            self.processing_stats['cascade_stops'] += len(result.cascade_stopped_segments)
            self.processing_stats['convergent_updates'] += len(result.convergent_updates)
            result.processing_stats = self.processing_stats.copy()
            
            summary = result.get_summary()
            DebugLogger.log(f"=== Enhanced Depth Recalculation Complete ===")
            DebugLogger.log(f"Summary: {summary}")
            
        except Exception as e:
            DebugLogger.log_error("Error in enhanced depth recalculation", e)
        
        return result
    
    def validate_network_and_recalculate_all(self, selected_only: bool = False) -> SmartCascadeResult:
        """
        Validate network integrity and recalculate all depths using smart cascade.
        
        Args:
            selected_only: If True, only process selected features
            
        Returns:
            SmartCascadeResult with validation and recalculation results
        """
        result = SmartCascadeResult()
        
        try:
            DebugLogger.log("=== Starting Full Network Validation and Recalculation ===")
            
            # Get features to process
            features_to_process = []
            if selected_only:
                features_to_process = list(self.layer.selectedFeatures())
                DebugLogger.log(f"Processing {len(features_to_process)} selected features")
            else:
                features_to_process = list(self.layer.getFeatures())
                DebugLogger.log(f"Processing all {len(features_to_process)} features")
            
            if not features_to_process:
                DebugLogger.log("No features to process")
                return result
            
            # Build network topology
            DebugLogger.log("Building complete network topology...")
            topology_snapshot = self.tree_mapper.capture_topology_snapshot()
            
            # Create comprehensive impact analysis for all features
            all_feature_ids = [f.id() for f in features_to_process]
            impacts = {
                'processing_order': self._get_network_processing_order(all_feature_ids),
                'convergent_nodes': self._get_all_convergent_nodes(),
                'elevation_updates_needed': all_feature_ids,
                'directly_moved': [],  # No moves in full recalculation
                'downstream_cascade': all_feature_ids
            }
            
            DebugLogger.log(f"Network analysis complete: {len(impacts['processing_order'])} segments in processing order")
            
            # Validate and update all elevations
            DebugLogger.log("Validating and updating elevations...")
            elevation_updates = self._validate_and_update_all_elevations(all_feature_ids)
            result.elevation_updates = elevation_updates
            
            # Execute full network recalculation with smart cascade
            DebugLogger.log("Executing full network recalculation...")
            cascade_result = self.tree_mapper.execute_smart_cascade_recalculation(
                impacts, self.depth_calculator, elevation_updates
            )
            
            # Post-process results
            self._post_process_cascade_results(cascade_result, result)
            
            summary = result.get_summary()
            DebugLogger.log(f"=== Full Network Recalculation Complete ===")
            DebugLogger.log(f"Summary: {summary}")
            
        except Exception as e:
            DebugLogger.log_error("Error in full network recalculation", e)
        
        return result
    
    def recalculate_affected_by_parameter_change(self, changed_parameters: Dict[str, float]) -> SmartCascadeResult:
        """
        Recalculate depths affected by parameter changes (slope, diameter, min cover).
        
        Args:
            changed_parameters: Dictionary of changed parameters
            
        Returns:
            SmartCascadeResult with parameter-based recalculation results
        """
        result = SmartCascadeResult()
        
        try:
            DebugLogger.log("=== Starting Parameter-Based Recalculation ===")
            DebugLogger.log(f"Changed parameters: {changed_parameters}")
            
            # For parameter changes, we need to recalculate the entire network
            # because any segment depth could be affected
            full_result = self.validate_network_and_recalculate_all(selected_only=False)
            
            # Update depth calculator parameters first
            self._update_depth_calculator_parameters(changed_parameters)
            
            DebugLogger.log("=== Parameter-Based Recalculation Complete ===")
            return full_result
            
        except Exception as e:
            DebugLogger.log_error("Error in parameter-based recalculation", e)
        
        return result
    
    def _update_elevations_tree_order(self, impacts: Dict[str, List[int]], 
                                    vertex_changes: List[VertexChange],
                                    elevation_updates: Dict[int, Dict[str, float]]) -> Dict[int, Dict[str, float]]:
        """Update elevations in proper tree order."""
        comprehensive_updates = elevation_updates.copy()
        
        try:
            # Process elevation updates for moved vertices
            for change in vertex_changes:
                feature_id = change.feature_id
                vertex_type = change.vertex_type
                
                # Get feature to interpolate elevation
                feature = self.layer.getFeature(feature_id)
                if not feature.isValid():
                    continue
                
                # Interpolate elevation at new position
                new_elevation = self._interpolate_elevation_at_point(change.new_coord)
                if new_elevation is not None:
                    if feature_id not in comprehensive_updates:
                        comprehensive_updates[feature_id] = {}
                    comprehensive_updates[feature_id][f'{vertex_type}_elev'] = new_elevation
                    
                    DebugLogger.log(f"Updated {vertex_type} elevation for feature {feature_id}: {new_elevation:.2f}m")
            
            # Validate elevations for all affected segments
            processing_order = impacts.get('processing_order', [])
            for feature_id in processing_order:
                if feature_id not in comprehensive_updates:
                    # Check if elevations need interpolation
                    missing_elevations = self._check_missing_elevations(feature_id)
                    if missing_elevations:
                        comprehensive_updates[feature_id] = missing_elevations
            
            DebugLogger.log(f"Elevation updates complete: {len(comprehensive_updates)} features updated")
            
        except Exception as e:
            DebugLogger.log_error("Error updating elevations in tree order", e)
        
        return comprehensive_updates
    
    def _post_process_cascade_results(self, cascade_result: Dict[str, List[int]], 
                                    result: SmartCascadeResult) -> None:
        """Post-process cascade results into comprehensive result structure."""
        try:
            result.recalculated_segments = cascade_result.get('recalculated_segments', [])
            result.cascade_stopped_segments = cascade_result.get('cascade_stopped_at', [])
            result.convergent_updates = cascade_result.get('convergent_updates', [])
            result.no_change_segments = cascade_result.get('no_change_needed', [])
            
            # Extract depth updates from tree mapper
            depth_updates = {}
            for feature_id in result.recalculated_segments:
                segment = self.tree_mapper.segments.get(feature_id)
                if segment:
                    p1_depth = self.tree_mapper.updated_depths.get(segment.upstream_node_key)
                    p2_depth = self.tree_mapper.updated_depths.get(segment.downstream_node_key)
                    
                    if p1_depth is not None or p2_depth is not None:
                        depth_updates[feature_id] = {}
                        if p1_depth is not None:
                            depth_updates[feature_id]['p1_h'] = p1_depth
                        if p2_depth is not None:
                            depth_updates[feature_id]['p2_h'] = p2_depth
            
            result.depth_updates = depth_updates
            
        except Exception as e:
            DebugLogger.log_error("Error post-processing cascade results", e)
    
    def _get_network_processing_order(self, feature_ids: List[int]) -> List[int]:
        """Get network processing order for given feature IDs."""
        try:
            # Use tree mapper to get topological order
            return self.tree_mapper._topological_sort_segments(set(feature_ids))
        except Exception as e:
            DebugLogger.log_error("Error getting network processing order", e)
            return feature_ids
    
    def _get_all_convergent_nodes(self) -> List[str]:
        """Get all convergent nodes in the network."""
        convergent_nodes = []
        for node_key, node in self.tree_mapper.nodes.items():
            if node.is_convergent:
                convergent_nodes.append(node_key)
        return convergent_nodes
    
    def _validate_and_update_all_elevations(self, feature_ids: List[int]) -> Dict[int, Dict[str, float]]:
        """Validate and update elevations for all specified features."""
        elevation_updates = {}
        
        try:
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            
            for feature_id in feature_ids:
                feature = self.layer.getFeature(feature_id)
                if not feature.isValid():
                    continue
                
                # Check if elevations are missing or need updating
                p1_elev = feature.attribute(p1_elev_idx) if p1_elev_idx >= 0 else None
                p2_elev = feature.attribute(p2_elev_idx) if p2_elev_idx >= 0 else None
                
                updates = {}
                
                # Interpolate missing P1 elevation
                if p1_elev is None or p1_elev == '':
                    p1, _ = self.tree_mapper._extract_feature_endpoints(feature)
                    if p1:
                        new_p1_elev = self._interpolate_elevation_at_point(p1)
                        if new_p1_elev is not None:
                            updates['p1_elev'] = new_p1_elev
                
                # Interpolate missing P2 elevation
                if p2_elev is None or p2_elev == '':
                    _, p2 = self.tree_mapper._extract_feature_endpoints(feature)
                    if p2:
                        new_p2_elev = self._interpolate_elevation_at_point(p2)
                        if new_p2_elev is not None:
                            updates['p2_elev'] = new_p2_elev
                
                if updates:
                    elevation_updates[feature_id] = updates
                    DebugLogger.log(f"Validated elevations for feature {feature_id}: {updates}")
            
        except Exception as e:
            DebugLogger.log_error("Error validating elevations", e)
        
        return elevation_updates
    
    def _check_missing_elevations(self, feature_id: int) -> Dict[str, float]:
        """Check and interpolate missing elevations for a feature."""
        missing_elevations = {}
        
        try:
            feature = self.layer.getFeature(feature_id)
            if not feature.isValid():
                return missing_elevations
            
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            
            p1_elev = feature.attribute(p1_elev_idx) if p1_elev_idx >= 0 else None
            p2_elev = feature.attribute(p2_elev_idx) if p2_elev_idx >= 0 else None
            
            p1, p2 = self.tree_mapper._extract_feature_endpoints(feature)
            
            # Check P1 elevation
            if (p1_elev is None or p1_elev == '') and p1:
                new_elev = self._interpolate_elevation_at_point(p1)
                if new_elev is not None:
                    missing_elevations['p1_elev'] = new_elev
            
            # Check P2 elevation
            if (p2_elev is None or p2_elev == '') and p2:
                new_elev = self._interpolate_elevation_at_point(p2)
                if new_elev is not None:
                    missing_elevations['p2_elev'] = new_elev
            
        except Exception as e:
            DebugLogger.log_error(f"Error checking missing elevations for feature {feature_id}", e)
        
        return missing_elevations
    
    def _interpolate_elevation_at_point(self, point: 'QgsPointXY') -> Optional[float]:
        """Interpolate elevation at given point using DEM."""
        # This would use the elevation updater or raster interpolator
        # For now, return None to indicate no interpolation available
        # In the actual implementation, this would connect to the elevation updater
        return None
    
    def _update_depth_calculator_parameters(self, changed_parameters: Dict[str, float]) -> None:
        """Update depth calculator with new parameters."""
        try:
            for param_name, value in changed_parameters.items():
                if hasattr(self.depth_calculator, param_name):
                    setattr(self.depth_calculator, param_name, value)
                    DebugLogger.log(f"Updated depth calculator parameter {param_name} = {value}")
        except Exception as e:
            DebugLogger.log_error("Error updating depth calculator parameters", e)
    
    def get_processing_statistics(self) -> Dict[str, int]:
        """Get processing statistics for debugging and monitoring."""
        return self.processing_stats.copy()
    
    def reset_statistics(self) -> None:
        """Reset processing statistics."""
        self.processing_stats = {
            'total_processed': 0,
            'cascade_stops': 0,
            'convergent_updates': 0,
            'topology_rebuilds': 0
        }
    
    def set_cascade_threshold(self, threshold: float) -> None:
        """Set depth increase threshold for cascade decisions."""
        self.depth_increase_threshold = max(0.001, threshold)  # Minimum 1mm
        DebugLogger.log(f"Cascade threshold set to {self.depth_increase_threshold:.3f}m")
    
    def set_minimum_depth_buffer(self, buffer: float) -> None:
        """Set minimum depth buffer for calculations."""
        self.minimum_depth_buffer = max(0.0, buffer)
        DebugLogger.log(f"Minimum depth buffer set to {self.minimum_depth_buffer:.3f}m")
