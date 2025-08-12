#!/usr/bin/env python3
"""Script to fix empty except and else blocks by adding pass statements."""

import re

def fix_empty_blocks(file_path):
    """Fix empty except and else blocks in a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            result.append(line)
            
            # Check if this is any control structure that needs a body
            if re.match(r'\s*(except[^:]*|else|elif[^:]+|if[^:]+|for[^:]+|while[^:]+|try|with[^:]+):\s*$', line):
                # Look ahead to see if next lines are only comments
                j = i + 1
                has_code = False
                indent_level = len(line) - len(line.lstrip())
                
                while j < len(lines):
                    next_line = lines[j]
                    if not next_line.strip():  # Empty line
                        j += 1
                        continue
                    
                    next_indent = len(next_line) - len(next_line.lstrip())
                    
                    # If indentation is same or less, we've moved to next block
                    if next_indent <= indent_level:
                        break
                        
                    # If it's a comment, skip it
                    if next_line.strip().startswith('#'):
                        j += 1
                        continue
                    else:
                        has_code = True
                        break
                
                # If no code found after except/else, add pass
                if not has_code:
                    # Add pass with same indentation as comments would have
                    pass_indent = ' ' * (indent_level + 4)
                    result.append(pass_indent + 'pass')
            
            i += 1

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(result))

        print('Fixed empty except and else blocks')
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

# Fix both files
fix_empty_blocks('sewerage_depth_estimator_dockwidget.py')
fix_empty_blocks('elevation_floater.py')
