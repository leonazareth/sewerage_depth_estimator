# -*- coding: utf-8 -*-
"""
Cascading depth recalculation system for sewerage networks.
"""

from typing import List, Dict, Set, Optional, Tuple
from qgis.core import QgsPointXY, QgsVectorLayer
from ..utils import DebugLogger, CoordinateUtils
from ..data import FieldMapper
from .depth_calculator import DepthCalculator
from .network_connectivity import NetworkConnectivityAnalyzer, NetworkConnection
from .advanced_connectivity_analyzer import AdvancedConnectivityAnalyzer
from .geometry_change_detector import VertexChange


class DepthRecalculator:
    """Handles cascading depth recalculation when vertices are moved."""
    
    def __init__(self, layer: QgsVectorLayer, field_mapper: FieldMapper, 
                 depth_calculator: DepthCalculator, connectivity_analyzer: NetworkConnectivityAnalyzer):
        """
        Initialize depth recalculator.
        
        Args:
            layer: Vector layer containing network segments
            field_mapper: Field mapping utility
            depth_calculator: Depth calculation utility
            connectivity_analyzer: Network connectivity analyzer
        """
        self.layer = layer
        self.field_mapper = field_mapper
        self.depth_calculator = depth_calculator
        self.connectivity_analyzer = connectivity_analyzer
        self.advanced_analyzer = AdvancedConnectivityAnalyzer(layer, field_mapper)
    
    def recalculate_depths_for_changes(self, vertex_changes: List[VertexChange], 
                                     updated_elevations: Dict[int, Dict[str, float]]) -> Dict[str, List[int]]:
        """
        Recalculate depths for vertex changes and cascade downstream.
        
        Args:
            vertex_changes: List of vertex coordinate changes
            updated_elevations: Dictionary of updated elevation values
            
        Returns:
            Dictionary with lists of feature IDs that were recalculated
        """
        recalculated_features = {
            'directly_recalculated': [],
            'cascade_recalculated': []
        }
        
        try:
            DebugLogger.log("Starting comprehensive vertex change analysis...")
            
            # Get comprehensive impact analysis
            impact_analysis = self.advanced_analyzer.analyze_vertex_movement_impacts(vertex_changes)
            
            # Get all affected features with special categorization
            all_affected_features = []
            orphaned_features = []
            orphaned_upstream_features = []
            convergent_affected_features = []
            
            for category, features in impact_analysis.items():
                if category == 'orphaned_downstream_chains':
                    orphaned_features.extend(features)
                elif category == 'orphaned_upstream_features':
                    orphaned_upstream_features.extend(features)
                elif category == 'convergent_affected_chains':
                    convergent_affected_features.extend(features)
                all_affected_features.extend(features)
            
            # Remove duplicates
            all_affected_features = list(set(all_affected_features))
            orphaned_features = list(set(orphaned_features))
            orphaned_upstream_features = list(set(orphaned_upstream_features))
            convergent_affected_features = list(set(convergent_affected_features))
            
            if not all_affected_features:
                DebugLogger.log("No affected features found")
                return recalculated_features
            
            DebugLogger.log(f"Found {len(orphaned_features)} orphaned downstream features, "
                          f"{len(orphaned_upstream_features)} orphaned upstream features, "
                          f"{len(convergent_affected_features)} convergent affected features")
            
            # Get proper recalculation order (upstream to downstream)
            ordered_features = self.advanced_analyzer.get_recalculation_order(all_affected_features)
            
            DebugLogger.log(f"Recalculating depths for {len(ordered_features)} features in network order")
            
            # Recalculate all affected features with enhanced special handling
            self._recalculate_segments_depths_enhanced(
                ordered_features, updated_elevations, 
                orphaned_features, orphaned_upstream_features, convergent_affected_features
            )
            
            # Set results
            recalculated_features['directly_recalculated'] = [change.feature_id for change in vertex_changes]
            cascade_features = [fid for fid in ordered_features 
                              if fid not in recalculated_features['directly_recalculated']]
            recalculated_features['cascade_recalculated'] = cascade_features
            
            total_recalculated = len(ordered_features)
            DebugLogger.log(f"Total depth recalculation complete: {total_recalculated} segments updated")
            
        except Exception as e:
            DebugLogger.log_error("Error in depth recalculation", e)
        
        return recalculated_features
    
    def _recalculate_segments_depths(self, feature_ids: List[int], 
                                   updated_elevations: Dict[int, Dict[str, float]]) -> None:
        """Recalculate depths for specific segments."""
        field_mapping = self.field_mapper.get_field_mapping()
        p1_elev_idx = field_mapping.get('p1_elev', -1)
        p2_elev_idx = field_mapping.get('p2_elev', -1)
        p1_h_idx = field_mapping.get('p1_h', -1)
        p2_h_idx = field_mapping.get('p2_h', -1)
        
        if min(p1_elev_idx, p2_elev_idx, p1_h_idx, p2_h_idx) < 0:
            DebugLogger.log_error("Missing required field indices for depth recalculation")
            return
        
        # Ensure layer is editable
        if not self.layer.isEditable():
            self.layer.startEditing()
        
        for feature_id in feature_ids:
            try:
                feature = self.layer.getFeature(feature_id)
                if not feature.isValid():
                    continue
                
                # Get current elevations (including any updates)
                p1_elev = self._get_current_elevation(feature, feature_id, 'p1', p1_elev_idx, updated_elevations)
                p2_elev = self._get_current_elevation(feature, feature_id, 'p2', p2_elev_idx, updated_elevations)
                
                if p1_elev is None or p2_elev is None:
                    DebugLogger.log(f"Missing elevations for feature {feature_id}, skipping depth recalculation")
                    continue
                
                # Get segment length
                segment_length = self._calculate_segment_length(feature)
                if segment_length <= 0:
                    continue
                
                # Get current upstream depth or calculate initial depth
                current_p1_depth = self._get_depth_value(feature, p1_h_idx)
                if current_p1_depth is None:
                    # Use minimum depth if no existing depth
                    current_p1_depth = self.depth_calculator.calculate_minimum_depth()
                
                # Calculate new depths
                p1_depth, p2_depth = self.depth_calculator.calculate_segment_depths(
                    current_p1_depth, p1_elev, p2_elev, segment_length
                )
                
                # Update depth attributes
                success = True
                success &= self.layer.changeAttributeValue(feature_id, p1_h_idx, round(p1_depth, 2))
                success &= self.layer.changeAttributeValue(feature_id, p2_h_idx, round(p2_depth, 2))
                
                if success:
                    DebugLogger.log(f"Recalculated depths for feature {feature_id}: "
                                  f"P1={p1_depth:.2f}m, P2={p2_depth:.2f}m")
                else:
                    DebugLogger.log_error(f"Failed to update depth attributes for feature {feature_id}")
                
            except Exception as e:
                DebugLogger.log_error(f"Error recalculating depths for feature {feature_id}", e)
    
    def _recalculate_segments_depths_in_order(self, feature_ids: List[int], 
                                            updated_elevations: Dict[int, Dict[str, float]],
                                            orphaned_features: Optional[List[int]] = None) -> None:
        """Recalculate depths for segments in proper network order."""
        field_mapping = self.field_mapper.get_field_mapping()
        p1_elev_idx = field_mapping.get('p1_elev', -1)
        p2_elev_idx = field_mapping.get('p2_elev', -1)
        p1_h_idx = field_mapping.get('p1_h', -1)
        p2_h_idx = field_mapping.get('p2_h', -1)
        
        if min(p1_elev_idx, p2_elev_idx, p1_h_idx, p2_h_idx) < 0:
            DebugLogger.log_error("Missing required field indices for ordered depth recalculation")
            return
        
        # Ensure layer is editable
        if not self.layer.isEditable():
            self.layer.startEditing()
        
        # Keep track of calculated depths for propagation
        calculated_depths = {}  # feature_id -> {'p1_depth': float, 'p2_depth': float}
        
        for feature_id in feature_ids:
            try:
                feature = self.layer.getFeature(feature_id)
                if not feature.isValid():
                    continue
                
                # Get current elevations (including any updates)
                p1_elev = self._get_current_elevation(feature, feature_id, 'p1', p1_elev_idx, updated_elevations)
                p2_elev = self._get_current_elevation(feature, feature_id, 'p2', p2_elev_idx, updated_elevations)
                
                if p1_elev is None or p2_elev is None:
                    DebugLogger.log(f"Missing elevations for feature {feature_id}, skipping")
                    continue
                
                # Get segment length
                segment_length = self._calculate_segment_length(feature)
                if segment_length <= 0:
                    continue
                
                # Determine upstream depth - special handling for orphaned features
                if orphaned_features and feature_id in orphaned_features:
                    # Orphaned features get minimum depth (lost their upstream connection)
                    upstream_depth = self.depth_calculator.calculate_minimum_depth()
                    DebugLogger.log(f"Feature {feature_id} is orphaned, using minimum depth {upstream_depth:.2f}m")
                else:
                    # Check if we have a calculated upstream depth from previous segments
                    upstream_depth = self._get_upstream_depth_from_network(feature_id, calculated_depths)
                    if upstream_depth is None:
                        # Fall back to existing depth or minimum depth
                        current_p1_depth = self._get_depth_value(feature, p1_h_idx)
                        if current_p1_depth is None:
                            upstream_depth = self.depth_calculator.calculate_minimum_depth()
                        else:
                            upstream_depth = current_p1_depth
                
                # Calculate new depths
                p1_depth, p2_depth = self.depth_calculator.calculate_segment_depths(
                    upstream_depth, p1_elev, p2_elev, segment_length
                )
                
                # Store calculated depths for downstream propagation
                calculated_depths[feature_id] = {
                    'p1_depth': p1_depth,
                    'p2_depth': p2_depth
                }
                
                # Update depth attributes
                success = True
                success &= self.layer.changeAttributeValue(feature_id, p1_h_idx, round(p1_depth, 2))
                success &= self.layer.changeAttributeValue(feature_id, p2_h_idx, round(p2_depth, 2))
                
                if success:
                    DebugLogger.log(f"Recalculated depths (ordered) for feature {feature_id}: "
                                  f"P1={p1_depth:.2f}m, P2={p2_depth:.2f}m")
                else:
                    DebugLogger.log_error(f"Failed to update depth attributes for feature {feature_id}")
                
            except Exception as e:
                DebugLogger.log_error(f"Error in ordered recalculation for feature {feature_id}", e)
    
    def _get_upstream_depth_from_network(self, feature_id: int, calculated_depths: Dict[int, Dict[str, float]]) -> Optional[float]:
        """Get upstream depth from connected segments that were already calculated."""
        try:
            # Get this feature's P1 coordinate from connectivity analyzer
            if not hasattr(self.advanced_analyzer, '_topology_after_changes') or not self.advanced_analyzer._topology_after_changes:
                return None
                
            endpoints = self.advanced_analyzer._topology_after_changes.get('endpoints', {})
            if feature_id not in endpoints:
                return None
            
            p1_coord, _ = endpoints[feature_id]
            p1_key = CoordinateUtils.node_key(p1_coord)
            
            # Find connections at P1
            connections = self.advanced_analyzer._topology_after_changes.get('connections', {})
            connection = connections.get(p1_key)
            
            if not connection:
                return None
            
            # Look for upstream features that have been calculated
            upstream_connections = connection.get_upstream_connections()
            max_upstream_depth = None
            
            for conn_info in upstream_connections:
                if conn_info.feature_id in calculated_depths:
                    upstream_depth = calculated_depths[conn_info.feature_id]['p2_depth']
                    if max_upstream_depth is None or upstream_depth > max_upstream_depth:
                        max_upstream_depth = upstream_depth
                        DebugLogger.log(f"Using upstream depth {upstream_depth:.2f}m from feature {conn_info.feature_id} for feature {feature_id}")
            
            return max_upstream_depth
            
        except Exception as e:
            DebugLogger.log_error(f"Error getting upstream depth for feature {feature_id}", e)
            return None
    
    def _handle_convergent_nodes_and_cascade(self, vertex_changes: List[VertexChange], 
                                           updated_elevations: Dict[int, Dict[str, float]]) -> List[int]:
        """Handle convergent nodes and cascade depth changes downstream."""
        cascade_recalculated = []
        
        try:
            # Find all convergent nodes that might be affected
            convergent_nodes = self.connectivity_analyzer.find_convergent_nodes()
            
            # Check each convergent node for depth updates needed
            for node in convergent_nodes:
                try:
                    # Get maximum upstream depth at this node
                    max_upstream_depth = node.get_max_upstream_depth()
                    if max_upstream_depth is None:
                        continue
                    
                    # Get downstream segments from this node
                    downstream_connections = node.get_downstream_connections()
                    
                    for conn_info in downstream_connections:
                        # Check if downstream segment needs depth update
                        if self._should_update_downstream_depth(conn_info.feature_id, max_upstream_depth):
                            # Cascade depth calculation downstream
                            cascaded_features = self._cascade_depth_from_point(
                                conn_info.feature_id, node.coordinate, max_upstream_depth
                            )
                            cascade_recalculated.extend(cascaded_features)
                
                except Exception as e:
                    DebugLogger.log_error(f"Error processing convergent node", e)
            
            # Remove duplicates
            cascade_recalculated = list(set(cascade_recalculated))
            
            if cascade_recalculated:
                DebugLogger.log(f"Cascaded depth updates to {len(cascade_recalculated)} downstream segments")
        
        except Exception as e:
            DebugLogger.log_error("Error handling convergent nodes and cascade", e)
        
        return cascade_recalculated
    
    def _cascade_depth_from_point(self, start_feature_id: int, start_coord: QgsPointXY, 
                                 upstream_depth: float) -> List[int]:
        """Cascade depth calculation downstream from a point."""
        cascaded_features = []
        
        try:
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            p1_h_idx = field_mapping.get('p1_h', -1)
            p2_h_idx = field_mapping.get('p2_h', -1)
            
            if min(p1_elev_idx, p2_elev_idx, p1_h_idx, p2_h_idx) < 0:
                return cascaded_features
            
            # Start cascading from the given feature
            current_feature_id = start_feature_id
            current_upstream_depth = upstream_depth
            visited_features = set()
            
            while current_feature_id and current_feature_id not in visited_features:
                visited_features.add(current_feature_id)
                
                feature = self.layer.getFeature(current_feature_id)
                if not feature.isValid():
                    break
                
                # Get elevations
                p1_elev = self._get_depth_value(feature, p1_elev_idx)
                p2_elev = self._get_depth_value(feature, p2_elev_idx)
                
                if p1_elev is None or p2_elev is None:
                    break
                
                # Calculate segment length
                segment_length = self._calculate_segment_length(feature)
                if segment_length <= 0:
                    break
                
                # Calculate new depths
                p1_depth, p2_depth = self.depth_calculator.calculate_segment_depths(
                    current_upstream_depth, p1_elev, p2_elev, segment_length
                )
                
                # Update depths
                success = True
                success &= self.layer.changeAttributeValue(current_feature_id, p1_h_idx, round(p1_depth, 2))
                success &= self.layer.changeAttributeValue(current_feature_id, p2_h_idx, round(p2_depth, 2))
                
                if success:
                    cascaded_features.append(current_feature_id)
                    DebugLogger.log(f"Cascaded depth update to feature {current_feature_id}: "
                                  f"P1={p1_depth:.2f}m, P2={p2_depth:.2f}m")
                
                # Find next downstream feature
                feature_endpoints = self.connectivity_analyzer._feature_endpoints.get(current_feature_id)
                if not feature_endpoints:
                    break
                
                _, p2_coord = feature_endpoints
                downstream_features = self.connectivity_analyzer.get_downstream_features_for_node(p2_coord)
                
                # Continue with next downstream feature (if any)
                next_feature = None
                for ds_feature_id in downstream_features:
                    if ds_feature_id not in visited_features:
                        next_feature = ds_feature_id
                        break
                
                current_feature_id = next_feature
                current_upstream_depth = p2_depth
        
        except Exception as e:
            DebugLogger.log_error("Error in depth cascade", e)
        
        return cascaded_features
    
    def _should_update_downstream_depth(self, feature_id: int, new_upstream_depth: float) -> bool:
        """Check if downstream segment should be updated with new upstream depth."""
        try:
            field_mapping = self.field_mapper.get_field_mapping()
            p1_h_idx = field_mapping.get('p1_h', -1)
            
            if p1_h_idx < 0:
                return False
            
            feature = self.layer.getFeature(feature_id)
            if not feature.isValid():
                return False
            
            current_p1_depth = self._get_depth_value(feature, p1_h_idx)
            if current_p1_depth is None:
                return True  # No current depth, should update
            
            # Update if new depth is significantly different (use convergent logic)
            tolerance = 0.01  # 1cm tolerance
            return abs(current_p1_depth - new_upstream_depth) > tolerance
        
        except Exception:
            return False
    
    def _get_current_elevation(self, feature, feature_id: int, vertex_type: str, 
                             field_idx: int, updated_elevations: Dict[int, Dict[str, float]]) -> Optional[float]:
        """Get current elevation value, considering recent updates."""
        # Check if elevation was recently updated
        if feature_id in updated_elevations and vertex_type in updated_elevations[feature_id]:
            return updated_elevations[feature_id][vertex_type]
        
        # Get from feature attribute
        return self._get_depth_value(feature, field_idx)
    
    def _get_depth_value(self, feature, field_idx: int) -> Optional[float]:
        """Get numeric value from feature attribute."""
        if field_idx < 0:
            return None
        try:
            value = feature.attribute(field_idx)
            return float(value) if value not in (None, '') else None
        except (ValueError, TypeError):
            return None
    
    def _calculate_segment_length(self, feature) -> float:
        """Calculate segment length from geometry."""
        try:
            geom = feature.geometry()
            if geom.isEmpty():
                return 0.0
            
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                if not lines or len(lines[0]) < 2:
                    return 0.0
                pts = lines[0]
            else:
                pts = geom.asPolyline()
                if len(pts) < 2:
                    return 0.0
            
            p1, p2 = QgsPointXY(pts[0]), QgsPointXY(pts[-1])
            return CoordinateUtils.point_distance_2d(p1, p2)
        
        except Exception:
            return 0.0
    
    def force_recalculate_network(self, feature_ids: Optional[List[int]] = None) -> Dict[str, int]:
        """
        Force recalculation of entire network or specific features.
        
        Args:
            feature_ids: List of feature IDs to recalculate, or None for all
            
        Returns:
            Dictionary with recalculation statistics
        """
        stats = {'recalculated': 0, 'failed': 0, 'skipped': 0}
        
        try:
            # Get features to process
            if feature_ids is not None:
                features = [self.layer.getFeature(fid) for fid in feature_ids]
                features = [f for f in features if f.isValid()]
            else:
                features = list(self.layer.getFeatures())
            
            # Rebuild connectivity and process in network order
            self.connectivity_analyzer.build_connectivity_map()
            
            # Use network analyzer to process features in proper order
            from .network_analyzer import NetworkAnalyzer
            network_analyzer = NetworkAnalyzer(self.layer, self.field_mapper, self.depth_calculator)
            
            success = network_analyzer.calculate_network_depths(features)
            
            if success:
                stats['recalculated'] = len(features)
                DebugLogger.log(f"Force recalculated depths for {len(features)} features")
            else:
                stats['failed'] = len(features)
                DebugLogger.log_error("Force recalculation failed")
        
        except Exception as e:
            DebugLogger.log_error("Error in force recalculation", e)
            stats['failed'] = len(features) if 'features' in locals() else 0
        
        return stats
    
    def _recalculate_segments_depths_enhanced(self, feature_ids: List[int], 
                                            updated_elevations: Dict[int, Dict[str, float]],
                                            orphaned_features: List[int],
                                            orphaned_upstream_features: List[int], 
                                            convergent_affected_features: List[int]) -> None:
        """
        Enhanced depth recalculation with special handling for complex scenarios.
        
        Args:
            feature_ids: Features to recalculate in network order
            updated_elevations: Dictionary of updated elevation values
            orphaned_features: Features that lost upstream connection (need minimum depth)
            orphaned_upstream_features: Features that lost downstream connection (keep existing P1 depth)
            convergent_affected_features: Features affected by convergent node conflicts
        """
        field_mapping = self.field_mapper.get_field_mapping()
        p1_elev_idx = field_mapping.get('p1_elev', -1)
        p2_elev_idx = field_mapping.get('p2_elev', -1)
        p1_h_idx = field_mapping.get('p1_h', -1)
        p2_h_idx = field_mapping.get('p2_h', -1)
        
        if min(p1_elev_idx, p2_elev_idx, p1_h_idx, p2_h_idx) < 0:
            DebugLogger.log_error("Missing required field indices for enhanced depth recalculation")
            return
        
        # Ensure layer is editable
        if not self.layer.isEditable():
            self.layer.startEditing()
        
        # Keep track of calculated depths for propagation
        calculated_depths = {}  # feature_id -> {'p1_depth': float, 'p2_depth': float}
        
        for feature_id in feature_ids:
            try:
                feature = self.layer.getFeature(feature_id)
                if not feature.isValid():
                    continue
                
                # Get current elevations (including any updates)
                p1_elev = self._get_current_elevation(feature, feature_id, 'p1', p1_elev_idx, updated_elevations)
                p2_elev = self._get_current_elevation(feature, feature_id, 'p2', p2_elev_idx, updated_elevations)
                
                if p1_elev is None or p2_elev is None:
                    DebugLogger.log(f"Missing elevations for feature {feature_id}, skipping")
                    continue
                
                # Get segment length
                segment_length = self._calculate_segment_length(feature)
                if segment_length <= 0:
                    continue
                
                # Determine upstream depth with enhanced special case handling
                upstream_depth = self._determine_upstream_depth_enhanced(
                    feature_id, feature, p1_h_idx, calculated_depths,
                    orphaned_features, orphaned_upstream_features, convergent_affected_features
                )
                
                # Calculate new depths
                p1_depth, p2_depth = self.depth_calculator.calculate_segment_depths(
                    upstream_depth, p1_elev, p2_elev, segment_length
                )
                
                # Check for convergent node depth conflict before updating
                should_update = True
                conflict_reason = ""
                
                if feature_id in convergent_affected_features:
                    should_update, conflict_reason = self._check_convergent_depth_conflict(
                        feature_id, feature, p1_depth, p1_h_idx, convergent_affected_features
                    )
                
                if should_update:
                    # Store calculated depths for downstream propagation
                    calculated_depths[feature_id] = {
                        'p1_depth': p1_depth,
                        'p2_depth': p2_depth
                    }
                    
                    # Update depth attributes
                    success = True
                    success &= self.layer.changeAttributeValue(feature_id, p1_h_idx, round(p1_depth, 2))
                    success &= self.layer.changeAttributeValue(feature_id, p2_h_idx, round(p2_depth, 2))
                else:
                    # Don't update - use existing depths for downstream propagation
                    existing_p1_depth = self._get_depth_value(feature, p1_h_idx)
                    existing_p2_depth = self._get_depth_value(feature, p2_h_idx)
                    
                    if existing_p1_depth is not None and existing_p2_depth is not None:
                        calculated_depths[feature_id] = {
                            'p1_depth': existing_p1_depth,
                            'p2_depth': existing_p2_depth
                        }
                    
                    success = True  # Mark as successful since we're keeping existing values
                
                if success:
                    special_status = ""
                    if feature_id in orphaned_features:
                        special_status = " (orphaned - minimum depth)"
                    elif feature_id in orphaned_upstream_features:
                        special_status = " (orphaned upstream - kept P1 depth)"
                    elif feature_id in convergent_affected_features:
                        if should_update:
                            special_status = " (convergent affected - updated)"
                        else:
                            special_status = f" (convergent conflict - {conflict_reason})"
                    
                    if should_update:
                        DebugLogger.log(f"Enhanced recalculation for feature {feature_id}: "
                                      f"P1={p1_depth:.2f}m, P2={p2_depth:.2f}m{special_status}")
                    else:
                        existing_p1 = calculated_depths[feature_id]['p1_depth']
                        existing_p2 = calculated_depths[feature_id]['p2_depth']
                        DebugLogger.log(f"Kept existing depths for feature {feature_id}: "
                                      f"P1={existing_p1:.2f}m, P2={existing_p2:.2f}m{special_status}")
                else:
                    DebugLogger.log_error(f"Failed to update depth attributes for feature {feature_id}")
                
            except Exception as e:
                DebugLogger.log_error(f"Error in enhanced recalculation for feature {feature_id}", e)
    
    def _determine_upstream_depth_enhanced(self, feature_id: int, feature, p1_h_idx: int,
                                         calculated_depths: Dict[int, Dict[str, float]],
                                         orphaned_features: List[int],
                                         orphaned_upstream_features: List[int],
                                         convergent_affected_features: List[int]) -> float:
        """
        Determine upstream depth with enhanced handling for special cases.
        
        Args:
            feature_id: Feature being processed
            feature: QgsFeature object
            p1_h_idx: P1 depth field index
            calculated_depths: Previously calculated depths
            orphaned_features: Features that lost upstream connection
            orphaned_upstream_features: Features that lost downstream connection
            convergent_affected_features: Features affected by convergent nodes
            
        Returns:
            Upstream depth to use for calculations
        """
        try:
            # Case 1: Orphaned downstream features get minimum depth (lost upstream connection)
            if feature_id in orphaned_features:
                upstream_depth = self.depth_calculator.calculate_minimum_depth()
                DebugLogger.log(f"Feature {feature_id} is orphaned downstream, using minimum depth {upstream_depth:.2f}m")
                return upstream_depth
            
            # Case 2: Orphaned upstream features keep their existing P1 depth (lost downstream connection)
            if feature_id in orphaned_upstream_features:
                current_p1_depth = self._get_depth_value(feature, p1_h_idx)
                if current_p1_depth is not None:
                    DebugLogger.log(f"Feature {feature_id} is orphaned upstream, keeping existing P1 depth {current_p1_depth:.2f}m")
                    return current_p1_depth
                else:
                    # Fall back to minimum if no existing depth
                    upstream_depth = self.depth_calculator.calculate_minimum_depth()
                    DebugLogger.log(f"Feature {feature_id} is orphaned upstream but has no existing depth, using minimum {upstream_depth:.2f}m")
                    return upstream_depth
            
            # Case 3: Convergent affected features need maximum depth from convergent node
            if feature_id in convergent_affected_features:
                convergent_depth = self._get_convergent_node_max_depth(feature_id)
                if convergent_depth is not None:
                    DebugLogger.log(f"Feature {feature_id} affected by convergent node, using maximum upstream depth {convergent_depth:.2f}m")
                    return convergent_depth
            
            # Case 4: Normal case - check if we have calculated upstream depth from network
            upstream_depth = self._get_upstream_depth_from_network(feature_id, calculated_depths)
            if upstream_depth is not None:
                return upstream_depth
            
            # Case 5: Fall back to existing depth or minimum depth
            current_p1_depth = self._get_depth_value(feature, p1_h_idx)
            if current_p1_depth is not None:
                return current_p1_depth
            else:
                return self.depth_calculator.calculate_minimum_depth()
                
        except Exception as e:
            DebugLogger.log_error(f"Error determining upstream depth for feature {feature_id}", e)
            return self.depth_calculator.calculate_minimum_depth()
    
    def _get_convergent_node_max_depth(self, feature_id: int) -> Optional[float]:
        """Get maximum upstream depth from convergent node affecting this feature."""
        try:
            if not hasattr(self.advanced_analyzer, '_topology_after_changes') or not self.advanced_analyzer._topology_after_changes:
                return None
                
            endpoints = self.advanced_analyzer._topology_after_changes.get('endpoints', {})
            if feature_id not in endpoints:
                return None
            
            p1_coord, _ = endpoints[feature_id]
            p1_key = CoordinateUtils.node_key(p1_coord)
            
            # Find connections at P1
            connections = self.advanced_analyzer._topology_after_changes.get('connections', {})
            connection = connections.get(p1_key)
            
            if not connection or not connection.is_convergent():
                return None
            
            # Get maximum depth from all upstream connections at this convergent node
            max_depth = connection.get_max_upstream_depth()
            
            if max_depth is not None:
                DebugLogger.log(f"Convergent node at P1 of feature {feature_id} has max upstream depth {max_depth:.2f}m")
            
            return max_depth
            
        except Exception as e:
            DebugLogger.log_error(f"Error getting convergent node max depth for feature {feature_id}", e)
            return None
    
    def _check_convergent_depth_conflict(self, feature_id: int, feature, calculated_p1_depth: float,
                                       p1_h_idx: int, convergent_affected_features: List[int]) -> Tuple[bool, str]:
        """
        Check if updating this feature would create a convergent node depth conflict.
        
        Args:
            feature_id: Feature being checked
            feature: QgsFeature object
            calculated_p1_depth: Newly calculated P1 depth
            p1_h_idx: P1 depth field index
            convergent_affected_features: List of convergent affected features
            
        Returns:
            Tuple of (should_update: bool, conflict_reason: str)
        """
        try:
            # Get existing depth
            existing_p1_depth = self._get_depth_value(feature, p1_h_idx)
            
            # If no existing depth, always update
            if existing_p1_depth is None:
                return True, ""
            
            # Tolerance for depth comparison (1cm)
            depth_tolerance = 0.01
            
            # If calculated depth is significantly greater than existing, respect existing (stopping criterion)
            # This happens when a branch with higher depth tries to overwrite a branch with lower but established depth
            if calculated_p1_depth > existing_p1_depth + depth_tolerance:
                # The existing depth is lower and should be preserved (it represents a constraint from another branch)
                return False, f"existing depth {existing_p1_depth:.2f}m < calculated {calculated_p1_depth:.2f}m (stopped)"
            
            # If calculated depth is significantly lower than existing, update (override with lower depth)
            # This happens when a new branch connection imposes a lower depth requirement
            if calculated_p1_depth < existing_p1_depth - depth_tolerance:
                return True, f"updated from {existing_p1_depth:.2f}m to {calculated_p1_depth:.2f}m (lower depth imposed)"
            
            # If depths are similar, use the higher one (maximum depth rule)
            if abs(calculated_p1_depth - existing_p1_depth) <= depth_tolerance:
                final_depth = max(calculated_p1_depth, existing_p1_depth)
                if final_depth != calculated_p1_depth:
                    return False, f"kept higher depth {existing_p1_depth:.2f}m vs {calculated_p1_depth:.2f}m"
                else:
                    return True, f"depths similar, updating to {calculated_p1_depth:.2f}m"
            
            # Default: update with calculated depth
            return True, ""
            
        except Exception as e:
            DebugLogger.log_error(f"Error checking convergent depth conflict for feature {feature_id}", e)
            return True, ""  # Default to updating on error