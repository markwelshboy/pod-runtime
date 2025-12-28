import os
import json
from PIL import Image

def extract_prompt_from_png(filepath):
    """Extract the prompt from PNG metadata"""
    try:
        img = Image.open(filepath)
        metadata = img.info
        if 'parameters' in metadata:
            params = json.loads(metadata['parameters'])
            if 'sui_image_params' in params and 'prompt' in params['sui_image_params']:
                return params['sui_image_params']['prompt'], metadata
        return None, metadata
    except Exception as e:
        return None, str(e)

def main():
    local_dir = 'local'
    png_files = [f for f in os.listdir(local_dir) if f.lower().endswith('.png')]
    
    files_with_prompts = []
    files_without_prompts = []
    
    print(f"Scanning {len(png_files)} files...\n")
    
    for filename in png_files:
        filepath = os.path.join(local_dir, filename)
        prompt, metadata_or_error = extract_prompt_from_png(filepath)
        
        if prompt:
            files_with_prompts.append(filename)
        else:
            files_without_prompts.append((filename, metadata_or_error))
    
    print(f"\n{'='*60}")
    print(f"Files WITH prompts: {len(files_with_prompts)}")
    print(f"Files WITHOUT prompts: {len(files_without_prompts)}")
    print(f"{'='*60}\n")
    
    if files_without_prompts:
        print("Files WITHOUT prompts:")
        print("-" * 60)
        for filename, metadata_or_error in files_without_prompts[:20]:  # Show first 20
            print(f"\n{filename}")
            if isinstance(metadata_or_error, str):
                print(f"  Error: {metadata_or_error}")
            else:
                print(f"  Available metadata keys: {list(metadata_or_error.keys()) if metadata_or_error else 'None'}")
        if len(files_without_prompts) > 20:
            print(f"\n... and {len(files_without_prompts) - 20} more files")
    else:
        print("All files have extractable prompts!")

if __name__ == "__main__":
    main()
