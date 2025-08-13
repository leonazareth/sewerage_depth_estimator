# -*- coding: utf-8 -*-
"""
Network tree mapper with smart cascade logic for sewerage depth estimation.

This module implements the tree-based approach for handling vertex movements:
1. Maps network topology as tree structure
2. Handles convergent vertices with maximum depth rule
3. Implements smart cascade that only propagates when depths increase
4. Processes changes in proper upstream→downstream order
"""

from typing import Dict, List, Set, Optional, Tuple, NamedTuple
from qgis.core import QgsPointXY, QgsVectorLayer, QgsFeature
from ..utils import DebugLogger, CoordinateUtils
from ..data import FieldMapper
from .geometry_change_detector import VertexChange


class NetworkNode(NamedTuple):
    """Represents a node in the network tree."""
    coordinate: QgsPointXY
    key: str
    upstream_segments: List[int]  # Feature IDs of segments ending at this node
    downstream_segments: List[int]  # Feature IDs of segments starting from this node
    current_depth: Optional[float] = None
    is_convergent: bool = False


class NetworkSegment(NamedTuple):
    """Represents a segment in the network tree."""
    feature_id: int
    upstream_node_key: str
    downstream_node_key: str
    p1_coord: QgsPointXY
    p2_coord: QgsPointXY
    length: float
    p1_elevation: Optional[float] = None
    p2_elevation: Optional[float] = None
    p1_depth: Optional[float] = None
    p2_depth: Optional[float] = None


class TreeTraversalResult(NamedTuple):
    """Result of tree traversal operations."""
    processing_order: List[int]  # Feature IDs in processing order
    convergent_nodes: List[str]  # Node keys of convergent nodes
    root_segments: List[int]  # Feature IDs of root segments
    orphaned_segments: List[int]  # Feature IDs of orphaned segments


class NetworkTreeMapper:
    """
    Network tree mapper with smart cascade logic.
    
    This class provides comprehensive network topology analysis and implements
    the smart cascade algorithm for efficient depth recalculation:
    - Maps network as tree structure with proper ordering
    - Handles convergent vertices with maximum depth rule  
    - Only propagates depth changes when they would increase depths
    - Processes changes in correct upstream→downstream order
    """
    
    def __init__(self, layer: QgsVectorLayer, field_mapper: FieldMapper, tolerance: float = 1e-6):
        """
        Initialize the enhanced network tree mapper.
        
        Args:
            layer: Vector layer containing network segments
            field_mapper: Field mapping utility
            tolerance: Coordinate tolerance for node matching
        """
        self.layer = layer
        self.field_mapper = field_mapper
        self.tolerance = tolerance
        
        # Network structure
        self.nodes: Dict[str, NetworkNode] = {}
        self.segments: Dict[int, NetworkSegment] = {}
        
        # Change tracking
        self.topology_before_changes: Optional[Dict] = None
        self.topology_after_changes: Optional[Dict] = None
        
        # Processing state
        self.current_depths: Dict[str, float] = {}  # node_key -> current_depth
        self.updated_depths: Dict[str, float] = {}  # node_key -> new_depth
        
    def capture_topology_snapshot(self) -> Dict:
        """
        Capture current network topology for change comparison.
        
        Returns:
            Dictionary containing topology snapshot
        """
        try:
            DebugLogger.log("Capturing network topology snapshot...")
            
            # Build current network structure
            self._build_network_structure()
            
            snapshot = {
                'nodes': self.nodes.copy(),
                'segments': self.segments.copy(),
                'current_depths': self.current_depths.copy()
            }
            
            DebugLogger.log(f"Captured topology: {len(self.nodes)} nodes, {len(self.segments)} segments")
            return snapshot
            
        except Exception as e:
            DebugLogger.log_error("Error capturing topology snapshot", e)
            return {}
    
    def analyze_vertex_movement_impacts_comprehensive(self, vertex_changes: List[VertexChange]) -> Dict[str, List[int]]:
        """
        Comprehensive analysis of vertex movement impacts using tree-based approach.
        
        Args:
            vertex_changes: List of vertex coordinate changes
            
        Returns:
            Dictionary with comprehensive impact analysis
        """
        try:
            DebugLogger.log("Starting comprehensive vertex movement impact analysis...")
            
            # Step 1: Capture topology before changes
            self.topology_before_changes = self.capture_topology_snapshot()
            
            # Step 2: Apply vertex changes and rebuild topology
            self._apply_vertex_changes(vertex_changes)
            self._build_network_structure()
            self.topology_after_changes = self.capture_topology_snapshot()
            
            # Step 3: Analyze all types of impacts
            impacts = self._analyze_comprehensive_impacts(vertex_changes)
            
            # Step 4: Get proper processing order
            traversal_result = self._get_tree_traversal_order(impacts)
            impacts['processing_order'] = traversal_result.processing_order
            impacts['convergent_nodes'] = traversal_result.convergent_nodes
            impacts['root_segments'] = traversal_result.root_segments
            impacts['orphaned_segments'] = traversal_result.orphaned_segments
            
            DebugLogger.log(f"Comprehensive impact analysis complete: {len(impacts['processing_order'])} segments to process")
            return impacts
            
        except Exception as e:
            DebugLogger.log_error("Error in comprehensive vertex movement analysis", e)
            return {}
    
    def execute_smart_cascade_recalculation(self, impacts: Dict[str, List[int]], 
                                          depth_calculator, elevation_updates: Dict[int, Dict[str, float]]) -> Dict[str, List[int]]:
        """
        Execute smart cascade recalculation following tree-based algorithm.
        
        Args:
            impacts: Impact analysis results
            depth_calculator: Depth calculation utility
            elevation_updates: Dictionary of updated elevations
            
        Returns:
            Dictionary with recalculation results
        """
        try:
            # Initialize affected convergent nodes tracking if not already set
            if not hasattr(self, '_affected_convergent_nodes'):
                self._affected_convergent_nodes = set()
            
            # Restore affected convergent nodes from impacts
            if 'affected_convergent_nodes' in impacts:
                for node_key in impacts['affected_convergent_nodes']:
                    self._affected_convergent_nodes.add(node_key)
                    DebugLogger.log(f"Restored affected convergent node: {node_key}")
            
            DebugLogger.log("Starting smart cascade recalculation...")
            
            recalculation_results = {
                'recalculated_segments': [],
                'cascade_stopped_at': [],
                'convergent_updates': [],
                'no_change_needed': []
            }
            
            # Process segments in proper tree order
            processing_order = impacts.get('processing_order', [])
            convergent_nodes = set(impacts.get('convergent_nodes', []))
            
            for feature_id in processing_order:
                try:
                    result = self._process_segment_smart_cascade(
                        feature_id, depth_calculator, elevation_updates, convergent_nodes
                    )
                    
                    # Categorize result
                    if result['recalculated']:
                        recalculation_results['recalculated_segments'].append(feature_id)
                        
                        if result['cascade_stopped']:
                            recalculation_results['cascade_stopped_at'].append(feature_id)
                        
                        if result['convergent_update']:
                            recalculation_results['convergent_updates'].append(feature_id)
                    else:
                        recalculation_results['no_change_needed'].append(feature_id)
                        
                except Exception as e:
                    DebugLogger.log_error(f"Error processing segment {feature_id}", e)
            
            total_processed = len(recalculation_results['recalculated_segments'])
            DebugLogger.log(f"Smart cascade complete: {total_processed} segments recalculated")
            
            return recalculation_results
            
        except Exception as e:
            DebugLogger.log_error("Error in smart cascade recalculation", e)
            return {}
    
    def _build_network_structure(self) -> None:
        """Build complete network structure with nodes and segments."""
        try:
            self.nodes.clear()
            self.segments.clear()
            self.current_depths.clear()
            
            # Get field mapping
            field_mapping = self.field_mapper.get_field_mapping()
            p1_elev_idx = field_mapping.get('p1_elev', -1)
            p2_elev_idx = field_mapping.get('p2_elev', -1)
            p1_h_idx = field_mapping.get('p1_h', -1)
            p2_h_idx = field_mapping.get('p2_h', -1)
            
            # Process all features
            for feature in self.layer.getFeatures():
                if not feature.isValid():
                    continue
                
                # Extract geometry endpoints
                p1, p2 = self._extract_feature_endpoints(feature)
                if not p1 or not p2:
                    continue
                
                # Create node keys
                p1_key = CoordinateUtils.node_key(p1)
                p2_key = CoordinateUtils.node_key(p2)
                
                # Get elevations and depths
                p1_elev = self._get_field_value(feature, p1_elev_idx)
                p2_elev = self._get_field_value(feature, p2_elev_idx)
                p1_depth = self._get_field_value(feature, p1_h_idx)
                p2_depth = self._get_field_value(feature, p2_h_idx)
                
                # Calculate segment length
                segment_length = CoordinateUtils.point_distance_2d(p1, p2)
                
                # Create segment
                segment = NetworkSegment(
                    feature_id=feature.id(),
                    upstream_node_key=p1_key,
                    downstream_node_key=p2_key,
                    p1_coord=p1,
                    p2_coord=p2,
                    length=segment_length,
                    p1_elevation=p1_elev,
                    p2_elevation=p2_elev,
                    p1_depth=p1_depth,
                    p2_depth=p2_depth
                )
                self.segments[feature.id()] = segment
                
                # Create or update nodes
                self._update_node(p1_key, p1, upstream_segment=None, downstream_segment=feature.id(), depth=p1_depth)
                self._update_node(p2_key, p2, upstream_segment=feature.id(), downstream_segment=None, depth=p2_depth)
            
            # Identify convergent nodes
            self._identify_convergent_nodes()
            
            DebugLogger.log(f"Built network structure: {len(self.nodes)} nodes, {len(self.segments)} segments")
            
        except Exception as e:
            DebugLogger.log_error("Error building network structure", e)
    
    def _update_node(self, node_key: str, coordinate: QgsPointXY, 
                    upstream_segment: Optional[int] = None, 
                    downstream_segment: Optional[int] = None,
                    depth: Optional[float] = None) -> None:
        """Update or create a network node."""
        if node_key in self.nodes:
            # Update existing node
            existing = self.nodes[node_key]
            upstream_segments = list(existing.upstream_segments)
            downstream_segments = list(existing.downstream_segments)
            
            if upstream_segment is not None and upstream_segment not in upstream_segments:
                upstream_segments.append(upstream_segment)
            if downstream_segment is not None and downstream_segment not in downstream_segments:
                downstream_segments.append(downstream_segment)
            
            # Update depth if provided and current is None
            current_depth = existing.current_depth
            if depth is not None and current_depth is None:
                current_depth = depth
                self.current_depths[node_key] = depth
                
            self.nodes[node_key] = NetworkNode(
                coordinate=coordinate,
                key=node_key,
                upstream_segments=upstream_segments,
                downstream_segments=downstream_segments,
                current_depth=current_depth
            )
        else:
            # Create new node
            upstream_segments = [upstream_segment] if upstream_segment is not None else []
            downstream_segments = [downstream_segment] if downstream_segment is not None else []
            
            if depth is not None:
                self.current_depths[node_key] = depth
            
            self.nodes[node_key] = NetworkNode(
                coordinate=coordinate,
                key=node_key,
                upstream_segments=upstream_segments,
                downstream_segments=downstream_segments,
                current_depth=depth
            )
    
    def _identify_convergent_nodes(self) -> None:
        """Identify convergent nodes (nodes with multiple upstream segments)."""
        for node_key, node in self.nodes.items():
            is_convergent = len(node.upstream_segments) > 1
            if is_convergent:
                self.nodes[node_key] = node._replace(is_convergent=True)
                DebugLogger.log(f"Identified convergent node {node_key} with {len(node.upstream_segments)} upstream segments")
    
    def _analyze_comprehensive_impacts(self, vertex_changes: List[VertexChange]) -> Dict[str, List[int]]:
        """Analyze all types of impacts from vertex changes."""
        impacts = {
            'directly_moved': [],
            'newly_connected': [],
            'newly_disconnected': [],
            'topology_changed': [],
            'downstream_cascade': [],
            'convergent_affected': [],
            'elevation_updates_needed': [],
            'orphaned_segments': []
        }
        
        try:
            # Collect directly moved segments
            for change in vertex_changes:
                impacts['directly_moved'].append(change.feature_id)
                
                # Check for topology changes
                if self._has_topology_change(change):
                    impacts['topology_changed'].append(change.feature_id)
                
                # Check if elevation update needed
                impacts['elevation_updates_needed'].append(change.feature_id)
                
                # Check for disconnections that create orphaned segments
                orphaned = self._find_orphaned_segments_from_change(change)
                impacts['orphaned_segments'].extend(orphaned)
            
            # Find all downstream segments from moved segments
            for feature_id in impacts['directly_moved']:
                downstream_segments = self._get_all_downstream_segments(feature_id)
                impacts['downstream_cascade'].extend(downstream_segments)
            
            # Find segments affected by convergent nodes
            convergent_affected = self._get_convergent_affected_segments()
            impacts['convergent_affected'].extend(convergent_affected)
            
            # Add orphaned segments and their downstream chains to processing
            for orphaned_id in impacts['orphaned_segments']:
                downstream_from_orphaned = self._get_all_downstream_segments(orphaned_id)
                impacts['downstream_cascade'].extend(downstream_from_orphaned)
                
            # For P2 movements that disconnect from convergent nodes,
            # add downstream segments from affected convergent nodes
            for change in vertex_changes:
                if change.vertex_type == 'p2':
                    old_key = CoordinateUtils.node_key(change.old_coord)
                    
                    # Find convergent nodes at the old P2 location
                    for node_key, node in self.nodes.items():
                        if node.is_convergent and node_key == old_key:
                            # This convergent node lost an upstream connection
                            DebugLogger.log(f"Convergent node {node_key} affected by P2 disconnection")
                            
                            # Mark this convergent node for recalculation
                            self._mark_convergent_node_affected(node_key)
                            
                            # Also store in impacts for cascade processing
                            if 'affected_convergent_nodes' not in impacts:
                                impacts['affected_convergent_nodes'] = []
                            impacts['affected_convergent_nodes'].append(node_key)
                            
                            # Add all downstream segments to be recalculated
                            for downstream_seg_id in node.downstream_segments:
                                if downstream_seg_id not in impacts['downstream_cascade']:
                                    impacts['downstream_cascade'].append(downstream_seg_id)
                                    DebugLogger.log(f"Added downstream segment {downstream_seg_id} from affected convergent node", "depth_calc")
                                    
                                    # Also add the entire downstream chain  
                                    chain = self._get_all_downstream_segments(downstream_seg_id)
                                    impacts['downstream_cascade'].extend(chain)
            
            # Remove duplicates
            for key in impacts:
                impacts[key] = list(set(impacts[key]))
            
            DebugLogger.log(f"Impact analysis: {len(impacts['directly_moved'])} moved, "
                          f"{len(impacts['downstream_cascade'])} downstream, "
                          f"{len(impacts['convergent_affected'])} convergent affected, "
                          f"{len(impacts['orphaned_segments'])} orphaned")
            
        except Exception as e:
            DebugLogger.log_error("Error in comprehensive impact analysis", e)
        
        return impacts
    
    def _get_tree_traversal_order(self, impacts: Dict[str, List[int]]) -> TreeTraversalResult:
        """Get proper tree traversal order for processing segments."""
        try:
            # Get all affected segments
            all_affected = set()
            for impact_list in impacts.values():
                if isinstance(impact_list, list):
                    all_affected.update(impact_list)
            
            # Identify root segments (no upstream connections)
            root_segments = []
            orphaned_segments = []
            
            for feature_id in all_affected:
                if feature_id not in self.segments:
                    continue
                
                segment = self.segments[feature_id]
                upstream_node = self.nodes.get(segment.upstream_node_key)
                
                if not upstream_node or len(upstream_node.upstream_segments) == 0:
                    root_segments.append(feature_id)
                elif len(upstream_node.upstream_segments) == 0:
                    orphaned_segments.append(feature_id)
            
            # Get processing order using topological sort
            processing_order = self._topological_sort_segments(all_affected)
            
            # Identify convergent nodes in affected area
            convergent_nodes = []
            for node_key, node in self.nodes.items():
                if node.is_convergent:
                    # Check if any upstream segments are affected
                    if any(seg_id in all_affected for seg_id in node.upstream_segments):
                        convergent_nodes.append(node_key)
            
            return TreeTraversalResult(
                processing_order=processing_order,
                convergent_nodes=convergent_nodes,
                root_segments=root_segments,
                orphaned_segments=orphaned_segments
            )
            
        except Exception as e:
            DebugLogger.log_error("Error getting tree traversal order", e)
            return TreeTraversalResult([], [], [], [])
    
    def _topological_sort_segments(self, segment_ids: Set[int]) -> List[int]:
        """Perform topological sort on segments to get proper processing order."""
        try:
            # Build dependency graph for affected segments
            in_degree = {}
            graph = {}
            
            for seg_id in segment_ids:
                in_degree[seg_id] = 0
                graph[seg_id] = []
            
            # Calculate in-degrees and build adjacency list
            for seg_id in segment_ids:
                segment = self.segments.get(seg_id)
                if not segment:
                    continue
                
                upstream_node = self.nodes.get(segment.upstream_node_key)
                if upstream_node:
                    # Count upstream segments that are also in our affected set
                    upstream_affected = [us for us in upstream_node.upstream_segments if us in segment_ids]
                    in_degree[seg_id] = len(upstream_affected)
                    
                    # Add edges from upstream segments to this segment
                    for upstream_seg_id in upstream_affected:
                        if upstream_seg_id in graph:
                            graph[upstream_seg_id].append(seg_id)
            
            # Kahn's algorithm for topological sorting
            queue = [seg_id for seg_id in segment_ids if in_degree[seg_id] == 0]
            result = []
            
            while queue:
                current = queue.pop(0)
                result.append(current)
                
                # Reduce in-degree of downstream segments
                for neighbor in graph.get(current, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            
            # If not all segments are in result, there might be a cycle
            if len(result) != len(segment_ids):
                DebugLogger.log("Warning: Possible cycle detected in network topology")
                # Add remaining segments
                remaining = segment_ids - set(result)
                result.extend(list(remaining))
            
            DebugLogger.log(f"Topological sort complete: {len(result)} segments in order")
            return result
            
        except Exception as e:
            DebugLogger.log_error("Error in topological sort", e)
            return list(segment_ids)
    
    def _process_segment_smart_cascade(self, feature_id: int, depth_calculator, 
                                     elevation_updates: Dict[int, Dict[str, float]],
                                     convergent_nodes: Set[str]) -> Dict[str, bool]:
        """Process a single segment with smart cascade logic."""
        result = {
            'recalculated': False,
            'cascade_stopped': False,
            'convergent_update': False,
            'depth_changed': False
        }
        
        try:
            segment = self.segments.get(feature_id)
            if not segment:
                return result
            
            # Get current elevations (with any updates)
            p1_elev = self._get_updated_elevation(feature_id, 'p1', segment.p1_elevation, elevation_updates)
            p2_elev = self._get_updated_elevation(feature_id, 'p2', segment.p2_elevation, elevation_updates)
            
            if p1_elev is None or p2_elev is None:
                DebugLogger.log(f"Missing elevations for segment {feature_id}, skipping")
                return result
            
            # Get upstream depth using smart logic
            upstream_depth = self._get_upstream_depth_smart(segment, convergent_nodes, depth_calculator)
            
            # Calculate new depths
            p1_depth, p2_depth = depth_calculator.calculate_segment_depths(
                upstream_depth, p1_elev, p2_elev, segment.length
            )
            
            # Check if we should update this segment
            current_p2_depth = self.current_depths.get(segment.downstream_node_key)
            depth_increase_threshold = 0.01  # 1cm threshold
            
            # Always recalculate if:
            # 1. No current depth exists
            # 2. Depth would increase significantly 
            # 3. This is a topology change (disconnection/reconnection)
            # 4. This segment was directly affected by vertex movement
            should_recalculate = (
                current_p2_depth is None or 
                p2_depth > current_p2_depth + depth_increase_threshold or
                abs(p2_depth - current_p2_depth) > 0.1  # Significant change (10cm) 
            )
            
            if should_recalculate:
                # Update depths
                success = self._update_segment_depths(feature_id, p1_depth, p2_depth)
                if success:
                    result['recalculated'] = True
                    result['depth_changed'] = True
                    
                    # Update our tracking
                    self.updated_depths[segment.upstream_node_key] = p1_depth
                    self.updated_depths[segment.downstream_node_key] = p2_depth
                    
                    # Check if this is a convergent node update
                    if segment.downstream_node_key in convergent_nodes:
                        result['convergent_update'] = True
                        self._update_convergent_node_depth(segment.downstream_node_key, p2_depth)
                    
                    DebugLogger.log(f"Updated segment {feature_id}: P1={p1_depth:.2f}m, P2={p2_depth:.2f}m")
                else:
                    DebugLogger.log_error(f"Failed to update depths for segment {feature_id}")
            else:
                # Only stop cascade if change is truly minimal and not a topology change
                if abs(p2_depth - current_p2_depth) < depth_increase_threshold:
                    result['cascade_stopped'] = True
                    DebugLogger.log(f"Cascade stopped at segment {feature_id}: no significant depth increase")
                else:
                    # Update anyway for consistency
                    success = self._update_segment_depths(feature_id, p1_depth, p2_depth)
                    if success:
                        result['recalculated'] = True
                        self.updated_depths[segment.upstream_node_key] = p1_depth
                        self.updated_depths[segment.downstream_node_key] = p2_depth
                        DebugLogger.log(f"Updated segment {feature_id} for consistency: P1={p1_depth:.2f}m, P2={p2_depth:.2f}m")
            
        except Exception as e:
            DebugLogger.log_error(f"Error processing segment {feature_id} in smart cascade", e)
        
        return result
    
    def _get_upstream_depth_smart(self, segment: NetworkSegment, convergent_nodes: Set[str], depth_calculator=None) -> float:
        """Get upstream depth using smart logic for different scenarios."""
        upstream_node_key = segment.upstream_node_key
        upstream_node = self.nodes.get(upstream_node_key)
        
        # Case 1: No upstream connections (root segment or orphaned)
        if not upstream_node or len(upstream_node.upstream_segments) == 0:
            # Use minimum depth for root/orphaned segments - get from depth_calculator if available
            min_depth = self._get_minimum_depth(depth_calculator)
            DebugLogger.log(f"Segment {segment.feature_id}: No upstream connections, using minimum depth {min_depth:.2f}m")
            return min_depth
        
        # Case 2: Convergent node - use maximum depth
        if upstream_node_key in convergent_nodes or upstream_node.is_convergent:
            # For P2 movements that affect convergent nodes, force recalculation
            force_recalc = self._should_force_convergent_recalculation(upstream_node_key)
            max_depth = self._get_convergent_node_max_depth(upstream_node_key, depth_calculator, force_recalc)
            DebugLogger.log(f"Segment {segment.feature_id}: Convergent node, using max depth {max_depth:.2f}m")
            return max_depth
        
        # Case 3: Single upstream connection - use upstream depth
        if len(upstream_node.upstream_segments) == 1:
            upstream_seg_id = upstream_node.upstream_segments[0]
            upstream_segment = self.segments.get(upstream_seg_id)
            if upstream_segment:
                # Use updated depth if available, otherwise current depth
                depth = (self.updated_depths.get(upstream_node_key) or 
                        self.current_depths.get(upstream_node_key) or 
                        self._get_minimum_depth(depth_calculator))
                DebugLogger.log(f"Segment {segment.feature_id}: Single upstream connection, using depth {depth:.2f}m")
                return depth
        
        # Fallback
        min_depth = self._get_minimum_depth(depth_calculator)
        DebugLogger.log(f"Segment {segment.feature_id}: Fallback to minimum depth {min_depth:.2f}m")
        return min_depth
    
    def _get_convergent_node_max_depth(self, node_key: str, depth_calculator=None, force_recalculate=False) -> float:
        """Get maximum depth at convergent node from all upstream segments."""
        node = self.nodes.get(node_key)
        if not node:
            return self._get_minimum_depth(depth_calculator)
        
        max_depth = 0.0
        connected_segments = 0
        
        for upstream_seg_id in node.upstream_segments:
            upstream_segment = self.segments.get(upstream_seg_id)
            if upstream_segment:
                # Check if this segment is still actually connected at this convergent node
                if upstream_segment.downstream_node_key == node_key:
                    # Get the downstream depth of the upstream segment
                    upstream_downstream_key = upstream_segment.downstream_node_key
                    
                    # Get the current depth - prefer updated, then current
                    depth = (self.updated_depths.get(upstream_downstream_key) or 
                            self.current_depths.get(upstream_downstream_key))
                    
                    if depth is not None and not force_recalculate:
                        # Use existing depth value only if not forcing recalculation
                        DebugLogger.log(f"Convergent node {node_key}: upstream segment {upstream_seg_id} depth = {depth:.2f}m")
                    else:
                        # Force recalculation or no current depth - recalculate from actual upstream chain
                        recalc_depth = self._recalculate_segment_from_source(upstream_seg_id, depth_calculator)
                        if force_recalculate:
                            DebugLogger.log(f"Convergent node {node_key}: force recalculated upstream segment {upstream_seg_id} depth = {recalc_depth:.2f}m (was {depth:.2f}m)")
                            depth = recalc_depth
                        else:
                            DebugLogger.log(f"Convergent node {node_key}: no current depth for segment {upstream_seg_id}, recalculated = {recalc_depth:.2f}m")
                            depth = recalc_depth
                    
                    max_depth = max(max_depth, depth)
                    connected_segments += 1
                else:
                    DebugLogger.log(f"Convergent node {node_key}: upstream segment {upstream_seg_id} no longer connected")
        
        # If no segments are connected, use minimum depth
        if connected_segments == 0:
            max_depth = self._get_minimum_depth(depth_calculator)
            DebugLogger.log(f"Convergent node {node_key}: no connected segments, using minimum depth {max_depth:.2f}m")
        else:
            DebugLogger.log(f"Convergent node {node_key}: max depth {max_depth:.2f}m from {connected_segments} connected segments")
        
        return max_depth
    
    def _recalculate_segment_from_source(self, segment_id: int, depth_calculator) -> float:
        """Recalculate a segment's downstream depth by using current network state."""
        segment = self.segments.get(segment_id)
        if not segment:
            return self._get_minimum_depth(depth_calculator)
        
        # Get the segment's upstream node
        upstream_node = self.nodes.get(segment.upstream_node_key)
        
        # If no upstream node or no upstream segments, this is a root - use minimum depth
        if not upstream_node or len(upstream_node.upstream_segments) == 0:
            DebugLogger.log(f"Segment {segment_id} is root, using minimum depth")
            return self._calculate_segment_with_upstream_depth(segment_id, self._get_minimum_depth(depth_calculator), depth_calculator)
        
        # If single upstream segment, get its current downstream depth
        elif len(upstream_node.upstream_segments) == 1:
            upstream_seg_id = upstream_node.upstream_segments[0]
            upstream_segment = self.segments.get(upstream_seg_id)
            if upstream_segment:
                # Get current depth at the connection point (the downstream depth of upstream segment)
                upstream_downstream_key = upstream_segment.downstream_node_key
                upstream_depth = (self.updated_depths.get(upstream_downstream_key) or 
                                self.current_depths.get(upstream_downstream_key))
                
                if upstream_depth is not None:
                    DebugLogger.log(f"Segment {segment_id} single upstream, using current depth {upstream_depth:.2f}m")
                    return self._calculate_segment_with_upstream_depth(segment_id, upstream_depth, depth_calculator)
                else:
                    DebugLogger.log(f"Segment {segment_id} single upstream, no current depth - using minimum")
                    return self._calculate_segment_with_upstream_depth(segment_id, self._get_minimum_depth(depth_calculator), depth_calculator)
        
        # If convergent node, this should not be recalculated individually - use minimum
        else:
            DebugLogger.log(f"Segment {segment_id} at convergent node, using minimum depth")
            return self._calculate_segment_with_upstream_depth(segment_id, self._get_minimum_depth(depth_calculator), depth_calculator)
        
        # Fallback
        return self._get_minimum_depth(depth_calculator)
    
    def _calculate_segment_with_upstream_depth(self, segment_id: int, upstream_depth: float, depth_calculator) -> float:
        """Calculate a segment's downstream depth given its upstream depth."""
        segment = self.segments.get(segment_id)
        if not segment:
            return self._get_minimum_depth(depth_calculator)
        
        # Get elevations from the segment
        p1_elev = getattr(segment, 'p1_elevation', None)
        p2_elev = getattr(segment, 'p2_elevation', None)
        
        if p1_elev is None or p2_elev is None:
            DebugLogger.log(f"Missing elevations for segment {segment_id}")
            return upstream_depth
        
        # Calculate with given upstream depth
        try:
            p1_depth, p2_depth = depth_calculator.calculate_segment_depths(
                upstream_depth, p1_elev, p2_elev, segment.length
            )
            DebugLogger.log(f"Segment {segment_id} calculated: {upstream_depth:.2f}m -> {p2_depth:.2f}m")
            return p2_depth
        except Exception as e:
            DebugLogger.log(f"Error calculating depth for segment {segment_id}: {e}")
            return upstream_depth
    
    def _calculate_forward_to_segment(self, root_seg_id: int, target_seg_id: int, depth_calculator) -> float:
        """Calculate depths forward from root segment to target segment."""
        if root_seg_id == target_seg_id:
            # If target is the root, calculate its downstream depth directly
            root_segment = self.segments.get(root_seg_id)
            if not root_segment:
                return self._get_minimum_depth(depth_calculator)
            
            # Get elevations from the segment
            p1_elev = getattr(root_segment, 'p1_elevation', None)
            p2_elev = getattr(root_segment, 'p2_elevation', None)
            
            if p1_elev is None or p2_elev is None:
                return self._get_minimum_depth(depth_calculator)
            
            # Calculate with minimum depth as upstream
            min_depth = self._get_minimum_depth(depth_calculator)
            p1_depth, p2_depth = depth_calculator.calculate_segment_depths(
                min_depth, p1_elev, p2_elev, root_segment.length
            )
            return p2_depth
        
        # For more complex tracing, implement breadth-first search
        # For now, simplified approach - return minimum depth
        DebugLogger.log(f"Complex path tracing from {root_seg_id} to {target_seg_id} - using minimum depth")
        return self._get_minimum_depth(depth_calculator)
    
    def _should_force_convergent_recalculation(self, node_key: str) -> bool:
        """Check if convergent node should force recalculation due to disconnections."""
        # Track convergent nodes that have been affected by P2 movements
        if not hasattr(self, '_affected_convergent_nodes'):
            self._affected_convergent_nodes = set()
        
        return node_key in self._affected_convergent_nodes
    
    def _mark_convergent_node_affected(self, node_key: str) -> None:
        """Mark a convergent node as affected by disconnection."""
        if not hasattr(self, '_affected_convergent_nodes'):
            self._affected_convergent_nodes = set()
        
        self._affected_convergent_nodes.add(node_key)
        DebugLogger.log(f"Marked convergent node {node_key} as affected by disconnection")

    def _update_convergent_node_depth(self, node_key: str, new_depth: float) -> None:
        """Update convergent node depth with maximum rule."""
        current_depth = self.updated_depths.get(node_key, 0.0)
        if new_depth > current_depth:
            self.updated_depths[node_key] = new_depth
            DebugLogger.log(f"Updated convergent node {node_key} depth to {new_depth:.2f}m")
    
    # Helper methods
    def _apply_vertex_changes(self, vertex_changes: List[VertexChange]) -> None:
        """Apply vertex changes to layer (conceptually - for topology analysis)."""
        # This would be used to simulate the changes for topology analysis
        # In practice, the changes are already applied to the layer
        pass
    
    def _extract_feature_endpoints(self, feature: QgsFeature) -> Tuple[Optional[QgsPointXY], Optional[QgsPointXY]]:
        """Extract start and end points from feature geometry."""
        try:
            geom = feature.geometry()
            if geom.isEmpty():
                return None, None
            
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                if not lines:
                    return None, None
                points = lines[0]
            else:
                points = geom.asPolyline()
            
            if len(points) < 2:
                return None, None
            
            return QgsPointXY(points[0]), QgsPointXY(points[-1])
            
        except Exception:
            return None, None
    
    def _get_field_value(self, feature: QgsFeature, field_idx: int) -> Optional[float]:
        """Get numeric field value from feature."""
        if field_idx < 0:
            return None
        
        try:
            value = feature.attribute(field_idx)
            if value is None or value == '':
                return None
            return float(value)
        except:
            return None
    
    def _has_topology_change(self, change: VertexChange) -> bool:
        """Check if vertex change results in topology change."""
        # Compare before/after topology for this specific change
        # This is a simplified check - in practice would compare connectivity
        return True  # Assume topology changes for now
    
    def _get_all_downstream_segments(self, feature_id: int) -> List[int]:
        """Get all downstream segments from a given segment."""
        downstream = []
        try:
            segment = self.segments.get(feature_id)
            if not segment:
                return downstream
            
            # Use breadth-first search to find all downstream segments
            visited = set()
            queue = [segment.downstream_node_key]
            
            while queue:
                node_key = queue.pop(0)
                if node_key in visited:
                    continue
                visited.add(node_key)
                
                node = self.nodes.get(node_key)
                if node:
                    for downstream_seg_id in node.downstream_segments:
                        if downstream_seg_id not in downstream:
                            downstream.append(downstream_seg_id)
                            # Add the downstream node of this segment to queue
                            downstream_segment = self.segments.get(downstream_seg_id)
                            if downstream_segment:
                                queue.append(downstream_segment.downstream_node_key)
            
        except Exception as e:
            DebugLogger.log_error(f"Error getting downstream segments for {feature_id}", e)
        
        return downstream
    
    def _get_convergent_affected_segments(self) -> List[int]:
        """Get segments affected by convergent nodes."""
        affected = []
        for node_key, node in self.nodes.items():
            if node.is_convergent:
                # Add all downstream segments from convergent nodes
                affected.extend(node.downstream_segments)
        return affected
    
    def _find_orphaned_segments_from_change(self, change: VertexChange) -> List[int]:
        """Find segments that became orphaned due to vertex change."""
        orphaned = []
        try:
            # Compare topology before and after to find disconnected segments
            if not self.topology_before_changes or not self.topology_after_changes:
                return orphaned
            
            before_connections = self.topology_before_changes.get('connections', {})
            after_connections = self.topology_after_changes.get('connections', {})
            
            # For the moved vertex, check what connections were lost
            if change.vertex_type == 'p2':
                # Moving P2 can disconnect segments that were previously connected to that point
                old_key = CoordinateUtils.node_key(change.old_coord)
                new_key = CoordinateUtils.node_key(change.new_coord)
                
                # Find segments that lost their upstream connection when P2 moved away
                old_node = before_connections.get(old_key)
                new_node = after_connections.get(old_key)  # Check what's still at the old location
                
                if old_node:
                    # Get segments that were downstream from the old P2 position
                    previously_connected_segments = old_node.downstream_segments.copy()
                    
                    # Remove the moved segment itself from the list
                    if change.feature_id in previously_connected_segments:
                        previously_connected_segments.remove(change.feature_id)
                    
                    # Check each previously connected segment
                    for seg_id in previously_connected_segments:
                        segment = self.segments.get(seg_id)
                        if segment:
                            # Check if this segment still has an upstream connection at the OLD location
                            upstream_node_key = segment.upstream_node_key
                            
                            # If this segment was connected at the old P2 location, it's now disconnected
                            if upstream_node_key == old_key:
                                orphaned.append(seg_id)
                                DebugLogger.log(f"Segment {seg_id} orphaned due to P2 movement - no longer connected at {old_key}")
                            else:
                                # Check if upstream connections were reduced
                                current_upstream_node = after_connections.get(upstream_node_key)
                                old_upstream_count = len(old_node.upstream_segments) if old_node else 0
                                new_upstream_count = len(current_upstream_node.upstream_segments) if current_upstream_node else 0
                                
                                if old_upstream_count > new_upstream_count and new_upstream_count == 0:
                                    orphaned.append(seg_id) 
                                    DebugLogger.log(f"Segment {seg_id} orphaned due to P2 movement - lost all upstream connections")
            
            elif change.vertex_type == 'p1':
                # Moving P1 can disconnect this segment from its upstream
                feature_id = change.feature_id
                segment = self.segments.get(feature_id)
                if segment:
                    new_upstream_key = segment.upstream_node_key
                    new_node = after_connections.get(new_upstream_key)
                    if not new_node or len(new_node.upstream_segments) == 0:
                        orphaned.append(feature_id)
                        DebugLogger.log(f"Segment {feature_id} orphaned due to P1 movement")
                        
                        # Also check if any segments were previously connected that are now orphaned
                        old_key = CoordinateUtils.node_key(change.old_coord)
                        old_node = before_connections.get(old_key)
                        if old_node:
                            for connected_seg_id in old_node.downstream_segments:
                                if connected_seg_id != feature_id:
                                    # Check if this segment is now disconnected
                                    connected_segment = self.segments.get(connected_seg_id)
                                    if connected_segment:
                                        connected_upstream_key = connected_segment.upstream_node_key
                                        connected_new_node = after_connections.get(connected_upstream_key)
                                        if not connected_new_node or len(connected_new_node.upstream_segments) == 0:
                                            orphaned.append(connected_seg_id)
                                            DebugLogger.log(f"Segment {connected_seg_id} orphaned due to P1 movement disconnection")
            
        except Exception as e:
            DebugLogger.log_error("Error finding orphaned segments", e)
        
        return orphaned
    
    def _get_updated_elevation(self, feature_id: int, vertex_type: str, 
                             current_elevation: Optional[float],
                             elevation_updates: Dict[int, Dict[str, float]]) -> Optional[float]:
        """Get elevation with any updates applied."""
        updates = elevation_updates.get(feature_id, {})
        updated_elev = updates.get(f'{vertex_type}_elev')
        return updated_elev if updated_elev is not None else current_elevation
    
    def _update_segment_depths(self, feature_id: int, p1_depth: float, p2_depth: float) -> bool:
        """Update segment depth attributes in the layer."""
        try:
            field_mapping = self.field_mapper.get_field_mapping()
            p1_h_idx = field_mapping.get('p1_h', -1)
            p2_h_idx = field_mapping.get('p2_h', -1)
            
            if p1_h_idx < 0 or p2_h_idx < 0:
                return False
            
            # Ensure layer is editable
            if not self.layer.isEditable():
                self.layer.startEditing()
            
            # Update attributes
            success1 = self.layer.changeAttributeValue(feature_id, p1_h_idx, round(p1_depth, 2))
            success2 = self.layer.changeAttributeValue(feature_id, p2_h_idx, round(p2_depth, 2))
            
            return success1 and success2
            
        except Exception as e:
            DebugLogger.log_error(f"Error updating depths for segment {feature_id}", e)
            return False
    
    def _get_minimum_depth(self, depth_calculator=None) -> float:
        """Get minimum depth for root/orphaned segments."""
        if depth_calculator:
            # Use actual parameters from depth calculator
            return depth_calculator.calculate_minimum_depth()
        else:
            # Fallback to default calculation
            min_cover = 0.9  # meters
            diameter = 0.15  # meters  
            return min_cover + diameter
