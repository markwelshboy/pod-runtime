"""
Folder Manager Module for SwarmUI Model Downloader
Handles dynamic folder selection and path resolution based on UI type and user preferences.
"""

import os
from typing import List, Dict, Tuple, Optional
from pathlib import Path


class FolderManager:
    """
    Manages folder structures and provides dynamic folder selection
    based on UI type (SwarmUI, ComfyUI, Forge) and user preferences.
    """
    
    def __init__(self, base_path: str, is_comfy_ui: bool = False, 
                 is_forge: bool = False, lowercase_folders: bool = False):
        """
        Initialize the folder manager.
        
        Args:
            base_path: Base download path (e.g., SwarmUI/Models)
            is_comfy_ui: Whether ComfyUI structure is enabled
            is_forge: Whether Forge structure is enabled
            lowercase_folders: Whether to use lowercase folder names
        """
        self.base_path = base_path
        self.is_comfy_ui = is_comfy_ui
        self.is_forge = is_forge
        self.lowercase_folders = lowercase_folders
        
        # Import the subdirectory definitions from the main app
        # We'll define them here to avoid circular imports
        self._init_folder_structures()
    
    def _init_folder_structures(self):
        """Initialize folder structure definitions."""
        
        # Base folder structure (SwarmUI default)
        self.base_subdirs = {
            "vae": "VAE",  # SwarmUI uses uppercase VAE folder
            "VAE": "VAE",  # Explicit uppercase mapping
            "diffusion_models": "diffusion_models", 
            "Stable-Diffusion": "Stable-Diffusion",
            "clip": "clip",  # SwarmUI uses clip folder for text encoders
            "text_encoders": "clip",  # Map text_encoders to clip folder for SwarmUI
            "clip_vision": "clip_vision",
            "yolov8": "yolov8",
            "style_models": "style_models",
            "Lora": "Lora",
            "upscale_models": "upscale_models",
            "LLM": "LLM",
            "Joy_caption": "Joy_caption",
            "controlnet": "controlnet",
            "embeddings": "Embeddings",
            "hypernetworks": "hypernetworks",
            "textual_inversion": "Embeddings",
        }
        
        # Additional folders for specific use cases
        self.additional_folders = {
            "checkpoints": "Stable-Diffusion",  # Alias for main models
            "models": "diffusion_models",       # Generic models folder
            "loras": "Lora",                   # Lowercase alias
            "vaes": "vae",                     # Plural alias
            "upscalers": "upscale_models",     # Alias
            "esrgan": "upscale_models",        # Specific upscaler type
            "controlnets": "controlnet",       # Plural alias
        }
    
    def get_current_subdirs(self) -> Dict[str, str]:
        """
        Get the current folder structure based on UI type settings.
        
        Returns:
            Dictionary mapping folder keys to actual folder paths
        """
        current_subdirs = self.base_subdirs.copy()
        current_subdirs.update(self.additional_folders)
        
        if self.is_comfy_ui:
            # ComfyUI specific modifications
            current_subdirs["Lora"] = "loras"
            current_subdirs["loras"] = "loras"
            current_subdirs["checkpoints"] = "checkpoints"
            current_subdirs["Stable-Diffusion"] = "checkpoints"
            current_subdirs["diffusion_models"] = "diffusion_models"  # ComfyUI has diffusion_models folder
            # ComfyUI uses text_encoders folder (also reads from clip for backward compatibility)
            current_subdirs["clip"] = "text_encoders"
            current_subdirs["text_encoders"] = "text_encoders"
            # ComfyUI uses lowercase vae folder
            current_subdirs["vae"] = "vae"
            current_subdirs["VAE"] = "vae"  # Map uppercase to lowercase for ComfyUI
            # ComfyUI uses lowercase embeddings
            current_subdirs["Embeddings"] = "embeddings"
            current_subdirs["embeddings"] = "embeddings"
            
        elif self.is_forge:
            # Forge WebUI specific modifications
            # Main checkpoint/diffusion models go to Stable-diffusion folder
            current_subdirs["Stable-diffusion"] = "Stable-diffusion"
            current_subdirs["Stable-Diffusion"] = "Stable-diffusion"
            current_subdirs["diffusion_models"] = "Stable-diffusion"
            current_subdirs["checkpoints"] = "Stable-diffusion"
            current_subdirs["models"] = "Stable-diffusion"
            
            # VAE models - Forge uses "VAE" folder
            current_subdirs["vae"] = "VAE"
            current_subdirs["VAE"] = "VAE"
            current_subdirs["vaes"] = "VAE"
            
            # LoRA models - Forge uses "Lora" folder
            current_subdirs["Lora"] = "Lora"
            current_subdirs["lora"] = "Lora"
            current_subdirs["loras"] = "Lora"
            
            # Text encoders - Forge uses text_encoder folder
            current_subdirs["clip"] = "text_encoder"
            current_subdirs["text_encoder"] = "text_encoder"
            current_subdirs["text_encoders"] = "text_encoder"  # Map SwarmUI text_encoders to Forge's text_encoder
            current_subdirs["clip_vision"] = "text_encoder"
            current_subdirs["t5"] = "text_encoder"
            current_subdirs["umt5"] = "text_encoder"
            
            # ControlNet models
            current_subdirs["controlnet"] = "ControlNet"
            current_subdirs["ControlNet"] = "ControlNet"
            current_subdirs["controlnets"] = "ControlNet"
            
            # ControlNet Preprocessor models
            current_subdirs["controlnetpreprocessor"] = "ControlNetPreprocessor"
            current_subdirs["ControlNetPreprocessor"] = "ControlNetPreprocessor"
            current_subdirs["preprocessor"] = "ControlNetPreprocessor"
            
            # ALL Upscaler models go to single ESRGAN folder
            current_subdirs["upscale_models"] = "ESRGAN"
            current_subdirs["ESRGAN"] = "ESRGAN"
            current_subdirs["RealESRGAN"] = "ESRGAN"
            current_subdirs["BSRGAN"] = "ESRGAN"
            current_subdirs["DAT"] = "ESRGAN"
            current_subdirs["SwinIR"] = "ESRGAN"
            current_subdirs["ScuNET"] = "ESRGAN"
            current_subdirs["upscalers"] = "ESRGAN"
            current_subdirs["esrgan"] = "ESRGAN"
            
            # Embeddings folder
            current_subdirs["embeddings"] = "embeddings"
            current_subdirs["embedding"] = "embeddings"
            current_subdirs["textual_inversion"] = "embeddings"
            current_subdirs["Embeddings"] = "embeddings"
            
            # Diffusers format models folder
            current_subdirs["diffusers"] = "diffusers"
            current_subdirs["diffusion"] = "diffusers"
            
            # Face restoration models
            current_subdirs["Codeformer"] = "Codeformer"
            current_subdirs["GFPGAN"] = "GFPGAN"
            
            # Interrogation/captioning models
            current_subdirs["BLIP"] = "BLIP"
            current_subdirs["deepbooru"] = "deepbooru"
            
            # Additional model types
            current_subdirs["hypernetworks"] = "hypernetworks"
            current_subdirs["LyCORIS"] = "LyCORIS"
        
        # Apply lowercase transformation if requested
        if self.lowercase_folders:
            current_subdirs = {k: v.lower() for k, v in current_subdirs.items()}
        
        return current_subdirs
    
    def get_available_folders(self) -> List[Tuple[str, str]]:
        """
        Get list of available folders for dropdown selection.
        
        Returns:
            List of tuples (display_name, folder_key) sorted alphabetically
        """
        subdirs = self.get_current_subdirs()
        
        # Create a mapping of unique folders with their display names
        folder_map = {}
        
        for key, folder_path in subdirs.items():
            # Create a display name
            if key == folder_path:
                display_name = key
            else:
                display_name = f"{key} → {folder_path}"
            
            # Use the folder path as the unique identifier
            if folder_path not in folder_map:
                folder_map[folder_path] = display_name
            else:
                # If we have multiple keys mapping to the same folder,
                # choose the most descriptive display name
                current_display = folder_map[folder_path]
                if len(display_name) > len(current_display):
                    folder_map[folder_path] = display_name
        
        # Convert to list of tuples and sort
        folder_list = [(display_name, folder_path) for folder_path, display_name in folder_map.items()]
        folder_list.sort(key=lambda x: x[0].lower())
        
        return folder_list
    
    def get_folder_suggestions_by_filename(self, filename: str) -> List[str]:
        """
        Suggest appropriate folders based on filename/extension.
        
        Args:
            filename: The filename to analyze
            
        Returns:
            List of suggested folder keys, ordered by relevance
        """
        if not filename:
            return ["diffusion_models"]  # Default fallback
        
        filename_lower = filename.lower()
        suggestions = []
        
        # Model file extensions and their typical folders
        if any(ext in filename_lower for ext in ['.safetensors', '.ckpt', '.pt', '.pth']):
            # Check for specific model types in filename
            if any(keyword in filename_lower for keyword in ['lora', 'lycoris']):
                suggestions.extend(["Lora", "loras"])
            elif any(keyword in filename_lower for keyword in ['vae', 'autoencoder']):
                suggestions.extend(["vae", "VAE"])
            elif any(keyword in filename_lower for keyword in ['controlnet', 'control_net']):
                suggestions.extend(["controlnet", "ControlNet"])
            elif any(keyword in filename_lower for keyword in ['upscale', 'esrgan', 'realesrgan', 'swinir']):
                suggestions.extend(["upscale_models", "ESRGAN"])
            elif any(keyword in filename_lower for keyword in ['embed', 'textual_inversion', 'ti']):
                suggestions.extend(["embeddings", "Embeddings"])
            elif any(keyword in filename_lower for keyword in ['xl', 'sdxl', 'sd_xl']):
                suggestions.extend(["Stable-Diffusion", "checkpoints", "diffusion_models"])
            else:
                # Default to main model folders
                suggestions.extend(["Stable-Diffusion", "diffusion_models", "checkpoints"])
        
        # GGUF files (typically LLM models)
        elif '.gguf' in filename_lower:
            suggestions.extend(["LLM"])
        
        # Other specific file types
        elif any(ext in filename_lower for ext in ['.bin', '.json']):
            if 'clip' in filename_lower:
                suggestions.extend(["clip", "text_encoder"])
            elif any(keyword in filename_lower for keyword in ['llm', 'language', 'chat']):
                suggestions.extend(["LLM"])
            else:
                suggestions.extend(["diffusion_models"])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            if suggestion not in seen:
                seen.add(suggestion)
                unique_suggestions.append(suggestion)
        
        # Add default if no specific suggestions
        if not unique_suggestions:
            unique_suggestions = ["diffusion_models"]
        
        return unique_suggestions
    
    def resolve_folder_path(self, folder_key: str, custom_path: Optional[str] = None) -> str:
        """
        Resolve the full folder path for a given folder key or custom path.
        
        Args:
            folder_key: The folder key from available folders
            custom_path: Optional custom path (relative or absolute)
            
        Returns:
            Full resolved path
        """
        if custom_path:
            # Handle custom path (can be relative or absolute)
            custom_path = custom_path.strip()
            
            if os.path.isabs(custom_path):
                # Absolute path - use as is
                return custom_path
            else:
                # Relative path - resolve relative to base path
                return os.path.join(self.base_path, custom_path)
        
        # Use predefined folder structure
        subdirs = self.get_current_subdirs()
        
        # Find the folder path for the given key
        folder_path = None
        for key, path in subdirs.items():
            if key == folder_key or path == folder_key:
                folder_path = path
                break
        
        if not folder_path:
            # Fallback to the key itself if not found
            folder_path = folder_key
        
        # Apply lowercase if needed
        if self.lowercase_folders:
            folder_path = folder_path.lower()
        
        # Resolve relative to base path
        return self._resolve_target_directory(self.base_path, folder_path)
    
    def _resolve_target_directory(self, base_dir: str, relative_path: str) -> str:
        """
        Resolve target directory path with case-insensitive handling on non-Windows systems.
        This is adapted from the main app's resolve_target_directory function.
        """
        import platform
        
        # Normalize the relative path
        normalized_relative_path = os.path.normpath(relative_path)
        
        # Apply lowercase to path if requested
        if self.lowercase_folders:
            normalized_relative_path = normalized_relative_path.lower()
        
        if platform.system() == "Windows":
            return os.path.join(base_dir, normalized_relative_path)
        
        # Linux/Mac - handle case insensitivity
        current_path = base_dir
        components = []
        head, tail = os.path.split(normalized_relative_path)
        while tail:
            components.insert(0, tail)
            head, tail = os.path.split(head)
        if head:
            components.insert(0, head)
        
        # Filter out empty or "." components
        components = [comp for comp in components if comp and comp != '.']
        
        for component in components:
            actual_cased_comp = None
            if os.path.isdir(current_path):
                actual_cased_comp = self._find_actual_cased_directory_component(current_path, component)
            
            if actual_cased_comp:
                current_path = os.path.join(current_path, actual_cased_comp)
            else:
                current_path = os.path.join(current_path, component)
        
        return current_path
    
    def _find_actual_cased_directory_component(self, parent_dir: str, component_name: str) -> Optional[str]:
        """
        Find an existing directory component case-insensitively.
        """
        if not os.path.isdir(parent_dir):
            return None
        
        name_lower = component_name.lower()
        try:
            for item in os.listdir(parent_dir):
                if item.lower() == name_lower:
                    if os.path.isdir(os.path.join(parent_dir, item)):
                        return item
        except OSError:
            pass
        return None
    
    def ensure_folder_exists(self, folder_path: str) -> Tuple[bool, str]:
        """
        Ensure that a folder exists, creating it if necessary.
        
        Args:
            folder_path: Full path to the folder
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            os.makedirs(folder_path, exist_ok=True)
            return True, f"✓ Folder ready: {folder_path}"
        except PermissionError:
            return False, f"✗ Permission denied: {folder_path}"
        except OSError as e:
            return False, f"✗ Cannot create folder: {folder_path} ({e})"
        except Exception as e:
            return False, f"✗ Unexpected error: {folder_path} ({e})"
    
    def get_ui_type_display(self) -> str:
        """
        Get a display string for the current UI type configuration.
        
        Returns:
            String describing the current UI type
        """
        if self.is_comfy_ui:
            ui_type = "ComfyUI"
        elif self.is_forge:
            ui_type = "Forge WebUI"
        else:
            ui_type = "SwarmUI"
        
        lowercase_note = " (lowercase)" if self.lowercase_folders else ""
        return f"{ui_type}{lowercase_note}"


def create_folder_manager(base_path: str, is_comfy_ui: bool = False, 
                         is_forge: bool = False, lowercase_folders: bool = False) -> FolderManager:
    """
    Factory function to create a folder manager instance.
    
    Args:
        base_path: Base download path
        is_comfy_ui: Whether ComfyUI structure is enabled
        is_forge: Whether Forge structure is enabled
        lowercase_folders: Whether to use lowercase folder names
        
    Returns:
        FolderManager instance
    """
    return FolderManager(base_path, is_comfy_ui, is_forge, lowercase_folders)


# Example usage and testing
if __name__ == "__main__":
    # Test different configurations
    base_path = "/path/to/models"
    
    print("=== SwarmUI Configuration ===")
    manager_swarm = create_folder_manager(base_path)
    folders = manager_swarm.get_available_folders()
    for display_name, folder_key in folders[:5]:  # Show first 5
        print(f"{display_name} -> {manager_swarm.resolve_folder_path(folder_key)}")
    
    print("\n=== ComfyUI Configuration ===")
    manager_comfy = create_folder_manager(base_path, is_comfy_ui=True)
    folders = manager_comfy.get_available_folders()
    for display_name, folder_key in folders[:5]:  # Show first 5
        print(f"{display_name} -> {manager_comfy.resolve_folder_path(folder_key)}")
    
    print("\n=== Forge Configuration ===")
    manager_forge = create_folder_manager(base_path, is_forge=True)
    folders = manager_forge.get_available_folders()
    for display_name, folder_key in folders[:5]:  # Show first 5
        print(f"{display_name} -> {manager_forge.resolve_folder_path(folder_key)}")
    
    print("\n=== Filename Suggestions ===")
    test_filenames = [
        "model.safetensors",
        "lora_style.safetensors", 
        "vae_model.safetensors",
        "controlnet_canny.safetensors",
        "upscaler_4x.pth",
        "llama_model.gguf"
    ]
    
    for filename in test_filenames:
        suggestions = manager_swarm.get_folder_suggestions_by_filename(filename)
        print(f"{filename} -> {suggestions[:3]}")  # Show top 3 suggestions



