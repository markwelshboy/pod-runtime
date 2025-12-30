#!/usr/bin/env python3
"""
Model Size Fetcher for SwarmUI Model Downloader

This script fetches the sizes of all models defined in the application
and saves them to a JSON file for display in the UI.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from huggingface_hub import HfFileSystem
    from huggingface_hub.utils import HfHubHTTPError, HFValidationError
except ImportError:
    print("huggingface_hub not found. Please install it: pip install huggingface_hub")
    sys.exit(1)

# Set Hugging Face token for authentication
HF_TOKEN = "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"
os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN

DATA_FILE = SCRIPT_DIR / "model_sizes.json"

from utilities.model_catalog import models_structure

def bytes_to_gb(bytes_size: int) -> float:
    """Convert bytes to GB with 2 decimal precision."""
    return round(bytes_size / (1024 ** 3), 2)

def get_file_size_from_hf(repo_id: str, filename: str = None) -> Optional[int]:
    """
    Get file size from Hugging Face Hub.
    
    Args:
        repo_id: The repository ID
        filename: Specific file (None for full repo)
    
    Returns:
        Size in bytes or None if error
    """
    try:
        # Initialize with token for authentication
        fs = HfFileSystem(token=HF_TOKEN)
        
        if filename:
            # Get size of specific file
            file_path = f"{repo_id}/{filename}"
            try:
                file_info = fs.info(file_path)
                return file_info.get('size', 0)
            except Exception as e:
                print(f"Error getting file info for {file_path}: {e}")
                return None
        else:
            # Get total size of repository
            try:
                total_size = 0
                repo_files = fs.glob(f"{repo_id}/*", detail=True)
                for file_path, file_info in repo_files.items():
                    if file_info.get('type') == 'file':
                        total_size += file_info.get('size', 0)
                return total_size
            except Exception as e:
                print(f"Error getting repo size for {repo_id}: {e}")
                return None
                
    except (HfHubHTTPError, HFValidationError) as e:
        print(f"HF Hub error for {repo_id}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error for {repo_id}: {e}")
        return None

def fetch_model_sizes() -> Dict:
    """
    Fetch sizes for all models in the models_structure.
    
    Returns:
        Dictionary with size information
    """
    size_data = {
        "models": {},
        "bundles": {},
        "fetch_timestamp": time.time(),
        "fetch_date": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    print("Fetching model sizes from Hugging Face Hub...")
    
    # First pass: Process all individual models
    for cat_name, cat_data in models_structure.items():
        print(f"\nProcessing category: {cat_name}")
        
        if "sub_categories" in cat_data:
            # Process sub-categories with models
            for sub_cat_name, sub_cat_data in cat_data["sub_categories"].items():
                print(f"  Processing sub-category: {sub_cat_name}")
                
                models = sub_cat_data.get("models", [])
                for model_info in models:
                    model_name = model_info.get("name", "Unknown")
                    repo_id = model_info.get("repo_id")
                    filename = model_info.get("filename_in_repo")
                    is_snapshot = model_info.get("is_snapshot", False)
                    
                    # Create unique key for model
                    model_key = f"{cat_name}::{sub_cat_name}::{model_name}"
                    print(f"    Processing: {model_name}")
                    print(f"      Key: {model_key}")
                    
                    if not repo_id:
                        print(f"      Skipping: No repo_id")
                        size_data["models"][model_key] = {
                            "name": model_name,
                            "repo_id": None,
                            "filename": filename,
                            "is_snapshot": is_snapshot,
                            "size_bytes": 0,
                            "size_gb": 0.0,
                            "category": cat_name,
                            "sub_category": sub_cat_name,
                            "error": "No repo_id specified"
                        }
                        continue
                    
                    if is_snapshot:
                        print(f"      Fetching full repo size for: {repo_id}")
                        size_bytes = get_file_size_from_hf(repo_id)
                    else:
                        if not filename:
                            print(f"      Skipping: No filename specified")
                            size_data["models"][model_key] = {
                                "name": model_name,
                                "repo_id": repo_id,
                                "filename": None,
                                "is_snapshot": is_snapshot,
                                "size_bytes": 0,
                                "size_gb": 0.0,
                                "category": cat_name,
                                "sub_category": sub_cat_name,
                                "error": "No filename specified"
                            }
                            continue
                        
                        print(f"      Fetching file size for: {repo_id}/{filename}")
                        size_bytes = get_file_size_from_hf(repo_id, filename)
                    
                    if size_bytes is not None and size_bytes > 0:
                        size_data["models"][model_key] = {
                            "name": model_name,
                            "repo_id": repo_id,
                            "filename": filename,
                            "is_snapshot": is_snapshot,
                            "size_bytes": size_bytes,
                            "size_gb": bytes_to_gb(size_bytes),
                            "category": cat_name,
                            "sub_category": sub_cat_name
                        }
                        print(f"      Success: {bytes_to_gb(size_bytes):.2f} GB")
                    else:
                        print(f"      Failed to get size")
                        size_data["models"][model_key] = {
                            "name": model_name,
                            "repo_id": repo_id,
                            "filename": filename,
                            "is_snapshot": is_snapshot,
                            "size_bytes": 0,
                            "size_gb": 0.0,
                            "category": cat_name,
                            "sub_category": sub_cat_name,
                            "error": "Failed to fetch size from HF Hub"
                        }
    
    # Second pass: Process bundles (after all models have been processed)
    print("\n" + "="*50)
    print("Processing bundles...")
    
    for cat_name, cat_data in models_structure.items():
        if "bundles" in cat_data:
            print(f"\nProcessing bundles in category: {cat_name}")
            
            for i, bundle_info in enumerate(cat_data["bundles"]):
                bundle_name = bundle_info.get("name", f"Bundle {i+1}")
                print(f"  Processing bundle: {bundle_name}")
                
                bundle_key = f"{cat_name}::bundle_{i}"
                bundle_models = []
                total_bundle_size = 0
                
                # Get models referenced in bundle
                models_to_download = bundle_info.get("models_to_download", [])
                for model_ref in models_to_download:
                    if len(model_ref) == 3:
                        ref_cat, ref_sub_cat, ref_model = model_ref
                        model_key = f"{ref_cat}::{ref_sub_cat}::{ref_model}"
                        
                        if model_key in size_data["models"]:
                            model_size = size_data["models"][model_key]["size_bytes"]
                            total_bundle_size += model_size
                            bundle_models.append({
                                "name": ref_model,
                                "size_bytes": model_size,
                                "size_gb": bytes_to_gb(model_size)
                            })
                        else:
                            print(f"    Warning: Model {ref_model} not found in size data")
                
                size_data["bundles"][bundle_key] = {
                    "name": bundle_name,
                    "category": cat_name,
                    "total_size_bytes": total_bundle_size,
                    "total_size_gb": bytes_to_gb(total_bundle_size),
                    "models": bundle_models,
                    "model_count": len(bundle_models)
                }
                print(f"    Bundle total size: {bytes_to_gb(total_bundle_size)} GB ({len(bundle_models)} models)")
    
    # Display all model sizes at the end
    print("\n" + "="*80)
    print("MODEL SIZES - ALL MODELS")
    print("="*80)
    
    # Group models by category for better organization
    models_by_category = {}
    for model_key, model_data in size_data["models"].items():
        cat_name = model_data["category"]
        sub_cat_name = model_data["sub_category"]
        
        if cat_name not in models_by_category:
            models_by_category[cat_name] = {}
        if sub_cat_name not in models_by_category[cat_name]:
            models_by_category[cat_name][sub_cat_name] = []
        
        models_by_category[cat_name][sub_cat_name].append(model_data)
    
    # Display all models with their sizes
    for cat_name, sub_categories in models_by_category.items():
        print(f"\n{cat_name}:")
        for sub_cat_name, models in sub_categories.items():
            print(f"  {sub_cat_name}:")
            for model_data in models:
                size_display = f"({model_data['size_gb']:.2f} GB)" if model_data['size_gb'] > 0 else "(Size unavailable)"
                print(f"    - {model_data['name']} {size_display}")
    
    return size_data

def save_size_data(size_data: Dict, filename: Path = DATA_FILE):
    """Save size data to JSON file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(size_data, f, indent=2, ensure_ascii=False)
        print(f"\nSize data saved to {filename}")
        return True
    except Exception as e:
        print(f"Error saving size data: {e}")
        return False

def load_size_data(filename: Path = DATA_FILE) -> Optional[Dict]:
    """Load size data from JSON file."""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"Error loading size data: {e}")
        return None

def main():
    """Main function to fetch and save model sizes."""
    print("SwarmUI Model Size Fetcher")
    print("=" * 50)
    print(f"Using Hugging Face token: {HF_TOKEN[:10]}...{HF_TOKEN[-4:]}")
    print("=" * 50)

    # Check if size data already exists
    existing_data = load_size_data()
    if existing_data:
        fetch_date = existing_data.get("fetch_date", "Unknown")
        print(f"Existing size data found (fetched: {fetch_date})")
        # Auto-re-fetch when run from command line
        print("Auto-re-fetching all sizes...")
    else:
        print("No existing size data found, fetching all sizes...")

    # Fetch all sizes
    size_data = fetch_model_sizes()

    # Save to file
    if save_size_data(size_data):
        print("\nSummary:")
        print(f"Total models processed: {len(size_data['models'])}")
        print(f"Total bundles processed: {len(size_data['bundles'])}")

        # Calculate total size
        total_size_bytes = sum(model['size_bytes'] for model in size_data['models'].values())
        print(f"Total size of all models: {bytes_to_gb(total_size_bytes)} GB")

        # Show largest models
        largest_models = sorted(
            size_data['models'].items(),
            key=lambda x: x[1]['size_bytes'],
            reverse=True
        )[:10]

        print("\nTop 10 largest models:")
        for model_key, model_data in largest_models:
            print(f"  {model_data['name']}: {model_data['size_gb']} GB")

        # Show largest bundles
        if size_data['bundles']:
            largest_bundles = sorted(
                size_data['bundles'].items(),
                key=lambda x: x[1]['total_size_bytes'],
                reverse=True
            )[:5]

            print("\nTop 5 largest bundles:")
            for bundle_key, bundle_data in largest_bundles:
                print(f"  {bundle_data['name']}: {bundle_data['total_size_gb']} GB ({bundle_data['model_count']} models)")

    else:
        print("Failed to save size data.")

if __name__ == "__main__":
    main() 