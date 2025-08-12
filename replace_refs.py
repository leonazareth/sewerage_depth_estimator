import re

# Replace references in change_management_system.py
file_path = r'core\change_management_system.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'self\.enhanced_recalculator', 'self.depth_recalculator', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Replaced all enhanced_recalculator references in change_management_system.py')

# Now update depth_recalculator.py
file_path = r'core\depth_recalculator.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace class name and docstring
content = re.sub(r'class EnhancedDepthRecalculator:', 'class DepthRecalculator:', content)
content = re.sub(r'Enhanced depth recalculator', 'Depth recalculator', content)
content = re.sub(r'enhanced tree-based algorithm', 'tree-based algorithm', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated depth_recalculator.py class name and references')
