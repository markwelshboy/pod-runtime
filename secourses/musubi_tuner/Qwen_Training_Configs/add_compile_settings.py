"""
Script to add compile settings to all TOML config files.
Adds the following lines after 'caption_strategy = "folder_name"':
    compile = true
    compile_backend = "inductor"
    compile_cache_size_limit = 0
    compile_dynamic = "auto"
    compile_fullgraph = false
    compile_mode = "default"
"""

import os
from pathlib import Path

# Settings to add (as individual lines)
SETTINGS_TO_ADD = '''compile = true
compile_backend = "inductor"
compile_cache_size_limit = 0
compile_dynamic = "auto"
compile_fullgraph = false
compile_mode = "default"
'''

# The line after which to insert
TARGET_LINE = 'caption_strategy = "folder_name"'

def process_file(file_path):
    """
    Process a single TOML file and add compile settings after caption_strategy line.
    Returns a tuple: (success, message)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if the target line exists
        if TARGET_LINE not in content:
            return (False, "Target line not found")
        
        # Check if settings already exist (avoid duplicate additions)
        if 'compile = true' in content and 'compile_backend = "inductor"' in content:
            return (False, "Settings already exist")
        
        # Split into lines for processing
        lines = content.split('\n')
        new_lines = []
        found = False
        
        for line in lines:
            new_lines.append(line)
            # Check if this is the target line (strip to handle any whitespace)
            if line.strip() == TARGET_LINE:
                found = True
                # Add the new settings after this line
                for setting_line in SETTINGS_TO_ADD.strip().split('\n'):
                    new_lines.append(setting_line)
        
        if not found:
            return (False, "Target line not found in line-by-line check")
        
        # Write the modified content back
        new_content = '\n'.join(new_lines)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return (True, "Successfully modified")
    
    except Exception as e:
        return (False, f"Error: {str(e)}")

def find_all_toml_files(root_dir):
    """Find all .toml files in the directory tree."""
    toml_files = []
    for root, dirs, files in os.walk(root_dir):
        # Skip the script's own directory if needed
        for file in files:
            if file.endswith('.toml'):
                toml_files.append(os.path.join(root, file))
    return toml_files

def main():
    # Get the directory where this script is located
    script_dir = Path(__file__).parent.resolve()
    
    print(f"Scanning for TOML files in: {script_dir}")
    print("=" * 80)
    
    # Find all TOML files
    toml_files = find_all_toml_files(script_dir)
    
    # Statistics
    stats = {
        'total': len(toml_files),
        'modified': 0,
        'skipped_already_exists': 0,
        'skipped_no_target': 0,
        'errors': 0
    }
    
    modified_files = []
    skipped_files = []
    error_files = []
    
    print(f"Found {len(toml_files)} TOML files\n")
    
    for file_path in sorted(toml_files):
        relative_path = os.path.relpath(file_path, script_dir)
        success, message = process_file(file_path)
        
        if success:
            stats['modified'] += 1
            modified_files.append(relative_path)
            status = "✓ MODIFIED"
        elif "already exist" in message.lower():
            stats['skipped_already_exists'] += 1
            skipped_files.append((relative_path, message))
            status = "⊘ SKIPPED (already has settings)"
        elif "not found" in message.lower():
            stats['skipped_no_target'] += 1
            skipped_files.append((relative_path, message))
            status = "⊘ SKIPPED (no target line)"
        else:
            stats['errors'] += 1
            error_files.append((relative_path, message))
            status = f"✗ ERROR: {message}"
        
        print(f"{status}: {relative_path}")
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total TOML files found:     {stats['total']}")
    print(f"Successfully modified:      {stats['modified']}")
    print(f"Skipped (already existed):  {stats['skipped_already_exists']}")
    print(f"Skipped (no target line):   {stats['skipped_no_target']}")
    print(f"Errors:                     {stats['errors']}")
    
    if modified_files:
        print("\n" + "-" * 40)
        print("MODIFIED FILES:")
        print("-" * 40)
        for f in modified_files:
            print(f"  ✓ {f}")
    
    if skipped_files:
        print("\n" + "-" * 40)
        print("SKIPPED FILES:")
        print("-" * 40)
        for f, reason in skipped_files:
            print(f"  ⊘ {f} ({reason})")
    
    if error_files:
        print("\n" + "-" * 40)
        print("ERROR FILES:")
        print("-" * 40)
        for f, error in error_files:
            print(f"  ✗ {f}: {error}")
    
    print("\n" + "=" * 80)
    print("Done!")
    
    return stats

if __name__ == "__main__":
    main()


