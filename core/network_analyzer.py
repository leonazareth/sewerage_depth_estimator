# -*- coding: utf-8 -*-
"""
Network topology analysis and tree traversal algorithms.
"""

from typing import List, Dict, Set, Tuple, Optional
from qgis.core import QgsPointXY, QgsVectorLayer, QgsFeature, QgsWkbTypes
from ..utils import DebugLogger, CoordinateUtils
from ..data import FieldMapper
from .depth_calculator import DepthCalculator


class NetworkAnalyzer:
    """Analyzes sewerage network topology and calculates depths using tree traversal."""
    
    def __init__(self, layer: QgsVectorLayer, field_mapper: FieldMapper, 
                 depth_calculator: DepthCalculator):
        """
        Initialize network analyzer.
        
        Args:
            layer: Vector layer containing network segments
            field_mapper: Field mapping utility
            depth_calculator: Depth calculation utility
        """
        self.layer = layer
        self.field_mapper = field_mapper
        self.depth_calculator = depth_calculator
    
    def build_network_topology(self, features: List[QgsFeature]) -> Tuple[List[dict], Dict[str, List[Tuple[int, bool]]]]:
        """
        Build network topology from features.
        
        Args:
            features: List of line features
            
        Returns:
            Tuple of (segments, node_connections)
            - segments: List of segment data dictionaries
            - node_connections: Dict mapping node keys to list of (segment_idx, is_upstream)
        """
        segments = []
        node_connections = {}
        
        field_mapping = self.field_mapper.get_field_mapping()
        p1_elev_idx = field_mapping['p1_elev']
        p2_elev_idx = field_mapping['p2_elev']
        
        DebugLogger.log("Building network topology...")
        
        for i, feature in enumerate(features):
            segment_data = self._extract_segment_data(feature, i, p1_elev_idx, p2_elev_idx)
            if segment_data:
                segments.append(segment_data)
                self._update_topology(segment_data, i, node_connections)
        
        DebugLogger.log(f"Built topology: {len(segments)} segments, {len(node_connections)} nodes")
        return segments, node_connections
    
    def _extract_segment_data(self, feature: QgsFeature, index: int, 
                            p1_elev_idx: int, p2_elev_idx: int) -> Optional[dict]:
        """Extract segment data from feature."""
        try:
            geom = feature.geometry()
            if geom.isEmpty():
                return None
                
            # Get segment endpoints
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                if not lines:
                    return None
                pts = lines[0]
            else:
                pts = geom.asPolyline()
            
            if len(pts) < 2:
                return None
            
            p1, p2 = QgsPointXY(pts[0]), QgsPointXY(pts[-1])
            
            # Get elevations
            p1_elev = self._get_elevation_value(feature, p1_elev_idx)
            p2_elev = self._get_elevation_value(feature, p2_elev_idx)
            
            if p1_elev is None or p2_elev is None:
                DebugLogger.log(f"Segment {index} missing elevations: P1={p1_elev}, P2={p2_elev}")
                return None
            
            # Calculate segment length
            seg_length = CoordinateUtils.point_distance_2d(p1, p2)
            
            return {
                'feature': feature,
                'index': index,
                'p1': p1,
                'p2': p2,
                'p1_elev': p1_elev,
                'p2_elev': p2_elev,
                'length': seg_length,
                'processed': False
            }
            
        except Exception as e:
            DebugLogger.log_error(f"Failed to extract segment data for feature {feature.id()}", e)
            return None
    
    def _get_elevation_value(self, feature: QgsFeature, field_idx: int) -> Optional[float]:
        """Get elevation value from feature attribute."""
        if field_idx < 0:
            return None
        try:
            value = feature.attribute(field_idx)
            return float(value) if value not in (None, '') else None
        except (ValueError, TypeError):
            return None
    
    def _update_topology(self, segment_data: dict, segment_idx: int, 
                        node_connections: Dict[str, List[Tuple[int, bool]]]) -> None:
        """Update topology connections for segment."""
        p1_key = CoordinateUtils.node_key(segment_data['p1'])
        p2_key = CoordinateUtils.node_key(segment_data['p2'])
        
        node_connections.setdefault(p1_key, []).append((segment_idx, True))   # p1 is upstream
        node_connections.setdefault(p2_key, []).append((segment_idx, False))  # p2 is downstream
    
    def find_root_segments(self, segments: List[dict], 
                          node_connections: Dict[str, List[Tuple[int, bool]]]) -> List[int]:
        """Find root segments (no upstream connections)."""
        roots = []
        for i, segment in enumerate(segments):
            p1_key = CoordinateUtils.node_key(segment['p1'])
            has_upstream = any(not is_upstream for _, is_upstream in node_connections.get(p1_key, []))
            if not has_upstream:
                roots.append(i)
                DebugLogger.log(f"Root segment {i}: Feature {segment['feature'].id()}")
        return roots
    
    def find_outlet_segments(self, segments: List[dict],
                           node_connections: Dict[str, List[Tuple[int, bool]]]) -> List[int]:
        """Find outlet segments (no downstream connections)."""
        outlets = []
        for i, segment in enumerate(segments):
            p2_key = CoordinateUtils.node_key(segment['p2'])
            has_downstream = any(is_upstream for _, is_upstream in node_connections.get(p2_key, []))
            if not has_downstream:
                outlets.append(i)
                DebugLogger.log(f"Outlet segment {i}: Feature {segment['feature'].id()}")
        return outlets
    
    def calculate_network_depths(self, features: List[QgsFeature], 
                               initial_depth: float = 0.0) -> bool:
        """
        Calculate depths for entire network using tree traversal.
        
        Args:
            features: List of features to process
            initial_depth: Initial depth override
            
        Returns:
            True if successful
        """
        try:
            DebugLogger.log("Starting network depth calculation...")
            
            # Build topology
            segments, node_connections = self.build_network_topology(features)
            if not segments:
                DebugLogger.log("No valid segments found")
                return False
            
            # Find roots and process network
            root_segments = self.find_root_segments(segments, node_connections)
            if not root_segments:
                DebugLogger.log("No root segments found")
                return False
            
            # Process network with unified traversal
            vertex_depths = {}
            segment_depths = {}
            
            self._process_unified_network(
                root_segments, segments, node_connections,
                vertex_depths, segment_depths, initial_depth
            )
            
            # Write results to features
            self._write_depth_results(segments, segment_depths)
            
            DebugLogger.log(f"Successfully calculated depths for {len(segment_depths)} segments")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Network depth calculation failed", e)
            return False
    
    def _process_unified_network(self, root_segments: List[int], segments: List[dict],
                               node_connections: Dict[str, List[Tuple[int, bool]]],
                               vertex_depths: Dict[str, float], segment_depths: Dict[int, Tuple[float, float]],
                               initial_depth: float) -> None:
        """Process network with unified traversal algorithm."""
        queue = []
        processed = set()
        
        # Initialize root segments
        for root_seg_idx in root_segments:
            segment = segments[root_seg_idx]
            upstream_depth = self.depth_calculator.calculate_initial_depth(
                segment['p1_elev'], initial_depth
            )
            p1_key = CoordinateUtils.node_key(segment['p1'])
            vertex_depths[p1_key] = upstream_depth
            queue.append((root_seg_idx, upstream_depth))
        
        # Process segments
        while queue:
            seg_idx, upstream_depth = queue.pop(0)
            
            if seg_idx in processed:
                continue
                
            segment = segments[seg_idx]
            p2_key = CoordinateUtils.node_key(segment['p2'])
            
            # Calculate segment depths
            p1_depth, p2_depth = self.depth_calculator.calculate_segment_depths(
                upstream_depth, segment['p1_elev'], segment['p2_elev'], segment['length']
            )
            segment_depths[seg_idx] = (p1_depth, p2_depth)
            processed.add(seg_idx)
            
            # Handle downstream vertex
            self._handle_downstream_vertex(
                seg_idx, p2_key, p2_depth, segments, node_connections,
                vertex_depths, segment_depths, queue, processed
            )
    
    def _handle_downstream_vertex(self, seg_idx: int, p2_key: str, p2_depth: float,
                                segments: List[dict], node_connections: Dict[str, List[Tuple[int, bool]]],
                                vertex_depths: Dict[str, float], segment_depths: Dict[int, Tuple[float, float]],
                                queue: List[Tuple[int, float]], processed: Set[int]) -> None:
        """Handle downstream vertex convergence logic."""
        upstream_segments_to_p2 = [idx for idx, is_upstream in node_connections.get(p2_key, []) if not is_upstream]
        downstream_segments = [idx for idx, is_upstream in node_connections.get(p2_key, []) if is_upstream]
        
        if len(upstream_segments_to_p2) > 1:
            # Convergent vertex
            all_upstream_processed = all(us_idx in processed for us_idx in upstream_segments_to_p2)
            
            if all_upstream_processed:
                # Get maximum depth from all upstream segments
                upstream_depths = [segment_depths[us_idx][1] for us_idx in upstream_segments_to_p2 if us_idx in segment_depths]
                if upstream_depths:
                    max_depth = max(upstream_depths)
                    vertex_depths[p2_key] = max_depth
                    
                    # Add downstream segments
                    for ds_idx in downstream_segments:
                        if ds_idx not in processed:
                            queue.append((ds_idx, max_depth))
        else:
            # Normal vertex
            vertex_depths[p2_key] = p2_depth
            
            for ds_idx in downstream_segments:
                if ds_idx not in processed:
                    queue.append((ds_idx, p2_depth))
    
    def _write_depth_results(self, segments: List[dict], 
                           segment_depths: Dict[int, Tuple[float, float]]) -> None:
        """Write calculated depths to feature attributes."""
        field_mapping = self.field_mapper.get_field_mapping()
        p1_h_idx = field_mapping['p1_h']
        p2_h_idx = field_mapping['p2_h']
        
        if not self.layer.isEditable():
            self.layer.startEditing()
        
        for seg_idx, (p1_depth, p2_depth) in segment_depths.items():
            if seg_idx < len(segments):
                feature = segments[seg_idx]['feature']
                
                if p1_h_idx >= 0:
                    self.layer.changeAttributeValue(feature.id(), p1_h_idx, round(p1_depth, 2))
                if p2_h_idx >= 0:
                    self.layer.changeAttributeValue(feature.id(), p2_h_idx, round(p2_depth, 2))
                
                DebugLogger.log_feature_processing(
                    feature.id(), "wrote depths", 
                    p1_h=round(p1_depth, 2), p2_h=round(p2_depth, 2)
                )