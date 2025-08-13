# -*- coding: utf-8 -*-
"""
Centralized field mapping utilities for attribute access.
"""

from typing import Dict, Optional
from qgis.core import QgsVectorLayer
from ..utils import DebugLogger


class FieldMapper:
    """Handles field name resolution and mapping for vector layers."""
    
    # Standard field names used by the plugin
    STANDARD_FIELDS = {
        'p1_elev': 'p1_elev',
        'p2_elev': 'p2_elev', 
        'p1_h': 'p1_h',
        'p2_h': 'p2_h'
    }
    
    def __init__(self, layer: QgsVectorLayer, ui_widget=None):
        """
        Initialize field mapper for given layer.
        
        Args:
            layer: Vector layer to map fields for
            ui_widget: Optional UI widget with combo boxes for field selection
        """
        self.layer = layer
        self.ui_widget = ui_widget
        self._field_cache = {}
        self._refresh_mapping()
    
    def _refresh_mapping(self) -> None:
        """Refresh field mapping cache."""
        self._field_cache = {
            'p1_elev': self._resolve_field_index('cmbP1Elev', 'p1_elev'),
            'p2_elev': self._resolve_field_index('cmbP2Elev', 'p2_elev'),
            'p1_h': self._resolve_field_index('cmbP1H', 'p1_h'),
            'p2_h': self._resolve_field_index('cmbP2H', 'p2_h')
        }
    
    def _resolve_field_index(self, ui_combo_name: str, default_name: str) -> int:
        """
        Resolve field index from UI combo or default name.
        
        Args:
            ui_combo_name: Name of UI combo box widget
            default_name: Default field name to use
            
        Returns:
            Field index or -1 if not found
        """
        try:
            # Try to get field name from UI combo box
            if self.ui_widget and hasattr(self.ui_widget, ui_combo_name):
                combo = getattr(self.ui_widget, ui_combo_name)
                if combo.currentIndex() >= 0:
                    field_name = combo.currentData()
                    if field_name:
                        return self.layer.fields().indexOf(field_name)
            
            # Fallback to default field name
            return self.layer.fields().indexOf(default_name)
        except Exception as e:
            DebugLogger.log_error(f"Failed to resolve field index for {ui_combo_name}/{default_name}", e)
            return -1
    
    def get_field_mapping(self) -> Dict[str, int]:
        """
        Get complete field mapping dictionary.
        
        Returns:
            Dictionary mapping logical field names to indices
        """
        return self._field_cache.copy()
    
    def get_field_index(self, logical_name: str) -> int:
        """
        Get field index for logical field name.
        
        Args:
            logical_name: Logical field name (p1_elev, p2_elev, p1_h, p2_h)
            
        Returns:
            Field index or -1 if not found
        """
        return self._field_cache.get(logical_name, -1)
    
    def has_required_fields(self) -> bool:
        """Check if layer has all required fields."""
        required = ['p1_elev', 'p2_elev', 'p1_h', 'p2_h']
        return all(self.get_field_index(name) >= 0 for name in required)
    
    def get_missing_fields(self) -> list:
        """Get list of missing required field names."""
        required = ['p1_elev', 'p2_elev', 'p1_h', 'p2_h']
        return [name for name in required if self.get_field_index(name) < 0]
    
    def create_missing_fields(self) -> bool:
        """
        Create missing required fields in the layer.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            from qgis.core import QgsField
            from qgis.PyQt.QtCore import QVariant
            
            missing = self.get_missing_fields()
            if not missing:
                return True
            
            if not self.layer.isEditable():
                self.layer.startEditing()
            
            for field_name in missing:
                field = QgsField(field_name, QVariant.Double)
                success = self.layer.addAttribute(field)
                if not success:
                    DebugLogger.log_error(f"Failed to add field {field_name}")
                    return False
            
            self.layer.updateFields()
            self.layer.commitChanges()
            
            # Refresh mapping after adding fields
            self._refresh_mapping()
            
            DebugLogger.log(f"Successfully created fields: {missing}")
            return True
            
        except Exception as e:
            DebugLogger.log_error("Failed to create missing fields", e)
            try:
                self.layer.rollBackChanges()
            except Exception:
                pass
            return False