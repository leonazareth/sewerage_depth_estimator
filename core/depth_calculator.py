# -*- coding: utf-8 -*-
"""
Core depth calculation algorithms for sewerage networks.
"""

from typing import Tuple, Optional
from ..utils import DebugLogger


class DepthCalculator:
    """Handles sewerage depth calculations based on hydraulic parameters."""
    
    def __init__(self, min_cover_m: float = 0.9, diameter_m: float = 0.15, 
                 slope_m_per_m: float = 0.005):
        """
        Initialize calculator with hydraulic parameters.
        
        Args:
            min_cover_m: Minimum cover depth in meters
            diameter_m: Pipe diameter in meters  
            slope_m_per_m: Pipe slope (dimensionless)
        """
        self.min_cover_m = min_cover_m
        self.diameter_m = diameter_m
        self.slope_m_per_m = slope_m_per_m
    
    def calculate_minimum_depth(self) -> float:
        """Calculate minimum allowable depth (cover + diameter)."""
        # Use integer arithmetic to avoid floating point precision issues
        min_cover_mm = int(round(self.min_cover_m * 1000))
        diameter_mm = int(round(self.diameter_m * 1000))
        return (min_cover_mm + diameter_mm) / 1000.0
    
    def calculate_segment_depths(self, upstream_depth: float, p1_elev: float, 
                               p2_elev: float, segment_length: float) -> Tuple[float, float]:
        """
        Calculate upstream and downstream depths for a segment.
        
        Args:
            upstream_depth: Depth at upstream end
            p1_elev: Ground elevation at upstream end
            p2_elev: Ground elevation at downstream end
            segment_length: Segment length in meters
            
        Returns:
            Tuple of (upstream_depth, downstream_depth)
        """
        try:
            # Calculate upstream bottom elevation (invert)
            upstream_bottom_elev = p1_elev - upstream_depth
            
            # Calculate required downstream bottom elevation based on slope
            fall = segment_length * max(0.0, self.slope_m_per_m)
            downstream_bottom_candidate = upstream_bottom_elev - fall
            
            # Calculate downstream depth from ground
            downstream_depth_candidate = p2_elev - downstream_bottom_candidate
            
            # Enforce minimum cover at downstream
            min_depth = self.calculate_minimum_depth()
            downstream_depth = max(downstream_depth_candidate, min_depth)
            
            # Calculate actual slope achieved
            actual_downstream_bottom = p2_elev - downstream_depth
            actual_fall = upstream_bottom_elev - actual_downstream_bottom
            actual_slope = actual_fall / segment_length if segment_length > 0 else 0
            
            DebugLogger.log(f"Segment calc: P1={p1_elev:.2f}m, P2={p2_elev:.2f}m, "
                          f"len={segment_length:.2f}m, depths={upstream_depth:.2f}m->{downstream_depth:.2f}m, "
                          f"slope={actual_slope:.4f}")
            
            return upstream_depth, downstream_depth
            
        except Exception as e:
            DebugLogger.log_error("Segment depth calculation failed", e)
            return upstream_depth, upstream_depth
    
    def calculate_initial_depth(self, ground_elevation: float, 
                              initial_depth_override: Optional[float] = None,
                              existing_depth: Optional[float] = None) -> float:
        """
        Calculate initial depth at network start point.
        
        Args:
            ground_elevation: Ground elevation at start point
            initial_depth_override: Explicit initial depth (if > 0)
            existing_depth: Existing depth from connected segments
            
        Returns:
            Calculated initial depth
        """
        # Priority order: existing_depth > initial_depth_override > minimum_depth
        if existing_depth is not None and existing_depth > 0:
            DebugLogger.log(f"Using existing depth: {existing_depth:.3f}m")
            return existing_depth
        
        if initial_depth_override and initial_depth_override > 0:
            DebugLogger.log(f"Using initial depth override: {initial_depth_override:.3f}m")
            return initial_depth_override
        
        min_depth = self.calculate_minimum_depth()
        DebugLogger.log(f"Using minimum depth: {min_depth:.3f}m")
        return min_depth
    
    def update_parameters(self, min_cover_m: Optional[float] = None,
                         diameter_m: Optional[float] = None,
                         slope_m_per_m: Optional[float] = None) -> None:
        """Update calculation parameters."""
        if min_cover_m is not None:
            self.min_cover_m = min_cover_m
        if diameter_m is not None:
            self.diameter_m = diameter_m
        if slope_m_per_m is not None:
            self.slope_m_per_m = slope_m_per_m
            
        DebugLogger.log(f"Updated parameters: cover={self.min_cover_m:.3f}m, "
                       f"diameter={self.diameter_m:.3f}m, slope={self.slope_m_per_m:.4f}")
    
    def get_parameters(self) -> dict:
        """Get current calculation parameters."""
        return {
            'min_cover_m': self.min_cover_m,
            'diameter_m': self.diameter_m, 
            'slope_m_per_m': self.slope_m_per_m
        }