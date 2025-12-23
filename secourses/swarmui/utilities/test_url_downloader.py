"""
Test script for URL Downloader functionality
Tests various URL formats and edge cases to ensure robustness.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.url_downloader import create_url_downloader
from utilities.folder_manager import create_folder_manager


def test_url_parsing():
    """Test URL parsing for different formats."""
    print("=== Testing URL Parsing ===")
    
    downloader = create_url_downloader()
    
    test_urls = [
        # CivitAI URLs
        "https://civitai.com/models/1940709/retro-anime?modelVersionId=2196504",
        "https://civitai.com/models/302872/lizmix?modelVersionId=1451507",
        
        # HuggingFace URLs
        "https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors?download=true",
        "https://huggingface.co/SG161222/RealVisXL_V5.0/blob/main/RealVisXL_V5.0_fp16.safetensors",
        
        # Generic URLs
        "https://example.com/models/test_model.safetensors",
        "https://files.example.com/download/model.ckpt"
    ]
    
    for url in test_urls:
        print(f"\nTesting URL: {url}")
        try:
            info = downloader.parse_url(url)
            print(f"  ✓ Source: {info['source_type']}")
            print(f"  ✓ Download URL: {info['download_url']}")
            print(f"  ✓ Filename: {info['filename']}")
        except Exception as e:
            print(f"  ✗ Error: {e}")


def test_folder_management():
    """Test folder management for different UI types."""
    print("\n=== Testing Folder Management ===")
    
    base_path = "/tmp/test_models"
    
    # Test different configurations
    configs = [
        ("SwarmUI", False, False, False),
        ("ComfyUI", True, False, False),
        ("Forge", False, True, False),
        ("SwarmUI Lowercase", False, False, True),
    ]
    
    for config_name, is_comfy, is_forge, lowercase in configs:
        print(f"\n--- {config_name} Configuration ---")
        
        manager = create_folder_manager(base_path, is_comfy, is_forge, lowercase)
        folders = manager.get_available_folders()
        
        print(f"Available folders: {len(folders)}")
        for display_name, folder_key in folders[:5]:  # Show first 5
            resolved_path = manager.resolve_folder_path(folder_key)
            print(f"  {display_name} -> {resolved_path}")
        
        # Test filename suggestions
        test_filenames = [
            "model.safetensors",
            "lora_style.safetensors", 
            "vae_model.safetensors",
            "controlnet_canny.safetensors",
            "upscaler_4x.pth"
        ]
        
        print("Filename suggestions:")
        for filename in test_filenames:
            suggestions = manager.get_folder_suggestions_by_filename(filename)
            print(f"  {filename} -> {suggestions[:2]}")  # Show top 2 suggestions


def test_url_validation():
    """Test URL validation functionality."""
    print("\n=== Testing URL Validation ===")
    
    downloader = create_url_downloader()
    
    # Test with some real URLs (these should be accessible)
    test_urls = [
        "https://httpbin.org/get",  # Should work
        "https://invalid-url-that-does-not-exist.com/file.bin",  # Should fail
        "not-a-url",  # Should fail
        "",  # Should fail
    ]
    
    for url in test_urls:
        print(f"\nValidating: {url}")
        try:
            is_valid, message = downloader.validate_url(url)
            status = "✓" if is_valid else "✗"
            print(f"  {status} {message}")
        except Exception as e:
            print(f"  ✗ Validation error: {e}")


def test_filename_extraction():
    """Test filename extraction from server headers."""
    print("\n=== Testing Filename Extraction ===")
    
    downloader = create_url_downloader()
    
    # Test with URLs that should provide filenames
    test_urls = [
        "https://httpbin.org/response-headers?Content-Disposition=attachment%3B%20filename%3D%22test.txt%22",
        "https://httpbin.org/get",  # No filename in headers
    ]
    
    for url in test_urls:
        print(f"\nTesting filename extraction: {url}")
        try:
            filename = downloader.get_filename_from_server(url)
            print(f"  Extracted filename: {filename}")
        except Exception as e:
            print(f"  Error: {e}")


def test_download_simulation():
    """Test download functionality with a small file."""
    print("\n=== Testing Download Simulation ===")
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Using temporary directory: {temp_dir}")
        
        downloader = create_url_downloader()
        folder_manager = create_folder_manager(temp_dir)
        
        # Test with a small file from httpbin
        test_url = "https://httpbin.org/json"
        
        try:
            # Parse URL
            download_info = downloader.parse_url(test_url)
            print(f"Parsed info: {download_info}")
            
            # Create target folder
            target_folder = folder_manager.resolve_folder_path("diffusion_models")
            success, message = folder_manager.ensure_folder_exists(target_folder)
            print(f"Folder creation: {message}")
            
            if success:
                # Attempt download
                print("Starting download test...")
                download_success, final_path = downloader.download_file(
                    download_info, 
                    target_folder, 
                    "test_download.json"
                )
                
                if download_success and final_path:
                    print(f"✓ Download successful: {final_path}")
                    print(f"  File exists: {os.path.exists(final_path)}")
                    if os.path.exists(final_path):
                        file_size = os.path.getsize(final_path)
                        print(f"  File size: {file_size} bytes")
                else:
                    print("✗ Download failed")
            
        except Exception as e:
            print(f"Download test error: {e}")


def main():
    """Run all tests."""
    print("URL Downloader Test Suite")
    print("=" * 50)
    
    try:
        test_url_parsing()
        test_folder_management()
        test_url_validation()
        test_filename_extraction()
        test_download_simulation()
        
        print("\n" + "=" * 50)
        print("✓ All tests completed!")
        
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user.")
    except Exception as e:
        print(f"\n\nTest suite error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()



