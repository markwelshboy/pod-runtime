import os
import json
import shutil
from PIL import Image
from collections import defaultdict
import re

def extract_prompt_from_png(filepath):
    """Extract the prompt from PNG metadata"""
    try:
        img = Image.open(filepath)
        metadata = img.info
        if 'parameters' in metadata:
            params = json.loads(metadata['parameters'])
            if 'sui_image_params' in params and 'prompt' in params['sui_image_params']:
                return params['sui_image_params']['prompt']
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return None

def sanitize_filename(prompt):
    """Create a safe filename from the prompt"""
    # Take first 50 characters and clean them
    filename = prompt[:50].strip()
    # Replace invalid characters with underscores
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove multiple spaces/underscores
    filename = re.sub(r'[_ ]+', '_', filename)
    return filename.strip('_')

def main():
    local_dir = 'local'
    sorted_dir = 'sorted'

    # Create sorted directory if it doesn't exist
    if not os.path.exists(sorted_dir):
        os.makedirs(sorted_dir)
    else:
        # Clear existing sorted directory
        print("Clearing existing sorted directory...")
        for file in os.listdir(sorted_dir):
            file_path = os.path.join(sorted_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error removing {file_path}: {e}")

    # Dictionary to group files by prompt
    prompt_groups = defaultdict(list)
    files_without_prompts = []
    copied_files = []
    failed_files = []

    # Read all PNG files and extract prompts
    print("Reading files and extracting prompts...")
    png_files = [f for f in os.listdir(local_dir) if f.lower().endswith('.png')]
    print(f"Found {len(png_files)} PNG files to process\n")

    for filename in png_files:
        filepath = os.path.join(local_dir, filename)
        prompt = extract_prompt_from_png(filepath)

        if prompt:
            prompt_groups[prompt].append(filepath)
        else:
            files_without_prompts.append(filepath)
            print(f"Warning: Could not extract prompt from {filename}")

    print(f"Found {len(prompt_groups)} unique prompts")
    print(f"Files without prompts: {len(files_without_prompts)}\n")

    # Track used filenames to prevent collisions
    used_filenames = set()
    file_counter = 0

    # Sort and copy files directly to sorted folder
    print("Sorting and copying files...")
    
    # First, copy files with prompts
    for prompt, filepaths in prompt_groups.items():
        # Create a sanitized filename from the prompt
        base_filename = sanitize_filename(prompt)

        # Copy files with numbered suffixes if needed
        for i, filepath in enumerate(filepaths):
            filename = os.path.basename(filepath)
            name, ext = os.path.splitext(filename)

            if len(filepaths) == 1:
                # Single file, but check for collisions
                new_filename = f"{base_filename}{ext}"
                counter = 1
                while new_filename in used_filenames:
                    new_filename = f"{base_filename}_{counter}{ext}"
                    counter += 1
            else:
                # Multiple files, add suffix starting from 1
                new_filename = f"{base_filename}_{i+1}{ext}"
                counter = i + 1
                while new_filename in used_filenames:
                    counter += 1
                    new_filename = f"{base_filename}_{counter}{ext}"

            used_filenames.add(new_filename)
            new_filepath = os.path.join(sorted_dir, new_filename)
            
            try:
                shutil.copy2(filepath, new_filepath)
                copied_files.append((filepath, new_filepath))
                file_counter += 1
                if file_counter % 100 == 0:
                    print(f"  Copied {file_counter}/{len(png_files)} files...")
            except Exception as e:
                failed_files.append((filepath, str(e)))
                print(f"ERROR copying {filename}: {e}")
    
    # Then, copy files without prompts using original filename or a safe version
    for filepath in files_without_prompts:
        filename = os.path.basename(filepath)
        name, ext = os.path.splitext(filename)
        
        # Use original filename but sanitize it
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
        safe_name = re.sub(r'[_ ]+', '_', safe_name).strip('_')
        new_filename = f"{safe_name}{ext}"
        
        # Handle collisions
        counter = 1
        while new_filename in used_filenames:
            new_filename = f"{safe_name}_{counter}{ext}"
            counter += 1
        
        used_filenames.add(new_filename)
        new_filepath = os.path.join(sorted_dir, new_filename)
        
        try:
            shutil.copy2(filepath, new_filepath)
            copied_files.append((filepath, new_filepath))
            file_counter += 1
            print(f"Copied (no prompt): {filename} -> {new_filename}")
        except Exception as e:
            failed_files.append((filepath, str(e)))
            print(f"ERROR copying {filename}: {e}")

    # Verification
    print(f"\n{'='*60}")
    print("VERIFICATION")
    print(f"{'='*60}")
    
    # Count files in sorted directory
    sorted_files = [f for f in os.listdir(sorted_dir) if f.lower().endswith('.png')]
    
    print(f"Source files (local): {len(png_files)}")
    print(f"Files copied successfully: {len(copied_files)}")
    print(f"Files in sorted directory: {len(sorted_files)}")
    print(f"Failed copies: {len(failed_files)}")
    print(f"Unique prompts: {len(prompt_groups)}")
    
    if len(copied_files) != len(png_files):
        print(f"\n⚠️  WARNING: File count mismatch!")
        print(f"   Expected: {len(png_files)}, Got: {len(copied_files)}")
        
    if len(sorted_files) != len(copied_files):
        print(f"\n⚠️  WARNING: Files in directory don't match copied count!")
        print(f"   Copied: {len(copied_files)}, In directory: {len(sorted_files)}")
    
    if failed_files:
        print(f"\n⚠️  Failed to copy {len(failed_files)} files:")
        for filepath, error in failed_files[:10]:
            print(f"   {os.path.basename(filepath)}: {error}")
        if len(failed_files) > 10:
            print(f"   ... and {len(failed_files) - 10} more")
    
    if len(copied_files) == len(png_files) == len(sorted_files):
        print(f"\n✅ SUCCESS: All {len(png_files)} files copied successfully!")
    
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
