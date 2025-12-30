import gradio as gr
import sys
import subprocess
import os
import platform
import shutil
import time
import threading
import queue
import argparse
import copy
import json
from pathlib import Path

from utilities.model_catalog import (
    models_structure as MODEL_CATALOG,
    HIDREAM_INFO_LINK,
    GGUF_QUALITY_INFO,
)
from utilities.HF_model_downloader import (
    download_hf_file,
    download_hf_snapshot,
)
from utilities.url_downloader import create_url_downloader
from utilities.folder_manager import create_folder_manager
try:
    from huggingface_hub import hf_hub_download, snapshot_download, HfFileSystem
    from huggingface_hub.utils import HfHubHTTPError, HFValidationError
except ImportError:
    print("huggingface_hub not found. Attempting installation...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub>=0.20.0"])  # Added version specifier
        import importlib
        importlib.invalidate_caches()
        from huggingface_hub import hf_hub_download, snapshot_download, HfFileSystem
        from huggingface_hub.utils import HfHubHTTPError, HFValidationError
        print("huggingface_hub installed and imported successfully.")
    except Exception as e:
        print(f"ERROR: Failed to install or import huggingface_hub: {e}")
        print("Please install it manually: pip install huggingface_hub>=0.20.0")
        sys.exit(1)


APP_TITLE = f"Unified AI Models Downloader for SwarmUI, ComfyUI, Automatic1111 and Forge Web UI"

def install_package(package_name, version_spec=""):
    """Installs a package using pip."""
    try:
        print(f"Attempting to install {package_name}{version_spec}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", f"{package_name}{version_spec}"])
        print(f"Successfully installed {package_name}.")
        if package_name == "huggingface_hub":
            import importlib
            importlib.invalidate_caches()
            globals()['hf_hub_download'] = importlib.import_module('huggingface_hub').hf_hub_download
            globals()['snapshot_download'] = importlib.import_module('huggingface_hub').snapshot_download
            globals()['HfFileSystem'] = importlib.import_module('huggingface_hub').HfFileSystem
            globals()['HfHubHTTPError'] = importlib.import_module('huggingface_hub.utils').HfHubHTTPError
            globals()['HFValidationError'] = importlib.import_module('huggingface_hub.utils').HFValidationError
        elif package_name == "hf_transfer":
             import importlib
             importlib.invalidate_caches()
             globals()['HF_TRANSFER_AVAILABLE'] = True
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to install {package_name}: {e}")
        print("Please install it manually using: pip install ", f"{package_name}{version_spec}")
    except ImportError:
         print(f"ERROR: Failed to import {package_name} even after attempting install.")
    return False

print("huggingface_hub found (or installed).")

try:
    import hf_transfer
    print("hf_transfer found.")
    HF_TRANSFER_AVAILABLE = True
except ImportError:
    print("hf_transfer is optional but recommended for faster downloads.")
    HF_TRANSFER_AVAILABLE = False
    if install_package("hf_transfer", ">=0.1.8"):
        try:
            import hf_transfer
            print("hf_transfer installed successfully after attempt.")
            HF_TRANSFER_AVAILABLE = True
        except ImportError:
            print("hf_transfer still not found after install attempt.")
            HF_TRANSFER_AVAILABLE = False
    else:
        HF_TRANSFER_AVAILABLE = False

LAST_SETTINGS_FILE = "last_settings.json"
MODEL_SIZES_FILE = "utilities/model_sizes.json"

# Global variable to store size data
size_data = None

def save_last_settings(path, comfy_ui_structure, forge_structure=False, lowercase_folders=False):
    """Saves the given path, ComfyUI structure, Forge structure, and lowercase folders setting to a JSON file for next startup."""
    try:
        settings = {
            "path": path,
            "comfy_ui_structure": comfy_ui_structure,
            "forge_structure": forge_structure,
            "lowercase_folders": lowercase_folders
        }
        with open(LAST_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        add_log(f"Saved settings - Path: '{path}', ComfyUI structure: {comfy_ui_structure}, Forge structure: {forge_structure}, Lowercase folders: {lowercase_folders}")
        return f"✓ Settings saved: {path} (ComfyUI: {comfy_ui_structure}, Forge: {forge_structure}, Lowercase: {lowercase_folders})"
    except Exception as e:
        error_msg = f"ERROR: Could not save settings to file: {e}"
        add_log(error_msg)
        return f"✗ Error saving settings: {e}"

def load_last_settings():
    """Loads the last used settings from the JSON file if it exists. Also handles backward compatibility with old text file format."""
    try:
        # First try to load from new JSON format
        if os.path.exists(LAST_SETTINGS_FILE):
            with open(LAST_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            path = settings.get("path", "")
            comfy_ui_structure = settings.get("comfy_ui_structure", False)
            forge_structure = settings.get("forge_structure", False)
            lowercase_folders = settings.get("lowercase_folders", False)
            
            if path and os.path.isdir(path):
                print(f"Loaded saved settings from {LAST_SETTINGS_FILE}: Path='{path}', ComfyUI={comfy_ui_structure}, Forge={forge_structure}, Lowercase={lowercase_folders}")
                return path, comfy_ui_structure, forge_structure, lowercase_folders
            else:
                print(f"Saved path '{path}' from {LAST_SETTINGS_FILE} is not a valid directory. Using defaults.")
                return None, False, False, False
        
        # Backward compatibility: check for old text file format
        old_file = "last_model_path.txt"
        if os.path.exists(old_file):
            with open(old_file, 'r', encoding='utf-8') as f:
                path = f.read().strip()
            if path and os.path.isdir(path):
                print(f"Loaded saved path from legacy file {old_file}: {path} (migrating to new format)")
                # Save to new format and remove old file
                try:
                    save_last_settings(path, False, False, False)
                    os.remove(old_file)
                    print(f"Migrated settings to new format and removed legacy file.")
                except Exception as e:
                    print(f"Warning: Could not migrate legacy settings: {e}")
                return path, False, False, False
            else:
                print(f"Legacy saved path '{path}' from {old_file} is not a valid directory. Using defaults.")
                return None, False, False, False
        
        print(f"No saved settings file ({LAST_SETTINGS_FILE}) found. Using defaults.")
        return None, False, False, False
    except Exception as e:
        print(f"ERROR: Could not load saved settings from {LAST_SETTINGS_FILE}: {e}. Using defaults.")
        return None, False, False, False

def load_last_path():
    """Legacy function for backward compatibility - loads only the path."""
    path, _, _, _ = load_last_settings()
    return path

def load_model_sizes():
    """Load model size data from JSON file."""
    global size_data
    try:
        if os.path.exists(MODEL_SIZES_FILE):
            with open(MODEL_SIZES_FILE, 'r', encoding='utf-8') as f:
                size_data = json.load(f)
            fetch_date = size_data.get("fetch_date", "Unknown")
            model_count = len(size_data.get("models", {}))
            bundle_count = len(size_data.get("bundles", {}))
            print(f"Loaded model size data from {MODEL_SIZES_FILE} (fetched: {fetch_date})")
            print(f"  - {model_count} individual models with size data")
            print(f"  - {bundle_count} bundles with size data")
            
            # Debug: Show first few model keys for troubleshooting
            if model_count > 0:
                model_keys = list(size_data.get("models", {}).keys())
                print(f"  - Sample model keys: {model_keys[:3]}...")
                
                # Check for models with errors
                error_count = 0
                success_count = 0
                for key, model_info in size_data.get("models", {}).items():
                    if model_info.get("error"):
                        error_count += 1
                    elif model_info.get("size_gb", 0) > 0:
                        success_count += 1
                        
                print(f"  - Successfully fetched sizes: {success_count}")
                print(f"  - Models with errors: {error_count}")
                
                # Show some examples of models with sizes
                models_with_sizes = []
                for key, model_info in size_data.get("models", {}).items():
                    if model_info.get("size_gb", 0) > 0:
                        models_with_sizes.append(f"{model_info['name']} ({model_info['size_gb']:.2f} GB)")
                        if len(models_with_sizes) >= 3:
                            break
                if models_with_sizes:
                    print(f"  - Example models with sizes: {', '.join(models_with_sizes)}")
                
            return True
        else:
            print(f"No model size data file ({MODEL_SIZES_FILE}) found. Sizes will not be displayed.")
            print(f"To generate size data, run: python fetch_model_sizes.py")
            return False
    except Exception as e:
        print(f"ERROR: Could not load model size data from {MODEL_SIZES_FILE}: {e}")
        print(f"Traceback: {str(e)}")
        return False

def get_subcategory_total_size_display(cat_name, sub_cat_name, models_list):
    """Get total size display string for all models in a subcategory."""
    if not size_data or not size_data.get("models"):
        return f" ({len(models_list)} models - sizes unknown)"
    
    total_size_gb = 0.0
    models_with_size = 0
    models_with_error = 0
    
    for model_info in models_list:
        model_name = model_info.get("name", "Unknown")
        model_key = f"{cat_name}::{sub_cat_name}::{model_name}"
        model_size_info = size_data.get("models", {}).get(model_key)
        
        # If exact match not found, try fuzzy matching like in get_model_size_display
        if not model_size_info:
            possible_matches = []
            for key, info in size_data.get("models", {}).items():
                if model_name.lower() in key.lower() or info.get("name", "").lower() == model_name.lower():
                    possible_matches.append((key, info))
            
            if len(possible_matches) == 1:
                model_size_info = possible_matches[0][1]
            elif len(possible_matches) > 1:
                for key, info in possible_matches:
                    if key.endswith(f"::{model_name}"):
                        model_size_info = info
                        break
        
        if model_size_info:
            size_gb = model_size_info.get("size_gb", 0.0)
            if size_gb > 0:
                total_size_gb += size_gb
                models_with_size += 1
            elif model_size_info.get("error"):
                models_with_error += 1
    
    total_models = len(models_list)
    missing_count = total_models - models_with_size - models_with_error
    
    if models_with_size == 0:
        return f" ({total_models} models - total size unknown)"
    elif models_with_size == total_models:
        return f" ({total_models} models - Total: {total_size_gb:.2f} GB)"
    elif missing_count > 0:
        # Only show unknown count if there are actually unknown models
        return f" ({total_models} models - {total_size_gb:.2f} GB + {missing_count} unknown)"
    else:
        # All models have sizes or errors, no unknown models
        return f" ({total_models} models - Total: {total_size_gb:.2f} GB)"

def get_model_size_display(cat_name, sub_cat_name, model_name):
    """Get size display string for a model."""
    if not size_data or not size_data.get("models"):
        return " (Size unknown - run fetch_model_sizes.py)"
    
    model_key = f"{cat_name}::{sub_cat_name}::{model_name}"
    model_info = size_data.get("models", {}).get(model_key)
    
    # If exact match not found, try fuzzy matching
    if not model_info:
        # Try to find the model by checking all keys that contain the model name
        possible_matches = []
        for key, info in size_data.get("models", {}).items():
            # Check if the model name is similar (allowing for small variations)
            if model_name.lower() in key.lower() or info.get("name", "").lower() == model_name.lower():
                possible_matches.append((key, info))
        
        # If we found exactly one match, use it
        if len(possible_matches) == 1:
            model_key, model_info = possible_matches[0]
            print(f"DEBUG: Used fuzzy match for '{model_name}': '{model_key}'")
        elif len(possible_matches) > 1:
            # Multiple matches, try to find the best one
            for key, info in possible_matches:
                if key.endswith(f"::{model_name}"):  # Exact model name match at the end
                    model_key, model_info = key, info
                    print(f"DEBUG: Used exact model name match for '{model_name}': '{model_key}'")
                    break
    
    # Debug: Print first few lookups to help troubleshoot
    if not hasattr(get_model_size_display, '_debug_count'):
        get_model_size_display._debug_count = 0
    
    if get_model_size_display._debug_count < 5:
        get_model_size_display._debug_count += 1
        print(f"DEBUG: Model key lookup #{get_model_size_display._debug_count}: '{model_key}' -> {'Found' if model_info else 'Not found'}")
        
        # If still not found, show available keys for this model name
        if not model_info:
            similar_keys = []
            for key in size_data.get("models", {}).keys():
                if any(part.lower() in key.lower() for part in model_name.split()):
                    similar_keys.append(key)
            if similar_keys:
                print(f"DEBUG: Keys containing parts of '{model_name}': {similar_keys[:3]}")
    
    if model_info:
        size_gb = model_info.get("size_gb", 0.0)
        if size_gb > 0:
            return f" ({size_gb:.2f} GB)"
        elif model_info.get("error"):
            error_msg = model_info.get("error", "Unknown error")
            return f" (Size error: {error_msg})"
        else:
            return " (Size: 0 GB)"
    else:
        # Debug: Print missing model key for troubleshooting
        print(f"DEBUG: No size data found for model key: {model_key}")
        return " (Size not found)"

def get_bundle_size_display(cat_name, bundle_index):
    """Get size display string for a bundle."""
    if not size_data or not size_data.get("bundles"):
        return " (Bundle size unknown - run fetch_model_sizes.py)"
    
    bundle_key = f"{cat_name}::bundle_{bundle_index}"
    bundle_info = size_data.get("bundles", {}).get(bundle_key)
    
    if bundle_info:
        total_size_gb = bundle_info.get("total_size_gb", 0.0)
        model_count = bundle_info.get("model_count", 0)
        if total_size_gb > 0:
            return f" (Total: {total_size_gb:.2f} GB, {model_count} models)"
        else:
            return f" (Bundle size: 0 GB, {model_count} models)"
    else:
        # Debug: Print missing bundle key for troubleshooting
        print(f"DEBUG: No size data found for bundle key: {bundle_key}")
        # List available bundle keys for debugging
        available_bundle_keys = list(size_data.get("bundles", {}).keys())
        if available_bundle_keys:
            print(f"DEBUG: Available bundle keys: {available_bundle_keys[:3]}")
        return " (Bundle size not found)"

def get_bundle_with_sizes_info(cat_name, bundle_index, original_info):
    """Get bundle info with sizes integrated into the Includes section."""
    if not size_data or not size_data.get("bundles"):
        return original_info + "\n\n*Note: Bundle size information unavailable. Run `python fetch_model_sizes.py` to generate size data.*"
    
    bundle_key = f"{cat_name}::bundle_{bundle_index}"
    bundle_info = size_data.get("bundles", {}).get(bundle_key)
    
    if not bundle_info:
        return original_info + "\n\n*Note: Bundle size information not found.*"
    
    models = bundle_info.get("models", [])
    if not models:
        return original_info + "\n\n*Note: No model size data found for this bundle.*"
    
    # Create a mapping of model names to their sizes
    model_size_map = {}
    for model in models:
        name = model.get("name", "Unknown")
        size_gb = model.get("size_gb", 0.0)
        error = model.get("error")
        
        if error:
            model_size_map[name] = f"Error: {error}"
        elif size_gb > 0:
            model_size_map[name] = f"{size_gb:.2f} GB"
        else:
            model_size_map[name] = "0 GB"
    
    # Process the original info to add sizes to the includes section
    updated_info = original_info
    
    # Split the info into lines and process each line in the includes section
    lines = updated_info.split('\n')
    in_includes_section = False
    processed_lines = []
    
    for line in lines:
        if "**Includes:**" in line:
            in_includes_section = True
            processed_lines.append(line)
        elif in_includes_section and line.strip().startswith("- "):
            # Extract the model name from the line (remove the "- " prefix)
            model_name_in_line = line.strip()[2:]  # Remove "- "
            
            # Try to find a matching model size using fuzzy matching
            matched_size = None
            
            # First try exact matches
            for model_name, size_display in model_size_map.items():
                if model_name == model_name_in_line or model_name in model_name_in_line or model_name_in_line in model_name:
                    matched_size = size_display
                    break
            
            # If no exact match, try fuzzy matching
            if not matched_size:
                for model_name, size_display in model_size_map.items():
                    # Check if key parts of the model name match
                    model_parts = model_name.lower().split()
                    line_parts = model_name_in_line.lower().split()
                    
                    # If at least 2 significant words match, consider it a match
                    significant_matches = 0
                    for part in model_parts:
                        if len(part) > 3:  # Only consider words longer than 3 characters
                            if any(part in line_part for line_part in line_parts):
                                significant_matches += 1
                    
                    if significant_matches >= 2:
                        matched_size = size_display
                        break
            
            if matched_size:
                processed_lines.append(f"{line} ({matched_size})")
            else:
                processed_lines.append(f"{line} (Size unknown)")
        elif in_includes_section and line.strip() and not line.strip().startswith("- ") and "**" not in line:
            # End of includes section
            in_includes_section = False
            processed_lines.append(line)
        else:
            processed_lines.append(line)
    
    return '\n'.join(processed_lines)

def get_default_base_path():
    """Determines the default base path based on the OS and known paths."""
    # First check for saved path
    saved_path = load_last_path()
    if saved_path:
        return saved_path
    
    # If no saved path, use original logic
    system = platform.system()
    if system == "Windows":
        swarm_path = os.environ.get("SWARM_MODEL_PATH")
        if swarm_path and os.path.isdir(swarm_path): return swarm_path
        return os.path.join(os.getcwd(), "SwarmUI", "Models")
    else:  # Linux/Unix systems
        swarm_path = os.environ.get("SWARM_MODEL_PATH")
        if swarm_path and os.path.isdir(swarm_path): return swarm_path
        if os.path.exists("/home/Ubuntu/apps/StableSwarmUI"):
            return "/home/Ubuntu/apps/StableSwarmUI/Models"
        elif os.path.exists("/workspace/SwarmUI"):
            return "/workspace/SwarmUI/Models"
        else:
            return os.path.join(os.getcwd(), "SwarmUI", "Models")

def get_default_comfy_ui_structure():
    """Determines the default ComfyUI structure setting from saved settings."""
    _, comfy_ui_structure, _, _ = load_last_settings()
    return comfy_ui_structure

def get_default_forge_structure():
    """Determines the default Forge structure setting from saved settings."""
    _, _, forge_structure, _ = load_last_settings()
    return forge_structure

def get_default_lowercase_folders():
    """Determines the default lowercase folders setting from saved settings."""
    _, _, _, lowercase_folders = load_last_settings()
    return lowercase_folders

DEFAULT_BASE_PATH = get_default_base_path()

BASE_SUBDIRS = { # Renamed from SUBDIRS
    "vae": "VAE",  # SwarmUI uses uppercase VAE folder
    "VAE": "VAE",  # Explicit uppercase mapping
    "diffusion_models": "diffusion_models",
    "Stable-Diffusion": "Stable-Diffusion",
    "clip": "clip",  # SwarmUI uses clip folder for text encoders
    "text_encoders": "clip",  # Map text_encoders to clip folder for SwarmUI
    "clip_vision": "clip_vision",
    "yolov8": "yolov8",
    "style_models": "style_models",
    "Lora": "Lora", # Default Lora, will be changed if ComfyUI mode is on
    "upscale_models": "upscale_models",
    "LLM": "LLM",
    "Joy_caption": "Joy_caption",
    "clip_vision_google_siglip": "clip_vision/google--siglip-so400m-patch14-384",
    "LLM_unsloth_llama": "LLM/unsloth--Meta-Llama-3.1-8B-Instruct",
    "Joy_caption_monster_joy": "Joy_caption/cgrkzexw-599808",
    "controlnet": "controlnet",
    "model_patches": "controlnet",  # SwarmUI: model_patches goes to controlnet folder
}

def get_current_subdirs(is_comfy_ui_structure: bool, is_forge_structure: bool = False):
    """Returns the subdirectory mapping based on ComfyUI or Forge structure flags."""
    current_s = BASE_SUBDIRS.copy()
    if is_comfy_ui_structure:
        current_s["Lora"] = "loras"  # Change Lora to loras for ComfyUI
        current_s["loras"] = "loras"  # Also add lowercase mapping
        # ComfyUI uses text_encoders folder (also reads from clip for backward compatibility)
        current_s["clip"] = "text_encoders"  # ComfyUI newer versions use text_encoders
        current_s["text_encoders"] = "text_encoders"  # Text encoders folder for ComfyUI
        # ComfyUI uses lowercase vae folder
        current_s["vae"] = "vae"
        current_s["VAE"] = "vae"  # Map uppercase to lowercase for ComfyUI
        # ComfyUI uses lowercase embeddings
        current_s["Embeddings"] = "embeddings"
        current_s["embeddings"] = "embeddings"
        # ComfyUI uses checkpoints folder for main models
        current_s["Stable-Diffusion"] = "checkpoints"
        current_s["checkpoints"] = "checkpoints"
        current_s["diffusion_models"] = "diffusion_models"  # ComfyUI also has diffusion_models
        # ComfyUI uses model_patches folder for certain controlnets (e.g., Z-Image-Turbo-Fun-Controlnet-Union)
        current_s["model_patches"] = "model_patches"
    elif is_forge_structure:
        # Forge WebUI folder structure based on MODEL_SUPPORT_README.md from sd-webui-forge-classic
        # Reference: E:\Forge_Neo_v1\sd-webui-forge-classic\MODEL_SUPPORT_README.md
        
        # Main checkpoint/diffusion models go to Stable-diffusion folder
        current_s["Stable-diffusion"] = "Stable-diffusion"  # Main checkpoints (lowercase d)
        current_s["Stable-Diffusion"] = "Stable-diffusion"  # Handle both cases for compatibility
        current_s["diffusion_models"] = "Stable-diffusion"  # Map ALL diffusion_models to Stable-diffusion
        
        # VAE models - Forge uses "VAE" folder
        current_s["vae"] = "VAE"  # VAE folder in Forge
        current_s["VAE"] = "VAE"  # Also handle uppercase
        
        # LoRA models - Forge uses "Lora" folder
        current_s["Lora"] = "Lora"  # Lora folder in Forge
        current_s["lora"] = "Lora"  # Map lowercase variant
        current_s["loras"] = "Lora"  # Map ComfyUI style to Forge style
        
        # Text encoders - Forge uses text_encoder folder for CLIP/T5 models
        current_s["clip"] = "text_encoder"  # CLIP models go to text_encoder folder
        current_s["text_encoder"] = "text_encoder"  # Text encoder folder
        current_s["text_encoders"] = "text_encoder"  # Map SwarmUI text_encoders to Forge's text_encoder
        current_s["clip_vision"] = "text_encoder"  # CLIP vision also goes to text_encoder
        current_s["t5"] = "text_encoder"  # T5 models also go here
        current_s["umt5"] = "text_encoder"  # UMT5 models also go here
        
        # ControlNet models
        current_s["controlnet"] = "ControlNet"  # ControlNet folder
        current_s["ControlNet"] = "ControlNet"  # Handle uppercase variant
        current_s["model_patches"] = "ControlNet"  # model_patches goes to ControlNet in Forge
        
        # ControlNet Preprocessor models
        current_s["controlnetpreprocessor"] = "ControlNetPreprocessor"
        current_s["ControlNetPreprocessor"] = "ControlNetPreprocessor"
        current_s["preprocessor"] = "ControlNetPreprocessor"
        
        # ALL Upscaler models go to single ESRGAN folder per README (lines 175-184)
        current_s["upscale_models"] = "ESRGAN"  # Default upscalers to ESRGAN
        current_s["ESRGAN"] = "ESRGAN"  # ESRGAN models
        current_s["RealESRGAN"] = "ESRGAN"  # Map to single ESRGAN folder
        current_s["BSRGAN"] = "ESRGAN"  # Map to single ESRGAN folder
        current_s["DAT"] = "ESRGAN"  # Map to single ESRGAN folder
        current_s["SwinIR"] = "ESRGAN"  # Map to single ESRGAN folder
        current_s["ScuNET"] = "ESRGAN"  # Map to single ESRGAN folder
        current_s["upscalers"] = "ESRGAN"  # Any upscaler goes to ESRGAN
        
        # Embeddings folder
        current_s["embeddings"] = "embeddings"  # Textual inversion embeddings
        current_s["embedding"] = "embeddings"  # Alternative naming
        current_s["textual_inversion"] = "embeddings"  # Alternative naming
        
        # Diffusers format models folder
        current_s["diffusers"] = "diffusers"  # Diffusers format models
        current_s["diffusion"] = "diffusers"  # Alternative naming
        
        # Face restoration models (keeping for backward compatibility, though not in official README)
        current_s["Codeformer"] = "Codeformer"  # Codeformer models
        current_s["GFPGAN"] = "GFPGAN"  # GFPGAN models
        
        # Interrogation/captioning models (keeping for backward compatibility)
        current_s["BLIP"] = "BLIP"  # BLIP models
        current_s["deepbooru"] = "deepbooru"  # Deepbooru models (lowercase)
        
        # Additional model types (keeping for backward compatibility)
        current_s["hypernetworks"] = "hypernetworks"  # Hypernetworks (lowercase)
        current_s["LyCORIS"] = "LyCORIS"  # LyCORIS networks
        
        # Note: These folders exist in Forge but may vary by installation
    return current_s

def find_actual_cased_directory_component(parent_dir: str, component_name: str) -> str | None:
    """
    Finds an existing directory component case-insensitively within parent_dir.
    Returns the actual cased name if found as a directory, otherwise None.
    """
    if not os.path.isdir(parent_dir):
        return None
    name_lower = component_name.lower()
    try:
        for item in os.listdir(parent_dir):
            if item.lower() == name_lower:
                if os.path.isdir(os.path.join(parent_dir, item)):
                    return item
    except OSError: # Permission denied, etc.
        pass
    return None

def resolve_target_directory(base_dir: str, relative_path_str: str, lowercase_folders: bool = False) -> str:
    """
    Resolves/constructs a target directory path. On non-Windows systems,
    it attempts to find existing path components case-insensitively.
    The returned path is what should be used for os.makedirs().
    
    Args:
        base_dir: The base directory path
        relative_path_str: The relative path string
        lowercase_folders: If True, convert all directory names to lowercase
    """
    # Normalize relative_path_str once
    normalized_relative_path = os.path.normpath(relative_path_str)
    
    # Apply lowercase to path if requested
    if lowercase_folders:
        normalized_relative_path = normalized_relative_path.lower()

    if platform.system() == "Windows":
        return os.path.join(base_dir, normalized_relative_path)

    # Linux/Mac
    current_path = base_dir
    # Split normalized_relative_path into components
    components = []
    head, tail = os.path.split(normalized_relative_path)
    while tail:
        components.insert(0, tail)
        head, tail = os.path.split(head)
    if head: # If there's a remaining head (e.g. from an absolute path, though not expected here)
        components.insert(0, head)
    
    # Filter out empty or "." components that might result from normpath or splitting
    components = [comp for comp in components if comp and comp != '.']

    for component in components:
        actual_cased_comp = None
        if os.path.isdir(current_path): # Only scan if parent is an existing directory
             actual_cased_comp = find_actual_cased_directory_component(current_path, component)

        if actual_cased_comp:
            current_path = os.path.join(current_path, actual_cased_comp)
        else:
            current_path = os.path.join(current_path, component)
            
    return current_path


def ensure_directories_exist(base_path: str, is_comfy_ui_structure: bool, is_forge_structure: bool = False, lowercase_folders: bool = False):
    """Creates the base Models directory and all predefined subdirectories, respecting ComfyUI or Forge structure if enabled."""
    if not base_path:
        print("ERROR: Base path is empty, cannot ensure directories.")
        return "Error: Base path is empty.", ["Base path is empty"]

    subdirs_to_use = get_current_subdirs(is_comfy_ui_structure, is_forge_structure)
    
    all_dirs_to_ensure = [base_path]
    for subdir_value in subdirs_to_use.values():
        resolved_full_path = resolve_target_directory(base_path, subdir_value, lowercase_folders)
        all_dirs_to_ensure.append(resolved_full_path)
    
    # Remove duplicates that might arise from resolve_target_directory if paths already exist with different casing
    all_dirs_to_ensure = sorted(list(set(all_dirs_to_ensure)))


    created_count = 0
    verified_count = 0
    errors = []

    for directory_path_str in all_dirs_to_ensure:
        try:
            # resolve_target_directory already gives the path to be created or that exists
            norm_dir = os.path.normpath(directory_path_str)
            if not os.path.exists(norm_dir):
                os.makedirs(norm_dir, exist_ok=True)
                print(f"Created directory: {norm_dir}")
                created_count += 1
            else:
                verified_count += 1
        except OSError as e:
            error_msg = f"ERROR creating directory {directory_path_str} (normalized: {norm_dir}): {str(e)}"
            print(error_msg)
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"UNEXPECTED ERROR with directory {directory_path_str}: {str(e)}"
            print(error_msg)
            errors.append(error_msg)

    status = f"Directory check complete for '{base_path}' (ComfyUI mode: {is_comfy_ui_structure}, Forge mode: {is_forge_structure}, Lowercase: {lowercase_folders}). Created: {created_count}, Verified Existing: {verified_count}."
    if errors:
        status += f" Errors: {len(errors)} (see console)."
    print(status)
    return status, errors

# --- Download Queue and Worker ---

download_queue = queue.Queue()
status_updates = queue.Queue()
stop_worker = threading.Event()
cancel_current_download = threading.Event()  # New: Signal to cancel current download
current_download_info = {"model_name": None, "file_path": None}  # Track current download
current_download_lock = threading.Lock()  # Protect current download info
log_history = []
log_lock = threading.Lock()

def add_log(message):
    """Adds a message to the log history and prints it."""
    print(message)
    with log_lock:
        log_history.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(log_history) > 100:
            log_history.pop(0)
    if status_updates:
        try:
            log_str = "\n".join(map(str, log_history))
            status_updates.put_nowait(log_str) 
        except queue.Full:
            print("Warning: Status update queue is full, skipping update.") 
        except Exception as e:
            print(f"Error putting log update to queue: {e}")


def get_target_path(base_path: str, model_info: dict, sub_category_info: dict, is_comfy_ui_structure: bool, is_forge_structure: bool = False, lowercase_folders: bool = False) -> str:
    """Determines the full target directory path for a model, respecting ComfyUI or Forge structure."""
    subdirs_to_use = get_current_subdirs(is_comfy_ui_structure, is_forge_structure)
    target_key = model_info.get("target_dir_key") or sub_category_info.get("target_dir_key")

    if not target_key or target_key not in subdirs_to_use: # Check against current subdirs
        model_name = model_info.get('name', 'Unknown Model')
        sub_cat_name = sub_category_info.get('name', 'Unknown SubCategory') 
        if target_key:
            add_log(f"WARNING: Invalid 'target_dir_key' ('{target_key}') for {model_name} in {sub_cat_name}. Using default 'diffusion_models'.")
        else:
            add_log(f"WARNING: Missing 'target_dir_key' for {model_name} in {sub_cat_name}. Using default 'diffusion_models'.")
        target_key = "diffusion_models" 

    target_subdir_name = subdirs_to_use.get(target_key, "diffusion_models") # Get from current subdirs
    
    # Resolve the actual target directory, handling case insensitivity on Linux
    target_dir = resolve_target_directory(base_path, target_subdir_name, lowercase_folders)

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        add_log(f"ERROR: Could not ensure target directory {target_dir} exists: {e}")
    return target_dir

def _download_model_internal(model_info, sub_category_info, base_path, use_hf_transfer, is_comfy_ui_structure, is_forge_structure=False, lowercase_folders=False):
    """
    Handles the download of a single model or snapshot directly to the target folder.
    
    SHA Verification Logic:
    - For individual files: HF downloader automatically verifies SHA256 from HuggingFace
    - If file exists and SHA matches: Skip download (file is verified correct)
    - If file exists but SHA fails: Automatically re-download (overwrite corrupted file)
    - If file doesn't exist: Download normally
    - pre_delete models: Always re-download to ensure latest version
    """
    model_name = model_info.get('name', model_info.get('repo_id'))
    repo_id = model_info.get('repo_id')
    filename = model_info.get('filename_in_repo') 
    save_filename = model_info.get('save_filename') 
    is_snapshot = model_info.get('is_snapshot', False)
    allow_patterns = model_info.get('allow_patterns')
    pre_delete = model_info.get('pre_delete_target', False)
    # Removed allow_overwrite - SHA verification will handle this automatically

    # Update current download tracking
    with current_download_lock:
        current_download_info["model_name"] = model_name
        current_download_info["file_path"] = None

    if not repo_id:
        add_log(f"ERROR: Missing 'repo_id' for model {model_name}. Skipping.")
        return
    if not base_path:
        add_log(f"ERROR: Missing 'base_path' for model {model_name}. Skipping.")
        return

    target_dir = get_target_path(base_path, model_info, sub_category_info, is_comfy_ui_structure, is_forge_structure, lowercase_folders)
    if not os.path.isdir(target_dir): # Re-check after get_target_path's makedirs attempt
         add_log(f"ERROR: Target directory {target_dir} could not be confirmed for {model_name}. Skipping.")
         return

    final_target_path = os.path.join(target_dir, save_filename) if save_filename else None

    # SHA verification logic for individual files (snapshots handle their own verification)
    if not is_snapshot and final_target_path and filename:
        if pre_delete:
            # For pre_delete models, always delete and re-download to ensure latest version
            if os.path.exists(final_target_path):
                add_log(f"INFO: File '{final_target_path}' exists. pre_delete is enabled, will remove and redownload to ensure latest version.")
                try:
                    os.remove(final_target_path)
                    add_log(f"INFO: Removed existing file for pre_delete model: {final_target_path}")
                except OSError as e:
                    add_log(f"WARNING: Could not remove existing file {final_target_path}: {e}")
        # For non-pre_delete models, the HF downloader will handle SHA verification automatically
        # If file exists and SHA matches, it will be skipped
        # If file exists but SHA fails, it will be re-downloaded
        # This is handled in download_hf_file() function
        if os.path.exists(final_target_path):
            add_log(f"INFO: File '{os.path.basename(final_target_path)}' exists. SHA verification will determine if redownload is needed.")

    if is_snapshot:
        # For snapshots, the snapshot downloader handles verification automatically
        if os.path.exists(target_dir):
            add_log(f"INFO: Snapshot target directory '{target_dir}' exists. Proceeding with snapshot_download (will auto-verify and skip existing files).")
        else:
            add_log(f"INFO: Creating snapshot target directory '{target_dir}' for download.")

    add_log(f"Starting download: {model_name}...")
    
    # Check for cancellation before starting
    if cancel_current_download.is_set():
        add_log(f"Download cancelled before starting: {model_name}")
        return
    
    try:
        start_time = time.time()
        actual_downloaded_path = None 

        if is_snapshot:
            add_log(f" -> Downloading snapshot from {repo_id} directly to {target_dir}...")
            success = download_hf_snapshot(
                repo_id=repo_id,
                target_dir=target_dir,
                allow_patterns=allow_patterns,
                cancel_event=cancel_current_download,
            )
            if success:
                add_log(f" -> Snapshot download complete for {repo_id} into {target_dir}.")
                final_target_path = target_dir
                actual_downloaded_path = target_dir
            else:
                add_log(f" -> ERROR: Snapshot download failed for {repo_id}")
                return

        elif filename and save_filename and final_target_path:
            add_log(f" -> Downloading file '{filename}' from {repo_id} into '{target_dir}' as '{save_filename}'...")

            # Update file path tracking
            with current_download_lock:
                current_download_info["file_path"] = os.path.join(target_dir, save_filename)
            
            # Check for cancellation before download
            if cancel_current_download.is_set():
                add_log(f"Download cancelled: {model_name}")
                return

            success = download_hf_file(
                repo_id=repo_id,
                filename=filename,
                target_dir=target_dir,
                save_filename=save_filename,
                cancel_event=cancel_current_download,
            )
            
            if success:
                actual_downloaded_path = os.path.join(target_dir, save_filename)
                add_log(f" -> File downloaded successfully to: {actual_downloaded_path}")
                
                # Check if we need to rename to final target path
                if actual_downloaded_path != final_target_path:
                    add_log(f" -> Renaming '{actual_downloaded_path}' to '{final_target_path}'...")
                    
                    os.makedirs(os.path.dirname(final_target_path), exist_ok=True)
                    
                    if os.path.exists(final_target_path):
                        # Always allow overwrite since we've already done SHA verification
                        add_log(f" -> Final target path {final_target_path} exists. Removing before rename...")
                        try:
                            if os.path.isfile(final_target_path):
                                os.remove(final_target_path)
                            else:
                                add_log(f" -> WARNING: Cannot remove final target path as it's not a file: {final_target_path}")
                                raise OSError(f"Target path for rename is not a file: {final_target_path}")
                        except OSError as e:
                            add_log(f"ERROR: Failed to remove existing file at final path '{final_target_path}' before rename: {e}. Aborting rename.")
                            raise e 
                    try:
                        os.rename(actual_downloaded_path, final_target_path)
                        add_log(f" -> Successfully renamed to: {final_target_path}")
                        actual_downloaded_path = final_target_path
                    except OSError as e:
                        add_log(f"ERROR: Failed to rename '{actual_downloaded_path}' to '{final_target_path}': {e}")
                        add_log(f" -> The originally downloaded file likely remains at: {actual_downloaded_path}")
                        raise e 
                else:
                    add_log(f" -> Downloaded file is already at correct location.")
            else:
                add_log(f" -> ERROR: Download failed for {filename} from {repo_id}")
                return

        else:
             if is_snapshot: 
                 add_log(f"ERROR: Internal logic error for snapshot {model_name}. Skipping.")
             elif not filename:
                  add_log(f"ERROR: Invalid configuration for model {model_name}. Missing 'filename_in_repo'. Skipping.")
             elif not save_filename:
                  add_log(f"ERROR: Invalid configuration for model {model_name}. Missing 'save_filename'. Skipping.")
             else:
                  add_log(f"ERROR: Invalid configuration for model {model_name}. Path issue? Skipping.")
             return 

        # Check for cancellation after download completes
        if cancel_current_download.is_set():
            add_log(f"Download was cancelled during processing: {model_name}")
            # Clean up any partially downloaded files
            if actual_downloaded_path and os.path.exists(actual_downloaded_path):
                try:
                    if os.path.isfile(actual_downloaded_path):
                        os.remove(actual_downloaded_path)
                        add_log(f"Cleaned up cancelled download: {actual_downloaded_path}")
                except Exception as e:
                    add_log(f"Warning: Could not clean up cancelled file {actual_downloaded_path}: {e}")
            return

        # Check for companion JSON file download
        companion_json = model_info.get('companion_json')
        if companion_json and not is_snapshot:
            add_log(f" -> Checking for companion JSON file: {companion_json}")
            try:
                # Check for cancellation before companion download
                if cancel_current_download.is_set():
                    add_log(f"Companion JSON download cancelled: {companion_json}")
                else:
                    json_success = download_hf_file(
                        repo_id=repo_id,
                        filename=companion_json,
                        target_dir=target_dir,
                        save_filename=companion_json,
                        cancel_event=cancel_current_download,
                    )
                    
                    if json_success:
                        json_path = os.path.join(target_dir, companion_json)
                        add_log(f" -> Companion JSON file downloaded successfully: {json_path}")
                    else:
                        add_log(f" -> WARNING: Companion JSON file '{companion_json}' not found or download failed (this is non-fatal)")
            except Exception as e:
                add_log(f" -> WARNING: Error downloading companion JSON file '{companion_json}': {e} (this is non-fatal)")

        end_time = time.time()
        success_path = final_target_path if not is_snapshot else actual_downloaded_path 
        add_log(f"SUCCESS: Downloaded and processed {model_name} in {end_time - start_time:.2f} seconds. Final location: {success_path}")

    except (HfHubHTTPError, HFValidationError) as e:
        add_log(f"ERROR downloading {model_name} (HF Hub): {type(e).__name__} - {str(e)}")
    except FileNotFoundError as e:
         add_log(f"ERROR during file operation for {model_name} (File System): {type(e).__name__} - {str(e)}")
    except OSError as e:
         add_log(f"ERROR during file operation (rename/delete) for {model_name} (OS Error/Permissions): {type(e).__name__} - {str(e)}")
    except Exception as e:
        add_log(f"UNEXPECTED ERROR during download/process for {model_name}: {type(e).__name__} - {str(e)}")
        if 'actual_downloaded_path' in locals() and actual_downloaded_path:
             add_log(f" -> State before error: actual_downloaded_path='{actual_downloaded_path}'")
        if 'final_target_path' in locals() and final_target_path:
             add_log(f" -> State before error: final_target_path='{final_target_path}'")
    finally:
        # Clear current download tracking
        with current_download_lock:
            current_download_info["model_name"] = None
            current_download_info["file_path"] = None

def download_worker():
    """Worker thread function to process the download queue."""
    print("Download worker thread started.")
    while not stop_worker.is_set():
        try:
            task = download_queue.get(timeout=1)
        except queue.Empty:
            # Check if cancellation was requested while queue was empty
            if cancel_current_download.is_set():
                add_log("Clearing download queue due to cancellation...")
                # Clear the queue
                while not download_queue.empty():
                    try:
                        download_queue.get_nowait()
                    except queue.Empty:
                        break
                cancel_current_download.clear()
                add_log("Download queue cleared and cancellation reset.")
            continue

        # Check for cancellation before processing task
        if cancel_current_download.is_set():
            add_log("Skipping queued download due to cancellation...")
            download_queue.task_done()
            # Clear all remaining items in queue immediately
            skipped_count = 0
            while not download_queue.empty():
                try:
                    download_queue.get_nowait()
                    download_queue.task_done()
                    skipped_count += 1
                except queue.Empty:
                    break
            if skipped_count > 0:
                add_log(f"Skipped {skipped_count} additional queued downloads.")
            cancel_current_download.clear()
            add_log("Download cancellation complete. Ready for new downloads.")
            continue

        model_info, sub_category_info, base_path, use_hf_transfer, is_comfy_ui_structure, is_forge_structure, lowercase_folders = task
        original_hf_transfer_env = None
        try:
            original_hf_transfer_env = os.environ.get('HF_HUB_ENABLE_HF_TRANSFER')
            transfer_env_value = '1' if use_hf_transfer and HF_TRANSFER_AVAILABLE else '0'
            os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = transfer_env_value
            
            _download_model_internal(model_info, sub_category_info, base_path, use_hf_transfer, is_comfy_ui_structure, is_forge_structure, lowercase_folders)

        except Exception as e:
            model_name_for_log = model_info.get('name', 'unknown task')
            add_log(f"CRITICAL WORKER ERROR processing '{model_name_for_log}': {type(e).__name__} - {e}")
        finally:
            if original_hf_transfer_env is None:
                if 'HF_HUB_ENABLE_HF_TRANSFER' in os.environ:
                    del os.environ['HF_HUB_ENABLE_HF_TRANSFER']
            else:
                os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = original_hf_transfer_env
            download_queue.task_done()
    print("Download worker thread stopped.")


# --- Filtering Logic ---
# No changes needed in filter_models for this request.
def filter_models(structure, search_term):
    search_term = search_term.lower().strip()
    visibility = {} 
    if not search_term:
        for cat_name, cat_data in structure.items():
            cat_key = f"cat_{cat_name}"
            visibility[cat_key] = True
            if "sub_categories" in cat_data:
                for sub_cat_name in cat_data["sub_categories"]:
                    sub_cat_key = f"subcat_{cat_name}_{sub_cat_name}"
                    visibility[sub_cat_key] = True
            elif "bundles" in cat_data:
                for i, bundle_data in enumerate(cat_data["bundles"]):
                     bundle_key = f"bundle_{cat_name}_{i}"
                     visibility[bundle_key] = True
                     bundle_button_key = f"bundlebutton_{cat_name}_{i}"
                     visibility[bundle_button_key] = True
        return visibility
    for cat_name, cat_data in structure.items():
        cat_key = f"cat_{cat_name}"
        visibility[cat_key] = False 
        if "sub_categories" in cat_data:
            for sub_cat_name in cat_data["sub_categories"]:
                sub_cat_key = f"subcat_{cat_name}_{sub_cat_name}"
                visibility[sub_cat_key] = False
        elif "bundles" in cat_data:
             for i, bundle_data in enumerate(cat_data["bundles"]):
                 bundle_key = f"bundle_{cat_name}_{i}"
                 visibility[bundle_key] = False
                 bundle_button_key = f"bundlebutton_{cat_name}_{i}"
                 visibility[bundle_button_key] = False
    for cat_name, cat_data in structure.items():
        cat_key = f"cat_{cat_name}"
        cat_match = search_term in cat_name.lower()
        cat_becomes_visible = cat_match 
        if "sub_categories" in cat_data:
            for sub_cat_name, sub_cat_data in cat_data["sub_categories"].items():
                sub_cat_key = f"subcat_{cat_name}_{sub_cat_name}"
                sub_cat_match = search_term in sub_cat_name.lower()
                sub_cat_becomes_visible = sub_cat_match 
                model_match_found = False
                for model_info in sub_cat_data.get("models", []):
                    model_name = model_info.get("name", "").lower()
                    if search_term in model_name:
                        model_match_found = True
                        break 
                if model_match_found or sub_cat_match:
                    visibility[sub_cat_key] = True 
                    cat_becomes_visible = True 
            if cat_becomes_visible:
                 visibility[cat_key] = True 
        elif "bundles" in cat_data:
             bundle_match_found_in_cat = False
             for i, bundle_data in enumerate(cat_data["bundles"]):
                 bundle_key = f"bundle_{cat_name}_{i}"
                 bundle_button_key = f"bundlebutton_{cat_name}_{i}"
                 bundle_name = bundle_data.get("name", "").lower()
                 bundle_info = bundle_data.get("info", "").lower() 
                 if search_term in bundle_name or search_term in bundle_info:
                     visibility[bundle_key] = True
                     visibility[bundle_button_key] = True
                     bundle_match_found_in_cat = True
             if bundle_match_found_in_cat or cat_match: 
                 visibility[cat_key] = True
    return visibility

# --- Bundle Helper ---
# No changes needed in find_model_by_key for this request.
def find_model_by_key(category_name, sub_category_name, model_name):
    try:
        category_data = MODEL_CATALOG[category_name]
        sub_category_data = category_data["sub_categories"][sub_category_name]
        for model_info in sub_category_data["models"]:
            if model_info["name"] == model_name:
                return model_info, sub_category_data
        add_log(f"ERROR: Model '{model_name}' not found in '{category_name}' -> '{sub_category_name}'.")
        return None, None
    except KeyError:
        add_log(f"ERROR: Category '{category_name}' or Sub-category '{sub_category_name}' not found while searching for model '{model_name}'.")
        return None, None
    except Exception as e:
        add_log(f"ERROR: Unexpected error finding model '{model_name}': {e}")
        return None, None


# --- Gradio UI Builder ---

# Custom CSS for Gradio 6.0+ (moved to launch())
# Theme-neutral styling that works with both light and dark modes
# Uses transparent overlays and CSS variables instead of hardcoded colors
CUSTOM_CSS = """
/* Import Google Fonts for maximum readability */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* Apply readable font to entire app */
*, body, .gradio-container, .gr-button, .gr-input, .gr-box, label, span, p, div {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif !important;
}

/* Improve text rendering */
body, .gradio-container {
    -webkit-font-smoothing: antialiased !important;
    -moz-osx-font-smoothing: grayscale !important;
    text-rendering: optimizeLegibility !important;
    font-size: 16px !important;
}

/* Monospace for logs and code */
.status-log, pre, code, .log-output textarea, textarea[data-testid="textbox"] {
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
}

/* Improve button text readability */
button {
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    font-size: 15px !important;
}

/* Improve heading readability */
h1, h2, h3, h4, h5, h6 {
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
}

/* Markdown text improvements */
.markdown-text, .prose, .md {
    line-height: 1.6 !important;
    letter-spacing: 0.01em !important;
}

/* Accordion labels */
.label-wrap, .accordion-label {
    font-weight: 500 !important;
    font-size: 15px !important;
}

/* Modern styling for the app */
.gradio-container {
    max-width: 100% !important;
}

/* Left-aligned buttons */
button {
    text-align: left !important;
    justify-content: flex-start !important;
}

.left-aligned-button,
.left-aligned-button > *,
[class*="left-aligned-button"],
[class*="left-aligned-button"] button,
[class*="left-aligned-button"] .gr-button {
    text-align: left !important;
    justify-content: flex-start !important;
}

#left-aligned-bundle-button,
#left-aligned-bundle-button button,
#left-aligned-bundle-button * {
    text-align: left !important;
    justify-content: flex-start !important;
    display: flex !important;
    align-items: center !important;
}

.left-aligned-button button,
.left-aligned-button .gr-button,
#left-aligned-bundle-button button {
    display: flex !important;
    justify-content: flex-start !important;
    text-align: left !important;
    padding-left: 12px !important;
}

.left-aligned-button button *,
.left-aligned-button .gr-button *,
#left-aligned-bundle-button * {
    text-align: left !important;
    justify-self: flex-start !important;
}

button[class*="left-aligned"],
.gradio-container button.left-aligned-button {
    text-align: left !important;
    justify-content: flex-start !important;
}

/* Hint text styling */
.hint-text {
    font-size: 0.9em !important;
    opacity: 0.8 !important;
    margin-top: 5px !important;
    margin-bottom: 10px !important;
}

/* Expand/Collapse buttons styling */
.expand-collapse-buttons {
    margin-bottom: 15px !important;
}

/* Toggle button for Expand/Collapse All */
.expand-collapse-toggle-btn {
    font-weight: 600 !important;
    font-size: 1.1em !important;
    padding: 14px 28px !important;
    border-radius: 10px !important;
    border: 2px solid currentColor !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    margin: 12px 0 !important;
    width: 100% !important;
    text-align: center !important;
    justify-content: center !important;
}

.expand-collapse-toggle-btn:hover {
    transform: translateY(-3px) scale(1.01) !important;
    box-shadow: 0 10px 30px rgba(128, 128, 128, 0.3) !important;
}

.expand-collapse-toggle-btn:active {
    transform: translateY(-1px) scale(1.005) !important;
}

/* Bundle accordion styling */
.bundle-accordion {
    border: 2px solid rgba(128, 128, 128, 0.3) !important;
    border-radius: 12px !important;
    margin-bottom: 12px !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.bundle-accordion:hover {
    border-color: rgba(128, 128, 128, 0.6) !important;
    box-shadow: 0 4px 20px rgba(128, 128, 128, 0.15) !important;
    transform: translateY(-2px) !important;
}

/* Bundle header styling */
.bundle-header {
    font-size: 1.1em !important;
    font-weight: 600 !important;
}

/* Bundle content panel */
.bundle-content {
    padding: 16px !important;
    border-radius: 8px !important;
    margin-top: 8px !important;
}

/* Bundle download button */
.bundle-download-btn {
    font-weight: 600 !important;
    padding: 12px 24px !important;
    border-radius: 8px !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    margin-top: 12px !important;
    border: 2px solid transparent !important;
}

.bundle-download-btn:hover {
    transform: translateY(-4px) scale(1.02) !important;
    box-shadow: 0 10px 30px rgba(72, 187, 120, 0.4) !important;
}

.bundle-download-btn:active {
    transform: translateY(-2px) scale(1.01) !important;
}

/* Model list in bundles */
.bundle-model-list {
    border-radius: 8px !important;
    padding: 12px !important;
    margin: 8px 0 !important;
}

/* Category styling */
.category-accordion {
    border-left: 4px solid var(--primary-500, #667eea) !important;
    margin-bottom: 8px !important;
}

/* Sub-category styling */
.sub-category-panel {
    border-left: 3px solid var(--secondary-500, #9f7aea) !important;
    padding-left: 12px !important;
    margin-bottom: 8px !important;
}

/* Model button styling - 3-column grid */
.model-download-btn {
    border: 2px solid rgba(128, 128, 128, 0.3) !important;
    padding: 10px 12px !important;
    border-radius: 8px !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    margin: 4px 0 !important;
    width: 100% !important;
    text-align: left !important;
    font-size: 0.9em !important;
    min-height: 60px !important;
    display: flex !important;
    align-items: center !important;
    word-break: break-word !important;
    white-space: normal !important;
    line-height: 1.3 !important;
}

.model-download-btn:hover {
    border-color: var(--primary-500, #48bb78) !important;
    transform: translateY(-3px) scale(1.02) !important;
    box-shadow: 0 8px 25px rgba(72, 187, 120, 0.3) !important;
}

.model-download-btn:active {
    transform: translateY(-1px) scale(1.01) !important;
}

/* Grid layout improvements */
.bundle-grid-row {
    display: flex !important;
    gap: 12px !important;
    margin-bottom: 12px !important;
}

.bundle-grid-col {
    flex: 1 !important;
    min-width: 0 !important;
}

/* Ensure accordions in grid take full width */
.bundle-accordion {
    width: 100% !important;
}

/* Download all button */
.download-all-btn {
    font-weight: 600 !important;
    margin-top: 8px !important;
}

/* Status log styling */
.status-log {
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    font-size: 0.85em !important;
    border-radius: 8px !important;
}

/* Queue status */
.queue-status {
    font-weight: 600 !important;
}

/* Individual model download links in bundles */
.individual-download-section {
    margin-top: 12px !important;
    padding: 8px !important;
    border-radius: 8px !important;
    border: 1px solid rgba(128, 128, 128, 0.3) !important;
}

.individual-download-row {
    display: flex !important;
    align-items: center !important;
    padding: 4px 0 !important;
    border-bottom: 1px solid rgba(128, 128, 128, 0.2) !important;
}

.individual-download-row:last-child {
    border-bottom: none !important;
}

.individual-download-btn {
    font-weight: 500 !important;
    font-size: 0.8em !important;
    padding: 1px 6px !important;
    border: 1px solid currentColor !important;
    border-radius: 3px !important;
    min-width: 0 !important;
    width: auto !important;
    max-width: fit-content !important;
    transition: all 0.2s ease !important;
    flex-shrink: 0 !important;
}

.individual-download-btn:hover {
    transform: scale(1.05) !important;
}

.model-name-text {
    font-size: 0.9em !important;
    flex: 1 !important;
}
"""

def create_ui(default_base_path):
    """Creates the Gradio interface with Gradio 6.0+ compatibility."""
    # Load model size data
    has_size_data = load_model_sizes()
    
    tracked_components = {}
    tracked_accordions = {}  # Track all accordion components for expand/collapse functionality
    bundle_accordions = {}  # Track bundle accordions separately for better organization

    # Create the Blocks app (Gradio 6.0: theme/css moved to launch())
    # Using analytics_enabled=False and show_progress='hidden' to speed up initial load
    with gr.Blocks(title=APP_TITLE, analytics_enabled=False) as app:
        gr.Markdown(f"## {APP_TITLE} V115 > Source : https://www.patreon.com/posts/114517862")
        gr.Markdown(f"### ComfyUI Installer for SwarmUI's Back-End > https://www.patreon.com/posts/105023709")
        
        with gr.Tabs():
            with gr.Tab("Model Downloader"):
                gr.Markdown("### Select models or bundles to download. Downloads will be added to a queue. Use the search bar to filter.")
                
                log_output = gr.Textbox(label="Download Status / Log - Watch CMD / Terminal To See Download Status & Speed", lines=10, max_lines=20, interactive=False, value="Welcome! Logs will appear here.")
                
                # Cancel button and queue status
                with gr.Row():
                    cancel_button = gr.Button("🛑 Cancel Current Download", variant="stop", size="sm", scale=1)
                    with gr.Column(scale=2):
                        queue_status_label = gr.Markdown(f"Queue Size: {download_queue.qsize()}")
                
                # Confirmation dialog for cancel - will be shown/hidden dynamically
                cancel_confirm_dialog = gr.Column(visible=False)
                with cancel_confirm_dialog:
                    gr.Markdown("⚠️ **Are you sure you want to cancel the current download?**")
                    gr.Markdown("This will stop the current download and delete any partially downloaded files.")
                    with gr.Row():
                        confirm_cancel_button = gr.Button("Yes, Cancel Download", variant="stop", size="sm")
                        cancel_cancel_button = gr.Button("No, Continue Download", variant="secondary", size="sm")

                with gr.Row():
                     search_box = gr.Textbox(placeholder="Search models or bundles...", label="Search", scale=2, interactive=True)
                     use_hf_transfer_checkbox = gr.Checkbox(label="Enable hf_transfer (Faster Downloads)", value=HF_TRANSFER_AVAILABLE, scale=1)
                
                with gr.Row():
                     base_path_input = gr.Textbox(label="Base Download Path (SwarmUI/Models)", value=default_base_path, scale=3)
                     comfy_ui_structure_checkbox = gr.Checkbox(label="ComfyUI Folder Structure (e.g. 'loras' folder)", value=get_default_comfy_ui_structure(), scale=1)
                     forge_structure_checkbox = gr.Checkbox(label="Forge WebUI / Automatic1111 Folder Structure", value=get_default_forge_structure(), scale=1)
                     lowercase_folders_checkbox = gr.Checkbox(label="Lowercase Folder Names", value=get_default_lowercase_folders(), scale=1)
                     remember_path_button = gr.Button("💾 Remember Settings", scale=1, size="sm")
                
                remember_path_status = gr.Markdown("", visible=False)
                
                # Consolidated info and buttons in one row
                with gr.Row():
                    with gr.Column(scale=4):
                        gr.Markdown("💡 **Tip:** Use 'Remember Settings' to save your preferred download location, ComfyUI/Forge structure, and lowercase folder preference. • **Note:** Only one structure (ComfyUI or Forge) can be active at a time. • **Lowercase Folders:** When enabled, folder names convert to lowercase (e.g., 'Stable-Diffusion' → 'stable-diffusion').", elem_classes="hint-text")
                    expand_all_button = gr.Button("📂 Expand All", size="sm", scale=1)
                    collapse_all_button = gr.Button("📁 Collapse All", size="sm", scale=1)
                
                # Search results container for direct download buttons
                # Reduced from 50 to 15 for faster initial load - search results scroll if needed
                with gr.Column(visible=False) as search_results_container:
                    gr.Markdown("### Search Results (showing top 15 matches)")
                    search_results_message = gr.Markdown("")
                    
                    # Pre-create search result rows (we'll show/hide them dynamically)
                    # Reduced from 50 to 15 for faster initial page load
                    MAX_SEARCH_RESULTS = 15
                    search_result_rows = []
                    search_result_buttons = []
                    
                    for i in range(MAX_SEARCH_RESULTS):
                        with gr.Row(visible=False) as row:
                            download_btn = gr.Button("", elem_classes="left-aligned-button", interactive=False)
                            
                        search_result_rows.append({
                            "row": row,
                            "button": download_btn
                        })
                
                # Functions to handle expand/collapse all
                def expand_all_accordions():
                    """Expand all accordions"""
                    updates = []
                    for accordion in tracked_accordions.values():
                        updates.append(gr.update(open=True))
                    add_log("Expanded all accordions")
                    return updates
                
                def collapse_all_accordions():
                    """Collapse all accordions"""
                    updates = []
                    for accordion in tracked_accordions.values():
                        updates.append(gr.update(open=False))
                    add_log("Collapsed all accordions")
                    return updates
                
                # We'll connect these buttons after creating all accordions

                # === CANCEL FUNCTIONALITY ===
                def handle_cancel_request():
                    """Show the confirmation dialog when cancel is requested"""
                    with current_download_lock:
                        current_model = current_download_info.get("model_name")
                    
                    if current_model:
                        add_log(f"Cancel requested for: {current_model}")
                        return gr.update(visible=True)  # Show confirmation dialog
                    else:
                        add_log("No active download to cancel.")
                        return gr.update(visible=False)  # Keep dialog hidden
                
                def handle_confirm_cancel():
                    """Actually cancel the download"""
                    with current_download_lock:
                        current_model = current_download_info.get("model_name")
                        current_file = current_download_info.get("file_path")
                    
                    if current_model:
                        add_log(f"⚠️ CANCELLING DOWNLOAD: {current_model}")
                        cancel_current_download.set()
                        
                        # Try to clean up current file immediately if we know where it is
                        if current_file and os.path.exists(current_file):
                            try:
                                if os.path.isfile(current_file):
                                    os.remove(current_file)
                                    add_log(f"Immediately cleaned up: {current_file}")
                            except Exception as e:
                                add_log(f"Warning: Could not immediately clean up {current_file}: {e}")
                        
                        add_log("Download cancellation signal sent. Current download will stop and queue will be cleared.")
                    else:
                        add_log("No active download found to cancel.")
                    
                    return gr.update(visible=False)  # Hide confirmation dialog
                
                def handle_cancel_cancel():
                    """User decided not to cancel"""
                    add_log("Download cancellation aborted by user.")
                    return gr.update(visible=False)  # Hide confirmation dialog

                # Connect cancel button handlers
                cancel_button.click(
                    fn=handle_cancel_request,
                    inputs=[],
                    outputs=[cancel_confirm_dialog]
                )
                
                confirm_cancel_button.click(
                    fn=handle_confirm_cancel,
                    inputs=[],
                    outputs=[cancel_confirm_dialog]
                )
                
                cancel_cancel_button.click(
                    fn=handle_cancel_cancel,
                    inputs=[],
                    outputs=[cancel_confirm_dialog]
                )

                # Initial directory check with default ComfyUI structure (False)
                # initial_dir_status, _ = ensure_directories_exist(default_base_path, False) # Pass comfy_ui_structure_checkbox.value (default False)
                # add_log(f"Initial directory check: {initial_dir_status}")

                def update_hf_transfer_setting(value):
                    add_log(f"User {'enabled' if value else 'disabled'} hf_transfer checkbox.")

                use_hf_transfer_checkbox.change(fn=update_hf_transfer_setting, inputs=use_hf_transfer_checkbox, outputs=None)

                def handle_remember_path_click(current_path, comfy_ui_checked, forge_checked, lowercase_folders_checked):
                    """Handles the remember path button click."""
                    if not current_path or not current_path.strip():
                        return gr.update(value="⚠️ Please enter a path first", visible=True)
                    
                    result = save_last_settings(current_path.strip(), comfy_ui_checked, forge_checked, lowercase_folders_checked)
                    return gr.update(value=result, visible=True)

                remember_path_button.click(
                    fn=handle_remember_path_click,
                    inputs=[base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox],
                    outputs=[remember_path_status]
                )

                def handle_comfy_checkbox_change(is_comfy_checked):
                    """Handle ComfyUI checkbox change and uncheck Forge if ComfyUI is checked."""
                    if is_comfy_checked:
                        add_log("ComfyUI folder structure enabled, disabling Forge structure.")
                        return gr.update(value=False)  # Uncheck Forge
                    return gr.update()  # No change to Forge
                
                def handle_forge_checkbox_change(is_forge_checked):
                    """Handle Forge checkbox change and uncheck ComfyUI if Forge is checked."""
                    if is_forge_checked:
                        add_log("Forge folder structure enabled, disabling ComfyUI structure.")
                        return gr.update(value=False)  # Uncheck ComfyUI
                    return gr.update()  # No change to ComfyUI

                def handle_dir_structure_change(current_base_path, is_comfy_checked, is_forge_checked, lowercase_folders_checked):
                    # status_msg, _ = ensure_directories_exist(current_base_path, is_comfy_checked, is_forge_checked, lowercase_folders_checked)
                    add_log(f"Base path or structure setting changed. Base: '{current_base_path}', ComfyUI Mode: {is_comfy_checked}, Forge Mode: {is_forge_checked}, Lowercase: {lowercase_folders_checked}. Directories will be ensured upon download initiation.")
                    # No direct output to UI component from here, log is sufficient.
                    # Or return status_msg to a dedicated status gr.Markdown if needed.

                # Handle mutual exclusivity between ComfyUI and Forge checkboxes
                comfy_ui_structure_checkbox.change(
                    fn=handle_comfy_checkbox_change,
                    inputs=[comfy_ui_structure_checkbox],
                    outputs=[forge_structure_checkbox]
                )
                forge_structure_checkbox.change(
                    fn=handle_forge_checkbox_change,
                    inputs=[forge_structure_checkbox],
                    outputs=[comfy_ui_structure_checkbox]
                )
                
                # Handle directory structure changes
                comfy_ui_structure_checkbox.change(
                    fn=handle_dir_structure_change,
                    inputs=[base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox],
                    outputs=None # Log output is handled by add_log
                )
                forge_structure_checkbox.change(
                    fn=handle_dir_structure_change,
                    inputs=[base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox],
                    outputs=None # Log output is handled by add_log
                )
                base_path_input.change( # Assuming base_path_input doesn't have other .change events that would conflict. If so, combine logic.
                    fn=handle_dir_structure_change,
                    inputs=[base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox],
                    outputs=None # Log output is handled by add_log
                )
                lowercase_folders_checkbox.change(
                    fn=handle_dir_structure_change,
                    inputs=[base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox],
                    outputs=None # Log output is handled by add_log
                )

                def enqueue_download(model_info, sub_category_info, current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders):
                    if not current_base_path:
                         add_log("ERROR: Cannot queue download, base path input is empty.")
                         return f"Queue Size: {download_queue.qsize()}"
                    if not isinstance(sub_category_info, dict):
                        add_log(f"ERROR: Invalid sub_category_info type ({type(sub_category_info)}) for model {model_info.get('name')}. Skipping queue.")
                        return f"Queue Size: {download_queue.qsize()}"

                    dir_status_msg, dir_errors = ensure_directories_exist(current_base_path, is_comfy_checked, is_forge_checked, lowercase_folders)
                    add_log(f"Directory check for download: {dir_status_msg}")
                    if dir_errors:
                        add_log(f"ERROR: Directory setup failed for '{current_base_path}'. Download of '{model_info.get('name', model_info.get('repo_id'))}' aborted.")
                        for err in dir_errors:
                            add_log(f"  - {err}")
                        return f"Queue Size: {download_queue.qsize()}"

                    download_queue.put((model_info, sub_category_info, current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders))
                    add_log(f"Queued: {model_info.get('name', model_info.get('repo_id'))}")
                    return f"Queue Size: {download_queue.qsize()}"

                def enqueue_bulk_download(models_list, sub_category_info, current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders):
                    if not current_base_path:
                         add_log("ERROR: Cannot queue bulk download, base path input is empty.")
                         return f"Queue Size: {download_queue.qsize()}"
                    if not isinstance(sub_category_info, dict):
                        add_log(f"ERROR: Invalid sub_category_info type ({type(sub_category_info)}) for bulk download. Skipping queue.")
                        return f"Queue Size: {download_queue.qsize()}"

                    dir_status_msg, dir_errors = ensure_directories_exist(current_base_path, is_comfy_checked, is_forge_checked, lowercase_folders)
                    add_log(f"Directory check for bulk download: {dir_status_msg}")
                    if dir_errors:
                        sub_cat_name_log = sub_category_info.get("name", "Group")
                        add_log(f"ERROR: Directory setup failed for '{current_base_path}'. Bulk download from '{sub_cat_name_log}' aborted.")
                        for err in dir_errors:
                            add_log(f"  - {err}")
                        return f"Queue Size: {download_queue.qsize()}"

                    count = 0
                    sub_cat_name = sub_category_info.get("name", "Group") 
                    for model_info in models_list:
                         download_queue.put((model_info, sub_category_info, current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders))
                         count += 1
                    add_log(f"Queued {count} models from '{sub_cat_name}'.")
                    return f"Queue Size: {download_queue.qsize()}"

                def enqueue_bundle_download(bundle_definition, current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders):
                    if not current_base_path:
                        add_log("ERROR: Cannot queue bundle download, base path input is empty.")
                        return f"Queue Size: {download_queue.qsize()}"

                    bundle_name = bundle_definition.get("name", "Unnamed Bundle")
                    dir_status_msg, dir_errors = ensure_directories_exist(current_base_path, is_comfy_checked, is_forge_checked, lowercase_folders)
                    add_log(f"Directory check for bundle '{bundle_name}': {dir_status_msg}")
                    if dir_errors:
                        add_log(f"ERROR: Directory setup failed for '{current_base_path}'. Bundle download '{bundle_name}' aborted.")
                        for err in dir_errors:
                            add_log(f"  - {err}")
                        return f"Queue Size: {download_queue.qsize()}"

                    model_keys = bundle_definition.get("models_to_download", [])
                    queued_count = 0
                    errors = 0

                    add_log(f"Queueing bundle: '{bundle_name}'...")
                    for cat_name, sub_cat_name, model_name in model_keys:
                        model_info, sub_cat_info = find_model_by_key(cat_name, sub_cat_name, model_name)
                        if model_info and sub_cat_info:
                            # Use the standard enqueue function, passing comfy_checked state
                            enqueue_download(model_info, sub_cat_info, current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders)
                            queued_count += 1
                        else:
                            errors += 1
                            add_log(f"  -> ERROR: Could not find model '{model_name}' for bundle. Skipping.")

                    add_log(f"Bundle '{bundle_name}' processed. Queued: {queued_count}, Errors: {errors}.")
                    return f"Queue Size: {download_queue.qsize()}"

                # Store section-specific accordions for expand/collapse functionality
                section_accordions = {}
                
                for cat_name, cat_data in MODEL_CATALOG.items():
                    cat_key = f"cat_{cat_name}"
                    
                    # Special handling for SwarmUI Bundles - more organized layout
                    if cat_name == "SwarmUI Bundles" and "bundles" in cat_data:
                        # Initialize section accordions list for this category
                        section_accordions[cat_name] = []
                        
                        with gr.Accordion(f"📦 {cat_name} (Click to Expand)", open=True, visible=True, elem_classes="bundle-accordion") as cat_accordion:
                            tracked_components[cat_key] = cat_accordion
                            tracked_accordions[f"cat_{cat_name}"] = cat_accordion
                            
                            gr.Markdown(f"""
### 🚀 Quick Start Model Bundles
{cat_data.get("info", "")}

**Click on any bundle below to see what's included and download all models with one click!**
                            """)
                            
                            # Single toggle button for Expand/Collapse
                            bundle_toggle_btn = gr.Button(
                                "📂 Expand All Bundles", 
                                size="lg", 
                                scale=1,
                                elem_classes="expand-collapse-toggle-btn",
                                variant="secondary"
                            )
                            bundle_is_expanded = gr.State(False)  # Track expanded state
                            
                            # Create 2-column grid layout for bundle cards
                            bundles_list = cat_data.get("bundles", [])
                            for row_start in range(0, len(bundles_list), 2):
                                with gr.Row():
                                    for col_idx in range(2):
                                        i = row_start + col_idx
                                        if i >= len(bundles_list):
                                            # Empty column placeholder for odd number of bundles
                                            with gr.Column(scale=1):
                                                pass
                                            continue
                                        
                                        bundle_info = bundles_list[i]
                                        bundle_key = f"bundle_{cat_name}_{i}"
                                        bundle_button_key = f"bundlebutton_{cat_name}_{i}"
                                        bundle_display_name = bundle_info.get("name", f"Bundle {i+1}")
                                        bundle_size_display = get_bundle_size_display(cat_name, i)
                                        
                                        # Choose icon based on bundle name
                                        bundle_icon = "📦"
                                        if "FLUX" in bundle_display_name:
                                            bundle_icon = "⚡"
                                        elif "Wan" in bundle_display_name:
                                            bundle_icon = "🎬"
                                        elif "HiDream" in bundle_display_name:
                                            bundle_icon = "✨"
                                        elif "Image" in bundle_display_name or "Qwen" in bundle_display_name:
                                            bundle_icon = "🖼️"
                                        elif "Video" in bundle_display_name:
                                            bundle_icon = "🎥"
                                        elif "Min" in bundle_display_name or "Requirements" in bundle_display_name:
                                            bundle_icon = "📋"
                                        
                                        with gr.Column(scale=1):
                                            # Each bundle gets its own accordion that opens to show full details
                                            with gr.Accordion(
                                                f"{bundle_icon} {bundle_display_name}{bundle_size_display}", 
                                                open=False, 
                                                visible=True,
                                                elem_classes="bundle-accordion"
                                            ) as bundle_accordion:
                                                tracked_components[bundle_key] = bundle_accordion
                                                bundle_accordions[f"bundle_{cat_name}_{i}"] = bundle_accordion
                                                tracked_accordions[f"bundle_{cat_name}_{i}"] = bundle_accordion
                                                
                                                # Bundle content with clear organization
                                                with gr.Column(elem_classes="bundle-content"):
                                                    # Extract description (before "**Includes:**") and show it
                                                    bundle_base_info = bundle_info.get("info", "*No description provided.*")
                                                    
                                                    # Split the info at "**Includes:**" to get just the description
                                                    if "**Includes:**" in bundle_base_info:
                                                        description_part = bundle_base_info.split("**Includes:**")[0].strip()
                                                    else:
                                                        description_part = bundle_base_info
                                                    
                                                    gr.Markdown(description_part)
                                                    
                                                    # Unified includes list with download buttons
                                                    models_to_dl = bundle_info.get("models_to_download", [])
                                                    if models_to_dl:
                                                        gr.Markdown("**Includes:**")
                                                        with gr.Column(elem_classes="individual-download-section"):
                                                            for model_ref in models_to_dl:
                                                                if len(model_ref) == 3:
                                                                    ref_cat, ref_sub_cat, ref_model = model_ref
                                                                    model_size = get_model_size_display(ref_cat, ref_sub_cat, ref_model)
                                                                    
                                                                    with gr.Row(elem_classes="individual-download-row"):
                                                                        gr.Markdown(f"○ {ref_model}{model_size}", elem_classes="model-name-text")
                                                                        individual_dl_btn = gr.Button(
                                                                            "Download",
                                                                            size="sm",
                                                                            elem_classes="individual-download-btn",
                                                                            scale=0,
                                                                            min_width=0
                                                                        )
                                                                        
                                                                        # Create closure to capture model reference
                                                                        def make_individual_download_handler(cat, subcat, model):
                                                                            def handler(base_path, hf_transfer, comfy_ui, forge, lowercase):
                                                                                model_info, sub_cat_info = find_model_by_key(cat, subcat, model)
                                                                                if model_info and sub_cat_info:
                                                                                    return enqueue_download(
                                                                                        model_info, sub_cat_info, base_path,
                                                                                        hf_transfer, comfy_ui, forge, lowercase
                                                                                    )
                                                                                else:
                                                                                    add_log(f"ERROR: Could not find model '{model}' for individual download")
                                                                                    return f"Queue Size: {download_queue.qsize()}"
                                                                            return handler
                                                                        
                                                                        individual_dl_btn.click(
                                                                            fn=make_individual_download_handler(ref_cat, ref_sub_cat, ref_model),
                                                                            inputs=[
                                                                                base_path_input,
                                                                                use_hf_transfer_checkbox,
                                                                                comfy_ui_structure_checkbox,
                                                                                forge_structure_checkbox,
                                                                                lowercase_folders_checkbox
                                                                            ],
                                                                            outputs=[queue_status_label]
                                                                        )
                                                    
                                                    # Download button - prominent and easy to find
                                                    download_bundle_button = gr.Button(
                                                        f"⬇️ Download All Models{bundle_size_display}", 
                                                        variant="primary",
                                                        size="lg",
                                                        elem_classes="bundle-download-btn"
                                                    )
                                                    tracked_components[bundle_button_key] = download_bundle_button
                                                    
                                                    download_bundle_button.click(
                                                        fn=enqueue_bundle_download,
                                                        inputs=[
                                                            gr.State(bundle_info), 
                                                            base_path_input,
                                                            use_hf_transfer_checkbox,
                                                            comfy_ui_structure_checkbox,
                                                            forge_structure_checkbox,
                                                            lowercase_folders_checkbox
                                                        ],
                                                        outputs=[queue_status_label]
                                                    )
                                                
                                                # Add this bundle accordion to the section list
                                                section_accordions[cat_name].append(bundle_accordion)
                            
                            # Toggle button handler for expand/collapse
                            def create_bundle_toggle_handler(accordions_list):
                                def toggle_bundles(is_expanded):
                                    if is_expanded:
                                        # Currently expanded, so collapse all
                                        new_state = False
                                        btn_update = gr.update(value="📂 Expand All Bundles")
                                        accordion_updates = [gr.update(open=False) for _ in accordions_list]
                                    else:
                                        # Currently collapsed, so expand all
                                        new_state = True
                                        btn_update = gr.update(value="📁 Collapse All Bundles")
                                        accordion_updates = [gr.update(open=True) for _ in accordions_list]
                                    return [new_state, btn_update] + accordion_updates
                                return toggle_bundles
                            
                            bundle_toggle_btn.click(
                                fn=create_bundle_toggle_handler(section_accordions[cat_name]),
                                inputs=[bundle_is_expanded],
                                outputs=[bundle_is_expanded, bundle_toggle_btn] + section_accordions[cat_name]
                            )
                    
                    # Regular category handling (non-bundle categories) - uses same style as SwarmUI Bundles
                    elif "bundles" in cat_data:
                        # Initialize section accordions list for this category
                        section_accordions[cat_name] = []
                        
                        with gr.Accordion(f"📦 {cat_name}", open=False, visible=True, elem_classes="bundle-accordion") as cat_accordion: 
                            tracked_components[cat_key] = cat_accordion
                            tracked_accordions[f"cat_{cat_name}"] = cat_accordion
                            
                            if cat_data.get("info"):
                                gr.Markdown(cat_data.get("info", ""))
                            
                            # Single toggle button for Expand/Collapse
                            other_bundle_toggle_btn = gr.Button(
                                "📂 Expand All", 
                                size="lg", 
                                scale=1,
                                elem_classes="expand-collapse-toggle-btn",
                                variant="secondary"
                            )
                            other_bundle_is_expanded = gr.State(False)
                            
                            # Create 2-column grid layout for bundle cards
                            other_bundles_list = cat_data.get("bundles", [])
                            for row_start in range(0, len(other_bundles_list), 2):
                                with gr.Row():
                                    for col_idx in range(2):
                                        i = row_start + col_idx
                                        if i >= len(other_bundles_list):
                                            with gr.Column(scale=1):
                                                pass
                                            continue
                                        
                                        bundle_info = other_bundles_list[i]
                                        bundle_key = f"bundle_{cat_name}_{i}"
                                        bundle_button_key = f"bundlebutton_{cat_name}_{i}"
                                        bundle_display_name = bundle_info.get("name", f"Bundle {i+1}")
                                        bundle_size_display = get_bundle_size_display(cat_name, i)
                                        
                                        with gr.Column(scale=1):
                                            with gr.Accordion(
                                                f"📦 {bundle_display_name}{bundle_size_display}",
                                                open=False,
                                                elem_classes="bundle-accordion"
                                            ) as bundle_accordion:
                                                tracked_components[bundle_key] = bundle_accordion
                                                tracked_accordions[f"bundle_{cat_name}_{i}"] = bundle_accordion
                                                section_accordions[cat_name].append(bundle_accordion)
                                                
                                                with gr.Column(elem_classes="bundle-content"):
                                                    # Extract description (before "**Includes:**") and show it
                                                    bundle_base_info = bundle_info.get("info", "*No description provided.*")
                                                    
                                                    # Split the info at "**Includes:**" to get just the description
                                                    if "**Includes:**" in bundle_base_info:
                                                        description_part = bundle_base_info.split("**Includes:**")[0].strip()
                                                    else:
                                                        description_part = bundle_base_info
                                                    
                                                    gr.Markdown(description_part)
                                                    
                                                    # Unified includes list with download buttons
                                                    other_models_to_dl = bundle_info.get("models_to_download", [])
                                                    if other_models_to_dl:
                                                        gr.Markdown("**Includes:**")
                                                        with gr.Column(elem_classes="individual-download-section"):
                                                            for other_model_ref in other_models_to_dl:
                                                                if len(other_model_ref) == 3:
                                                                    other_ref_cat, other_ref_sub_cat, other_ref_model = other_model_ref
                                                                    other_model_size = get_model_size_display(other_ref_cat, other_ref_sub_cat, other_ref_model)
                                                                    
                                                                    with gr.Row(elem_classes="individual-download-row"):
                                                                        gr.Markdown(f"○ {other_ref_model}{other_model_size}", elem_classes="model-name-text")
                                                                        other_individual_dl_btn = gr.Button(
                                                                            "Download",
                                                                            size="sm",
                                                                            elem_classes="individual-download-btn",
                                                                            scale=0,
                                                                            min_width=0
                                                                        )
                                                                        
                                                                        # Create closure to capture model reference
                                                                        def make_other_individual_download_handler(cat, subcat, model):
                                                                            def handler(base_path, hf_transfer, comfy_ui, forge, lowercase):
                                                                                model_info, sub_cat_info = find_model_by_key(cat, subcat, model)
                                                                                if model_info and sub_cat_info:
                                                                                    return enqueue_download(
                                                                                        model_info, sub_cat_info, base_path,
                                                                                        hf_transfer, comfy_ui, forge, lowercase
                                                                                    )
                                                                                else:
                                                                                    add_log(f"ERROR: Could not find model '{model}' for individual download")
                                                                                    return f"Queue Size: {download_queue.qsize()}"
                                                                            return handler
                                                                        
                                                                        other_individual_dl_btn.click(
                                                                            fn=make_other_individual_download_handler(other_ref_cat, other_ref_sub_cat, other_ref_model),
                                                                            inputs=[
                                                                                base_path_input,
                                                                                use_hf_transfer_checkbox,
                                                                                comfy_ui_structure_checkbox,
                                                                                forge_structure_checkbox,
                                                                                lowercase_folders_checkbox
                                                                            ],
                                                                            outputs=[queue_status_label]
                                                                        )
                                                    
                                                    download_bundle_button = gr.Button(
                                                        f"⬇️ Download All Models{bundle_size_display}",
                                                        variant="primary",
                                                        size="lg",
                                                        elem_classes="bundle-download-btn"
                                                    )
                                                    tracked_components[bundle_button_key] = download_bundle_button
                                                    download_bundle_button.click(
                                                        fn=enqueue_bundle_download,
                                                        inputs=[
                                                            gr.State(bundle_info), 
                                                            base_path_input,
                                                            use_hf_transfer_checkbox,
                                                            comfy_ui_structure_checkbox,
                                                            forge_structure_checkbox,
                                                            lowercase_folders_checkbox
                                                        ],
                                                        outputs=[queue_status_label]
                                                    )
                            
                            # Toggle button handler for expand/collapse
                            def create_other_toggle_handler(accordions_list):
                                def toggle_items(is_expanded):
                                    if is_expanded:
                                        new_state = False
                                        btn_update = gr.update(value="📂 Expand All")
                                        accordion_updates = [gr.update(open=False) for _ in accordions_list]
                                    else:
                                        new_state = True
                                        btn_update = gr.update(value="📁 Collapse All")
                                        accordion_updates = [gr.update(open=True) for _ in accordions_list]
                                    return [new_state, btn_update] + accordion_updates
                                return toggle_items
                            
                            other_bundle_toggle_btn.click(
                                fn=create_other_toggle_handler(section_accordions[cat_name]),
                                inputs=[other_bundle_is_expanded],
                                outputs=[other_bundle_is_expanded, other_bundle_toggle_btn] + section_accordions[cat_name]
                            )
                    
                    elif "sub_categories" in cat_data:
                        # Initialize section accordions list for this category
                        section_accordions[cat_name] = []
                        
                        # Choose icon based on category name
                        cat_icon = "📁"
                        if "Image" in cat_name:
                            cat_icon = "🖼️"
                        elif "Video" in cat_name:
                            cat_icon = "🎬"
                        elif "Text" in cat_name or "Encoder" in cat_name:
                            cat_icon = "📝"
                        elif "VAE" in cat_name:
                            cat_icon = "🔧"
                        elif "Clip" in cat_name:
                            cat_icon = "🔗"
                        elif "Other" in cat_name or "Yolo" in cat_name:
                            cat_icon = "🛠️"
                        elif "LoRA" in cat_name:
                            cat_icon = "✨"
                        
                        with gr.Accordion(f"{cat_icon} {cat_name}", open=False, visible=True, elem_classes="category-accordion") as cat_accordion:
                            tracked_components[cat_key] = cat_accordion
                            tracked_accordions[f"cat_{cat_name}"] = cat_accordion
                            
                            # Category info and expand/collapse buttons
                            if cat_data.get("info"):
                                gr.Markdown(cat_data.get("info", ""))
                            
                            # Single toggle button for Expand/Collapse
                            cat_toggle_btn = gr.Button(
                                "📂 Expand All", 
                                size="lg", 
                                scale=1,
                                elem_classes="expand-collapse-toggle-btn",
                                variant="secondary"
                            )
                            cat_is_expanded = gr.State(False)
                            
                            # Create 2-column grid layout for subcategories
                            sub_cats_list = list(cat_data.get("sub_categories", {}).items())
                            for row_start in range(0, len(sub_cats_list), 2):
                                with gr.Row():
                                    for col_idx in range(2):
                                        sub_idx = row_start + col_idx
                                        if sub_idx >= len(sub_cats_list):
                                            with gr.Column(scale=1):
                                                pass
                                            continue
                                        
                                        sub_cat_name, sub_cat_data = sub_cats_list[sub_idx]
                                        sub_cat_key = f"subcat_{cat_name}_{sub_cat_name}"
                                        
                                        # Calculate total size for subcategory
                                        models_in_subcat = sub_cat_data.get("models", [])
                                        subcat_size_display = get_subcategory_total_size_display(cat_name, sub_cat_name, models_in_subcat)
                                        
                                        with gr.Column(scale=1):
                                            # Each subcategory gets its own compact accordion
                                            with gr.Accordion(f"{sub_cat_name}{subcat_size_display}", open=False, elem_classes="bundle-accordion") as subcat_accordion:
                                                tracked_components[sub_cat_key] = subcat_accordion
                                                tracked_accordions[f"subcat_{cat_name}_{sub_cat_name}"] = subcat_accordion
                                                section_accordions[cat_name].append(subcat_accordion)
                                                
                                                with gr.Column(elem_classes="bundle-content"):
                                                    if sub_cat_data.get("info"):
                                                        gr.Markdown(sub_cat_data.get("info", ""))
                                                    
                                                    if not models_in_subcat:
                                                        gr.Markdown("*No models listed in this sub-category yet.*")
                                                        continue
                                                    
                                                    # Display models in 3-column grid
                                                    for model_row_start in range(0, len(models_in_subcat), 3):
                                                        with gr.Row():
                                                            for model_col_idx in range(3):
                                                                model_idx = model_row_start + model_col_idx
                                                                if model_idx >= len(models_in_subcat):
                                                                    # Empty column placeholder
                                                                    with gr.Column(scale=1, min_width=200):
                                                                        pass
                                                                    continue
                                                                
                                                                model_info = models_in_subcat[model_idx]
                                                                model_display_name = model_info.get("name", "Unknown Model")
                                                                model_size_display = get_model_size_display(cat_name, sub_cat_name, model_display_name)
                                                                button_text = f"⬇️ {model_display_name}{model_size_display}"
                                                                
                                                                with gr.Column(scale=1, min_width=200):
                                                                    download_button = gr.Button(
                                                                        button_text, 
                                                                        elem_classes="left-aligned-button model-download-btn",
                                                                        size="sm"
                                                                    )
                                                                    
                                                                    current_sub_cat_state_data = sub_cat_data.copy()
                                                                    if 'name' not in current_sub_cat_state_data:
                                                                        current_sub_cat_state_data['name'] = sub_cat_name
                                                                    
                                                                    download_button.click(
                                                                        fn=enqueue_download,
                                                                        inputs=[
                                                                            gr.State(model_info),
                                                                            gr.State(current_sub_cat_state_data), 
                                                                            base_path_input,
                                                                            use_hf_transfer_checkbox,
                                                                            comfy_ui_structure_checkbox,
                                                                            forge_structure_checkbox,
                                                                            lowercase_folders_checkbox
                                                                        ],
                                                                        outputs=[queue_status_label]
                                                                    )
                                                    
                                                    if models_in_subcat:
                                                        gr.Markdown("---")
                                                        download_all_button = gr.Button(
                                                            f"📥 Download All{subcat_size_display}", 
                                                            elem_classes="bundle-download-btn",
                                                            variant="primary",
                                                            size="lg"
                                                        )
                                                        all_sub_cat_state_data = sub_cat_data.copy()
                                                        if 'name' not in all_sub_cat_state_data:
                                                            all_sub_cat_state_data['name'] = sub_cat_name
                                                        download_all_button.click(
                                                            fn=enqueue_bulk_download,
                                                            inputs=[
                                                                gr.State(models_in_subcat),
                                                                gr.State(all_sub_cat_state_data), 
                                                                base_path_input,
                                                                use_hf_transfer_checkbox,
                                                                comfy_ui_structure_checkbox,
                                                                forge_structure_checkbox,
                                                                lowercase_folders_checkbox
                                                            ],
                                                            outputs=[queue_status_label]
                                                        )
                            
                            # Toggle button handler for expand/collapse
                            def create_cat_toggle_handler(accordions_list):
                                def toggle_subcats(is_expanded):
                                    if is_expanded:
                                        new_state = False
                                        btn_update = gr.update(value="📂 Expand All")
                                        accordion_updates = [gr.update(open=False) for _ in accordions_list]
                                    else:
                                        new_state = True
                                        btn_update = gr.update(value="📁 Collapse All")
                                        accordion_updates = [gr.update(open=True) for _ in accordions_list]
                                    return [new_state, btn_update] + accordion_updates
                                return toggle_subcats
                            
                            cat_toggle_btn.click(
                                fn=create_cat_toggle_handler(section_accordions[cat_name]),
                                inputs=[cat_is_expanded],
                                outputs=[cat_is_expanded, cat_toggle_btn] + section_accordions[cat_name]
                            )
                    
                    else:
                        with gr.Accordion(f"📁 {cat_name}", open=False, visible=True, elem_classes="category-accordion") as cat_accordion:
                            tracked_components[cat_key] = cat_accordion
                            tracked_accordions[f"cat_{cat_name}"] = cat_accordion
                            gr.Markdown(cat_data.get("info", "*No sub-categories or bundles defined.*"))

                # Connect expand/collapse buttons after all accordions are created
                expand_all_button.click(
                    fn=expand_all_accordions,
                    inputs=[],
                    outputs=list(tracked_accordions.values())
                )
                
                collapse_all_button.click(
                    fn=collapse_all_accordions,
                    inputs=[],
                    outputs=list(tracked_accordions.values())
                )

                # Store search results data for button handlers
                search_results_data = []
                updating_search_ui = False  # Flag to prevent handlers during UI updates
                
                def update_search_results(search_term: str):
                    """Update search results display"""
                    nonlocal updating_search_ui
                    updating_search_ui = True
                    
                    try:
                        if not search_term or not search_term.strip():
                            # Hide search results and show normal view
                            updates = [gr.update(visible=False), gr.update()]  # search container, message
                            
                            # Show all normal components
                            for key, component in tracked_components.items():
                                updates.append(gr.update(visible=True))
                            
                            # Hide all search result rows
                            for row_data in search_result_rows:
                                updates.append(gr.update(visible=False))  # row
                                updates.append(gr.update(value="", interactive=False))  # button - disable when hidden
                                
                            return updates
                        
                        search_term_lower = search_term.lower().strip()
                        matching_items = []
                        
                        # Search for matching models
                        for cat_name, cat_data in MODEL_CATALOG.items():
                            if "sub_categories" in cat_data:
                                for sub_cat_name, sub_cat_data in cat_data["sub_categories"].items():
                                    for model_info in sub_cat_data.get("models", []):
                                        model_name = model_info.get("name", "")
                                        if search_term_lower in model_name.lower():
                                            matching_items.append({
                                                "type": "model",
                                                "model": model_info,
                                                "category": cat_name,
                                                "subcategory": sub_cat_name,
                                                "sub_cat_data": sub_cat_data
                                            })
                            
                            # Search for matching bundles
                            if "bundles" in cat_data:
                                for i, bundle_info in enumerate(cat_data.get("bundles", [])):
                                    bundle_name = bundle_info.get("name", "")
                                    bundle_info_text = bundle_info.get("info", "")
                                    if search_term_lower in bundle_name.lower() or search_term_lower in bundle_info_text.lower():
                                        matching_items.append({
                                            "type": "bundle",
                                            "bundle": bundle_info,
                                            "category": cat_name,
                                            "index": i
                                        })
                        
                        # Clear search results data
                        search_results_data.clear()
                        search_results_data.extend(matching_items)
                        
                        # Prepare updates
                        updates = []
                        
                        # Show search container
                        updates.append(gr.update(visible=True))
                        
                        # Update message
                        if not matching_items:
                            updates.append(gr.update(value=f"No results found for '{search_term}'"))
                        else:
                            model_count = sum(1 for item in matching_items if item["type"] == "model")
                            bundle_count = sum(1 for item in matching_items if item["type"] == "bundle")
                            msg = f"Found {len(matching_items)} results: "
                            if model_count > 0:
                                msg += f"{model_count} model{'s' if model_count > 1 else ''}"
                            if bundle_count > 0:
                                if model_count > 0:
                                    msg += f", "
                                msg += f"{bundle_count} bundle{'s' if bundle_count > 1 else ''}"
                            updates.append(gr.update(value=msg))
                        
                        # Hide all normal components
                        for key, component in tracked_components.items():
                            updates.append(gr.update(visible=False))
                        
                        # Update search result rows
                        for i, row_data in enumerate(search_result_rows):
                            if i < len(matching_items):
                                item = matching_items[i]
                                
                                if item["type"] == "model":
                                    model_info = item["model"]
                                    cat_name = item["category"]
                                    sub_cat_name = item["subcategory"]
                                    
                                    model_display_name = model_info.get("name", "Unknown Model")
                                    model_size_display = get_model_size_display(cat_name, sub_cat_name, model_display_name)
                                    
                                    button_text = f"- {model_display_name}{model_size_display}"
                                else:  # bundle
                                    bundle_info = item["bundle"]
                                    cat_name = item["category"]
                                    bundle_index = item["index"]
                                    
                                    bundle_name = bundle_info.get("name", "Unknown Bundle")
                                    bundle_size_display = get_bundle_size_display(cat_name, bundle_index)
                                    
                                    button_text = f"Download {bundle_name}{bundle_size_display}"
                                
                                updates.append(gr.update(visible=True))  # row
                                updates.append(gr.update(value=button_text, interactive=True))  # button
                            else:
                                updates.append(gr.update(visible=False))  # row
                                updates.append(gr.update(value="", interactive=False))  # button - disable when hidden
                        
                        return updates
                    finally:
                        updating_search_ui = False
                
                # Create button click handlers for search results
                def create_download_handler(index):
                    def handler(current_base_path, hf_transfer_enabled, is_comfy_checked, is_forge_checked, lowercase_folders):
                        # Safety check: prevent execution during UI updates
                        if updating_search_ui:
                            return f"Queue Size: {download_queue.qsize()}"
                        
                        # Safety check: ensure we have enough search results data
                        if not search_results_data or index >= len(search_results_data):
                            return f"Queue Size: {download_queue.qsize()}"
                        
                        # Safety check: ensure inputs are valid (all parameters must be provided)
                        if (current_base_path is None or hf_transfer_enabled is None or 
                            is_comfy_checked is None or is_forge_checked is None or lowercase_folders is None):
                            return f"Queue Size: {download_queue.qsize()}"
                        
                        if not current_base_path or current_base_path.strip() == "":
                            return f"Queue Size: {download_queue.qsize()}"
                        
                        # Additional safety check: ensure the button should be active
                        if index >= MAX_SEARCH_RESULTS:
                            return f"Queue Size: {download_queue.qsize()}"
                            
                        try:
                            item = search_results_data[index]
                            
                            if item["type"] == "model":
                                model_info = item["model"]
                                sub_cat_data = item["sub_cat_data"]
                                sub_cat_name = item["subcategory"]
                                
                                # Prepare state data
                                current_sub_cat_state_data = sub_cat_data.copy()
                                if 'name' not in current_sub_cat_state_data:
                                    current_sub_cat_state_data['name'] = sub_cat_name
                                
                                return enqueue_download(
                                    model_info,
                                    current_sub_cat_state_data,
                                    current_base_path,
                                    hf_transfer_enabled,
                                    is_comfy_checked,
                                    is_forge_checked,
                                    lowercase_folders
                                )
                            else:  # bundle
                                bundle_info = item["bundle"]
                                
                                return enqueue_bundle_download(
                                    bundle_info,
                                    current_base_path,
                                    hf_transfer_enabled,
                                    is_comfy_checked,
                                    is_forge_checked,
                                    lowercase_folders
                                )
                        except Exception as e:
                            add_log(f"Error in search result button handler {index}: {e}")
                            return f"Queue Size: {download_queue.qsize()}"
                    return handler
                
                # Connect search result buttons with proper closure handling
                for i, row_data in enumerate(search_result_rows):
                    # Create a handler with the index properly captured
                    handler_func = create_download_handler(i)
                    
                    row_data["button"].click(
                        fn=handler_func,
                        inputs=[
                            base_path_input,
                            use_hf_transfer_checkbox,
                            comfy_ui_structure_checkbox,
                            forge_structure_checkbox,
                            lowercase_folders_checkbox
                        ],
                        outputs=[queue_status_label]
                    )
                
                # Create outputs list for search change handler
                search_outputs = [search_results_container, search_results_message]
                search_outputs.extend(list(tracked_components.values()))
                for row_data in search_result_rows:
                    search_outputs.extend([row_data["row"], row_data["button"]])
                
                search_box.change(
                    fn=update_search_results,
                    inputs=[search_box],
                    outputs=search_outputs
                )

                try:
                    # Timer interval increased to 2 seconds (from 1) to reduce UI overhead
                    # The tick function is lightweight so active=True is fine
                    timer = gr.Timer(2, active=True) 
                    def update_log_display():
                        log_update = gr.update() 
                        queue_update = gr.update() 
                        try:
                            latest_log = status_updates.get_nowait()
                            log_update = latest_log 
                        except queue.Empty:
                            pass 
                        q_size = download_queue.qsize()
                        queue_update = f"Queue Size: {q_size}"
                        return log_update, queue_update
                    # show_progress=False prevents loading spinner from showing during timer updates
                    timer.tick(update_log_display, None, [log_output, queue_status_label], show_progress=False)
                    add_log("Using gr.Timer for UI updates.")
                except AttributeError:
                    add_log("gr.Timer not found, falling back to deprecated app.load(every=1) for UI updates.")
                    def update_log_display_legacy():
                         log_update = gr.update()
                         queue_update = gr.update()
                         try:
                             latest_log = status_updates.get_nowait()
                             log_update = latest_log
                         except queue.Empty:
                             pass
                         q_size = download_queue.qsize()
                         queue_update = f"Queue Size: {q_size}"
                         return {log_output: log_update, queue_status_label: queue_update}
                    app.load(update_log_display_legacy, None, [log_output, queue_status_label], every=1)

            with gr.Tab("URL Downloader"):
                gr.Markdown("### Download models from direct URLs (CivitAI, HuggingFace, and generic URLs)")
                gr.Markdown("💡 **Supports:** CivitAI model pages, HuggingFace direct links, and any direct download URL. The downloader will automatically detect the source and handle filename extraction.")
                
                # URL input section
                with gr.Row():
                    url_input = gr.Textbox(
                        label="Model URL", 
                        placeholder="Enter CivitAI model URL, HuggingFace direct link, or any download URL...",
                        scale=4,
                        lines=1
                    )
                    validate_url_button = gr.Button("🔍 Validate URL", size="sm", scale=1)
                
                url_validation_status = gr.Markdown("", visible=False)
                
                # API Keys section (optional)
                with gr.Row():
                    civitai_api_input = gr.Textbox(
                        label="CivitAI API Key (Optional)",
                        placeholder="Enter your CivitAI API key for private models and higher rate limits...",
                        type="password",
                        scale=1,
                        lines=1
                    )
                    huggingface_api_input = gr.Textbox(
                        label="HuggingFace API Key (Optional)", 
                        placeholder="Enter your HuggingFace token for private repos and higher rate limits...",
                        type="password",
                        scale=1,
                        lines=1
                    )
                
                with gr.Row():
                    gr.Markdown("""
                    **🔑 API Keys (Optional):**
                    - **CivitAI**: Required for some private/premium models. Get yours at [civitai.com/user/account](https://civitai.com/user/account)
                    - **HuggingFace**: Enables access to private repositories and removes rate limits. Get yours at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
                    - **Default**: Built-in keys work for most public models. Only add your own if you need access to private content or encounter rate limits.
                    """, elem_classes="hint-text")
                
                # Pre-compute initial folder choices to avoid app.load() blocking
                def get_initial_folder_choices():
                    """Pre-compute folder dropdown choices at UI creation time."""
                    try:
                        folder_manager = create_folder_manager(
                            default_base_path, 
                            get_default_comfy_ui_structure(), 
                            get_default_forge_structure(), 
                            get_default_lowercase_folders()
                        )
                        available_folders = folder_manager.get_available_folders()
                        choices = [(display_name, folder_key) for display_name, folder_key in available_folders]
                        
                        # Find default value
                        default_value = None
                        for display_name, folder_key in choices:
                            if folder_key == 'diffusion_models':
                                default_value = folder_key
                                break
                        if not default_value:
                            for display_name, folder_key in choices:
                                if folder_key in ['checkpoints', 'Stable-Diffusion']:
                                    default_value = folder_key
                                    break
                        if not default_value and choices:
                            default_value = choices[0][1]
                        
                        ui_type = folder_manager.get_ui_type_display()
                        return choices, default_value, ui_type
                    except Exception:
                        return [("diffusion_models → diffusion_models", "diffusion_models")], "diffusion_models", "SwarmUI"
                
                initial_choices, initial_value, initial_ui_type = get_initial_folder_choices()
                
                # Folder selection section
                with gr.Row():
                    folder_dropdown = gr.Dropdown(
                        label="Target Folder",
                        choices=initial_choices,  # Pre-populated for fast load
                        value=initial_value,
                        scale=2,
                        interactive=True
                    )
                    custom_folder_input = gr.Textbox(
                        label="Custom Folder Path (Optional)",
                        placeholder="e.g., 'custom_models' or '/absolute/path/to/folder'",
                        scale=2
                    )
                    suggest_folder_button = gr.Button("💡 Auto-Suggest", size="sm", scale=1)
                
                # Filename section
                with gr.Row():
                    custom_filename_input = gr.Textbox(
                        label="Custom Filename (Optional)",
                        placeholder="Leave empty to use server-provided filename",
                        scale=3
                    )
                    download_url_button = gr.Button("⬇️ Download", variant="primary", size="lg", scale=1)
                
                # Status and info section
                url_download_status = gr.Markdown("")
                
                with gr.Row():
                    with gr.Column(scale=3):
                        gr.Markdown("""
                        **Supported URL formats:**
                        - **CivitAI:** `https://civitai.com/models/1864658/finalcut-sdxl?modelVersionId=2119886`
                        - **HuggingFace:** `https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors`
                        - **Direct URLs:** Any direct download link to model files
                        
                        **Features:**
                        - Automatic filename detection from server
                        - Smart folder suggestions based on filename
                        - Support for custom folder paths (relative or absolute)
                        - Progress tracking and cancellation support
                        """, elem_classes="hint-text")
                    
                    with gr.Column(scale=1):
                        folder_info_display = gr.Markdown(f"**Current UI:** {initial_ui_type}", elem_classes="hint-text")
                
                # URL Downloader Functions
                def update_folder_dropdown(base_path, is_comfy_ui, is_forge, lowercase_folders):
                    """Update the folder dropdown based on current settings."""
                    try:
                        folder_manager = create_folder_manager(base_path, is_comfy_ui, is_forge, lowercase_folders)
                        available_folders = folder_manager.get_available_folders()
                        
                        # Create choices for dropdown (display_name, folder_key)
                        choices = [(display_name, folder_key) for display_name, folder_key in available_folders]
                        
                        # Set default selection to models → diffusion_models (prioritize diffusion_models)
                        default_value = None
                        
                        # First priority: look for diffusion_models
                        for display_name, folder_key in choices:
                            if folder_key == 'diffusion_models':
                                default_value = folder_key
                                break
                        
                        # Second priority: look for models mapping to diffusion_models
                        if not default_value:
                            for display_name, folder_key in choices:
                                if 'models' in display_name.lower() and 'diffusion_models' in display_name.lower():
                                    default_value = folder_key
                                    break
                        
                        # Third priority: other common model folders
                        if not default_value:
                            for display_name, folder_key in choices:
                                if folder_key in ['checkpoints', 'Stable-Diffusion']:
                                    default_value = folder_key
                                    break
                        
                        # Fallback: first choice
                        if not default_value and choices:
                            default_value = choices[0][1]
                        
                        ui_type = folder_manager.get_ui_type_display()
                        
                        return (
                            gr.update(choices=choices, value=default_value),
                            gr.update(value=f"**Current UI:** {ui_type}")
                        )
                    except Exception as e:
                        add_log(f"Error updating folder dropdown: {e}")
                        return (
                            gr.update(choices=[("Error loading folders", "diffusion_models")], value="diffusion_models"),
                            gr.update(value="**Current UI:** Error")
                        )
                
                def validate_url(url, base_path, is_comfy_ui, is_forge, lowercase_folders, civitai_api, hf_api):
                    """Validate a URL and show information about it."""
                    if not url or not url.strip():
                        return gr.update(value="", visible=False)
                    
                    try:
                        # Use custom API keys if provided, otherwise use defaults
                        civitai_key = civitai_api.strip() if civitai_api and civitai_api.strip() else "5577db242d28f46030f55164cdd2da5d"
                        hf_key = hf_api.strip() if hf_api and hf_api.strip() else None
                        
                        # Create URL downloader with API keys
                        url_downloader = create_url_downloader(civitai_api_key=civitai_key, huggingface_api_key=hf_key)
                        is_valid, message = url_downloader.validate_url(url.strip())
                        
                        if is_valid:
                            # Parse URL to get additional info
                            download_info = url_downloader.parse_url(url.strip())
                            source_type = download_info.get('source_type', 'unknown')
                            suggested_filename = download_info.get('filename', 'Unknown')
                            
                            status_msg = f"**{message}**\n\n"
                            status_msg += f"**Source:** {source_type.title()}\n"
                            if suggested_filename:
                                status_msg += f"**Suggested filename:** {suggested_filename}\n"
                            
                            # Get folder suggestions
                            folder_manager = create_folder_manager(base_path, is_comfy_ui, is_forge, lowercase_folders)
                            if suggested_filename:
                                suggestions = folder_manager.get_folder_suggestions_by_filename(suggested_filename)
                                if suggestions:
                                    status_msg += f"**Suggested folders:** {', '.join(suggestions[:3])}"
                            
                            return gr.update(value=status_msg, visible=True)
                        else:
                            return gr.update(value=f"**{message}**", visible=True)
                            
                    except Exception as e:
                        return gr.update(value=f"**✗ Validation error:** {str(e)}", visible=True)
                
                def suggest_folder_for_url(url, base_path, is_comfy_ui, is_forge, lowercase_folders, civitai_api, hf_api):
                    """Suggest folder based on URL analysis."""
                    if not url or not url.strip():
                        return gr.update()
                    
                    try:
                        # Use custom API keys if provided, otherwise use defaults
                        civitai_key = civitai_api.strip() if civitai_api and civitai_api.strip() else "5577db242d28f46030f55164cdd2da5d"
                        hf_key = hf_api.strip() if hf_api and hf_api.strip() else None
                        
                        # Create URL downloader with API keys
                        url_downloader = create_url_downloader(civitai_api_key=civitai_key, huggingface_api_key=hf_key)
                        download_info = url_downloader.parse_url(url.strip())
                        suggested_filename = download_info.get('filename')
                        
                        if not suggested_filename:
                            # Try to get filename from server
                            suggested_filename = url_downloader.get_filename_from_server(download_info['download_url'])
                        
                        if suggested_filename:
                            folder_manager = create_folder_manager(base_path, is_comfy_ui, is_forge, lowercase_folders)
                            suggestions = folder_manager.get_folder_suggestions_by_filename(suggested_filename)
                            
                            if suggestions:
                                # Update dropdown to the first suggestion
                                return gr.update(value=suggestions[0])
                        
                        return gr.update()
                        
                    except Exception as e:
                        add_log(f"Error suggesting folder: {e}")
                        return gr.update()
                
                def download_from_url(url, folder_key, custom_folder, custom_filename, 
                                    base_path, is_comfy_ui, is_forge, lowercase_folders, use_hf_transfer, civitai_api, hf_api):
                    """Download a file from URL."""
                    if not url or not url.strip():
                        return "❌ Please enter a URL"
                    
                    if not base_path or not base_path.strip():
                        return "❌ Please set a base download path"
                    
                    try:
                        # Use custom API keys if provided, otherwise use defaults
                        civitai_key = civitai_api.strip() if civitai_api and civitai_api.strip() else "5577db242d28f46030f55164cdd2da5d"
                        hf_key = hf_api.strip() if hf_api and hf_api.strip() else None
                        
                        # Create managers with API keys
                        url_downloader = create_url_downloader(civitai_api_key=civitai_key, huggingface_api_key=hf_key)
                        folder_manager = create_folder_manager(base_path, is_comfy_ui, is_forge, lowercase_folders)
                        
                        # Parse URL
                        download_info = url_downloader.parse_url(url.strip())
                        add_log(f"Parsed URL: {download_info['source_type']} - {download_info['download_url']}")
                        
                        # Determine target folder
                        if custom_folder and custom_folder.strip():
                            target_folder = folder_manager.resolve_folder_path(None, custom_folder.strip())
                        elif folder_key:
                            target_folder = folder_manager.resolve_folder_path(folder_key)
                        else:
                            target_folder = folder_manager.resolve_folder_path("diffusion_models")
                        
                        # Ensure folder exists
                        folder_success, folder_message = folder_manager.ensure_folder_exists(target_folder)
                        if not folder_success:
                            return f"❌ {folder_message}"
                        
                        add_log(f"Target folder: {target_folder}")
                        
                        # Start download
                        success, final_path = url_downloader.download_file(
                            download_info, 
                            target_folder, 
                            custom_filename.strip() if custom_filename and custom_filename.strip() else None,
                            cancel_current_download
                        )
                        
                        if success:
                            add_log(f"✅ Download completed: {final_path}")
                            return f"✅ **Download completed!**\n\nSaved to: `{final_path}`"
                        else:
                            add_log(f"❌ Download failed for URL: {url}")
                            return "❌ Download failed. Check the log for details."
                            
                    except Exception as e:
                        error_msg = f"❌ Download error: {str(e)}"
                        add_log(error_msg)
                        return error_msg
                
                # Connect URL downloader events
                validate_url_button.click(
                    fn=validate_url,
                    inputs=[url_input, base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox, civitai_api_input, huggingface_api_input],
                    outputs=[url_validation_status]
                )
                
                suggest_folder_button.click(
                    fn=suggest_folder_for_url,
                    inputs=[url_input, base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox, civitai_api_input, huggingface_api_input],
                    outputs=[folder_dropdown]
                )
                
                download_url_button.click(
                    fn=download_from_url,
                    inputs=[
                        url_input, folder_dropdown, custom_folder_input, custom_filename_input,
                        base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, 
                        lowercase_folders_checkbox, use_hf_transfer_checkbox, civitai_api_input, huggingface_api_input
                    ],
                    outputs=[url_download_status]
                )
                
                # Note: folder_dropdown is now pre-populated during UI creation to avoid blocking app.load()
                # Update folder dropdown when settings change
                for component in [base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox]:
                    component.change(
                        fn=update_folder_dropdown,
                        inputs=[base_path_input, comfy_ui_structure_checkbox, forge_structure_checkbox, lowercase_folders_checkbox],
                        outputs=[folder_dropdown, folder_info_display]
                    )

            with gr.Tab("Tutorials"):
                gr.Markdown(f"### 5 May 2025 Main How To Install & Use Tutorial : https://youtu.be/fTzlQ0tjxj0")   
                gr.Markdown(f"### 17 June 2025 WAN 2.1 FusionX is the New Best of Local Video Generation with Only 8 Steps + FLUX Upscaling Guide Tutorial : https://youtu.be/Xbn93GRQKsQ")    
                gr.Markdown(f"### 2 August 2025 Wan 2.2 & FLUX Krea Full Tutorial - Automated Install - Ready Perfect Presets - SwarmUI with ComfyUI Tutorial : https://youtu.be/8MvvuX4YPeo")         
    return app

# --- Main Execution ---

def get_available_drives():
    """Detect available drives on the system regardless of OS"""
    available_paths = []
    if platform.system() == "Windows":
        import string
        from ctypes import windll
        drives = []
        try:
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1: drives.append(f"{letter}:\\")
                bitmask >>= 1
            available_paths = drives
        except Exception as e:
            print(f"Warning: Could not get Windows drives via ctypes: {e}")
            available_paths = ["C:\\"] # Fallback
    elif platform.system() == "Darwin":
         available_paths = ["/", "/Volumes"]
    else: # Linux/Other
        available_paths = ["/", "/mnt", "/media", "/run/media"] 

    existing_paths = [p for p in available_paths if os.path.isdir(p)]
    try:
        home_dir = os.path.expanduser("~")
        if os.path.isdir(home_dir) and home_dir not in existing_paths:
            is_sub = False
            for p in existing_paths:
                try:
                    norm_p = os.path.normpath(p)
                    norm_home = os.path.normpath(home_dir)
                    if os.path.commonpath([norm_p, norm_home]) == norm_p:
                        is_sub = True
                        break
                except ValueError: pass 
                except Exception: pass 
            if not is_sub:
                existing_paths.append(home_dir)
    except Exception as e:
        print(f"Warning: Could not reliably determine home directory: {e}")
    try:
        cwd = os.getcwd()
        is_subpath = False
        for p in existing_paths:
            try:
                norm_p = os.path.normpath(p)
                norm_cwd = os.path.normpath(cwd)
                if os.path.commonpath([norm_p, norm_cwd]) == norm_p:
                     is_subpath = True
                     break
            except ValueError: pass 
            except Exception as e:
                 print(f"Warning: Error checking common path for {p} and {cwd}: {e}")
        if not is_subpath and os.path.isdir(cwd) and cwd not in existing_paths:
             existing_paths.append(cwd)
    except Exception as e:
        print(f"Warning: Could not reliably determine current working directory: {e}")
    print(f"Detected potential root paths: {existing_paths}")
    return existing_paths

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SwarmUI Model Downloader - Direct Download Version with Search and Bundles")
    parser.add_argument("--share", action="store_true", help="Enable Gradio sharing link")
    parser.add_argument("--model-path", type=str, default=None, help="Override default SwarmUI Models path")
    args = parser.parse_args()

    if args.model_path:
        current_base_path = os.path.abspath(args.model_path)
        print(f"Using base path from command line: {current_base_path}")
    else:
        current_base_path = os.path.abspath(DEFAULT_BASE_PATH) 
        saved_path, saved_comfy_ui_structure, saved_forge_structure, saved_lowercase_folders = load_last_settings()
        if saved_path:
            print(f"Using saved settings from previous session: Path='{current_base_path}', ComfyUI={saved_comfy_ui_structure}, Forge={saved_forge_structure}, Lowercase={saved_lowercase_folders}")
        else:
            print(f"Using default base path: {current_base_path}")

    # Ensure Base Dirs Exist Early (default ComfyUI mode to False for this initial call)
    # ensure_directories_exist(current_base_path, False) 

    worker_thread = threading.Thread(target=download_worker, daemon=True)
    worker_thread.start()

    gradio_app = create_ui(current_base_path)
    allowed_paths_list = get_available_drives()
    try:
        base_dir_norm = os.path.normpath(current_base_path)
        parent_dir_norm = os.path.normpath(os.path.dirname(base_dir_norm))
        def is_subpath_of_allowed(path_to_check, allowed_list):
            norm_check = os.path.normpath(path_to_check)
            for allowed in allowed_list:
                norm_allowed = os.path.normpath(allowed)
                try:
                    if os.path.commonpath([norm_allowed, norm_check]) == norm_allowed:
                        return True
                except ValueError: 
                    pass
                except Exception as e:
                    print(f"Warning: Error checking common path for {norm_allowed} and {norm_check}: {e}")
            return False
        if os.path.isdir(base_dir_norm) and not is_subpath_of_allowed(base_dir_norm, allowed_paths_list):
            allowed_paths_list.append(base_dir_norm)
        if os.path.isdir(parent_dir_norm) and parent_dir_norm != base_dir_norm and not is_subpath_of_allowed(parent_dir_norm, allowed_paths_list):
            allowed_paths_list.append(parent_dir_norm)
    except Exception as e:
        print(f"Warning: Error processing base/parent paths for Gradio allowed_paths: {e}")
        if os.path.isdir(current_base_path) and current_base_path not in allowed_paths_list:
             allowed_paths_list.append(current_base_path)
    print(f"Final allowed Gradio paths for launch: {allowed_paths_list}")

    try:
        # Gradio 6.0+: theme and CSS are now passed to launch() instead of Blocks()
        # Using Soft theme with custom CSS for Inter font (most readable)
        gradio_app.launch(
            inbrowser=True,
            share=args.share,
            allowed_paths=allowed_paths_list,
            theme=gr.themes.Soft(),
            css=CUSTOM_CSS
        )
    except KeyboardInterrupt:
        print("\nCtrl+C received. Shutting down...")
    except Exception as e:
         print(f"ERROR launching Gradio: {e}")
         print("Please ensure Gradio is installed correctly (`pip install gradio`) and that the specified port is available.")
    finally:
        stop_worker.set()
        print("Waiting for download worker to finish current task (up to 5s)...")
        worker_thread.join(timeout=5.0) 
        if worker_thread.is_alive():
            print("Worker thread did not finish cleanly after 5 seconds.")
        else:
            print("Download worker stopped.")
        if status_updates is not None:
             status_updates.put(None) 
             status_updates = None
    print("Gradio app closed.")