#!/usr/bin/env python3
# Simple test for imports

try:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    
    from core import ChangeManagementSystem, DepthRecalculator
    print('✅ Core imports successful!')
    
    from change_manager_integration import ChangeManagerIntegration  
    print('✅ Integration import successful!')
    
    print('✅ All refactored imports working correctly')
    
except Exception as e:
    print(f'❌ Import error: {e}')
    import traceback
    traceback.print_exc()
