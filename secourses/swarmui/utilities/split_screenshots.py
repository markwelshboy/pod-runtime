#!/usr/bin/env python3
"""
Screenshot Splitter for Reddit Gallery
Splits screenshots vertically into optimal parts (square when possible, max 20) for easy sharing as a gallery on Reddit.
"""

import os
import sys
from PIL import Image
import math

def create_split_folder():
    """Create the split subfolder if it doesn't exist"""
    split_folder = os.path.join("screenshots", "split")
    if not os.path.exists(split_folder):
        os.makedirs(split_folder)
        print(f"Created split folder: {split_folder}")
    return split_folder

def calculate_optimal_parts(width, height, max_parts=20):
    """Calculate optimal number of parts - square when possible, max 20"""
    # For square parts: part_height should equal width
    # So number of parts = total_height / width
    square_parts = math.ceil(height / width)
    
    if square_parts <= max_parts:
        return square_parts, "square"
    else:
        return max_parts, "max_limit"

def split_image_vertically(image_path, output_folder, max_parts=20):
    """Split an image vertically into optimal parts"""
    try:
        # Open the image
        with Image.open(image_path) as img:
            width, height = img.size
            print(f"Processing {os.path.basename(image_path)} ({width}x{height})")
            
            # Calculate optimal number of parts
            parts, split_type = calculate_optimal_parts(width, height, max_parts)
            
            # Calculate height for each part
            part_height = height // parts
            remainder = height % parts
            
            if split_type == "square":
                print(f"Using SQUARE split: {parts} parts, each approximately {width}x{part_height} (target: {width}x{width})")
            else:
                print(f"Using MAX LIMIT split: {parts} parts, each approximately {width}x{part_height}")
            
            # Get base filename without extension
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            
            current_y = 0
            
            for part_number in range(1, parts + 1):
                # Calculate the height for this part
                # Distribute remainder pixels across the first few parts
                current_part_height = part_height + (1 if part_number <= remainder else 0)
                
                # Calculate crop box (vertical split)
                left = 0
                top = current_y
                right = width
                bottom = current_y + current_part_height
                
                # Crop the image
                cropped = img.crop((left, top, right, bottom))
                
                # Save the part
                output_filename = f"{base_name}_part_{part_number:02d}.png"
                output_path = os.path.join(output_folder, output_filename)
                cropped.save(output_path, "PNG")
                
                print(f"Saved part {part_number}/{parts}: {output_filename} ({width}x{current_part_height})")
                
                # Move to next vertical position
                current_y += current_part_height
            
            print(f"✓ Successfully split {os.path.basename(image_path)} into {parts} vertical parts ({split_type})")
            
    except Exception as e:
        print(f"✗ Error processing {image_path}: {str(e)}")
        return False, 0
    
    return True, parts

def main():
    """Main function to process all screenshots"""
    print("🖼️  Screenshot Splitter for Reddit Gallery (Smart Vertical Split)")
    print("=" * 65)
    print("📐 Logic: Square parts when possible (< 20), otherwise max 20 parts")
    print()
    
    # Check if screenshots folder exists
    screenshots_folder = "screenshots"
    if not os.path.exists(screenshots_folder):
        print(f"❌ Screenshots folder '{screenshots_folder}' not found!")
        sys.exit(1)
    
    # Create split folder
    split_folder = create_split_folder()
    
    # Find all image files in screenshots folder
    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')
    image_files = []
    
    for filename in os.listdir(screenshots_folder):
        if filename.lower().endswith(image_extensions):
            image_files.append(os.path.join(screenshots_folder, filename))
    
    if not image_files:
        print(f"❌ No image files found in '{screenshots_folder}' folder!")
        sys.exit(1)
    
    print(f"📁 Found {len(image_files)} image file(s) to process:")
    for img_file in image_files:
        print(f"   - {os.path.basename(img_file)}")
    
    print(f"\n🔄 Processing images (smart vertical split)...")
    
    # Process each image
    success_count = 0
    total_parts = 0
    
    for image_path in image_files:
        success, parts_created = split_image_vertically(image_path, split_folder, max_parts=20)
        if success:
            success_count += 1
            total_parts += parts_created
        print()  # Empty line for readability
    
    # Summary
    print("📊 Processing Summary:")
    print(f"   - Images processed: {success_count}/{len(image_files)}")
    print(f"   - Total parts created: {total_parts}")
    print(f"   - Output folder: {split_folder}")
    
    if success_count == len(image_files):
        print("\n✅ All images processed successfully!")
        print(f"💡 Reddit Gallery Tip: Upload the split images from '{split_folder}' to create a gallery post")
    else:
        print(f"\n⚠️  {len(image_files) - success_count} images failed to process")
    
    print("\n🎯 Reddit Gallery Instructions:")
    print("   1. Go to Reddit and create a new post")
    print("   2. Choose 'Images & Video' post type")
    print("   3. Upload all the split images from the 'split' folder")
    print("   4. Reddit will automatically create a gallery")
    print("   5. Add your title and description")
    print("   6. Post and enjoy!")

if __name__ == "__main__":
    # Check if PIL is available
    try:
        from PIL import Image
    except ImportError:
        print("❌ PIL (Pillow) is required but not installed!")
        print("💡 Install it with: pip install Pillow")
        sys.exit(1)
    
    main() 