# -*- coding: utf-8 -*-
"""
Network connectivity analysis for sewerage networks.
"""

from typing import Dict, List, Set, Tuple, Optional, NamedTuple
from qgis.core import QgsPointXY, QgsVectorLayer, QgsFeature
from ..utils import DebugLogger, CoordinateUtils
from ..data import FieldMapper


class ConnectionInfo(NamedTuple):
    """Information about a network connection."""
    feature_id: int
    vertex_type: str  # 'p1' or 'p2'
    coordinate: QgsPointXY
    current_depth: Optional[float]


class NetworkConnection:
    """Represents a network connection point."""
    
    def __init__(self, coordinate: QgsPointXY, tolerance: float = 1e-6):
        self.coordinate = coordinate
        self.tolerance = tolerance
        self.connections: List[ConnectionInfo] = []
        self._node_key = CoordinateUtils.node_key(coordinate)
    
    def add_connection(self, feature_id: int, vertex_type: str, depth: Optional[float] = None):
        """Add a connection to this network node."""
        conn_info = ConnectionInfo(
            feature_id=feature_id,
            vertex_type=vertex_type,
            coordinate=self.coordinate,
            current_depth=depth
        )
        self.connections.append(conn_info)
    
    def get_upstream_connections(self) -> List[ConnectionInfo]:
        """Get upstream connections (P2 vertices connecting to this node)."""
        return [conn for conn in self.connections if conn.vertex_type == 'p2']
    
    def get_downstream_connections(self) -> List[ConnectionInfo]:
        """Get downstream connections (P1 vertices connecting from this node)."""
        return [conn for conn in self.connections if conn.vertex_type == 'p1']
    
    def is_convergent(self) -> bool:
        """Check if this is a convergent node (multiple upstream connections)."""
        return len(self.get_upstream_connections()) > 1
    
    def is_divergent(self) -> bool:
        """Check if this is a divergent node (multiple downstream connections)."""
        return len(self.get_downstream_connections()) > 1
    
    def get_max_upstream_depth(self) -> Optional[float]:
        """Get maximum depth from upstream connections."""
        upstream_depths = [conn.current_depth for conn in self.get_upstream_connections() 
                          if conn.current_depth is not None]
        return max(upstream_depths) if upstream_depths else None
    
    def get_node_key(self) -> str:
        """Get node key for this connection."""
        return self._node_key


class NetworkConnectivityAnalyzer:
    """Analyzes network connectivity and identifies affected segments."""
    
    def __init__(self, layer: QgsVectorLayer, field_mapper: FieldMapper, tolerance: float = 1e-6):
        """
        Initialize connectivity analyzer.
        
        Args:
            layer: Vector layer containing network segments
            field_mapper: Field mapping utility
            tolerance: Coordinate tolerance for connection detection
        """
        self.layer = layer
        self.field_mapper = field_mapper
        self.tolerance = tolerance
        self._network_connections: Dict[str, NetworkConnection] = {}
        self._feature_endpoints: Dict[int, Tuple[QgsPointXY, QgsPointXY]] = {}
    
    def build_connectivity_map(self, feature_ids: Optional[List[int]] = None) -> None:
        """
        Build network connectivity map.
        
        Args:
            feature_ids: List of feature IDs to include, or None for all features
        """
        self._network_connections.clear()
        self._feature_endpoints.clear()
        
        try:
            # Get features to analyze
            if feature_ids is not None:
                features = [self.layer.getFeature(fid) for fid in feature_ids]
                features = [f for f in features if f.isValid()]
            else:
                features = list(self.layer.getFeatures())
            
            field_mapping = self.field_mapper.get_field_mapping()
            p1_h_idx = field_mapping.get('p1_h', -1)
            p2_h_idx = field_mapping.get('p2_h', -1)
            
            DebugLogger.log(f"Building connectivity map for {len(features)} features")
            
            for feature in features:
                self._process_feature_connectivity(feature, p1_h_idx, p2_h_idx)
            
            DebugLogger.log(f"Built connectivity map with {len(self._network_connections)} connection points")
            
        except Exception as e:
            DebugLogger.log_error("Error building connectivity map", e)
    
    def _process_feature_connectivity(self, feature: QgsFeature, p1_h_idx: int, p2_h_idx: int) -> None:
        """Process connectivity for a single feature."""
        try:
            # Extract endpoints
            geom = feature.geometry()
            if geom.isEmpty():
                return
            
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                if not lines or len(lines[0]) < 2:
                    return
                pts = lines[0]
            else:
                pts = geom.asPolyline()
                if len(pts) < 2:
                    return
            
            p1, p2 = QgsPointXY(pts[0]), QgsPointXY(pts[-1])
            self._feature_endpoints[feature.id()] = (p1, p2)
            
            # Get current depths
            p1_depth = self._get_depth_value(feature, p1_h_idx)
            p2_depth = self._get_depth_value(feature, p2_h_idx)
            
            # Add connections to network map
            p1_key = CoordinateUtils.node_key(p1)
            p2_key = CoordinateUtils.node_key(p2)
            
            # Ensure connection points exist
            if p1_key not in self._network_connections:
                self._network_connections[p1_key] = NetworkConnection(p1, self.tolerance)
            if p2_key not in self._network_connections:
                self._network_connections[p2_key] = NetworkConnection(p2, self.tolerance)
            
            # Add feature connections
            self._network_connections[p1_key].add_connection(feature.id(), 'p1', p1_depth)
            self._network_connections[p2_key].add_connection(feature.id(), 'p2', p2_depth)
            
        except Exception as e:
            DebugLogger.log_error(f"Error processing feature {feature.id()} connectivity", e)
    
    def _get_depth_value(self, feature: QgsFeature, field_idx: int) -> Optional[float]:
        """Get depth value from feature attribute."""
        if field_idx < 0:
            return None
        try:
            value = feature.attribute(field_idx)
            return float(value) if value not in (None, '') else None
        except (ValueError, TypeError):
            return None
    
    def find_affected_segments(self, changed_vertex_coords: List[QgsPointXY]) -> Dict[str, List[int]]:
        """
        Find segments affected by vertex coordinate changes.
        
        Args:
            changed_vertex_coords: List of coordinates that have changed
            
        Returns:
            Dictionary with 'directly_affected' and 'downstream_affected' feature lists
        """
        directly_affected = set()
        downstream_affected = set()
        
        try:
            for coord in changed_vertex_coords:
                node_key = CoordinateUtils.node_key(coord)
                
                if node_key in self._network_connections:
                    connection = self._network_connections[node_key]
                    
                    # All features connected to this vertex are directly affected
                    for conn_info in connection.connections:
                        directly_affected.add(conn_info.feature_id)
                    
                    # Find downstream affected segments
                    downstream_features = self._trace_downstream_from_node(connection)
                    downstream_affected.update(downstream_features)
            
            # Remove directly affected from downstream (no double-counting)
            downstream_affected = downstream_affected - directly_affected
            
            DebugLogger.log(f"Found {len(directly_affected)} directly affected and "
                          f"{len(downstream_affected)} downstream affected segments")
            
        except Exception as e:
            DebugLogger.log_error("Error finding affected segments", e)
        
        return {
            'directly_affected': list(directly_affected),
            'downstream_affected': list(downstream_affected)
        }
    
    def find_affected_segments_by_vertex_changes(self, vertex_changes) -> Dict[str, List[int]]:
        """
        Find segments affected by specific vertex changes (with old and new coordinates).
        
        Args:
            vertex_changes: List of VertexChange objects
            
        Returns:
            Dictionary with 'directly_affected' and 'downstream_affected' feature lists
        """
        directly_affected = set()
        downstream_affected = set()
        
        try:
            for change in vertex_changes:
                # The changed feature is always directly affected
                directly_affected.add(change.feature_id)
                
                # For downstream tracing, we need to check the current endpoints of the moved feature
                # to see what connects downstream from it
                if change.feature_id in self._feature_endpoints:
                    _, p2_coord = self._feature_endpoints[change.feature_id]
                    
                    # Check if the moved vertex was P2 (downstream end)
                    if change.vertex_type == 'p2':
                        # If P2 was moved, trace downstream from the NEW P2 position
                        p2_key = CoordinateUtils.node_key(change.new_coord)
                        DebugLogger.log(f"Checking downstream from moved P2 at {change.new_coord.x():.3f}, {change.new_coord.y():.3f}")
                    else:
                        # If P1 was moved, trace downstream from the unchanged P2 position
                        p2_key = CoordinateUtils.node_key(p2_coord)
                        DebugLogger.log(f"Checking downstream from unchanged P2 at {p2_coord.x():.3f}, {p2_coord.y():.3f}")
                    
                    if p2_key in self._network_connections:
                        connection = self._network_connections[p2_key]
                        downstream_features = self._trace_downstream_from_node(connection)
                        downstream_affected.update(downstream_features)
                        DebugLogger.log(f"Found {len(downstream_features)} downstream segments from feature {change.feature_id}")
                    else:
                        DebugLogger.log(f"No downstream connections found from feature {change.feature_id}")
                else:
                    DebugLogger.log(f"Feature {change.feature_id} endpoints not found in connectivity map")
            
            # Remove directly affected from downstream (no double-counting)
            downstream_affected = downstream_affected - directly_affected
            
            DebugLogger.log(f"Vertex changes analysis: {len(directly_affected)} directly affected, "
                          f"{len(downstream_affected)} downstream affected")
            
        except Exception as e:
            DebugLogger.log_error("Error finding affected segments by vertex changes", e)
        
        return {
            'directly_affected': list(directly_affected),
            'downstream_affected': list(downstream_affected)
        }
    
    def _trace_downstream_from_node(self, start_connection: NetworkConnection) -> Set[int]:
        """Trace all downstream segments from a connection point."""
        downstream_features = set()
        visited_nodes = set()
        nodes_to_visit = [start_connection]
        
        while nodes_to_visit:
            current_connection = nodes_to_visit.pop(0)
            node_key = current_connection.get_node_key()
            
            if node_key in visited_nodes:
                continue
            visited_nodes.add(node_key)
            
            # Get downstream connections from this node
            downstream_connections = current_connection.get_downstream_connections()
            
            for conn_info in downstream_connections:
                downstream_features.add(conn_info.feature_id)
                
                # Find where this segment ends (P2) and continue tracing
                if conn_info.feature_id in self._feature_endpoints:
                    _, p2 = self._feature_endpoints[conn_info.feature_id]
                    p2_key = CoordinateUtils.node_key(p2)
                    
                    if p2_key in self._network_connections and p2_key not in visited_nodes:
                        nodes_to_visit.append(self._network_connections[p2_key])
        
        return downstream_features
    
    def get_connection_at_point(self, coordinate: QgsPointXY) -> Optional[NetworkConnection]:
        """Get network connection at given coordinate."""
        node_key = CoordinateUtils.node_key(coordinate)
        return self._network_connections.get(node_key)
    
    def find_convergent_nodes(self) -> List[NetworkConnection]:
        """Find all convergent nodes in the network."""
        return [conn for conn in self._network_connections.values() if conn.is_convergent()]
    
    def find_divergent_nodes(self) -> List[NetworkConnection]:
        """Find all divergent nodes in the network."""
        return [conn for conn in self._network_connections.values() if conn.is_divergent()]
    
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
        issues = {
            'isolated_segments': [],
            'multiple_outlets': [],
            'circular_references': [],
            'missing_connections': []
        }
        
        try:
            # Find isolated segments (no connections)
            for node_key, connection in self._network_connections.items():
                if len(connection.connections) == 1:
                    conn_info = connection.connections[0]
                    issues['isolated_segments'].append(
                        f"Feature {conn_info.feature_id} has isolated {conn_info.vertex_type} at {connection.coordinate.x():.3f}, {connection.coordinate.y():.3f}"
                    )
            
            # Find multiple outlets (segments with no downstream connections)
            outlet_count = 0
            for connection in self._network_connections.values():
                if len(connection.get_downstream_connections()) == 0 and len(connection.get_upstream_connections()) > 0:
                    outlet_count += 1
            
            if outlet_count > 1:
                issues['multiple_outlets'].append(f"Network has {outlet_count} outlet points")
            
            # Additional validation could include circular reference detection
            
        except Exception as e:
            DebugLogger.log_error("Error validating network connectivity", e)
        
        return issues
    
    def get_network_statistics(self) -> Dict[str, int]:
        """Get network connectivity statistics."""
        try:
            convergent_nodes = len(self.find_convergent_nodes())
            divergent_nodes = len(self.find_divergent_nodes())
            total_connections = len(self._network_connections)
            total_features = len(self._feature_endpoints)
            
            return {
                'total_features': total_features,
                'total_connection_points': total_connections,
                'convergent_nodes': convergent_nodes,
                'divergent_nodes': divergent_nodes,
                'simple_nodes': total_connections - convergent_nodes - divergent_nodes
            }
        except Exception as e:
            DebugLogger.log_error("Error getting network statistics", e)
            return {}