# -*- coding: utf-8 -*-
"""
Raster interpolation functionality extracted from elevation_floater.py.
"""

import math
from typing import Optional
from qgis.core import QgsPointXY, QgsRectangle, QgsMapLayer
from ..utils import DebugLogger


class RasterInterpolator:
    """Handles raster value interpolation using bilinear method."""
    
    def __init__(self, raster_layer: QgsMapLayer, band: int = 1):
        """
        Initialize interpolator for given raster layer and band.
        
        Args:
            raster_layer: QGIS raster layer
            band: Band number (1-based)
        """
        self.layer = raster_layer
        self.dp = raster_layer.dataProvider()
        self.band = int(band)

        try:
            self.nodata = self.dp.sourceNoDataValue(self.band) if self.dp.sourceHasNoDataValue(self.band) else None
        except Exception:
            self.nodata = None

        self.extent = self.dp.extent()
        self.width = self.dp.xSize()
        self.height = self.dp.ySize()

        try:
            self.xres = self.extent.width() / self.width
            self.yres = self.extent.height() / self.height
        except Exception:
            try:
                self.xres = self.layer.rasterUnitsPerPixelX()
                self.yres = self.layer.rasterUnitsPerPixelY()
            except Exception:
                self.xres = 1.0
                self.yres = 1.0

    def _is_nodata(self, value) -> bool:
        """Check if value represents no data."""
        if value is None:
            return True
        try:
            fv = float(value)
            if math.isnan(fv):
                return True
            if self.nodata is not None and fv == self.nodata:
                return True
            return False
        except Exception:
            return True

    def nearest(self, pt_layer_crs: QgsPointXY) -> Optional[float]:
        """Get nearest neighbor value at point."""
        try:
            val, ok = self.dp.sample(pt_layer_crs, self.band)
        except Exception:
            return None
        if not ok or self._is_nodata(val):
            return None
        try:
            return float(val)
        except Exception:
            return None

    def bilinear(self, pt_layer_crs: QgsPointXY) -> Optional[float]:
        """
        Get bilinear interpolated value at point.
        
        Args:
            pt_layer_crs: Point in layer CRS coordinates
            
        Returns:
            Interpolated value or None if unavailable
        """
        x = pt_layer_crs.x()
        y = pt_layer_crs.y()

        try:
            col = int(round((x - self.extent.xMinimum()) / self.xres))
            row = int(round((self.extent.yMaximum() - y) / self.yres))
        except Exception:
            return self.nearest(pt_layer_crs)

        xMin = self.extent.xMinimum() + (col - 1) * self.xres
        xMax = xMin + 2 * self.xres
        yMax = self.extent.yMaximum() - (row - 1) * self.yres
        yMin = yMax - 2 * self.yres

        if (xMin < self.extent.xMinimum() or xMax > self.extent.xMaximum() or
                yMin < self.extent.yMinimum() or yMax > self.extent.yMaximum()):
            return self.nearest(pt_layer_crs)

        pixel_extent = QgsRectangle(xMin, yMin, xMax, yMax)
        block = self.dp.block(self.band, pixel_extent, 2, 2)
        if block is None or block.width() != 2 or block.height() != 2:
            return self.nearest(pt_layer_crs)

        v12 = block.value(0, 0)
        v22 = block.value(0, 1)
        v11 = block.value(1, 0)
        v21 = block.value(1, 1)

        if any(self._is_nodata(v) for v in (v11, v12, v21, v22)):
            return self.nearest(pt_layer_crs)

        x1 = xMin + self.xres / 2.0
        x2 = xMax - self.xres / 2.0
        y1 = yMin + self.yres / 2.0
        y2 = yMax - self.yres / 2.0

        denom = (x2 - x1) * (y2 - y1)
        if denom == 0:
            return self.nearest(pt_layer_crs)

        val = (
            v11 * (x2 - x) * (y2 - y)
            + v21 * (x - x1) * (y2 - y)
            + v12 * (x2 - x) * (y - y1)
            + v22 * (x - x1) * (y - y1)
        ) / denom

        try:
            fv = float(val)
            if self._is_nodata(fv):
                return None
            return fv
        except Exception:
            return None
            
    def is_valid(self) -> bool:
        """Check if interpolator is still valid (data provider available)."""
        try:
            _ = self.dp
            return True
        except Exception:
            return False