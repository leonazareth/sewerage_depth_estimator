# -*- coding: utf-8 -*-
"""
Comprehensive connectivity analyzer for sewerage networks.

This module provides complete network connectivity analysis including:
- Basic connectivity mapping and validation
- Advanced vertex movement impact analysis
- Topology change detection and handling
- Network statistics and validation
"""

from typing import List, Dict, Set, Optional, Tuple
from qgis.core import QgsPointXY, QgsVectorLayer
from ..utils import DebugLogger, CoordinateUtils
from ..data import FieldMapper
from .network_connectivity import ConnectivityAnalyzer
from .geometry_change_detector import VertexChange


class ConnectivityAnalyzer:
    """
    Comprehensive connectivity analyzer for sewerage networks.
    
    This class provides both basic connectivity analysis and advanced vertex movement
    handling. It combines the functionality of basic connectivity mapping with 
    sophisticated impact analysis for geometry changes.
    """
    
    def __init__(self, layer: QgsVectorLayer, field_mapper: FieldMapper, tolerance: float = 1e-6):
        self.layer = layer
        self.field_mapper = field_mapper
        self.tolerance = tolerance
        self.base_analyzer = ConnectivityAnalyzer(layer, field_mapper, tolerance)
        
        # Store topology before and after changes
        self._topology_before_changes = None
        self._topology_after_changes = None
    
    def prepare_for_vertex_changes(self, vertex_changes: List[VertexChange]) -> None:
        """Prepare connectivity analysis by capturing current topology."""
        try:
            DebugLogger.log("Capturing topology before vertex changes...")
            
            # Build current connectivity map
            self.base_analyzer.build_connectivity_map()
            self._topology_before_changes = {
                'connections': self.base_analyzer._network_connections.copy(),
                'endpoints': self.base_analyzer._feature_endpoints.copy()
            }
            
            DebugLogger.log(f"Captured topology: {len(self._topology_before_changes['connections'])} connections, "
                          f"{len(self._topology_before_changes['endpoints'])} features")
            
        except Exception as e:
            DebugLogger.log_error("Error preparing for vertex changes", e)
    
    def analyze_vertex_movement_impacts(self, vertex_changes: List[VertexChange]) -> Dict[str, List[int]]:
        """
        Comprehensive analysis of vertex movement impacts.
        
        Args:
            vertex_changes: List of vertex changes
            
        Returns:
            Dictionary with different categories of affected segments
        """
        try:
            # Rebuild connectivity with new positions
            self.base_analyzer.build_connectivity_map()
            self._topology_after_changes = {
                'connections': self.base_analyzer._network_connections.copy(),
                'endpoints': self.base_analyzer._feature_endpoints.copy()
            }
            
            # Analyze impacts
            impacts = {
                'moved_features': [],
                'newly_connected_downstream': [],
                'newly_disconnected_features': [],
                'existing_downstream_chains': [],
                'orphaned_downstream_chains': [],  # Features that lost upstream connection and need minimum depth
                'orphaned_upstream_features': [],  # Features that lost downstream connection and need recalculation
                'convergent_affected_chains': []   # Downstream chains from convergent nodes that need depth conflict resolution
            }
            
            for change in vertex_changes:
                # The moved feature itself
                impacts['moved_features'].append(change.feature_id)
                
                # Special case: if we moved P1 (upstream vertex), analyze connection changes
                if change.vertex_type == 'p1':
                    old_key = CoordinateUtils.node_key(change.old_coord)
                    new_key = CoordinateUtils.node_key(change.new_coord)
                    
                    old_connections = self._topology_before_changes.get('connections', {}).get(old_key)
                    new_connections = self._topology_after_changes.get('connections', {}).get(new_key)
                    
                    # Count upstream connections at old and new positions
                    old_upstream_count = len(old_connections.get_upstream_connections()) if old_connections else 0
                    new_upstream_count = len(new_connections.get_upstream_connections()) if new_connections else 0
                    
                    # If the moved feature had upstream connections before but lost them, it needs minimum depth
                    if old_upstream_count > 0 and new_upstream_count == 0:
                        impacts['orphaned_downstream_chains'].append(change.feature_id)
                        DebugLogger.log(f"Moved feature {change.feature_id} lost upstream connection (P1 moved away), needs minimum depth")
                    
                    # If the moved feature gained upstream connections, it needs recalculation with new upstream depths
                    elif new_upstream_count > old_upstream_count:
                        impacts['convergent_affected_chains'].append(change.feature_id)
                        DebugLogger.log(f"Moved feature {change.feature_id} gained upstream connections (P1 moved to new location), needs upstream-based recalculation")
                    
                    # If the moved feature had connections before and still has connections (but possibly different ones), needs recalculation
                    elif old_upstream_count > 0 and new_upstream_count > 0:
                        impacts['convergent_affected_chains'].append(change.feature_id)
                        DebugLogger.log(f"Moved feature {change.feature_id} changed upstream connections (P1 moved), needs recalculation based on new upstream depths")
                
                # Analyze connection changes
                self._analyze_connection_changes(change, impacts)
                
                # Find existing downstream chains from the moved feature
                self._find_downstream_chains(change, impacts)
            
            # Remove duplicates
            for key in impacts:
                impacts[key] = list(set(impacts[key]))
            
            DebugLogger.log(f"Movement impact analysis: "
                          f"moved={len(impacts['moved_features'])}, "
                          f"newly_connected={len(impacts['newly_connected_downstream'])}, "
                          f"disconnected={len(impacts['newly_disconnected_features'])}, "
                          f"downstream_chains={len(impacts['existing_downstream_chains'])}, "
                          f"orphaned_chains={len(impacts['orphaned_downstream_chains'])}, "
                          f"orphaned_upstream={len(impacts['orphaned_upstream_features'])}, "
                          f"convergent_affected={len(impacts['convergent_affected_chains'])}")
            
            return impacts
            
        except Exception as e:
            DebugLogger.log_error("Error analyzing vertex movement impacts", e)
            return {'moved_features': [change.feature_id for change in vertex_changes]}
    
    def _analyze_connection_changes(self, change: VertexChange, impacts: Dict[str, List[int]]) -> None:
        """Analyze how connections changed for a specific vertex movement."""
        try:
            old_coord = change.old_coord
            new_coord = change.new_coord
            
            old_key = CoordinateUtils.node_key(old_coord)
            new_key = CoordinateUtils.node_key(new_coord)
            
            if not self._topology_before_changes:
                return
            
            # Check what was connected at old position
            old_connections = self._topology_before_changes['connections'].get(old_key)
            if old_connections:
                # Features that were connected to the old position but now disconnected
                for conn_info in old_connections.connections:
                    if conn_info.feature_id != change.feature_id:
                        impacts['newly_disconnected_features'].append(conn_info.feature_id)
                        DebugLogger.log(f"Feature {conn_info.feature_id} disconnected from moved vertex ({change.vertex_type})")
                        
                        # If we moved an upstream vertex (P1), any downstream segments connected to that vertex
                        # are now disconnected and need minimum depth recalculation
                        if change.vertex_type == 'p1':
                            self._trace_disconnected_downstream_from_feature(conn_info.feature_id, impacts)
                        
                        # If we moved a downstream vertex (P2), any segments that had this as upstream
                        # are now disconnected and need minimum depth recalculation  
                        elif change.vertex_type == 'p2':
                            self._trace_disconnected_downstream_from_feature(conn_info.feature_id, impacts)
                            
                        # Also check if this disconnection leaves upstream features orphaned
                        # (features that lost their only downstream connection)
                        self._check_for_orphaned_upstream_features(conn_info.feature_id, change, impacts)
            
            # Check what is now connected at new position
            new_connections = self._topology_after_changes['connections'].get(new_key)
            if new_connections:
                # Features that are now connected to the new position
                for conn_info in new_connections.connections:
                    if conn_info.feature_id != change.feature_id:
                        impacts['newly_connected_downstream'].append(conn_info.feature_id)
                        DebugLogger.log(f"Feature {conn_info.feature_id} newly connected to moved vertex ({change.vertex_type})")
                        
                        # Check if this new connection creates a convergent node
                        self._check_for_convergent_node_impact(new_coord, change, impacts)
            
        except Exception as e:
            DebugLogger.log_error("Error analyzing connection changes", e)
    
    def _find_downstream_chains(self, change: VertexChange, impacts: Dict[str, List[int]]) -> None:
        """Find all downstream chains from the moved feature."""
        try:
            # Get the current P2 coordinate of the moved feature
            if change.feature_id not in self._topology_after_changes['endpoints']:
                return
            
            _, p2_coord = self._topology_after_changes['endpoints'][change.feature_id]
            p2_key = CoordinateUtils.node_key(p2_coord)
            
            # Trace downstream from this point
            visited = set()
            to_visit = [p2_key]
            
            while to_visit:
                current_key = to_visit.pop(0)
                if current_key in visited:
                    continue
                visited.add(current_key)
                
                connection = self._topology_after_changes['connections'].get(current_key)
                if not connection:
                    continue
                
                # Get downstream features from this connection point
                downstream_connections = connection.get_downstream_connections()
                
                for conn_info in downstream_connections:
                    if conn_info.feature_id not in impacts['moved_features']:
                        impacts['existing_downstream_chains'].append(conn_info.feature_id)
                        
                        # Continue tracing from this feature's P2
                        if conn_info.feature_id in self._topology_after_changes['endpoints']:
                            _, next_p2 = self._topology_after_changes['endpoints'][conn_info.feature_id]
                            next_key = CoordinateUtils.node_key(next_p2)
                            if next_key not in visited:
                                to_visit.append(next_key)
            
            DebugLogger.log(f"Found {len(impacts['existing_downstream_chains'])} segments in downstream chain from feature {change.feature_id}")
            
        except Exception as e:
            DebugLogger.log_error("Error finding downstream chains", e)
    
    def _trace_disconnected_downstream_from_feature(self, feature_id: int, impacts: Dict[str, List[int]]) -> None:
        """Trace downstream from a feature that lost its upstream connection."""
        try:
            if not self._topology_before_changes:
                return
                
            # Get the feature's P2 coordinate from BEFORE topology (where it was connected)
            old_endpoints = self._topology_before_changes['endpoints'].get(feature_id)
            if not old_endpoints:
                return
                
            _, p2_coord = old_endpoints
            p2_key = CoordinateUtils.node_key(p2_coord)
            
            # Find what was connected downstream from this feature before the change
            old_connections = self._topology_before_changes['connections'].get(p2_key)
            if not old_connections:
                return
            
            # Get downstream features that were connected to this P2
            downstream_connections = old_connections.get_downstream_connections()
            
            for conn_info in downstream_connections:
                if conn_info.feature_id != feature_id:
                    # This downstream feature is now orphaned (lost its upstream connection)
                    impacts['orphaned_downstream_chains'].append(conn_info.feature_id)
                    DebugLogger.log(f"Feature {conn_info.feature_id} is now orphaned (lost upstream connection)")
                    
                    # Recursively trace downstream from this orphaned feature
                    self._trace_orphaned_chain_recursively(conn_info.feature_id, impacts, set([feature_id]))
            
        except Exception as e:
            DebugLogger.log_error(f"Error tracing disconnected downstream from feature {feature_id}", e)
    
    def _trace_orphaned_chain_recursively(self, start_feature_id: int, impacts: Dict[str, List[int]], visited: set) -> None:
        """Recursively trace an orphaned downstream chain."""
        try:
            if start_feature_id in visited:
                return
            visited.add(start_feature_id)
            
            # Get this feature's P2 from the BEFORE topology
            if not self._topology_before_changes:
                return
                
            old_endpoints = self._topology_before_changes['endpoints'].get(start_feature_id)
            if not old_endpoints:
                return
                
            _, p2_coord = old_endpoints
            p2_key = CoordinateUtils.node_key(p2_coord)
            
            # Find downstream features from this P2
            old_connections = self._topology_before_changes['connections'].get(p2_key)
            if not old_connections:
                return
            
            downstream_connections = old_connections.get_downstream_connections()
            
            for conn_info in downstream_connections:
                if conn_info.feature_id not in visited:
                    impacts['orphaned_downstream_chains'].append(conn_info.feature_id)
                    DebugLogger.log(f"Feature {conn_info.feature_id} is part of orphaned chain")
                    self._trace_orphaned_chain_recursively(conn_info.feature_id, impacts, visited)
                    
        except Exception as e:
            DebugLogger.log_error(f"Error in recursive orphaned chain tracing from {start_feature_id}", e)
    
    def _check_for_orphaned_upstream_features(self, disconnected_feature_id: int, change: VertexChange, impacts: Dict[str, List[int]]) -> None:
        """Check if disconnection leaves upstream features orphaned (lost their only downstream connection)."""
        try:
            if not self._topology_before_changes:
                return
            
            # Get the P1 coordinate of the disconnected feature (where it received upstream connection)
            old_endpoints = self._topology_before_changes['endpoints'].get(disconnected_feature_id)
            if not old_endpoints:
                return
                
            p1_coord, _ = old_endpoints
            p1_key = CoordinateUtils.node_key(p1_coord)
            
            # Find what was connected upstream to this feature before the change
            old_connections = self._topology_before_changes['connections'].get(p1_key)
            if not old_connections:
                return
            
            # Get upstream features that were connected to this P1
            upstream_connections = old_connections.get_upstream_connections()
            
            for conn_info in upstream_connections:
                if conn_info.feature_id != change.feature_id:
                    # Check if this upstream feature now has no downstream connections
                    upstream_endpoints = self._topology_after_changes['endpoints'].get(conn_info.feature_id)
                    if upstream_endpoints:
                        _, upstream_p2 = upstream_endpoints
                        upstream_p2_key = CoordinateUtils.node_key(upstream_p2)
                        
                        current_connections = self._topology_after_changes['connections'].get(upstream_p2_key)
                        downstream_count = len(current_connections.get_downstream_connections()) if current_connections else 0
                        
                        if downstream_count == 0:
                            # This upstream feature lost its downstream connection
                            impacts['orphaned_upstream_features'].append(conn_info.feature_id)
                            DebugLogger.log(f"Feature {conn_info.feature_id} is orphaned upstream (lost downstream connection)")
            
        except Exception as e:
            DebugLogger.log_error(f"Error checking orphaned upstream features", e)
    
    def _check_for_convergent_node_impact(self, connection_coord: QgsPointXY, change: VertexChange, impacts: Dict[str, List[int]]) -> None:
        """Check if new connection creates convergent node requiring depth conflict resolution."""
        try:
            coord_key = CoordinateUtils.node_key(connection_coord)
            
            # Get connections at this coordinate in the new topology
            new_connections = self._topology_after_changes['connections'].get(coord_key)
            if not new_connections:
                return
            
            # Check if this is now a convergent node (multiple upstream connections)
            upstream_connections = new_connections.get_upstream_connections()
            if len(upstream_connections) > 1:
                DebugLogger.log(f"Convergent node detected at {connection_coord.x():.3f}, {connection_coord.y():.3f} with {len(upstream_connections)} upstream connections")
                
                # All downstream chains from this convergent node need depth conflict resolution
                downstream_connections = new_connections.get_downstream_connections()
                for conn_info in downstream_connections:
                    impacts['convergent_affected_chains'].append(conn_info.feature_id)
                    # Trace the entire downstream chain
                    self._trace_convergent_downstream_chain(conn_info.feature_id, impacts, set())
            
        except Exception as e:
            DebugLogger.log_error("Error checking convergent node impact", e)
    
    def _trace_convergent_downstream_chain(self, start_feature_id: int, impacts: Dict[str, List[int]], visited: set) -> None:
        """Trace downstream chain from convergent node for depth conflict resolution."""
        try:
            if start_feature_id in visited:
                return
            visited.add(start_feature_id)
            
            # Get this feature's P2 coordinate
            endpoints = self._topology_after_changes['endpoints'].get(start_feature_id)
            if not endpoints:
                return
                
            _, p2_coord = endpoints
            p2_key = CoordinateUtils.node_key(p2_coord)
            
            # Find downstream features
            connections = self._topology_after_changes['connections'].get(p2_key)
            if not connections:
                return
            
            downstream_connections = connections.get_downstream_connections()
            
            for conn_info in downstream_connections:
                if conn_info.feature_id not in visited:
                    impacts['convergent_affected_chains'].append(conn_info.feature_id)
                    self._trace_convergent_downstream_chain(conn_info.feature_id, impacts, visited)
                    
        except Exception as e:
            DebugLogger.log_error(f"Error tracing convergent downstream chain from {start_feature_id}", e)
    
    def get_all_affected_features(self, vertex_changes: List[VertexChange]) -> List[int]:
        """Get comprehensive list of all features that need recalculation."""
        try:
            # Prepare topology analysis
            self.prepare_for_vertex_changes(vertex_changes)
            
            # Analyze impacts
            impacts = self.analyze_vertex_movement_impacts(vertex_changes)
            
            # Combine all affected features
            all_affected = set()
            for category, features in impacts.items():
                all_affected.update(features)
            
            DebugLogger.log(f"Total affected features: {len(all_affected)}")
            return list(all_affected)
            
        except Exception as e:
            DebugLogger.log_error("Error getting all affected features", e)
            return [change.feature_id for change in vertex_changes]
    
    def get_recalculation_order(self, affected_features: List[int]) -> List[int]:
        """Get features in proper upstream-to-downstream order for recalculation."""
        try:
            if not self._topology_after_changes:
                return affected_features
            
            # Build dependency graph
            upstream_dependencies = {}  # feature_id -> list of upstream feature_ids
            
            for feature_id in affected_features:
                if feature_id not in self._topology_after_changes['endpoints']:
                    continue
                
                p1_coord, _ = self._topology_after_changes['endpoints'][feature_id]
                p1_key = CoordinateUtils.node_key(p1_coord)
                
                connection = self._topology_after_changes['connections'].get(p1_key)
                if connection:
                    upstream_features = [
                        conn.feature_id for conn in connection.get_upstream_connections()
                        if conn.feature_id in affected_features and conn.feature_id != feature_id
                    ]
                    upstream_dependencies[feature_id] = upstream_features
                else:
                    upstream_dependencies[feature_id] = []
            
            # Topological sort
            ordered = []
            remaining = set(affected_features)
            
            while remaining:
                # Find features with no remaining upstream dependencies
                ready = [
                    fid for fid in remaining 
                    if not any(dep in remaining for dep in upstream_dependencies.get(fid, []))
                ]
                
                if not ready:
                    # Circular dependency or isolated features - add remaining arbitrarily
                    ready = list(remaining)
                
                for fid in ready:
                    ordered.append(fid)
                    remaining.remove(fid)
                    if len(ordered) >= len(affected_features):
                        break
            
            DebugLogger.log(f"Ordered {len(ordered)} features for recalculation")
            return ordered
            
        except Exception as e:
            DebugLogger.log_error("Error getting recalculation order", e)
            return affected_features
    
    # ============= BASIC CONNECTIVITY METHODS =============
    # Consolidated methods from ConnectivityAnalyzer
    
    def get_connection_at_point(self, coordinate: QgsPointXY) -> Optional['NetworkConnection']:
        """Get network connection at given coordinate."""
        node_key = CoordinateUtils.node_key(coordinate)
        if hasattr(self.base_analyzer, '_network_connections'):
            return self.base_analyzer._network_connections.get(node_key)
        return None
    
    def find_convergent_nodes(self) -> List['NetworkConnection']:
        """Find all convergent nodes in the network."""
        if hasattr(self.base_analyzer, '_network_connections'):
            return [conn for conn in self.base_analyzer._network_connections.values() if conn.is_convergent()]
        return []
    
    def find_divergent_nodes(self) -> List['NetworkConnection']:
        """Find all divergent nodes in the network.""" 
        if hasattr(self.base_analyzer, '_network_connections'):
            return [conn for conn in self.base_analyzer._network_connections.values() if conn.is_divergent()]
        return []
    
    def get_upstream_features_for_node(self, coordinate: QgsPointXY) -> List[int]:
        """Get feature IDs of segments ending at given coordinate."""
        connection = self.get_connection_at_point(coordinate)
        if connection:
            return [conn.feature_id for conn in connection.get_upstream_connections()]
        return []
    
    def get_downstream_features_for_node(self, coordinate: QgsPointXY) -> List[int]:
        """Get feature IDs of segments starting from given coordinate."""
        connection = self.get_connection_at_point(coordinate)
        if connection:
            return [conn.feature_id for conn in connection.get_downstream_connections()]
        return []
    
    def validate_network_connectivity(self) -> Dict[str, List[str]]:
        """
        Validate network connectivity and return issues found.
        
        Returns:
            Dictionary with lists of different types of connectivity issues
        """
        if hasattr(self.base_analyzer, 'validate_network_connectivity'):
            return self.base_analyzer.validate_network_connectivity()
        
        # Basic validation if base analyzer doesn't have it
        issues = {
            'isolated_segments': [],
            'multiple_outlets': [],
            'circular_references': [],
            'missing_connections': []
        }
        return issues
    
    def get_network_statistics(self) -> Dict[str, int]:
        """Get network connectivity statistics."""
        if hasattr(self.base_analyzer, 'get_network_statistics'):
            return self.base_analyzer.get_network_statistics()
        
        # Basic stats if base analyzer doesn't have them
        return {
            'total_features': 0,
            'total_connection_points': 0,
            'convergent_nodes': 0,
            'divergent_nodes': 0,
            'simple_nodes': 0
        }