#!/usr/bin/env python3
"""Script to update imports to use consolidated modules."""

import os
import re

# Define the mappings
import_mappings = [
    # Utils consolidation - for root level imports
    (r'from \.utils\.debug_logger import DebugLogger', 'from .utils import DebugLogger'),
    (r'from \.utils\.coordinate_utils import CoordinateUtils', 'from .utils import CoordinateUtils'),
    # Utils consolidation - for relative imports
    (r'from \.\.utils\.debug_logger import DebugLogger', 'from ..utils import DebugLogger'),
    (r'from \.\.utils\.coordinate_utils import CoordinateUtils', 'from ..utils import CoordinateUtils'),
    
    # Connectivity analyzer consolidation - for core internal imports
    (r'from \.network_connectivity import NetworkConnectivityAnalyzer', 'from .connectivity_analyzer import ConnectivityAnalyzer'),
    (r'from \.advanced_connectivity_analyzer import AdvancedConnectivityAnalyzer', 'from .connectivity_analyzer import ConnectivityAnalyzer'),
    # For external imports
    (r'from \.core\.network_connectivity import NetworkConnectivityAnalyzer', 'from .core.connectivity_analyzer import ConnectivityAnalyzer'),
    (r'from \.core\.advanced_connectivity_analyzer import AdvancedConnectivityAnalyzer', 'from .core.connectivity_analyzer import ConnectivityAnalyzer'),
    
    # Class name updates
    (r'NetworkConnectivityAnalyzer', 'ConnectivityAnalyzer'),
    (r'AdvancedConnectivityAnalyzer', 'ConnectivityAnalyzer'),
]

def update_file_imports(file_path):
    """Update imports in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Apply import mappings
        for old_pattern, new_pattern in import_mappings:
            content = re.sub(old_pattern, new_pattern, content)
        
        # Only write if content changed
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated: {file_path}")
        
    except Exception as e:
        print(f"Error updating {file_path}: {e}")

def main():
    """Update all relevant files."""
    
    # Get current directory (should be plugin root)
    plugin_root = os.path.dirname(__file__)
    
    # Root level files that might need updating
    root_files = [
        'change_manager_integration.py',
        'elevation_floater_refactored.py',
        'elevation_floater.py',
        'sewerage_depth_estimator.py',
        'sewerage_depth_estimator_dockwidget.py'
    ]
    
    for filename in root_files:
        file_path = os.path.join(plugin_root, filename)
        if os.path.exists(file_path):
            update_file_imports(file_path)
    
    # Files to update - core files
    core_dir = os.path.join(plugin_root, 'core')
    if os.path.exists(core_dir):
        for filename in os.listdir(core_dir):
            if filename.endswith('.py') and filename != '__init__.py':
                file_path = os.path.join(core_dir, filename)
                update_file_imports(file_path)
    
    # Update data files
    data_dir = os.path.join(plugin_root, 'data')
    if os.path.exists(data_dir):
        for filename in os.listdir(data_dir):
            if filename.endswith('.py') and filename != '__init__.py':
                file_path = os.path.join(data_dir, filename)
                update_file_imports(file_path)
    
    print("Import updates complete!")

if __name__ == '__main__':
    main()
