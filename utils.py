# -*- coding: utf-8 -*-
"""
Common utilities for sewerage depth estimator plugin.

This module consolidates debug logging, coordinate operations, and other 
utility functions used throughout the plugin.
"""

import functools
from typing import Any, Optional
from qgis.core import (
    QgsPointXY, 
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsProject
)


class DebugLogger:
    """Centralized debug logging with consistent formatting."""
    
    PREFIX = "[SEWERAGE DEBUG]"
    
    @classmethod
    def log(cls, message: str, *args) -> None:
        """Log a debug message with consistent formatting."""
        formatted_msg = message
        if args:
            try:
                formatted_msg = message.format(*args)
            except (IndexError, KeyError):
                formatted_msg = f"{message} {args}"
        print(f"{cls.PREFIX} {formatted_msg}")
    
    @classmethod
    def log_error(cls, message: str, exception: Optional[Exception] = None) -> None:
        """Log an error message with optional exception details."""
        if exception:
            cls.log(f"ERROR: {message}: {exception}")
        else:
            cls.log(f"ERROR: {message}")
    
    @classmethod
    def log_method_entry(cls, method_name: str, *args) -> None:
        """Log entry to a method with arguments."""
        args_str = ", ".join(str(arg) for arg in args) if args else ""
        cls.log(f"-> {method_name}({args_str})")
    
    @classmethod
    def log_feature_processing(cls, feature_id: Any, action: str, **kwargs) -> None:
        """Log feature processing actions."""
        details = ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        cls.log(f"Feature {feature_id}: {action} {details}")


class CoordinateUtils:
    """Utilities for coordinate transformations and distance calculations."""
    
    @staticmethod
    def create_transform(from_crs: QgsCoordinateReferenceSystem, 
                        to_crs: QgsCoordinateReferenceSystem) -> Optional[QgsCoordinateTransform]:
        """Create coordinate transform with error handling."""
        try:
            return QgsCoordinateTransform(from_crs, to_crs, QgsProject.instance().transformContext())
        except Exception as e:
            DebugLogger.log_error("Failed to create coordinate transform", e)
            return None
    
    @staticmethod
    def transform_point(point: QgsPointXY, 
                       transform: QgsCoordinateTransform) -> Optional[QgsPointXY]:
        """Transform point with error handling."""
        try:
            return transform.transform(point)
        except Exception as e:
            DebugLogger.log_error(f"Failed to transform point {point.x():.6f}, {point.y():.6f}", e)
            return None
    
    @staticmethod
    def distance_m(a: QgsPointXY, b: QgsPointXY, 
                   crs: Optional[QgsCoordinateReferenceSystem] = None,
                   raster_transform: Optional[QgsCoordinateTransform] = None) -> float:
        """
        Calculate distance in meters between two points.
        
        Args:
            a, b: Points to measure between
            crs: Measurement CRS (if None, assumes projected in meters)
            raster_transform: Transform to projected CRS if measurement CRS is geographic
        """
        try:
            # If CRS is geographic, transform to projected coordinates
            if crs and crs.isGeographic() and raster_transform:
                pa = CoordinateUtils.transform_point(a, raster_transform)
                pb = CoordinateUtils.transform_point(b, raster_transform)
                if pa and pb:
                    dx = pb.x() - pa.x()
                    dy = pb.y() - pa.y()
                    return (dx * dx + dy * dy) ** 0.5
            
            # Assume projected CRS in meters
            dx = b.x() - a.x()
            dy = b.y() - a.y()
            return (dx * dx + dy * dy) ** 0.5
        except Exception as e:
            DebugLogger.log_error("Distance calculation failed", e)
            return 0.0
    
    @staticmethod
    def point_distance_2d(p1: QgsPointXY, p2: QgsPointXY) -> float:
        """Simple 2D distance between points."""
        try:
            dx = p1.x() - p2.x()
            dy = p1.y() - p2.y()
            return (dx * dx + dy * dy) ** 0.5
        except Exception:
            return float('inf')
    
    @staticmethod
    def node_key(point: QgsPointXY, precision: int = 6) -> str:
        """Generate consistent node key for topology building."""
        return f"{point.x():.{precision}f},{point.y():.{precision}f}"


def debug_method(func):
    """Decorator to automatically log method entry and exceptions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = f"{func.__qualname__}"
        DebugLogger.log_method_entry(method_name)
        try:
            return func(*args, **kwargs)
        except Exception as e:
            DebugLogger.log_error(f"Exception in {method_name}", e)
            raise
    return wrapper
