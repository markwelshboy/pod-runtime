# Constants used in model catalog
HIDREAM_INFO_LINK = "https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#hidream-i1"
GGUF_QUALITY_INFO = "GGUF Quality: Q8 > Q6 > Q5 (K_M > K_S > 1 > 0) > Q4 (K_M > K_S > 1 > 0) > Q3 (K_M > K_S) > Q2_K."
FLUX_AE_DEFAULT_NAME = "Flux AE (Saved as Flux/ae.safetensors - SwarmUI default)"

# Individual model entry definitions
ltx_vae_companion_entry = {
    "name": "LTX VAE (BF16) - Companion for LTX 13B Dev Models",
    "repo_id": "wsbagnsv1/ltxv-13b-0.9.7-dev-GGUF",
    "filename_in_repo": "ltxv-13b-0.9.7-vae-BF16.safetensors",
    "save_filename": "LTX_VAE_13B_Dev_BF16.safetensors",
    "target_dir_key": "vae",
}

wan_causvid_14b_lora_v2_entry = {
    "name": "Wan 2.1 CausVid T2V/I2V LoRA v2 14B (Rank 32) - Companion",
    "repo_id": "Kijai/WanVideo_comfy",
    "filename_in_repo": "Wan21_CausVid_14B_T2V_lora_rank32_v2.safetensors",
    "save_filename": "Wan21_CausVid_14B_T2V_lora_rank32_v2.safetensors",
    "target_dir_key": "Lora",
    "info": "High-speed LoRA v2 for Wan 2.1 14B T2V/I2V. Saves to Lora folder. Also listed under 'Wan 2.1 Models' and 'LoRA Models'. See SwarmUI Video Docs for usage details on CFG, Steps, FPS, and Trim Video Start Frames.",
}

wan_causvid_14b_lora_entry = {
    "name": "Wan 2.1 CausVid T2V/I2V LoRA 14B (Rank 32) - Companion",
    "repo_id": "Kijai/WanVideo_comfy",
    "filename_in_repo": "Wan21_CausVid_14B_T2V_lora_rank32.safetensors",
    "save_filename": "Wan21_CausVid_14B_T2V_lora_rank32.safetensors",
    "target_dir_key": "Lora",
    "info": "High-speed LoRA for Wan 2.1 14B T2V/I2V. Saves to Lora folder. Also listed under 'Wan 2.1 Models' and 'LoRA Models'. See SwarmUI Video Docs for usage details on CFG, Steps, FPS, and Trim Video Start Frames.",
}

wan_causvid_1_3b_lora_entry = {
    "name": "Wan 2.1 CausVid T2V LoRA 1.3B (Rank 32) - Companion",
    "repo_id": "Kijai/WanVideo_comfy",
    "filename_in_repo": "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors",
    "save_filename": "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors",
    "target_dir_key": "Lora",
    "info": "High-speed LoRA for Wan 2.1 1.3B T2V. Saves to Lora folder. Also listed under 'Wan 2.1 Models' and 'LoRA Models'. See SwarmUI Video Docs for usage details.",
}

wan_self_forcing_lora_entry = {
    "name": "Wan 2.1 14B Self Forcing LoRA T2V/I2V",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan21_14B_Self_Forcing_LoRA_T2V_I2V.safetensors",
    "save_filename": "Wan21_14B_Self_Forcing_LoRA_T2V_I2V.safetensors",
    "target_dir_key": "Lora",
    "info": "Self Forcing LoRA for Wan 2.1 14B T2V/I2V models. Saves to Lora folder. See SwarmUI Video Docs for usage details.",
}

wan_lightx2v_lora_entry = {
    "name": "Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64_fixed.safetensors",
    "save_filename": "Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64_fixed.safetensors",
    "target_dir_key": "Lora",
    "info": "LightX2V CFG Step Distill LoRA V2 for Wan 2.1 14B T2V and I2V models. Saves to Lora folder. See SwarmUI Video Docs for usage details.",
}

wan_uni3c_controlnet_lora_entry = {
    "name": "Wan 2.1 Uni3C ControlNet",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan21_Uni3C_controlnet_fp16.safetensors",
    "save_filename": "Wan21_Uni3C_controlnet_fp16.safetensors",
    "target_dir_key": "controlnet",
    "info": "Uni3C ControlNet for Wan 2.1 models. Saves to ControlNet folder.",
}

wan_vae_entry = {
    "name": "Wan 2.1 VAE BF16",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2_1_VAE_bf16.safetensors",
    "save_filename": "Wan/wan_2.1_vae.safetensors",
    "target_dir_key": "vae",
}

wan_fusionx_i2v_gguf_q4_entry = {
    "name": "Wan 2.1 FusionX I2V 14B GGUF Q4_K_M",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q4_K_M.gguf",
    "save_filename": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q4_K_M.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_i2v_gguf_q5_entry = {
    "name": "Wan 2.1 FusionX I2V 14B GGUF Q5_K_M",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q5_K_M.gguf",
    "save_filename": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q5_K_M.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_i2v_gguf_q6_entry = {
    "name": "Wan 2.1 FusionX I2V 14B GGUF Q6_K",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q6_K.gguf",
    "save_filename": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q6_K.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_i2v_gguf_q8_entry = {
    "name": "Wan 2.1 FusionX I2V 14B GGUF Q8",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q8.gguf",
    "save_filename": "Wan2.1_14b_FusionX_Image_to_Video_GGUF_Q8.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_t2v_gguf_q4_entry = {
    "name": "Wan 2.1 FusionX T2V 14B GGUF Q4_K_M",
    "repo_id": "QuantStack/Wan2.1_T2V_14B_FusionX-GGUF",
    "filename_in_repo": "Wan2.1_T2V_14B_FusionX-Q4_K_M.gguf",
    "save_filename": "Wan2.1_T2V_14B_FusionX_GGUF_Q4_K_M.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_t2v_gguf_q5_entry = {
    "name": "Wan 2.1 FusionX T2V 14B GGUF Q5_K_M",
    "repo_id": "QuantStack/Wan2.1_T2V_14B_FusionX-GGUF",
    "filename_in_repo": "Wan2.1_T2V_14B_FusionX-Q5_K_M.gguf",
    "save_filename": "Wan2.1_T2V_14B_FusionX_GGUF_Q5_K_M.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_t2v_gguf_q6_entry = {
    "name": "Wan 2.1 FusionX T2V 14B GGUF Q6_K",
    "repo_id": "QuantStack/Wan2.1_T2V_14B_FusionX-GGUF",
    "filename_in_repo": "Wan2.1_T2V_14B_FusionX-Q6_K.gguf",
    "save_filename": "Wan2.1_T2V_14B_FusionX_GGUF_Q6_K.gguf",
    "target_dir_key": "diffusion_models",
}

wan_fusionx_t2v_gguf_q8_entry = {
    "name": "Wan 2.1 FusionX T2V 14B GGUF Q8_0",
    "repo_id": "QuantStack/Wan2.1_T2V_14B_FusionX-GGUF",
    "filename_in_repo": "Wan2.1_T2V_14B_FusionX-Q8_0.gguf",
    "save_filename": "Wan2.1_T2V_14B_FusionX_GGUF_Q8_0.gguf",
    "target_dir_key": "diffusion_models",
}

# New Wan 2.2 Fast Model entries
wan_2_2_i2v_fast_low_entry = {
    "name": "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-Low_fp8_scaled.safetensors",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-Low_fp8_scaled.safetensors",
    "save_filename": "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-Low_fp8_scaled.safetensors",
    "target_dir_key": "diffusion_models",
}

wan_2_2_i2v_fast_high_entry = {
    "name": "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-High_fp8_scaled.safetensors",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-High_fp8_scaled.safetensors",
    "save_filename": "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-High_fp8_scaled.safetensors",
    "target_dir_key": "diffusion_models",
}

# New Z Image Turbo model entries
z_image_turbo_bf16_entry = {
    "name": "Z Image Turbo BF16",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Z-Image-Turbo-Models/Z_Image_Turbo_BF16.safetensors",
    "save_filename": "Z_Image_Turbo_BF16.safetensors",
    "target_dir_key": "diffusion_models",
    "info": "Z Image Turbo diffusion model in BF16 format. Requires qwen_3_4b text encoder and FLUX ae.safetensors VAE.",
}

z_image_turbo_fp8_scaled_entry = {
    "name": "Z Image Turbo FP8 Scaled",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Z-Image-Turbo-Models/Z_Image_Turbo_FP8_scaled.safetensors",
    "save_filename": "Z_Image_Turbo_FP8_scaled.safetensors",
    "target_dir_key": "diffusion_models",
    "info": "Z Image Turbo diffusion model in FP8 Scaled format. **FP8 Scaled is better than GGUF models for quality.** Requires qwen_3_4b text encoder and FLUX ae.safetensors VAE.",
}

qwen_3_4b_text_encoder_entry = {
    "name": "Qwen 3 4B Text Encoder (For Z Image Turbo)",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Z-Image-Turbo-Models/qwen_3_4b.safetensors",
    "save_filename": "qwen_3_4b.safetensors",
    "target_dir_key": "clip",
    "info": "Qwen 3 4B text encoder required for Z Image Turbo models. Saves to clip folder (SwarmUI), text_encoders (ComfyUI), or text_encoder (Forge).",
}

z_image_turbo_controlnet_union_entry = {
    "name": "Z-Image-Turbo-Fun-Controlnet-Union",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors",
    "save_filename": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors",
    "target_dir_key": "model_patches",
    "info": "ControlNet Union model for Z Image Turbo. Saves to model_patches folder (ComfyUI) or controlnet folder (SwarmUI/Forge/others).",
}

# New Qwen Image FP8 model entry
qwen_image_fp8_scaled_entry = {
    "name": "Qwen_Image_FP8_Scaled",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Qwen_Image_FP8_Scaled.safetensors",
    "save_filename": "Qwen_Image_FP8_Scaled.safetensors",
    "target_dir_key": "diffusion_models",
}

# New Qwen Image FP8 Lightning 4steps model entry
qwen_image_fp8_lightning_4steps_entry = {
    "name": "Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors",
    "save_filename": "Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors",
    "target_dir_key": "Lora",
    "info": "Qwen Image Lightning LoRA for fast 4-step image generation. Saves to Lora folder. Use with Qwen Image models for optimized inference.",
}

# New Qwen Image Edit 2509 Lightning 4steps model entry
qwen_image_edit_2509_lightning_4steps_entry = {
    "name": "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors",
    "save_filename": "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors",
    "target_dir_key": "Lora",
    "info": "Qwen Image Edit Lightning LoRA for fast 4-step image editing. Saves to Lora folder. Use with Qwen Image models for optimized inference.",
}

# New Qwen LoRA model entries
qwen_lora_amateur_photo_v1_entry = {
    "name": "Qwen_LoRA_Amateur_Photo_v1.safetensors",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Qwen_LoRA_Amateur_Photo_v1.safetensors",
    "save_filename": "Qwen_LoRA_Amateur_Photo_v1.safetensors",
    "target_dir_key": "Lora",
    "info": "Qwen Amateur Photo LoRA v1 for enhanced photo-realistic image generation. Saves to Lora folder. Use with Qwen Image models.",
}

qwen_lora_skin_fix_v2_entry = {
    "name": "Qwen_LoRA_Skin_Fix_v2.safetensors",
    "repo_id": "MonsterMMORPG/Wan_GGUF",
    "filename_in_repo": "Qwen_LoRA_Skin_Fix_v2.safetensors",
    "save_filename": "Qwen_LoRA_Skin_Fix_v2.safetensors",
    "target_dir_key": "Lora",
    "info": "Qwen Skin Fix LoRA v2 for improved skin texture and quality in generated images. Saves to Lora folder. Use with Qwen Image models.",
}

models_structure = {
    "SwarmUI Bundles": {
        "info": "Download pre-defined bundles of commonly used models for SwarmUI with a single click.",
        "bundles": [
            {
                "name": "Complete Image Generation and Editing Bundle",
                "info": (
                    "Downloads core models for image generation and editing in SwarmUI, including Z Image Turbo, Qwen, Wan, FLUX, FLUX 2, and utility models.\n\n"
                    "**Includes:**\n"
                    "- Z Image Turbo BF16 (Fast image generation)\n"
                    "- Qwen 3 4B Text Encoder (For Z Image Turbo)\n"
                    "- Z-Image-Turbo-Fun-Controlnet-Union (ControlNet for Z Image Turbo)\n"
                    "- Qwen_Image_Edit_Plus_2509_FP8_Scaled\n"
                    "- Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors\n"
                    "- Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors\n"
                    "- Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors\n"
                    "- Qwen-Image-Edit-2509-Relight-LoRA.safetensors\n"
                    "- Qwen-Image-Edit-2509-Fusion-LoRA.safetensors\n"
                    "- Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors\n"
                    "- Qwen_Image_FP8_Scaled\n"
                    "- qwen_2.5_vl_7b_fp8_scaled.safetensors\n"
                    "- qwen_image_vae.safetensors\n"
                    "- Qwen Image Lightning 8steps-V2 LoRA\n"
                    "- Qwen_LoRA_Amateur_Photo_v1.safetensors\n"
                    "- Qwen_LoRA_Skin_Fix_v2.safetensors\n"
                    "- Face Segment/Masking Models (4 individual models: YOLOv9c, YOLOv12L, Male & Female)\n"
                    "- Best Upscaler Models (Full Set Snapshot)\n"
                    "- Wan 2.2 T2V Low Noise 14B FP8 Scaled (13.31 GB)\n"
                    "- Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors\n"
                    "- Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors\n"
                    "- Wan 2.2 VAE (1.31 GB)\n"
                    "- Wan 2.1 VAE BF16 (0.24 GB)\n"
                    "- UMT5 XXL FP16 (Default for SwarmUI) (10.59 GB)\n"
                    "- FLUX SRPO (Saved as FLUX-SRPO-bf16.safetensors) (22.17 GB)\n"
                    "- FLUX DEV Fill (In/Out-Painting) (Saved as FLUX_DEV_Fill.safetensors)\n"
                    "- T5 XXL FP16 (Saved as t5xxl_enconly.safetensors) (9.12 GB)\n"
                    f"- {FLUX_AE_DEFAULT_NAME} (0.31 GB)\n"
                    "- CLIP-SAE-ViT-L-14 (Saved as clip_l.safetensors - SwarmUI Default) (9.12 GB)\n"
                    "- FLUX 2 Dev FP8 Mixed Scaled High Quality (35.5 GB)\n"
                    "- FLUX 2 VAE (0.31 GB)\n"
                    "- Mistral 3 Small FLUX 2 Text Encoder FP8 (16.80 GB)\n"
                ),
                "models_to_download": [
                    ("Image Generation Models", "Z Image Turbo Models", "Z Image Turbo BF16"),
                    ("Text Encoder Models", "Clip Models", "Qwen 3 4B Text Encoder (For Z Image Turbo)"),
                    ("Image Generation Models", "Z Image Turbo Models", "Z-Image-Turbo-Fun-Controlnet-Union"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen_Image_Edit_Plus_2509_FP8_Scaled"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Relight-LoRA.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Fusion-LoRA.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen_Image_FP8_Scaled"),
                    ("Text Encoder Models", "Clip Models", "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "qwen_image_vae.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen Image Lightning 8steps-V2 LoRA"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen_LoRA_Amateur_Photo_v1.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen_LoRA_Skin_Fix_v2.safetensors"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Face YOLOv9c Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "YOLOv12L Face Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Male Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Female Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Image Upscaling Models", "Best Upscaler Models (Full Set Snapshot)"),
                    ("Video Generation Models", "Wan 2.2 Official Models", "Wan 2.2 T2V Low Noise 14B FP8 Scaled"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.2 VAE"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.1 VAE BF16"),
                    ("Text Encoder Models", "UMT5 XXL Models", "UMT5 XXL FP16 (Save As default for SwarmUI)"),
                    ("Image Generation Models", "FLUX Models", "FLUX SRPO"),
                    ("Image Generation Models", "FLUX Models", "FLUX DEV Fill (In/Out-Painting)"),
                    ("Text Encoder Models", "T5 XXL Models", "T5 XXL FP16 (Save As t5xxl_enconly for SwarmUI default name)"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", FLUX_AE_DEFAULT_NAME),
                    ("Text Encoder Models", "Clip Models", "CLIP-SAE-ViT-L-14 (Save As clip_l.safetensors - SwarmUI default name)"),
                    ("Image Generation Models", "FLUX 2 Models", "FLUX 2 Dev FP8 Mixed Scaled High Quality"),
                    ("Image Generation Models", "FLUX 2 Models", "FLUX 2 VAE"),
                    ("Image Generation Models", "FLUX 2 Models", "Mistral 3 Small FLUX 2 Text Encoder FP8"),
                ]
            },
            {
                "name": "Z Image Turbo Core Bundle",
                "info": (
                    "Downloads the core Z Image Turbo models for fast image generation with all necessary components.\n\n"
                    "**Includes:**\n"
                    "- Z Image Turbo BF16 (Diffusion Model)\n"
                    "- Qwen 3 4B Text Encoder (Required for Z Image Turbo)\n"
                    "- Z-Image-Turbo-Fun-Controlnet-Union (ControlNet)\n"
                    f"- {FLUX_AE_DEFAULT_NAME} (VAE - saved to VAE/Flux/ folder)\n"
                    "\n"
                    "**Note:** FP8 Scaled version is also available and offers better quality than GGUF models.\n"
                    "**Repo:** [MonsterMMORPG/Wan_GGUF](https://huggingface.co/MonsterMMORPG/Wan_GGUF)"
                ),
                "models_to_download": [
                    ("Image Generation Models", "Z Image Turbo Models", "Z Image Turbo BF16"),
                    ("Text Encoder Models", "Clip Models", "Qwen 3 4B Text Encoder (For Z Image Turbo)"),
                    ("Image Generation Models", "Z Image Turbo Models", "Z-Image-Turbo-Fun-Controlnet-Union"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", FLUX_AE_DEFAULT_NAME),
                ]
            },
            {
                "name": "FLUX 2 Core Bundle",
                "info": (
                    "Downloads the core FLUX 2 models for image generation with all necessary components.\n\n"
                    "**Includes:**\n"
                    "- FLUX 2 Dev FP8 Mixed Scaled High Quality (35.5 GB)\n"
                    "- FLUX 2 VAE (0.31 GB)\n"
                    "- Mistral 3 Small FLUX 2 Text Encoder FP8 (16.80 GB)\n"
                ),
                "models_to_download": [
                    ("Image Generation Models", "FLUX 2 Models", "FLUX 2 Dev FP8 Mixed Scaled High Quality"),
                    ("Image Generation Models", "FLUX 2 Models", "FLUX 2 VAE"),
                    ("Image Generation Models", "FLUX 2 Models", "Mistral 3 Small FLUX 2 Text Encoder FP8"),
                ]
            },
            {
                "name": "Qwen Image Core Bundle",
                "info": (
                    "Downloads the core Qwen Image models for image generation with necessary components and face segmentation models.\n\n"
                    "**Includes:**\n"
                    "- Qwen_Image_FP8_Scaled\n"
                    "- Qwen_Image_Edit_Plus_2509_FP8_Scaled\n"
                    "- Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors\n"
                    "- Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors\n"
                    "- Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors\n"
                    "- Qwen-Image-Edit-2509-Relight-LoRA.safetensors\n"
                    "- Qwen-Image-Edit-2509-Fusion-LoRA.safetensors\n"
                    "- Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors\n"
                    "- qwen_2.5_vl_7b_fp8_scaled.safetensors (Text encoder)\n"
                    "- qwen_image_vae.safetensors (VAE model)\n"
                    "- Qwen Image Lightning 8steps-V2 LoRA (Fast inference LoRA)\n"
                    "- Qwen_LoRA_Amateur_Photo_v1.safetensors\n"
                    "- Qwen_LoRA_Skin_Fix_v2.safetensors\n"
                    "- Face Segment/Masking Models (4 individual models: YOLOv9c, YOLOv12L, Male & Female)\n"
                    "- Best Upscaler Models (Full Set Snapshot)\n"
                ),
                "models_to_download": [
                    ("Image Generation Models", "Qwen Image Models", "Qwen_Image_FP8_Scaled"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen_Image_Edit_Plus_2509_FP8_Scaled"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Relight-LoRA.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Fusion-LoRA.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen-Image-FP8-Lightning-4steps-V1.0-fp32.safetensors"),
                    ("Text Encoder Models", "Clip Models", "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "qwen_image_vae.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen Image Lightning 8steps-V2 LoRA"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen_LoRA_Amateur_Photo_v1.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen_LoRA_Skin_Fix_v2.safetensors"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Face YOLOv9c Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "YOLOv12L Face Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Male Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Female Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Image Upscaling Models", "Best Upscaler Models (Full Set Snapshot)"),
                ]
            },
            {
                "name": "Wan 2.2 Core 4 Steps Bundle",
                "info": (
                    "Downloads the new Wan 2.2 models in FP8 precision for efficient 4-step video generation, with all necessary supporting files.\n\n"
                    "**Includes:**\n"
                    "- Wan 2.2 I2V High Noise 14B FP8 Scaled\n"
                    "- Wan 2.2 I2V Low Noise 14B FP8 Scaled\n"
                    "- Wan 2.2 T2V High Noise 14B FP8 Scaled\n"
                    "- Wan 2.2 T2V Low Noise 14B FP8 Scaled\n"
                    "- Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-Low_fp8_scaled.safetensors (13.31 GB)\n"
                    "- Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-High_fp8_scaled.safetensors (13.31 GB)\n"
                    "- Wan 2.2 VAE\n"
                    "- Wan 2.1 VAE BF16\n"
                    "- UMT5 XXL FP16 (Default for SwarmUI)\n"
                    "- Wan2.2-T2V-A14B-4steps-lora-250928-Low.safetensors\n"
                    "- Wan2.2-T2V-A14B-4steps-lora-250928-High.safetensors\n"
                    "- Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_Low\n"
                    "- Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_High\n"
                    "- Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-Low.safetensors\n"
                    "- Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-High.safetensors\n"
                    "- Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors\n"
                    "- Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors\n"
                    "- Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)\n"
                    "- Best Upscaler Models (Full Set Snapshot)\n"
                    "- Face Segment/Masking Models (4 individual models: YOLOv9c, YOLOv12L, Male & Female)\n"
                    "\n"
                    "**How to use Wan 2.2:** [Wan 2.2 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-22-parameters)"
                ),
                "models_to_download": [
                    ("Video Generation Models", "Wan 2.2 Official Models", "Wan 2.2 I2V High Noise 14B FP8 Scaled"),
                    ("Video Generation Models", "Wan 2.2 Official Models", "Wan 2.2 I2V Low Noise 14B FP8 Scaled"),
                    ("Video Generation Models", "Wan 2.2 Official Models", "Wan 2.2 T2V High Noise 14B FP8 Scaled"),
                    ("Video Generation Models", "Wan 2.2 Official Models", "Wan 2.2 T2V Low Noise 14B FP8 Scaled"),
                    ("Video Generation Models", "Wan 2.2 Fast Models", "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-Low_fp8_scaled.safetensors"),
                    ("Video Generation Models", "Wan 2.2 Fast Models", "Wan2.2-I2V-A14B-Moe-Distill-Lightx2v-High_fp8_scaled.safetensors"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.2 VAE"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.1 VAE BF16"),
                    ("Text Encoder Models", "UMT5 XXL Models", "UMT5 XXL FP16 (Save As default for SwarmUI)"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2-T2V-A14B-4steps-lora-250928-Low.safetensors"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2-T2V-A14B-4steps-lora-250928-High.safetensors"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_Low"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_High"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-Low.safetensors"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-High.safetensors"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors"),
                    ("Video Generation Models", "Wan 2.2 LoRAs", "Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors"),
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Image Upscaling Models", "Best Upscaler Models (Full Set Snapshot)"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Face YOLOv9c Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "YOLOv12L Face Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Male Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Female Face Segmentation Model"),
                ]
            },
            {
                "name": "Wan 2.1 Core Models Bundle (GGUF Q6_K + Best LoRAs)",
                "info": (
                    "Downloads a core set of Wan 2.1 models for video generation, including T2V, I2V, and companion LoRAs, plus the recommended UMT5 text encoder and CLIP Vision H.\n\n"
                    "**Includes:**\n"
                    "- Wan 2.1 T2V 1.3B FP16\n"
                    "- Wan 2.1 T2V 14B FusionX LoRA\n"
                    "- Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)\n"
                    "- Phantom Wan 14B FusionX LoRA\n"
                    "- Wan 2.1 I2V 14B FusionX LoRA\n"
                    "- Wan 2.1 14B Self Forcing LoRA T2V/I2V\n"
                    "- Wan 2.1 T2V 14B 720p GGUF Q6_K\n"
                    "- Wan 2.1 I2V 14B 720p GGUF Q6_K\n"
                    "- Wan 2.1 VAE BF16\n"
                    "- UMT5 XXL FP8 Scaled (Default for SwarmUI)\n"
                    "- CLIP Vision H (Used by Wan 2.1)\n"
                    "- Best Upscaler Models (Full Set Snapshot)\n"
                    "- Face Segment/Masking Models (4 individual models: YOLOv9c, YOLOv12L, Male & Female)\n"
                    "\n"
                    "**How to use Wan 2.1:** [Wan 2.1 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-21-parameters)"
                ),
                "models_to_download": [
                    ("Video Generation Models", "Wan 2.1 Official Models", "Wan 2.1 T2V 1.3B FP16"),
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Wan 2.1 T2V 14B FusionX LoRA"),
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)"),
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Phantom Wan 14B FusionX LoRA"),
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Wan 2.1 I2V 14B FusionX LoRA"),
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Wan 2.1 14B Self Forcing LoRA T2V/I2V"),
                    ("Video Generation Models", "Wan 2.1 Official Models", "Wan 2.1 T2V 14B 720p GGUF Q6_K"),
                    ("Video Generation Models", "Wan 2.1 Official Models", "Wan 2.1 I2V 14B 720p GGUF Q6_K"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.1 VAE BF16"),
                    ("Text Encoder Models", "UMT5 XXL Models", "UMT5 XXL FP8 Scaled (Default for SwarmUI)"),
                    ("Clip Vision Models", "Standard Clip Vision Models", "CLIP Vision H (Used by Wan 2.1)"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Image Upscaling Models", "Best Upscaler Models (Full Set Snapshot)"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Face YOLOv9c Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "YOLOv12L Face Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Male Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Female Face Segmentation Model"),
                ]
            },
            {
                "name": "FLUX Models Bundle",
                "info": (
                    "Downloads a core set of models for using FLUX models in SwarmUI, plus common utility models.\n\n"
                    "**Includes:**\n"
                    "- FLUX SRPO (Saved as FLUX-SRPO-bf16.safetensors)\n"
                    "- FLUX Kontext DEV BF16 (Saved as FLUX_Kontext_Dev.safetensors)\n"
                    "- FLUX DEV 1.0 FP16 (Saved as FLUX_Dev.safetensors)\n"
                    "- FLUX DEV Fill (In/Out-Painting) (Saved as FLUX_DEV_Fill.safetensors)\n"
                    "- FLUX DEV Redux (Style/Mix) (Saved as FLUX_DEV_Redux.safetensors)\n" 
                    "- FLUX Krea DEV (Saved as FLUX_Krea_Dev.safetensors)\n"
                    "- T5 XXL FP16 (Saved as t5xxl_enconly.safetensors)\n"
                    f"- {FLUX_AE_DEFAULT_NAME}\n"
                    "- CLIP-SAE-ViT-L-14 (Saved as clip_l.safetensors - SwarmUI Default)\n"
                    "- Best Image Upscaler Models (Full Set)\n"
                    "- Face Segment/Masking Models (4 individual models: YOLOv9c, YOLOv12L, Male & Female)\n"
                    "\n"
                    "**How to use FLUX:** [FLUX Model Support](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#black-forest-labs-flux1-models)\n"
                    "**Important Setup Guide:** [General FLUX Install/Usage](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#install)"
                ),
                "models_to_download": [
                    ("Image Generation Models", "FLUX Models", "FLUX SRPO"),
                    ("Image Generation Models", "FLUX Models", "FLUX Kontext DEV BF16"),
                    ("Image Generation Models", "FLUX Models", "FLUX DEV 1.0 FP16"),
                    ("Image Generation Models", "FLUX Models", "FLUX DEV Fill (In/Out-Painting)"),
                    ("Image Generation Models", "FLUX Models", "FLUX DEV Redux (Style/Mix)"),
                    ("Image Generation Models", "FLUX Models", "FLUX Krea DEV"),
                    ("Text Encoder Models", "T5 XXL Models", "T5 XXL FP16 (Save As t5xxl_enconly for SwarmUI default name)"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", FLUX_AE_DEFAULT_NAME),
                    ("Text Encoder Models", "Clip Models", "CLIP-SAE-ViT-L-14 (Save As clip_l.safetensors - SwarmUI default name)"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Image Upscaling Models", "Best Upscaler Models (Full Set Snapshot)"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Face YOLOv9c Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "YOLOv12L Face Detection Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Male Face Segmentation Model"),
                    ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Female Face Segmentation Model"),
                ]
            },
            {
                 "name": "HiDream-I1 Dev Bundle (Recommended)",
                 "info": (
                     "Downloads the recommended HiDream-I1 Dev model (Q8 GGUF), necessary supporting files, and common utility models.\n\n"
                     "**Includes:**\n"
                     "- HiDream-I1 Dev GGUF Q8_0 (Saved as HiDream_I1_Dev_GGUF_Q8_0.gguf)\n"
                     "- T5 XXL FP16 (Saved as t5xxl_enconly.safetensors)\n"
                     "- Long Clip L for HiDream-I1 (Saved as long_clip_l_hi_dream.safetensors)\n"
                     "- Long Clip G for HiDream-I1 (Saved as long_clip_g_hi_dream.safetensors)\n"
                     "- LLAMA 3.1 8b Instruct FP8 Scaled for HiDream-I1 (Saved as llama_3.1_8b_instruct_fp8_scaled.safetensors)\n"
                     f"- {FLUX_AE_DEFAULT_NAME}\n"
                     "- Best Image Upscaler Models (Full Set)\n"
                     "- Face Segment/Masking Models (4 individual models: YOLOv9c, YOLOv12L, Male & Female)\n"
                     "\n"
                     "**How to use HiDream:** [HiDream Model Support](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#hidream-i1)"
                 ),
                 "models_to_download": [
                     ("Image Generation Models", "HiDream-I1 Dev Models (Recommended)", "HiDream-I1 Dev GGUF Q8_0"),
                     ("Text Encoder Models", "T5 XXL Models", "T5 XXL FP16 (Save As t5xxl_enconly for SwarmUI default name)"),
                     ("Text Encoder Models", "Clip Models", "Long Clip L for HiDream-I1"),
                     ("Text Encoder Models", "Clip Models", "Long Clip G for HiDream-I1"),
                     ("Text Encoder Models", "LLM Text Encoders", "LLAMA 3.1 8b Instruct FP8 Scaled for HiDream-I1"),
                     ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", FLUX_AE_DEFAULT_NAME),
                     ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Image Upscaling Models", "Best Upscaler Models (Full Set Snapshot)"),
                     ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Face YOLOv9c Detection Model"),
                     ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "YOLOv12L Face Detection Model"),
                     ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Male Face Segmentation Model"),
                     ("Other Models (e.g. Yolo Face Segment, Image Upscaling)", "Auto Yolo Masking/Segment Models", "Female Face Segmentation Model"),
                 ]
             },
             {
                "name": "Trained Models Min Requirements",
                "info": (
                    "Downloads the minimum required VAE, CLIP, and text encoder models for Wan, FLUX, and Qwen models. Uses SwarmUI default names to avoid duplicate downloads.\n\n"
                    "**Includes:**\n"
                    f"- {FLUX_AE_DEFAULT_NAME} - Used by FLUX, HiDream, etc.\n"
                    "- Qwen Image VAE (Saved as QwenImage/qwen_image_vae.safetensors)\n"
                    "- Wan 2.2 VAE (Saved as Wan/wan2.2_vae.safetensors)\n"
                    "- Wan 2.1 VAE BF16 (Saved as Wan/wan_2.1_vae.safetensors)\n"
                    "- T5 XXL FP16 (Saved as t5xxl_enconly.safetensors - SwarmUI default)\n"
                    "- UMT5 XXL FP8 Scaled (Saved as umt5_xxl_fp8_e4m3fn_scaled.safetensors - SwarmUI default for Wan)\n"
                    "- CLIP-SAE-ViT-L-14 (Saved as clip_l.safetensors - SwarmUI default)\n"
                    "- CLIP Vision H (Saved as clip_vision_h.safetensors - Required for Wan 2.1 I2V)\n"
                    "- Qwen 2.5 VL 7B FP8 Scaled (Saved as qwen_2.5_vl_7b_fp8_scaled.safetensors)\n"
                    "- Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors (Lightning LoRA)\n"
                    "- Qwen_LoRA_Skin_Fix_v2.safetensors (Skin Fix LoRA)\n"
                    "\n"
                    "**Note:** These models use SwarmUI's expected file names, so they won't be downloaded again if you already have them."
                ),
                "models_to_download": [
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", FLUX_AE_DEFAULT_NAME),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "qwen_image_vae.safetensors"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.2 VAE"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.1 VAE BF16"),
                    ("Text Encoder Models", "T5 XXL Models", "T5 XXL FP16 (Save As t5xxl_enconly for SwarmUI default name)"),
                    ("Text Encoder Models", "UMT5 XXL Models", "UMT5 XXL FP8 Scaled (Default for SwarmUI)"),
                    ("Text Encoder Models", "Clip Models", "CLIP-SAE-ViT-L-14 (Save As clip_l.safetensors - SwarmUI default name)"),
                    ("Clip Vision Models", "Standard Clip Vision Models", "CLIP Vision H (Used by Wan 2.1)"),
                    ("Text Encoder Models", "Clip Models", "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
                    ("Image Generation Models", "Qwen Image Editing Models", "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors"),
                    ("Image Generation Models", "Qwen Image Models", "Qwen_LoRA_Skin_Fix_v2.safetensors"),
                ]
             },
        ]
    },
    "ComfyUI Bundles": {
        "info": "Download pre-defined bundles for specific ComfyUI workflows, including models and related assets.",
        "bundles": [
            {
                "name": "Clothing Migration Workflow Bundle",
                "info": (
                    "Downloads all necessary models and assets for the Clothing Migration workflow in ComfyUI (SwarmUI backend).\n\n"
                    "**Includes:**\n"
                    "- Joy Caption Alpha Two (Captioning Assets)\n"
                    "- Migration LoRA Cloth (TTPlanet)\n"
                    "- Figures TTP Migration LoRA (TTPlanet)\n"
                    "- SigLIP SO400M Patch14 384px (Full Repo)\n"
                    "- Meta-Llama-3.1-8B-Instruct (Full Repo)\n"
                    f"- {FLUX_AE_DEFAULT_NAME}\n"
                    "- FLUX DEV ControlNet Inpainting Beta (Alimama) (ControlNet for inpainting)\n"
                    "- T5 XXL FP16 (Text Encoder)\n"
                    "- CLIP-SAE-ViT-L-14 (CLIP L Text Encoder, saved as clip_l.safetensors)\n"
                    "\n"
                    "**Important:** Ensure your ComfyUI setup and the specific workflow are configured to use these models in their respective SwarmUI model paths. "
                    "This bundle downloads models to their default SwarmUI locations (e.g., Models/Lora, Models/LLM, Models/controlnet, etc.)."
                ),
                "models_to_download": [
                    ("ComfyUI Workflows", "Captioning Workflows", "Joy Caption Alpha Two (Full Repo)"),
                    ("LoRA Models", "Various LoRAs", "Migration LoRA Cloth (TTPlanet)"),
                    ("LoRA Models", "Various LoRAs", "Figures TTP Migration LoRA (TTPlanet)"),
                    ("Clip Vision Models", "SigLIP Vision Models", "SigLIP SO400M Patch14 384px (Full Repo)"),
                    ("LLM Models", "General LLMs", "Meta-Llama-3.1-8B-Instruct (Full Repo)"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", FLUX_AE_DEFAULT_NAME),
                    ("Image Generation Models", "FLUX Models", "FLUX DEV ControlNet Inpainting Beta (Alimama)"),
                    ("Text Encoder Models", "T5 XXL Models", "T5 XXL FP16"),
                    ("Text Encoder Models", "Clip Models", "CLIP-SAE-ViT-L-14 (Save As clip_l.safetensors - SwarmUI default name)"),
                ]
            },
            {
                "name": "ComfyUI MultiTalk Bundle",
                "info": (
                    "Downloads all necessary models for ComfyUI MultiTalk workflow, including the latest Wan 2.1 MultiTalk model and supporting components.\n\n"
                    "**Includes:**\n"
                    "- Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)\n"
                    "- Wan 2.1 Uni3C ControlNet\n"
                    "- WanVideo 2.1 MultiTalk 14B FP32\n"
                    "- Wan 2.1 I2V 14B 480p GGUF Q8\n"
                    "- Wan 2.1 I2V 14B 720p GGUF Q8\n"
                    "- Wan 2.1 FusionX I2V 14B GGUF Q8\n"
                    "- CLIP Vision H (Used by Wan 2.1)\n"
                    "- UMT5 XXL FP16 (Default for SwarmUI)\n"
                    "- Wan 2.1 VAE BF16\n"
                    "\n"
                    "**How to use Wan 2.1:** [Wan 2.1 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-21-parameters)"
                ),
                "models_to_download": [
                    ("Video Generation Models", "Wan 2.1 LoRAs", "Wan 2.1 14B LightX2V CFG Step Distill LoRA V2 (T2V + I2V) (Rank 64)"),
                    ("ControlNet Models", "Various ControlNets", "Wan 2.1 Uni3C ControlNet"),
                    ("Video Generation Models", "Wan 2.1 Official Models", "WanVideo 2.1 MultiTalk 14B FP32"),
                    ("Video Generation Models", "Wan 2.1 Official Models", "Wan 2.1 I2V 14B 480p GGUF Q8"),
                    ("Video Generation Models", "Wan 2.1 Official Models", "Wan 2.1 I2V 14B 720p GGUF Q8"),
                    ("Video Generation Models", "Wan 2.1 FusionX Models", "Wan 2.1 FusionX I2V 14B GGUF Q8"),
                    ("Clip Vision Models", "Standard Clip Vision Models", "CLIP Vision H (Used by Wan 2.1)"),
                    ("Text Encoder Models", "UMT5 XXL Models", "UMT5 XXL FP16 (Save As default for SwarmUI)"),
                    ("VAE Models", "Most Common VAEs (e.g. FLUX and HiDream-I1)", "Wan 2.1 VAE BF16"),
                ]
            },
        ]
    },
    "Image Generation Models": {
        "info": "Models for generating images from text or other inputs.",
        "sub_categories": {
            "Z Image Turbo Models": {
                "info": ("Z Image Turbo fast image generation models. **FP8 Scaled is recommended over GGUF models for better quality.**\n\n"
                         "**Requirements:** Z Image Turbo uses FLUX VAE (ae.safetensors) and Qwen 3 4B text encoder.\n"
                         "**Repo:** [MonsterMMORPG/Wan_GGUF](https://huggingface.co/MonsterMMORPG/Wan_GGUF)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    z_image_turbo_bf16_entry,
                    z_image_turbo_fp8_scaled_entry,
                    qwen_3_4b_text_encoder_entry,
                    z_image_turbo_controlnet_union_entry,
                    {"name": "FLUX VAE ae.safetensors (For Z Image Turbo)", "repo_id": "MonsterMMORPG/Kohya_Train", "filename_in_repo": "ae.safetensors", "save_filename": "Flux/ae.safetensors", "target_dir_key": "vae", "info": "FLUX VAE required for Z Image Turbo models. Same as standard FLUX ae.safetensors."},
                ]
            },
            "FLUX 2 Models": {
                "info": ("FLUX 2 image generation models including text encoders and VAE.\n\n"
                         "**FLUX 2 requires:** Mistral text encoder models (BF16 or FP8) and FLUX 2 VAE.\n"
                         "**How to use FLUX 2:** [FLUX Model Support](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#black-forest-labs-flux1-models)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    {
                        "name": "FLUX 2 Dev FP8 Mixed Scaled High Quality",
                        "repo_id": "MonsterMMORPG/Wan_GGUF",
                        "filename_in_repo": "FLUX_2_Models/FLUX_2_Dev_FP8_Mixed_Scaled.safetensors",
                        "save_filename": "FLUX_2_Dev_FP8_Mixed_Scaled.safetensors",
                        "info": "FLUX 2 Dev model in FP8 mixed precision format (35.5 GB). Main diffusion model for FLUX 2 image generation."
                    },
                    {
                        "name": "FLUX 2 Dev BF16",
                        "repo_id": "MonsterMMORPG/Wan_GGUF",
                        "filename_in_repo": "FLUX_2_Models/FLUX_2_Dev_BF16.safetensors",
                        "save_filename": "FLUX_2_Dev_BF16.safetensors",
                        "info": "FLUX 2 Dev model in BF16 format (64.4 GB). Full precision diffusion model for FLUX 2 image generation."
                    },
                    {
                        "name": "FLUX 2 VAE",
                        "repo_id": "MonsterMMORPG/Wan_GGUF",
                        "filename_in_repo": "FLUX_2_Models/flux2-vae.safetensors",
                        "save_filename": "Flux/flux2-vae.safetensors",
                        "target_dir_key": "vae",
                        "info": "FLUX 2 VAE model (336 MB). Saved to VAE/Flux/ subfolder for SwarmUI organization."
                    },
                    {
                        "name": "Mistral 3 Small FLUX 2 Text Encoder BF16",
                        "repo_id": "MonsterMMORPG/Wan_GGUF",
                        "filename_in_repo": "FLUX_2_Models/mistral_3_small_flux2_bf16.safetensors",
                        "save_filename": "mistral_3_small_flux2_bf16.safetensors",
                        "target_dir_key": "text_encoders",
                        "info": "Mistral 3 Small text encoder for FLUX 2 in BF16 format (35.6 GB). Higher quality but uses more VRAM."
                    },
                    {
                        "name": "Mistral 3 Small FLUX 2 Text Encoder FP8",
                        "repo_id": "MonsterMMORPG/Wan_GGUF",
                        "filename_in_repo": "FLUX_2_Models/mistral_3_small_flux2_fp8.safetensors",
                        "save_filename": "mistral_3_small_flux2_fp8.safetensors",
                        "target_dir_key": "text_encoders",
                        "info": "Mistral 3 Small text encoder for FLUX 2 in FP8 format (18 GB). Lower VRAM usage with minimal quality loss."
                    },
                    {
                        "name": "FLUX 2 Dev GGUF Q4_1",
                        "repo_id": "city96/FLUX.2-dev-gguf",
                        "filename_in_repo": "flux2-dev-Q4_1.gguf",
                        "save_filename": "flux2-dev-Q4_1.gguf",
                        "info": "FLUX 2 Dev model in GGUF Q4_1 quantization. Better quality with moderate size."
                    },
                    {
                        "name": "FLUX 2 Dev GGUF Q3_K_M",
                        "repo_id": "city96/FLUX.2-dev-gguf",
                        "filename_in_repo": "flux2-dev-Q3_K_M.gguf",
                        "save_filename": "flux2-dev-Q3_K_M.gguf",
                        "info": "FLUX 2 Dev model in GGUF Q3_K_M quantization. Good balance of size and quality."
                    },
                    {
                        "name": "FLUX 2 Dev GGUF Q2_K",
                        "repo_id": "city96/FLUX.2-dev-gguf",
                        "filename_in_repo": "flux2-dev-Q2_K.gguf",
                        "save_filename": "flux2-dev-Q2_K.gguf",
                        "info": "FLUX 2 Dev model in GGUF Q2_K quantization. Smallest size with reduced quality."
                    },
                ]
            },
            "Qwen Image Models": {
                "info": "Qwen Image generation models in various quantization formats (GGUF and safetensors).",
                "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "Qwen_Image_BF16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen_image_bf16.safetensors", "save_filename": "qwen_image_bf16.safetensors"},
                    qwen_image_fp8_scaled_entry,
                    {"name": "Qwen_Image_Q8_0", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen-image-Q8_0.gguf", "save_filename": "Qwen_Image_Q8_0.gguf"},
                    {"name": "Qwen_Image_Q6_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen-image-Q6_K.gguf", "save_filename": "Qwen_Image_Q6_K.gguf"},
                    {"name": "Qwen_Image_FP8_e4m3f", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen_image_fp8_e4m3fn.safetensors", "save_filename": "qwen_image_fp8_e4m3fn.safetensors"},
                    {"name": "Qwen_Image_Q5_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen-image-Q5_1.gguf", "save_filename": "Qwen_Image_Q5_1.gguf"},
                    {"name": "Qwen_Image_Q4_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen-image-Q4_1.gguf", "save_filename": "Qwen_Image_Q4_1.gguf"},
                    qwen_image_fp8_lightning_4steps_entry,
                    {"name": "Qwen Image Lightning 8steps-V2 LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Lightning-8steps-V2.0.safetensors", "save_filename": "Qwen-Image-Lightning-8steps-V2.0.safetensors", "target_dir_key": "Lora", "info": "Qwen Image Lightning V2.0 LoRA for fast 8-step image generation. Saves to Lora folder. Use with Qwen Image models for optimized inference."},
                    {"name": "Qwen Image Lightning 8steps V1.1 LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Lightning-8steps-V1.1.safetensors", "save_filename": "Qwen-Image-Lightning-8steps-V1.1.safetensors", "target_dir_key": "Lora", "info": "Qwen Image Lightning LoRA for fast 8-step image generation. Saves to Lora folder. Use with Qwen Image models for optimized inference."},
                    qwen_lora_amateur_photo_v1_entry,
                    qwen_lora_skin_fix_v2_entry,
                ]
            },
            "Qwen Image Editing Models": {
                "info": "Qwen Image editing models in various quantization formats (GGUF and safetensors) for image editing tasks.",
                "target_dir_key": "diffusion_models",
                "models": [
                    # New Qwen Image Edit Plus 2509 models (ordered as requested)
                    {"name": "Qwen_Image_Edit_Plus_2509_BF16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_Plus_2509_bf16.safetensors", "save_filename": "Qwen_Image_Edit_Plus_2509_bf16.safetensors"},
                    {"name": "Qwen_Image_Edit_Plus_2509_FP8_Scaled", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_Plus_2509_FP8_Scaled.safetensors", "save_filename": "Qwen_Image_Edit_Plus_2509_FP8_Scaled.safetensors"},
                    {"name": "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors", "save_filename": "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-fp32.safetensors", "target_dir_key": "Lora", "info": "Qwen Image Edit Lightning LoRA for fast 8-step image editing. Saves to Lora folder. Use with Qwen Image models for optimized inference."},
                    qwen_image_edit_2509_lightning_4steps_entry,
                    {"name": "Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors", "save_filename": "Qwen-Image-Edit-2509-Multiple-Angles-LoRA.safetensors", "target_dir_key": "Lora", "info": "Multi-angle Qwen Image Edit LoRA for improving consistency across diverse camera angles. Saves to Lora folder."},
                    {"name": "Qwen-Image-Edit-2509-Relight-LoRA.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-2509-Relight-LoRA.safetensors", "save_filename": "Qwen-Image-Edit-2509-Relight-LoRA.safetensors", "target_dir_key": "Lora", "info": "Relighting LoRA tuned for Qwen Image Edit 2509 to improve lighting adjustments and highlight control. Saves to Lora folder."},
                    {"name": "Qwen-Image-Edit-2509-Fusion-LoRA.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-2509-Fusion-LoRA.safetensors", "save_filename": "Qwen-Image-Edit-2509-Fusion-LoRA.safetensors", "target_dir_key": "Lora", "info": "Fusion LoRA blend for Qwen Image Edit 2509 to combine multiple stylistic enhancements in one pass. Saves to Lora folder."},
                    {"name": "Qwen_Image_Edit_Plus_2509_Q8_0", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-Plus-2509-Q8_0.gguf", "save_filename": "Qwen-Image-Edit-Plus-2509-Q8_0.gguf", "companion_json": "Qwen-Image-Edit-Plus-2509-Q8_0.swarm.json"},
                    {"name": "Qwen_Image_Edit_Plus_2509_Q6_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-Plus-2509-Q6_K.gguf", "save_filename": "Qwen-Image-Edit-Plus-2509-Q6_K.gguf"},
                    {"name": "Qwen_Image_Edit_Plus_2509_FP8_e4m3fn", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_Plus_2509_fp8_e4m3fn.safetensors", "save_filename": "Qwen_Image_Edit_Plus_2509_fp8_e4m3fn.safetensors"},
                    {"name": "Qwen_Image_Edit_Plus_2509_Q5_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-Plus-2509-Q5_1.gguf", "save_filename": "Qwen-Image-Edit-Plus-2509-Q5_1.gguf"},
                    {"name": "Qwen_Image_Edit_Plus_2509_Q4_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-Plus-2509-Q4_1.gguf", "save_filename": "Qwen-Image-Edit-Plus-2509-Q4_1.gguf"},
                    {"name": "Qwen_Image_Edit_Plus_2509_Q3_K_M", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen-Image-Edit-Plus-2509-Q3_K_M.gguf", "save_filename": "Qwen-Image-Edit-Plus-2509-Q3_K_M.gguf"},
                    # Existing Qwen Image Edit models
                    {"name": "Qwen_Image_Edit_BF16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_BF16.safetensors", "save_filename": "Qwen_Image_Edit_BF16.safetensors"},
                    {"name": "Qwen_Image_Edit_FP8_e4m3fn", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_FP8_e4m3fn.safetensors", "save_filename": "Qwen_Image_Edit_FP8_e4m3fn.safetensors"},
                    {"name": "Qwen_Image_Edit_GGUF_Q8_0", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_GGUF_Q8_0.gguf", "save_filename": "Qwen_Image_Edit_GGUF_Q8_0.gguf"},
                    {"name": "Qwen_Image_Edit_GGUF_Q6_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_GGUF_Q6_K.gguf", "save_filename": "Qwen_Image_Edit_GGUF_Q6_K.gguf"},
                    {"name": "Qwen_Image_Edit_GGUF_Q5_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_GGUF_Q5_1.gguf", "save_filename": "Qwen_Image_Edit_GGUF_Q5_1.gguf"},
                    {"name": "Qwen_Image_Edit_GGUF_Q4_K_M", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Qwen_Image_Edit_GGUF_Q4_K_M.gguf", "save_filename": "Qwen_Image_Edit_GGUF_Q4_K_M.gguf"},
                ]
            },
            "FLUX Models": {
                "info": ("FLUX models including Dev, ControlNet-like variants in standard formats (safetensors, FP16, FP8).\n\n"
                         "**How to use FLUX:** [FLUX Model Support](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#black-forest-labs-flux1-models)\n"
                         "**Extremely Important How To Use Parameters and Guide:**\n"
                         "- [General FLUX Install/Usage](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#install)\n"
                         "- [FLUX Tools Usage (Depth, Canny, etc.)](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#flux1-tools)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "FLUX SRPO", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "FLUX-SRPO-bf16.safetensors", "save_filename": "FLUX-SRPO-bf16.safetensors"},
                    {"name": "FLUX Krea DEV", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "flux1-krea-dev.safetensors", "save_filename": "FLUX_Krea_Dev.safetensors"},
                    {"name": "FLUX Kontext DEV BF16", "repo_id": "MonsterMMORPG/Best_FLUX_Models", "filename_in_repo": "flux1-kontext-dev.safetensors", "save_filename": "FLUX_Kontext_Dev.safetensors"},
                    {"name": "FLUX DEV 1.0 FP16", "repo_id": "OwlMaster/FLUX_LoRA_Train", "filename_in_repo": "flux1-dev.safetensors", "save_filename": "FLUX_Dev.safetensors"},
                    {"name": "FLUX DEV Fill (In/Out-Painting)", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "flux1-fill-dev.safetensors", "save_filename": "FLUX_DEV_Fill.safetensors"},
                    {"name": "FLUX DEV Depth", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "flux1-depth-dev.safetensors", "save_filename": "FLUX_DEV_Depth.safetensors"},
                    {"name": "FLUX DEV Canny", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "flux1-canny-dev.safetensors", "save_filename": "FLUX_DEV_Canny.safetensors"},
                    {"name": "FLUX DEV Redux (Style/Mix)", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "flux1-redux-dev.safetensors", "save_filename": "FLUX_DEV_Redux.safetensors", "target_dir_key": "style_models"},
                    {"name": "FLUX DEV 1.0 FP8 Scaled", "repo_id": "comfyanonymous/flux_dev_scaled_fp8_test", "filename_in_repo": "flux_dev_fp8_scaled_diffusion_model.safetensors", "save_filename": "FLUX_Dev_FP8_Scaled.safetensors"},
                    {"name": "FLUX DEV PixelWave V3", "repo_id": "mikeyandfriends/PixelWave_FLUX.1-dev_03", "filename_in_repo": "pixelwave_flux1_dev_bf16_03.safetensors", "save_filename": "FLUX_DEV_PixelWave_V3.safetensors"},
                    {"name": "FLUX DEV De-Distilled (Normal CFG 3.5)", "repo_id": "nyanko7/flux-dev-de-distill", "filename_in_repo": "consolidated_s6700.safetensors", "save_filename": "FLUX_DEV_De_Distilled.safetensors"},
                    {"name": "Flux Sigma Vision Alpha1 FP16 (Normal CFG 3.5)", "repo_id": "MonsterMMORPG/Best_FLUX_Models", "filename_in_repo": "fluxSigmaVision_fp16.safetensors", "save_filename": "Flux_Sigma_Vision_Alpha1_FP16.safetensors"},
                    {"name": "FLEX 1 Alpha (New Arch)", "repo_id": "ostris/Flex.1-alpha", "filename_in_repo": "Flex.1-alpha.safetensors", "save_filename": "FLEX_1_Alpha.safetensors"},
                    {
                        "name": "FLUX DEV ControlNet Inpainting Beta (Alimama)",
                        "repo_id": "alimama-creative/FLUX.1-dev-Controlnet-Inpainting-Beta",
                        "filename_in_repo": "diffusion_pytorch_model.safetensors",
                        "save_filename": "alimama_flux_inpainting.safetensors",
                        "target_dir_key": "controlnet"
                    },
                ]
            },
            "FLUX GGUF Models": {
                "info": ("FLUX models in GGUF quantized format for reduced memory usage. Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).\n\n"
                         "**How to use FLUX:** [FLUX Model Support](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Model%20Support.md#black-forest-labs-flux1-models)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    # FLUX SRPO GGUF - Q8 to Q4
                    {"name": "FLUX SRPO GGUF Q8_0", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "FLUX-SRPO-GGUF_Q8_0.gguf", "save_filename": "FLUX-SRPO-GGUF_Q8_0.gguf"},
                    {"name": "FLUX SRPO GGUF Q6_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "FLUX-SRPO-GGUF_Q6_K.gguf", "save_filename": "FLUX-SRPO-GGUF_Q6_K.gguf"},
                    {"name": "FLUX SRPO GGUF Q5_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "FLUX-SRPO-GGUF_Q5_K.gguf", "save_filename": "FLUX-SRPO-GGUF_Q5_K.gguf"},
                    {"name": "FLUX SRPO GGUF Q4_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "FLUX-SRPO-GGUF_Q4_K.gguf", "save_filename": "FLUX-SRPO-GGUF_Q4_K.gguf"},
                    # FLUX Krea DEV GGUF - Q8 to Q4
                    {"name": "FLUX Krea DEV GGUF Q8_0", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "flux1_krea_dev_BF16_Q8_0.gguf", "save_filename": "FLUX_Krea_Dev_GGUF_Q8_0.gguf"},
                    {"name": "FLUX Krea DEV GGUF Q6_K", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "flux1_krea_dev_BF16_Q6_K.gguf", "save_filename": "FLUX_Krea_Dev_GGUF_Q6_K.gguf"},
                    {"name": "FLUX Krea DEV GGUF Q5_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "flux1_krea_dev_BF16_Q5_1.gguf", "save_filename": "FLUX_Krea_Dev_GGUF_Q5_1.gguf"},
                    {"name": "FLUX Krea DEV GGUF Q4_1", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "flux1_krea_dev_BF16_Q4_1.gguf", "save_filename": "FLUX_Krea_Dev_GGUF_Q4_1.gguf"},
                    # FLUX DEV 1.0 GGUF - Q8 to Q4
                    {"name": "FLUX DEV 1.0 GGUF Q8", "repo_id": "city96/FLUX.1-dev-gguf", "filename_in_repo": "flux1-dev-Q8_0.gguf", "save_filename": "FLUX_Dev_GGUF_Q8.gguf"},
                    {"name": "FLUX DEV 1.0 GGUF Q6_K", "repo_id": "city96/FLUX.1-dev-gguf", "filename_in_repo": "flux1-dev-Q6_K.gguf", "save_filename": "FLUX_Dev_GGUF_Q6_K.gguf"},
                    {"name": "FLUX DEV 1.0 GGUF Q5_K_S", "repo_id": "city96/FLUX.1-dev-gguf", "filename_in_repo": "flux1-dev-Q5_K_S.gguf", "save_filename": "FLUX_Dev_GGUF_Q5_K_S.gguf"},
                    {"name": "FLUX DEV 1.0 GGUF Q4_K_S", "repo_id": "city96/FLUX.1-dev-gguf", "filename_in_repo": "flux1-dev-Q4_K_S.gguf", "save_filename": "FLUX_Dev_GGUF_Q4_K_S.gguf"},
                    # FLUX DEV Fill GGUF - Q8 to Q4
                    {"name": "FLUX DEV Fill GGUF Q8_0", "repo_id": "YarvixPA/FLUX.1-Fill-dev-gguf", "filename_in_repo": "flux1-fill-dev-Q8_0.gguf", "save_filename": "FLUX_DEV_Fill_GGUF_Q8_0.gguf"},
                    {"name": "FLUX DEV Fill GGUF Q6_K", "repo_id": "YarvixPA/FLUX.1-Fill-dev-gguf", "filename_in_repo": "flux1-fill-dev-Q6_K.gguf", "save_filename": "FLUX_DEV_Fill_GGUF_Q6_K.gguf"},
                    {"name": "FLUX DEV Fill GGUF Q5_K_S", "repo_id": "YarvixPA/FLUX.1-Fill-dev-gguf", "filename_in_repo": "flux1-fill-dev-Q5_K_S.gguf", "save_filename": "FLUX_DEV_Fill_GGUF_Q5_K_S.gguf"},
                    {"name": "FLUX DEV Fill GGUF Q4_K_S", "repo_id": "YarvixPA/FLUX.1-Fill-dev-gguf", "filename_in_repo": "flux1-fill-dev-Q4_K_S.gguf", "save_filename": "FLUX_DEV_Fill_GGUF_Q4_K_S.gguf"},
                    # FLUX Kontext DEV GGUF - Q8 to Q4
                    {"name": "FLUX Kontext DEV GGUF Q8_0", "repo_id": "bullerwins/FLUX.1-Kontext-dev-GGUF", "filename_in_repo": "flux1-kontext-dev-Q8_0.gguf", "save_filename": "FLUX_Kontext_Dev_GGUF_Q8_0.gguf"},
                    {"name": "FLUX Kontext DEV GGUF Q6_K", "repo_id": "bullerwins/FLUX.1-Kontext-dev-GGUF", "filename_in_repo": "flux1-kontext-dev-Q6_K.gguf", "save_filename": "FLUX_Kontext_Dev_GGUF_Q6_K.gguf"},
                    {"name": "FLUX Kontext DEV GGUF Q5_K_M", "repo_id": "bullerwins/FLUX.1-Kontext-dev-GGUF", "filename_in_repo": "flux1-kontext-dev-Q5_K_M.gguf", "save_filename": "FLUX_Kontext_Dev_GGUF_Q5_K_M.gguf"},
                    {"name": "FLUX Kontext DEV GGUF Q4_K_M", "repo_id": "bullerwins/FLUX.1-Kontext-dev-GGUF", "filename_in_repo": "flux1-kontext-dev-Q4_K_M.gguf", "save_filename": "FLUX_Kontext_Dev_GGUF_Q4_K_M.gguf"},
                ]
            },
            "HiDream-I1 Image Editing Models": {
                "info": f"Image editing specific variant of HiDream-I1.\n\n**How to use HiDream:** [{HIDREAM_INFO_LINK}]({HIDREAM_INFO_LINK})",
                "target_dir_key": "diffusion_models",
                "models": [
                     {"name": "HiDream-I1-E1 BF16 Image Editing", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_e1_full_bf16.safetensors", "save_filename": "HiDream_I1_E1_Image_Editing_BF16.safetensors"},
                ]
            },
            "HiDream-I1 Full Models": {
                "info": f"Full version of HiDream-I1 models. {GGUF_QUALITY_INFO}\n\n**How to use HiDream:** [{HIDREAM_INFO_LINK}]({HIDREAM_INFO_LINK})",
                "target_dir_key": "diffusion_models",
                "models": [
                     {"name": "HiDream-I1 Full FP16", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_i1_full_fp16.safetensors", "save_filename": "HiDream_I1_Full_FP16.safetensors"},
                     {"name": "HiDream-I1 Full FP8", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_i1_full_fp8.safetensors", "save_filename": "HiDream_I1_Full_FP8.safetensors"},
                     {"name": "HiDream-I1 Full GGUF F16", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-F16.gguf", "save_filename": "HiDream_I1_Full_GGUF_F16.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q8_0", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q8_0.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q8_0.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q6_K", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q6_K.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q6_K.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q5_K_M", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q5_K_M.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q5_K_M.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q5_K_S", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q5_K_S.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q5_K_S.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q5_1", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q5_1.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q5_1.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q5_0", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q5_0.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q5_0.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q4_K_M", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q4_K_M.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q4_K_M.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q4_K_S", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q4_K_S.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q4_K_S.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q4_1", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q4_1.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q4_1.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q4_0", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q4_0.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q4_0.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q3_K_M", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q3_K_M.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q3_K_M.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q3_K_S", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q3_K_S.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q3_K_S.gguf"},
                     {"name": "HiDream-I1 Full GGUF Q2_K", "repo_id": "city96/HiDream-I1-Full-gguf", "filename_in_repo": "hidream-i1-full-Q2_K.gguf", "save_filename": "HiDream_I1_Full_GGUF_Q2_K.gguf"},
                ]
            },
            "HiDream-I1 Dev Models (Recommended)": {
                "info": f"Development version of HiDream-I1 models (Recommended for general use). {GGUF_QUALITY_INFO}\n\n**How to use HiDream:** [{HIDREAM_INFO_LINK}]({HIDREAM_INFO_LINK})",
                "target_dir_key": "diffusion_models",
                "models": [
                     {"name": "HiDream-I1 Dev BF16", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_i1_dev_bf16.safetensors", "save_filename": "HiDream_I1_Dev_BF16.safetensors"},
                     {"name": "HiDream-I1 Dev FP8", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_i1_dev_fp8.safetensors", "save_filename": "HiDream_I1_Dev_FP8.safetensors"},
                     {"name": "HiDream-I1 Dev GGUF BF16", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-BF16.gguf", "save_filename": "HiDream_I1_Dev_GGUF_BF16.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q8_0", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q8_0.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q8_0.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q6_K", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q6_K.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q6_K.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q5_K_M", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q5_K_M.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q5_K_M.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q5_K_S", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q5_K_S.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q5_K_S.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q5_1", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q5_1.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q5_1.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q5_0", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q5_0.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q5_0.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q4_K_M", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q4_K_M.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q4_K_M.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q4_K_S", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q4_K_S.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q4_K_S.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q4_1", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q4_1.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q4_1.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q4_0", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q4_0.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q4_0.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q3_K_M", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q3_K_M.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q3_K_M.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q3_K_S", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q3_K_S.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q3_K_S.gguf"},
                     {"name": "HiDream-I1 Dev GGUF Q2_K", "repo_id": "city96/HiDream-I1-Dev-gguf", "filename_in_repo": "hidream-i1-dev-Q2_K.gguf", "save_filename": "HiDream_I1_Dev_GGUF_Q2_K.gguf"},
                ]
            },
            "HiDream-I1 Fast Models": {
                "info": f"Faster distilled version of HiDream-I1 models. {GGUF_QUALITY_INFO}\n\n**How to use HiDream:** [{HIDREAM_INFO_LINK}]({HIDREAM_INFO_LINK})",
                "target_dir_key": "diffusion_models",
                "models": [
                     {"name": "HiDream-I1 Fast BF16", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_i1_fast_bf16.safetensors", "save_filename": "HiDream_I1_Fast_BF16.safetensors"},
                     {"name": "HiDream-I1 Fast FP8", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/diffusion_models/hidream_i1_fast_fp8.safetensors", "save_filename": "HiDream_I1_Fast_FP8.safetensors"},
                     {"name": "HiDream-I1 Fast GGUF BF16", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-BF16.gguf", "save_filename": "HiDream_I1_Fast_GGUF_BF16.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q8_0", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q8_0.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q8_0.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q6_K", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q6_K.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q6_K.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q5_K_M", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q5_K_M.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q5_K_M.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q5_K_S", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q5_K_S.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q5_K_S.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q5_1", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q5_1.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q5_1.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q5_0", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q5_0.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q5_0.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q4_K_M", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q4_K_M.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q4_K_M.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q4_K_S", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q4_K_S.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q4_K_S.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q4_1", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q4_1.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q4_1.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q4_0", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q4_0.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q4_0.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q3_K_M", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q3_K_M.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q3_K_M.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q3_K_S", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q3_K_S.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q3_K_S.gguf"},
                     {"name": "HiDream-I1 Fast GGUF Q2_K", "repo_id": "city96/HiDream-I1-Fast-gguf", "filename_in_repo": "hidream-i1-fast-Q2_K.gguf", "save_filename": "HiDream_I1_Fast_GGUF_Q2_K.gguf"},
                ]
            },
            "Stable Diffusion 1.5 Models": {
                 "info": "Popular fine-tuned models based on Stable Diffusion 1.5.",
                 "target_dir_key": "Stable-Diffusion",
                 "models": [
                    {"name": "Realistic Vision V6", "repo_id": "SG161222/Realistic_Vision_V6.0_B1_noVAE", "filename_in_repo": "Realistic_Vision_V6.0_NV_B1.safetensors", "save_filename": "SD1.5_Realistic_Vision_V6.safetensors"},
                    {"name": "RealCartoon3D V18", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "realcartoon3dv18.safetensors", "save_filename": "SD1.5_RealCartoon3D_V18.safetensors"},
                    {"name": "CyberRealistic V8", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "cyberrealistic_v80.safetensors", "save_filename": "SD1.5_CyberRealistic_V8.safetensors"},
                    {"name": "epiCPhotoGasm Ultimate Fidelity", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "epicphotogasm_ultimateFidelity.safetensors", "save_filename": "epiCPhotoGasm_Ultimate_Fidelity.safetensors"},

                 ]
            },
            "Stable Diffusion XL (SDXL) Models": {
                 "info": "Models based on the Stable Diffusion XL architecture.",
                 "target_dir_key": "Stable-Diffusion",
                 "models": [
                    {"name": "SDXL Base 1.0 (Official)", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "sd_xl_base_1.0_0.9vae.safetensors", "save_filename": "SDXL_Base_1_0.safetensors"},
                    {"name": "Juggernaut XL V11", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "Juggernaut-XI-byRunDiffusion.safetensors", "save_filename": "SDXL_Juggernaut_V11.safetensors"},
                    {"name": "epiCRealism XL LastFame", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "epicrealismXL_vxviLastfameRealism.safetensors", "save_filename": "SDXL_epiCRealism_Last_LastFame.safetensors"},
                    {"name": "RealVisXL V5", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "realvisxlV50_v50Bakedvae.safetensors", "save_filename": "SDXL_RealVisXL_V5.safetensors"},
                    {"name": "Real Dream SDXL 5", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "realDream_sdxl5.safetensors", "save_filename": "SDXL_RealDream_5.safetensors"},
                    {"name": "Eldritch Photography V1", "repo_id": "OwlMaster/Some_best_SDXL", "filename_in_repo": "eldritchPhotography_v1.safetensors", "save_filename": "SDXL_Eldritch_Photography_V1.safetensors"},
                 ]
            },
            "Stable Diffusion 3.5 Large Models": {
                "info": "Official Stable Diffusion 3.5 Large models and variants. GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).",
                "target_dir_key": "diffusion_models",
                "models": [
                     {"name": "Stable Diffusion 3.5 Large (Official) - FP16", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "sd3.5_large.safetensors", "save_filename": "SD3.5_Official_Large.safetensors"},
                     {"name": "Stable Diffusion 3.5 Large (Official) - FP8 Scaled", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "sd3.5_large_fp8_scaled.safetensors", "save_filename": "SD3.5_Official_Large_FP8_Scaled.safetensors", "target_dir_key": "Stable-Diffusion"},
                     {"name": "Stable Diffusion 3.5 Large (Official) - GGUF Q8", "repo_id": "city96/stable-diffusion-3.5-large-gguf", "filename_in_repo": "sd3.5_large-Q8_0.gguf", "save_filename": "SD3.5_Official_Large_GGUF_Q8.gguf"},
                     {"name": "Stable Diffusion 3.5 Large (Official) - GGUF Q5_1", "repo_id": "city96/stable-diffusion-3.5-large-gguf", "filename_in_repo": "sd3.5_large-Q5_1.gguf", "save_filename": "SD3.5_Official_Large_GGUF_Q5_1.gguf"},
                     {"name": "Stable Diffusion 3.5 Large (Official) - GGUF Q4_1", "repo_id": "city96/stable-diffusion-3.5-large-gguf", "filename_in_repo": "sd3.5_large-Q4_1.gguf", "save_filename": "SD3.5_Official_Large_GGUF_Q4_1.gguf"},
                ]
            }
        }
    }, "Other Models (e.g. Yolo Face Segment, Image Upscaling)": {
        "info": "Utility models like upscalers and segmentation models.",
        "sub_categories": {
            "Image Upscaling Models": {
                "info": "High-quality deterministic image upscaling models (from OpenModelDB and other sources).",
                "target_dir_key": "upscale_models",
                "models": [
                    {"name": "Best Upscaler Models (Full Set Snapshot)", "repo_id": "MonsterMMORPG/BestImageUpscalers", "is_snapshot": True},
                    {"name": "LTX Spatial Upscaler 0.9.7 (Lightricks)", "repo_id": "Lightricks/LTX-Video", "filename_in_repo": "ltxv-spatial-upscaler-0.9.7.safetensors", "save_filename": "LTX_Spatial_Upscaler_0_9_7.safetensors"},
                    {"name": "LTX Temporal Upscaler 0.9.7 (Lightricks)", "repo_id": "Lightricks/LTX-Video", "filename_in_repo": "ltxv-temporal-upscaler-0.9.7.safetensors", "save_filename": "LTX_Temporal_Upscaler_0_9_7.safetensors"},
                ]
            },
            "Auto Yolo Masking/Segment Models": {
                 "info": "YOLO-based models for automatic face segmentation/masking (from MonsterMMORPG), useful for inpainting.",
                 "target_dir_key": "yolov8",
                 "models": [
                     {"name": "Face YOLOv9c Detection Model", "repo_id": "MonsterMMORPG/FaceSegments", "filename_in_repo": "face_yolov9c.pt", "save_filename": "face_yolov9c.pt"},
                     {"name": "YOLOv12L Face Detection Model", "repo_id": "MonsterMMORPG/FaceSegments", "filename_in_repo": "yolov12l-face.pt", "save_filename": "yolov12l-face.pt"},
                     {"name": "Male Face Segmentation Model", "repo_id": "MonsterMMORPG/FaceSegments", "filename_in_repo": "man_face.pt", "save_filename": "man_face.pt"},
                     {"name": "Female Face Segmentation Model", "repo_id": "MonsterMMORPG/FaceSegments", "filename_in_repo": "woman_face.pt", "save_filename": "woman_face.pt"},
                 ]
             }
        }
    }, "Text Encoder Models": {
         "info": "Text encoder models used by various generation models.",
         "sub_categories": {
            "T5 XXL Models": {
                "info": "T5 XXL variants used by FLUX, SD 3.5, Hunyuan, etc. GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).",
                "target_dir_key": "text_encoders",
                "models": [
                    {"name": "T5 XXL FP16", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "t5xxl_fp16.safetensors", "save_filename": "t5xxl_fp16.safetensors"},
                    {"name": "T5 XXL FP8 (e4m3fn)", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "t5xxl_fp8_e4m3fn.safetensors", "save_filename": "t5xxl_fp8_e4m3fn.safetensors"},
                    {"name": "T5 XXL FP8 Scaled (e4m3fn)", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "t5xxl_fp8_e4m3fn_scaled.safetensors", "save_filename": "t5xxl_fp8_e4m3fn_scaled.safetensors"},
                    {"name": "T5 XXL FP16 (Save As t5xxl_enconly for SwarmUI default name)", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "t5xxl_fp16.safetensors", "save_filename": "t5xxl_enconly.safetensors"},
                    {"name": "T5 XXL GGUF Q8", "repo_id": "calcuis/mochi", "filename_in_repo": "t5xxl_fp16-q8_0.gguf", "save_filename": "t5xxl_GGUF_Q8.gguf"},
                    {"name": "T5 XXL GGUF Q4_0", "repo_id": "calcuis/mochi", "filename_in_repo": "t5xxl_fp16-q4_0.gguf", "save_filename": "t5xxl_GGUF_Q4_0.gguf"},
                ]
            },
            "UMT5 XXL Models": {
                "info": "UMT5 XXL variants used by Wan 2.1. GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0). Select non-GGUF FP16/BF16/FP8 based on your Wan model choice, or use GGUF if preferred (manual setup needed in SwarmUI).",
                "target_dir_key": "text_encoders",
                "models": [
                    {"name": "UMT5 XXL BF16 (Used by Wan 2.1)", "repo_id": "Kijai/WanVideo_comfy", "filename_in_repo": "umt5-xxl-enc-bf16.safetensors", "save_filename": "umt5-xxl-enc-bf16.safetensors"},
                    # These save the same file, choose one or rename target
                    {"name": "UMT5 XXL BF16 (Save As default for SwarmUI)", "repo_id": "Kijai/WanVideo_comfy", "filename_in_repo": "umt5-xxl-enc-bf16.safetensors", "save_filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "target_dir_key": "text_encoders", "allow_overwrite": True},
                    {"name": "UMT5 XXL FP16 (Save As default for SwarmUI)", "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "filename_in_repo": "split_files/text_encoders/umt5_xxl_fp16.safetensors", "save_filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "target_dir_key": "text_encoders", "allow_overwrite": True},
                    {"name": "UMT5 XXL FP8 Scaled (Default for SwarmUI)", "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "filename_in_repo": "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "save_filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "target_dir_key": "text_encoders", "allow_overwrite": True},
                    # GGUF models
                    {"name": "UMT5 XXL GGUF Q8 (Manual Setup)", "repo_id": "city96/umt5-xxl-encoder-gguf", "filename_in_repo": "umt5-xxl-encoder-Q8_0.gguf", "save_filename": "umt5-xxl-encoder-Q8_0.gguf"},
                    {"name": "UMT5 XXL GGUF Q6_K (Manual Setup)", "repo_id": "city96/umt5-xxl-encoder-gguf", "filename_in_repo": "umt5-xxl-encoder-Q6_K.gguf", "save_filename": "umt5-xxl-encoder-Q6_K.gguf"},
                    {"name": "UMT5 XXL GGUF Q5_K_M (Manual Setup)", "repo_id": "city96/umt5-xxl-encoder-gguf", "filename_in_repo": "umt5-xxl-encoder-Q5_K_M.gguf", "save_filename": "umt5-xxl-encoder-Q5_K_M.gguf"},
                    {"name": "UMT5 XXL GGUF Q4_K_M (Manual Setup)", "repo_id": "city96/umt5-xxl-encoder-gguf", "filename_in_repo": "umt5-xxl-encoder-Q4_K_M.gguf", "save_filename": "umt5-xxl-encoder-Q4_K_M.gguf"},
                ]
            },
            "Clip Models": {
                "info": "CLIP models (L and G variants) used by many models.",
                "target_dir_key": "text_encoders",
                "models": [
                    {"name": "CLIP-SAE-ViT-L-14 (Save As clip_l.safetensors - SwarmUI default name)", "repo_id": "OwlMaster/zer0int-CLIP-SAE-ViT-L-14", "filename_in_repo": "clip_l.safetensors", "save_filename": "clip_l.safetensors", "pre_delete_target": True},
                    {"name": "CLIP-SAE-ViT-L-14 (Save As CLIP_SAE_ViT_L_14)", "repo_id": "OwlMaster/zer0int-CLIP-SAE-ViT-L-14", "filename_in_repo": "clip_l.safetensors", "save_filename": "CLIP_SAE_ViT_L_14.safetensors"},
                    {"name": "Default Clip L", "repo_id": "MonsterMMORPG/Kohya_Train", "filename_in_repo": "clip_l.safetensors", "save_filename": "clip_l.safetensors"}, # Use specific save name
                    {"name": "Clip G", "repo_id": "OwlMaster/SD3New", "filename_in_repo": "clip_g.safetensors", "save_filename": "clip_g.safetensors"},
                    {"name": "Long Clip L for HiDream-I1", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/text_encoders/clip_l_hidream.safetensors", "save_filename": "long_clip_l_hi_dream.safetensors"},
                    {"name": "Long Clip G for HiDream-I1", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/text_encoders/clip_g_hidream.safetensors", "save_filename": "long_clip_g_hi_dream.safetensors"},
                    qwen_3_4b_text_encoder_entry,
                    {"name": "qwen_2.5_vl_7b_fp16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen_2.5_vl_7b_fp16.safetensors", "save_filename": "qwen_2.5_vl_7b_fp16.safetensors"},
                    {"name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "save_filename": "qwen_2.5_vl_7b_fp8_scaled.safetensors"},
                ]
            },
            "LLM Text Encoders": {
                 "info": "Large Language Model based text encoders, currently used by HiDream-I1.",
                 "target_dir_key": "text_encoders",
                 "models": [
                     {"name": "LLAMA 3.1 8b Instruct FP8 Scaled for HiDream-I1", "repo_id": "Comfy-Org/HiDream-I1_ComfyUI", "filename_in_repo": "split_files/text_encoders/llama_3.1_8b_instruct_fp8_scaled.safetensors", "save_filename": "llama_3.1_8b_instruct_fp8_scaled.safetensors"},
                 ]
             },
         }
    },
    "Video Generation Models": {
        "info": "Models for generating videos from text or images.",
        "sub_categories": {
            "Wan 2.1 Official Models": {
                 "info": ("Official Wan 2.1 text-to-video and image-to-video models (non-FusionX). GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [Wan 2.1 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-21-parameters)"),
                 "target_dir_key": "diffusion_models",
                 "models": [
                    {"name": "Wan 2.1 T2V 1.3B FP16", "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "filename_in_repo": "split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors", "save_filename": "Wan2.1_1.3b_Text_to_Video.safetensors"},
                    {"name": "Wan 2.1 T2V 14B 720p FP16", "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "filename_in_repo": "split_files/diffusion_models/wan2.1_t2v_14B_fp16.safetensors", "save_filename": "Wan2.1_14b_Text_to_Video.safetensors"},
                    {"name": "Wan 2.1 T2V 14B 720p FP8", "repo_id": "Kijai/WanVideo_comfy", "filename_in_repo": "Wan2_1-T2V-14B_fp8_e4m3fn.safetensors", "save_filename": "Wan2.1_14b_Text_to_Video_FP8.safetensors"},
                    {"name": "Wan 2.1 I2V 14B 480p FP16", "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "filename_in_repo": "split_files/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors", "save_filename": "Wan2.1_14b_Image_to_Video_480p.safetensors"},
                    {"name": "Wan 2.1 I2V 14B 480p FP8", "repo_id": "Kijai/WanVideo_comfy", "filename_in_repo": "Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors", "save_filename": "Wan2.1_14b_Image_to_Video_480p_FP8.safetensors"},
                    {"name": "Wan 2.1 I2V 14B 720p FP16", "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "filename_in_repo": "split_files/diffusion_models/wan2.1_i2v_720p_14B_fp16.safetensors", "save_filename": "Wan2.1_14b_Image_to_Video_720p.safetensors"},
                    {"name": "Wan 2.1 I2V 14B 720p FP8", "repo_id": "Kijai/WanVideo_comfy", "filename_in_repo": "Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors", "save_filename": "Wan2.1_14b_Image_to_Video_720p_FP8.safetensors"},
                    {"name": "WanVideo 2.1 MultiTalk 14B FP32", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "WanVideo_2_1_Multitalk_14B_fp32.safetensors", "save_filename": "WanVideo_2_1_Multitalk_14B_fp32.safetensors"},
                    {"name": "Wan 2.1 T2V 14B 720p GGUF Q8", "repo_id": "city96/Wan2.1-T2V-14B-gguf", "filename_in_repo": "wan2.1-t2v-14b-Q8_0.gguf", "save_filename": "Wan2.1_14b_Text_to_Video_GGUF_Q8.gguf"},
                    {"name": "Wan 2.1 T2V 14B 720p GGUF Q6_K", "repo_id": "city96/Wan2.1-T2V-14B-gguf", "filename_in_repo": "wan2.1-t2v-14b-Q6_K.gguf", "save_filename": "Wan2.1_14b_Text_to_Video_GGUF_Q6_K.gguf"},
                    {"name": "Wan 2.1 T2V 14B 720p GGUF Q5_K_M", "repo_id": "city96/Wan2.1-T2V-14B-gguf", "filename_in_repo": "wan2.1-t2v-14b-Q5_K_M.gguf", "save_filename": "Wan2.1_14b_Text_to_Video_GGUF_Q5_K_M.gguf"},
                    {"name": "Wan 2.1 T2V 14B 720p GGUF Q4_K_M", "repo_id": "city96/Wan2.1-T2V-14B-gguf", "filename_in_repo": "wan2.1-t2v-14b-Q4_K_M.gguf", "save_filename": "Wan2.1_14b_Text_to_Video_GGUF_Q4_K_M.gguf"},
                    {"name": "Wan 2.1 I2V 14B 480p GGUF Q8", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan21_i2v_480p_14B_Q8.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_480p_GGUF_Q8.gguf"},
                    {"name": "Wan 2.1 I2V 14B 480p GGUF Q6_K", "repo_id": "city96/Wan2.1-I2V-14B-480P-gguf", "filename_in_repo": "wan2.1-i2v-14b-480p-Q6_K.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_480p_GGUF_Q6_K.gguf"},
                    {"name": "Wan 2.1 I2V 14B 480p GGUF Q5_K_M", "repo_id": "city96/Wan2.1-I2V-14B-480P-gguf", "filename_in_repo": "wan2.1-i2v-14b-480p-Q5_K_M.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_480p_GGUF_Q5_K_M.gguf"},
                    {"name": "Wan 2.1 I2V 14B 480p GGUF Q4_K_M", "repo_id": "city96/Wan2.1-I2V-14B-480P-gguf", "filename_in_repo": "wan2.1-i2v-14b-480p-Q4_K_M.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_480p_GGUF_Q4_K_M.gguf"},
                    {"name": "Wan 2.1 I2V 14B 720p GGUF Q8", "repo_id": "city96/Wan2.1-I2V-14B-720P-gguf", "filename_in_repo": "wan2.1-i2v-14b-720p-Q8_0.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_720p_GGUF_Q8.gguf"},
                    {"name": "Wan 2.1 I2V 14B 720p GGUF Q6_K", "repo_id": "city96/Wan2.1-I2V-14B-720P-gguf", "filename_in_repo": "wan2.1-i2v-14b-720p-Q6_K.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_720p_GGUF_Q6_K.gguf"},
                    {"name": "Wan 2.1 I2V 14B 720p GGUF Q5_K_M", "repo_id": "city96/Wan2.1-I2V-14B-720P-gguf", "filename_in_repo": "wan2.1-i2v-14b-720p-Q5_K_M.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_720p_GGUF_Q5_K_M.gguf"},
                    {"name": "Wan 2.1 I2V 14B 720p GGUF Q4_K_M", "repo_id": "city96/Wan2.1-I2V-14B-720P-gguf", "filename_in_repo": "wan2.1-i2v-14b-720p-Q4_K_M.gguf", "save_filename": "Wan2.1_14b_Image_to_Video_720p_GGUF_Q4_K_M.gguf"},
                 ]
             },
            "Wan 2.1 FusionX Models": {
                 "info": ("Wan 2.1 FusionX text-to-video and image-to-video models with enhanced performance. GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [Wan 2.1 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-21-parameters)"),
                 "target_dir_key": "diffusion_models",
                 "models": [
                    {"name": "Wan 2.1 FusionX T2V 14B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2_1_14B_FusionX_T2V_fp16.safetensors", "save_filename": "Wan2.1_14b_FusionX_Text_to_Video_FP16.safetensors"},
                    {"name": "Wan 2.1 FusionX T2V 14B FP8", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2_1_14B_FusionX_T2V_fp8.safetensors", "save_filename": "Wan2.1_14b_FusionX_Text_to_Video_FP8.safetensors"},
                    {"name": "Wan 2.1 FusionX I2V 14B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2_1_14B_FusionX_I2V_fp16.safetensors", "save_filename": "Wan2.1_14b_FusionX_Image_to_Video_FP16.safetensors"},
                    {"name": "Wan 2.1 FusionX I2V 14B FP8", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2_1_14B_FusionX_I2V_fp8.safetensors", "save_filename": "Wan2.1_14b_FusionX_Image_to_Video_FP8.safetensors"},
                    wan_fusionx_t2v_gguf_q8_entry,
                    wan_fusionx_t2v_gguf_q6_entry,
                    wan_fusionx_t2v_gguf_q5_entry,
                    wan_fusionx_t2v_gguf_q4_entry,
                    wan_fusionx_i2v_gguf_q8_entry,
                    wan_fusionx_i2v_gguf_q6_entry,
                    wan_fusionx_i2v_gguf_q5_entry,
                    wan_fusionx_i2v_gguf_q4_entry,
                 ]
             },
            "Wan 2.1 LoRAs": {
                 "info": ("Wan 2.1 LoRA models for enhanced performance and specialized use cases. See SwarmUI Video Docs for usage details on CFG, Steps, FPS, and Trim Video Start Frames.\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [Wan 2.1 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-21-parameters)"),
                 "target_dir_key": "Lora",
                 "models": [
                    wan_causvid_14b_lora_v2_entry,
                    wan_causvid_14b_lora_entry,
                    wan_causvid_1_3b_lora_entry,
                    wan_self_forcing_lora_entry,
                    {"name": "Phantom Wan 14B FusionX LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Phantom_Wan_14B_FusionX_LoRA.safetensors", "save_filename": "Phantom_Wan_14B_FusionX_LoRA.safetensors", "target_dir_key": "Lora", "info": "Phantom FusionX LoRA for Wan 2.1 14B models. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    {"name": "Wan 2.1 I2V 14B FusionX LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.1_Image_to_Video_14B_FusionX_LoRA.safetensors", "save_filename": "Wan2.1_Image_to_Video_14B_FusionX_LoRA.safetensors", "target_dir_key": "Lora", "info": "FusionX I2V LoRA for Wan 2.1 14B models. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    {"name": "Wan 2.1 T2V 14B FusionX LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.1_Text_to_Video_14B_FusionX_LoRA.safetensors", "save_filename": "Wan2.1_Text_to_Video_14B_FusionX_LoRA.safetensors", "target_dir_key": "Lora", "info": "FusionX T2V LoRA for Wan 2.1 14B models. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    wan_lightx2v_lora_entry,
                 ]
             },
            "Wan 2.2 Official Models": {
                 "info": ("Official Wan 2.2 text-to-video and image-to-video models. Includes both high and low noise variants.\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [Wan 2.2 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-22)"),
                 "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "Wan 2.2 T2V High Noise 14B BF16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan-2.2-T2V-High-Noise-BF16.safetensors", "save_filename": "Wan-2.2-T2V-High-Noise-BF16.safetensors"},
                    {"name": "Wan 2.2 I2V High Noise 14B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_i2v_high_noise_14B_fp16.safetensors", "save_filename": "wan2.2_i2v_high_noise_14B_fp16.safetensors"},
                    {"name": "Wan 2.2 I2V High Noise 14B FP8 Scaled", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "save_filename": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"},
                    {"name": "Wan 2.2 T2V Low Noise 14B BF16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan-2.2-T2V-Low-Noise-BF16.safetensors", "save_filename": "Wan-2.2-T2V-Low-Noise-BF16.safetensors"},
                    {"name": "Wan 2.2 I2V Low Noise 14B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_i2v_low_noise_14B_fp16.safetensors", "save_filename": "wan2.2_i2v_low_noise_14B_fp16.safetensors"},
                    {"name": "Wan 2.2 I2V Low Noise 14B FP8 Scaled", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "save_filename": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"},
                    {"name": "Wan 2.2 T2V High Noise 14B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_t2v_high_noise_14B_fp16.safetensors", "save_filename": "wan2.2_t2v_high_noise_14B_fp16.safetensors"},
                    {"name": "Wan 2.2 T2V High Noise 14B FP8 Scaled", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "save_filename": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"},
                    {"name": "Wan 2.2 T2V Low Noise 14B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_t2v_low_noise_14B_fp16.safetensors", "save_filename": "wan2.2_t2v_low_noise_14B_fp16.safetensors"},
                    {"name": "Wan 2.2 T2V Low Noise 14B FP8 Scaled", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "save_filename": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"},
                    {"name": "Wan 2.2 TI2V 5B FP16", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_ti2v_5B_fp16.safetensors", "save_filename": "wan2.2_ti2v_5B_fp16.safetensors"},
                 ]
             },
             "Wan 2.2 Fast Models": {
                 "info": ("Fast Wan 2.2 image-to-video models with MoE Distill Lightx2v optimization for improved performance.\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [Wan 2.2 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-22)"),
                 "target_dir_key": "diffusion_models",
                 "models": [
                    wan_2_2_i2v_fast_low_entry,
                    wan_2_2_i2v_fast_high_entry,
                 ]
             },
            "Wan 2.2 LoRAs": {
                 "info": ("Wan 2.2 LoRA models for enhanced performance and specialized use cases. See SwarmUI Video Docs for usage details on CFG, Steps, FPS, and Trim Video Start Frames.\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [Wan 2.2 Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-22)"),
                 "target_dir_key": "Lora",
                 "models": [
                    {"name": "Wan2.2-T2V-A14B-4steps-lora-250928-Low.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.2-T2V-A14B-4steps-lora-250928-Low.safetensors", "save_filename": "Wan2.2-T2V-A14B-4steps-lora-250928-Low.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 T2V LoRA Low Noise variant for fast 4-step generation. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    {"name": "Wan2.2-T2V-A14B-4steps-lora-250928-High.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.2-T2V-A14B-4steps-lora-250928-High.safetensors", "save_filename": "Wan2.2-T2V-A14B-4steps-lora-250928-High.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 T2V LoRA High Noise variant for fast 4-step generation. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                   {"name": "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_Low", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_Low.safetensors", "save_filename": "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_Low.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 I2V LoRA Low Noise variant for fast 4-step generation. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                   {"name": "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_High", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_High.safetensors", "save_filename": "Wan2_2-I2V-A14B-4steps-lora-rank64-Seko-V1_High.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 I2V LoRA High Noise variant for fast 4-step generation. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                   {"name": "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-Low.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-Low.safetensors", "save_filename": "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-Low.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 T2V LoRA Low Noise Seko V2.0 variant for fast 4-step generation. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                   {"name": "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-High.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-High.safetensors", "save_filename": "Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V2.0-High.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 T2V LoRA High Noise Seko V2.0 variant for fast 4-step generation. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                   {"name": "Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors", "save_filename": "Wan2.2_T2V_High_Noise_Lightx2v_4steps_LoRA_1217.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 T2V High Noise Lightx2v LoRA for fast 4-step generation (December 2024 release). Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                   {"name": "Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors", "save_filename": "Wan2.2_T2V_Low_Noise_Lightx2v_4steps_LoRA_1217.safetensors", "target_dir_key": "Lora", "info": "Wan 2.2 T2V Low Noise Lightx2v LoRA for fast 4-step generation (December 2024 release). Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                 ]
             },
            "Hunyuan Models": {
                "info": ("Hunyuan text-to-video and image-to-video models. GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).\n\n"
                         "**Extremely Important How To Use Parameters and Guide:** [Hunyuan Video Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#hunyuan-video-parameters)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "HunYuan T2V 720p BF16", "repo_id": "Comfy-Org/HunyuanVideo_repackaged", "filename_in_repo": "split_files/diffusion_models/hunyuan_video_t2v_720p_bf16.safetensors", "save_filename": "HunYuan_Text_to_Video.safetensors"},
                    {"name": "HunYuan I2V 720p BF16", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_I2V_720_fixed_bf16.safetensors", "save_filename": "HunYuan_Image_to_Video.safetensors"},
                    {"name": "HunYuan T2V 720p CFG Distill BF16", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_720_cfgdistill_bf16.safetensors", "save_filename": "HunYuan_Text_to_Video_CFG_Distill.safetensors"},
                    {"name": "HunYuan T2V 720p CFG Distill FP8 Scaled", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors", "save_filename": "HunYuan_Text_to_Video_CFG_Distill_FP8_Scaled.safetensors"},
                    {"name": "HunYuan I2V 720p FP8 Scaled", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_I2V_720_fixed_fp8_e4m3fn.safetensors", "save_filename": "HunYuan_Image_to_Video_FP8_Scaled.safetensors"},
                    {"name": "HunYuan I2V 720p GGUF Q8", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_I2V-Q8_0.gguf", "save_filename": "HunYuan_Image_to_Video_GGUF_Q8.gguf"},
                    {"name": "HunYuan I2V 720p GGUF Q6_K", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_I2V-Q6_K.gguf", "save_filename": "HunYuan_Image_to_Video_GGUF_Q6_K.gguf"},
                    {"name": "HunYuan I2V 720p GGUF Q4_K_S", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_I2V-Q4_K_S.gguf", "save_filename": "HunYuan_Image_to_Video_GGUF_Q4_K_S.gguf"},
                ]
            },
            "Fast Hunyuan Models - 6 Steps": {
                "info": ("Faster distilled Hunyuan text-to-video models (6 steps). GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).\n\n"
                         "**Extremely Important How To Use Parameters and Guide:** [FastVideo Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#fastvideo)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "FAST HunYuan T2V 720p GGUF BF16", "repo_id": "city96/FastHunyuan-gguf", "filename_in_repo": "fast-hunyuan-video-t2v-720p-BF16.gguf", "save_filename": "FAST_HunYuan_Text_to_Video_GGUF_BF16.gguf"},
                    {"name": "FAST HunYuan T2V 720p FP8", "repo_id": "Kijai/HunyuanVideo_comfy", "filename_in_repo": "hunyuan_video_FastVideo_720_fp8_e4m3fn.safetensors", "save_filename": "FAST_HunYuan_Text_to_Video_FP8.safetensors"},
                    {"name": "FAST HunYuan T2V 720p GGUF Q8", "repo_id": "city96/FastHunyuan-gguf", "filename_in_repo": "fast-hunyuan-video-t2v-720p-Q8_0.gguf", "save_filename": "FAST_HunYuan_Text_to_Video_GGUF_Q8.gguf"},
                    {"name": "FAST HunYuan T2V 720p GGUF Q6_K", "repo_id": "city96/FastHunyuan-gguf", "filename_in_repo": "fast-hunyuan-video-t2v-720p-Q6_K.gguf", "save_filename": "FAST_HunYuan_Text_to_Video_GGUF_Q6_K.gguf"},
                    {"name": "FAST HunYuan T2V 720p GGUF Q5_K_M", "repo_id": "city96/FastHunyuan-gguf", "filename_in_repo": "fast-hunyuan-video-t2v-720p-Q5_K_M.gguf", "save_filename": "FAST_HunYuan_Text_to_Video_GGUF_Q5_K_M.gguf"},
                    {"name": "FAST HunYuan T2V 720p GGUF Q4_K_M", "repo_id": "city96/FastHunyuan-gguf", "filename_in_repo": "fast-hunyuan-video-t2v-720p-Q4_K_M.gguf", "save_filename": "FAST_HunYuan_Text_to_Video_GGUF_Q4_K_M.gguf"},
                ]
            },
             "SkyReels HunYuan Models": {
                "info": ("SkyReels fine-tuned Hunyuan models. GGUF Quality: Q8 > Q6 > Q5 > Q4 (K_M > K_S > K > 1 > 0).\n\n"
                         "**Extremely Important How To Use Parameters and Guide:** [SkyReels Text2Video Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#skyreels-text2video)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "SkyReels HunYuan T2V 720p BF16", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels_hunyuan_t2v_bf16.safetensors", "save_filename": "SkyReels_Text_to_Video.safetensors"},
                    {"name": "SkyReels HunYuan I2V 720p BF16", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels_hunyuan_i2v_bf16.safetensors", "save_filename": "SkyReels_Image_to_Video.safetensors"},
                    {"name": "SkyReels HunYuan T2V 720p FP8", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels_hunyuan_t2v_fp8_e4m3fn.safetensors", "save_filename": "SkyReels_Text_to_Video_FP8.safetensors"},
                    {"name": "SkyReels HunYuan I2V 720p FP8", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels_hunyuan_i2v_fp8_e4m3fn.safetensors", "save_filename": "SkyReels_Image_to_Video_FP8.safetensors"},
                    {"name": "SkyReels HunYuan I2V 720p GGUF Q8", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels-hunyuan-I2V-Q8_0.gguf", "save_filename": "SkyReels_Image_to_Video_GGUF_Q8.gguf"},
                    {"name": "SkyReels HunYuan I2V 720p GGUF Q6_K", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels-hunyuan-I2V-Q6_K.gguf", "save_filename": "SkyReels_Image_to_Video_GGUF_Q6_K.gguf"},
                    {"name": "SkyReels HunYuan I2V 720p GGUF Q5_K_M", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels-hunyuan-I2V-Q5_K_M.gguf", "save_filename": "SkyReels_Image_to_Video_GGUF_Q5_K_M.gguf"},
                    {"name": "SkyReels HunYuan I2V 720p GGUF Q4_K_S", "repo_id": "Kijai/SkyReels-V1-Hunyuan_comfy", "filename_in_repo": "skyreels-hunyuan-I2V-Q4_K_S.gguf", "save_filename": "SkyReels_Image_to_Video_GGUF_Q4_K_S.gguf"},
                ]
            },
            "Genmo Mochi 1 Models": {
                "info": ("Preview release of Genmo Mochi 1 text-to-video model.\n\n"
                         "**Extremely Important How To Use Parameters and Guide:** [Genmo Mochi 1 Text2Video Parameters](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#genmo-mochi-1-text2video)"),
                "target_dir_key": "diffusion_models",
                "models": [
                    {"name": "Genmo Mochi 1 Preview T2V BF16", "repo_id": "Comfy-Org/mochi_preview_repackaged", "filename_in_repo": "split_files/diffusion_models/mochi_preview_bf16.safetensors", "save_filename": "Genmo_Mochi_1_Text_to_Video.safetensors"},
                    {"name": "Genmo Mochi 1 Preview T2V FP8 Scaled", "repo_id": "Comfy-Org/mochi_preview_repackaged", "filename_in_repo": "split_files/diffusion_models/mochi_preview_fp8_scaled.safetensors", "save_filename": "Genmo_Mochi_1_Text_to_Video_FP8_Scaled.safetensors"},
                ]
            },
             "Lightricks LTX Video Models - Ultra Fast": {
                 "info": (f"Ultra-fast text-to-video and image-to-video models from Lightricks. "
                          f"The companion 'LTX VAE (BF16)' is listed below and also in the VAEs section; it's recommended for the 13B Dev models. "
                          f"{GGUF_QUALITY_INFO} (for GGUF variants)\n\n"
                          "**Extremely Important How To Use Parameters and Guide:** [LTX Video Installation/Usage](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#ltxv-install)"),
                 "target_dir_key": "diffusion_models", # Default for this sub-category (will be used by GGUFs)
                 "models": [
                    {"name": "LTX 2b T2V+I2V 768x512 v0.9.5", "repo_id": "Lightricks/LTX-Video", "filename_in_repo": "ltx-video-2b-v0.9.5.safetensors", "save_filename": "LTX_2b_V_0_9_5.safetensors", "target_dir_key": "Stable-Diffusion"},
                    {"name": "LTX 13B Dev T2V+I2V 0.9.7 (FP16/BF16)", "repo_id": "Lightricks/LTX-Video", "filename_in_repo": "ltxv-13b-0.9.7-dev.safetensors", "save_filename": "LTX_13B_Dev_V_0_9_7.safetensors", "target_dir_key": "Stable-Diffusion"},
                    {"name": "LTX 13B Dev T2V+I2V 0.9.7 FP8", "repo_id": "Lightricks/LTX-Video", "filename_in_repo": "ltxv-13b-0.9.7-dev-fp8.safetensors", "save_filename": "LTX_13B_Dev_V_0_9_7_FP8.safetensors", "target_dir_key": "Stable-Diffusion"},
                    # GGUF models will use the sub-category's default target_dir_key: "diffusion_models"
                    {"name": "LTX 13B Dev T2V+I2V 0.9.7 GGUF Q8_0", "repo_id": "wsbagnsv1/ltxv-13b-0.9.7-dev-GGUF", "filename_in_repo": "ltxv-13b-0.9.7-dev-Q8_0.gguf", "save_filename": "LTX_13B_Dev_V_0_9_7_GGUF_Q8_0.gguf"},
                    {"name": "LTX 13B Dev T2V+I2V 0.9.7 GGUF Q6_K", "repo_id": "wsbagnsv1/ltxv-13b-0.9.7-dev-GGUF", "filename_in_repo": "ltxv-13b-0.9.7-dev-Q6_K.gguf", "save_filename": "LTX_13B_Dev_V_0_9_7_GGUF_Q6_K.gguf"},
                    {"name": "LTX 13B Dev T2V+I2V 0.9.7 GGUF Q5_K_M", "repo_id": "wsbagnsv1/ltxv-13b-0.9.7-dev-GGUF", "filename_in_repo": "ltxv-13b-0.9.7-dev-Q5_K_M.gguf", "save_filename": "LTX_13B_Dev_V_0_9_7_GGUF_Q5_K_M.gguf"},
                    {"name": "LTX 13B Dev T2V+I2V 0.9.7 GGUF Q4_K_M", "repo_id": "wsbagnsv1/ltxv-13b-0.9.7-dev-GGUF", "filename_in_repo": "ltxv-13b-0.9.7-dev-Q4_K_M.gguf", "save_filename": "LTX_13B_Dev_V_0_9_7_GGUF_Q4_K_M.gguf"},
                    ltx_vae_companion_entry, # This entry has its own target_dir_key: "vae"
                 ]
             },
        }
    },
    "LoRA Models": {
        "info": "Readme for Wan 2.1 CausVid LoRA to Speed Up : [LoRA Models](https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Video%20Model%20Support.md#wan-causvid---high-speed-14b)",
        "sub_categories": {
            "Wan 2.1 LoRAs": {
                "info": "Wan 2.1 LoRA models for enhanced performance and specialized use cases. See SwarmUI Video Docs for usage details on CFG, Steps, FPS, and Trim Video Start Frames.",
                "target_dir_key": "Lora",
                "models": [
                    wan_causvid_14b_lora_v2_entry,
                    wan_causvid_14b_lora_entry,
                    wan_causvid_1_3b_lora_entry,
                    {"name": "Phantom Wan 14B FusionX LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Phantom_Wan_14B_FusionX_LoRA.safetensors", "save_filename": "Phantom_Wan_14B_FusionX_LoRA.safetensors", "target_dir_key": "Lora", "info": "Phantom FusionX LoRA for Wan 2.1 14B models. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    {"name": "Wan 2.1 I2V 14B FusionX LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.1_Image_to_Video_14B_FusionX_LoRA.safetensors", "save_filename": "Wan2.1_Image_to_Video_14B_FusionX_LoRA.safetensors", "target_dir_key": "Lora", "info": "FusionX I2V LoRA for Wan 2.1 14B models. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    {"name": "Wan 2.1 T2V 14B FusionX LoRA", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "Wan2.1_Text_to_Video_14B_FusionX_LoRA.safetensors", "save_filename": "Wan2.1_Text_to_Video_14B_FusionX_LoRA.safetensors", "target_dir_key": "Lora", "info": "FusionX T2V LoRA for Wan 2.1 14B models. Saves to Lora folder. See SwarmUI Video Docs for usage details."},
                    wan_self_forcing_lora_entry,
                    wan_lightx2v_lora_entry,
                ]
            },
            "Various LoRAs": {
                "info": "A collection of LoRA models.",
                "target_dir_key": "Lora",
                "models": [
                    {"name": "Migration LoRA Cloth (TTPlanet)", "repo_id": "TTPlanet/Migration_Lora_flux", "filename_in_repo": "Migration_Lora_cloth.safetensors", "save_filename": "Migration_Lora_cloth.safetensors"},
                    {"name": "Figures TTP Migration LoRA (TTPlanet)", "repo_id": "TTPlanet/Migration_Lora_flux", "filename_in_repo": "figures_TTP_Migration.safetensors", "save_filename": "figures_TTP_Migration.safetensors"},
                ]
            }
        }
    },
    "ControlNet Models": {
        "info": "ControlNets",
        "sub_categories": {
            "Various ControlNets": {
                "info": "A collection of ControlNet models.",
                "target_dir_key": "controlnet",
                "models": [
                    wan_uni3c_controlnet_lora_entry,                    
                ]
            }
        }
    },
    "LLM Models": {
        "info": "Large Language Models (LLMs) used for various purposes, such as advanced text encoders or other functionalities.",
        "sub_categories": {
            "General LLMs": {
                "info": "Full LLM model repositories.",
                "target_dir_key": "LLM", # General target for this sub_category
                "models": [
                    {"name": "Meta-Llama-3.1-8B-Instruct (Full Repo)", "repo_id": "unsloth/Meta-Llama-3.1-8B-Instruct", "is_snapshot": True, "target_dir_key": "LLM_unsloth_llama"}
                ]
            }
        }
    },
    "VAE Models": {
        "info": "Variational Autoencoder models, used to improve image quality and details.",
        "sub_categories": {
            "Most Common VAEs (e.g. FLUX and HiDream-I1)": {
                "info": "VAEs commonly used with various models like FLUX and HiDream.",
                "target_dir_key": "vae", # Correct target directory
                "models": [
                    {"name": FLUX_AE_DEFAULT_NAME, "repo_id": "MonsterMMORPG/Kohya_Train", "filename_in_repo": "ae.safetensors", "save_filename": "Flux/ae.safetensors"},
                    ltx_vae_companion_entry, # Added the VAE companion here
                    wan_vae_entry,
                    {"name": "Wan 2.2 VAE", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "wan2.2_vae.safetensors", "save_filename": "Wan/wan2.2_vae.safetensors", "target_dir_key": "vae"},
                    {"name": "qwen_image_vae.safetensors", "repo_id": "MonsterMMORPG/Wan_GGUF", "filename_in_repo": "qwen_image_vae.safetensors", "save_filename": "QwenImage/qwen_image_vae.safetensors"},
                ]
            },
        }
    },
    "Clip Vision Models": {
        "info": "Vision encoder models, e.g., for image understanding or as part of larger multi-modal systems.",
        "sub_categories": {
            "Standard Clip Vision Models": {
                "info": "Standard CLIP vision encoders used by various models including Wan 2.1.",
                "target_dir_key": "clip_vision",
                "models": [
                    {
                        "name": "CLIP Vision H (Used by Wan 2.1)",
                        "repo_id": "MonsterMMORPG/Wan_GGUF",
                        "filename_in_repo": "clip_vision_h.safetensors",
                        "save_filename": "clip_vision_h.safetensors"
                    }
                ]
            },
            "SigLIP Vision Models": {
                "info": "Sigmoid-Loss for Language-Image Pre-Training (SigLIP) vision encoders. These are typically used by specific model architectures that require them.",
                "target_dir_key": "clip_vision",
                "models": [
                    {
                        "name": "SigLIP Vision Patch14 384px",
                        "repo_id": "Comfy-Org/sigclip_vision_384",
                        "filename_in_repo": "sigclip_vision_patch14_384.safetensors",
                        "save_filename": "sigclip_vision_patch14_384.safetensors"
                    },
                    {
                        "name": "SigLIP SO400M Patch14 384px (Full Repo)",
                        "repo_id": "google/siglip-so400m-patch14-384",
                        "is_snapshot": True,
                        "target_dir_key": "clip_vision_google_siglip"
                    }
                ]
            }
        }
    },
    "ComfyUI Workflows": {
        "info": "Downloadable ComfyUI workflow JSON files or related assets.",
        "sub_categories": {
            "Captioning Workflows": {
                "info": "Workflows and assets related to image captioning.",
                "target_dir_key": "Joy_caption", # General target for this sub_category
                "models": [
                    {"name": "Joy Caption Alpha Two (Full Repo)", "repo_id": "MonsterMMORPG/joy-caption-alpha-two", "is_snapshot": True, "target_dir_key": "Joy_caption_monster_joy"}
                ]
            }
        }
    },

}

__all__ = [
    "models_structure",
    "HIDREAM_INFO_LINK",
    "GGUF_QUALITY_INFO",
    # Z Image Turbo entries
    "z_image_turbo_bf16_entry",
    "z_image_turbo_fp8_scaled_entry",
    "qwen_3_4b_text_encoder_entry",
    "z_image_turbo_controlnet_union_entry",
]