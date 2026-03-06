#!/usr/bin/env python3
"""
caption_openrouter.py

OpenRouter Auto-Captioner for LoRA Training
===========================================
Captions images and/or videos in dataset folders using an OpenRouter multimodal model.
Outputs .txt files alongside each file with LoRA-optimized captions.

Environment:
  OPENROUTER_API_KEY   Required

Examples:
  python caption_openrouter.py --images --images-dir datasets/annika/images
  python caption_openrouter.py --videos --videos-dir datasets/annika/videos
  python caption_openrouter.py \
    --images --videos \
    --images-dir datasets/annika/images \
    --videos-dir datasets/annika/videos \
    --trigger-word "annika" \
    --model "google/gemini-2.0-flash-001"

  # Override only IMAGE_USER_PROMPT:
  python caption_openrouter.py \
    --images --images-dir datasets/annika/images \
    --prompts ./new-image-user-prompt.txt

Dependencies:
  None beyond the Python standard library.
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# =============================================================================
# Defaults / examples
# =============================================================================

# Dataset folder examples (not auto-used unless you pass them)
IMAGES_DIR = r"datasets\annika\images"
VIDEOS_DIR = r"datasets\annika\videos"

# Default trigger word
CHARACTER_NAME = "ohwx woman"

# Default OpenRouter model
GEMINI_MODEL = "google/gemini-2.0-flash-001"

# Skip files that already have a .txt caption file next to them
SKIP_EXISTING = True

# OpenRouter API
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# Optional attribution headers
HTTP_REFERER = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
X_TITLE = os.environ.get("OPENROUTER_X_TITLE", "caption_openrouter.py").strip()

# File extensions to process
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}

# =============================================================================
# Prompt templates
# =============================================================================

SYSTEM_PROMPT_BASE = """You are a captioning assistant for AI model training data. Your captions must follow a strict format.

RULES:
1. Every caption starts with "{CHARACTER_NAME}" followed by what they are doing
2. Include the camera view: "full body view", "medium shot", "close up", "upper body view", etc.
3. Include the camera angle: "straight on", "from above", "from below", "from the side", "three quarter view", etc.
4. After the initial line, describe ONLY:
   - Specific movements or poses (arms raised, head tilted, stepping forward)
   - Facial expressions (smiling, frowning, looking surprised)
   - Hair or accessory motion/position (hair blowing, scarf draped)
   - Emotions or states (laughing, shouting, looking pensive)
   - Environmental interaction (picking up an object, leaning on a wall)
5. Do NOT describe the character's physical appearance, clothing colors, body type, or features
6. Do NOT describe the background or setting unless the character directly interacts with it
7. Keep the caption to 1-3 sentences maximum
8. Use simple, direct language — no flowery prose
9. Write as a single continuous caption, not a list

EXAMPLES OF GOOD CAPTIONS:
"{CHARACTER_NAME} walking forward in a full body view, straight on, arms swinging naturally with a slight bounce in their step"
"{CHARACTER_NAME} sitting and turning to look over their shoulder in a medium shot, three quarter view, expression shifting from neutral to surprised"
"{CHARACTER_NAME} jumping and landing in a full body view, from the side, hair bouncing on impact with arms spread for balance"

EXAMPLES OF BAD CAPTIONS (do not do this):
"{CHARACTER_NAME} is a red character with blocky features wearing a green hat, walking through a forest" (describes appearance + setting)
"{CHARACTER_NAME}, a voxel-style figure, stands in a colorful meadow" (describes art style + setting)"""

VIDEO_USER_PROMPT = """Caption this video following the rules exactly. Focus on the motion and actions happening over time. Output ONLY the caption text, nothing else — no quotes, no labels, no explanation."""

IMAGE_USER_PROMPT = """Caption this image following the rules exactly. Describe the pose, framing, and any expression or gesture. Output ONLY the caption text, nothing else — no quotes, no labels, no explanation."""

PROMPT_VARIABLES = {
    "SYSTEM_PROMPT_BASE",
    "VIDEO_USER_PROMPT",
    "IMAGE_USER_PROMPT",
}

# =============================================================================
# Helpers
# =============================================================================


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Caption images/videos using OpenRouter multimodal models."
    )

    parser.add_argument(
        "--images",
        action="store_true",
        help="Process images.",
    )
    parser.add_argument(
        "--videos",
        action="store_true",
        help="Process videos.",
    )
    parser.add_argument(
        "--images-dir",
        default=None,
        help=f"Images directory. Required if --images is set. Example default: {IMAGES_DIR}",
    )
    parser.add_argument(
        "--videos-dir",
        default=None,
        help=f"Videos directory. Required if --videos is set. Example default: {VIDEOS_DIR}",
    )
    parser.add_argument(
        "--trigger-word",
        default=CHARACTER_NAME,
        help=f'Trigger word to prepend/enforce in captions. Default: "{CHARACTER_NAME}"',
    )
    parser.add_argument(
        "--model",
        default=GEMINI_MODEL,
        help=f'OpenRouter model name. Default: "{GEMINI_MODEL}"',
    )
    parser.add_argument(
        "--prompts",
        default=None,
        help="Path to a file containing prompt variable overrides.",
    )

    # Python 3.9+
    try:
        bool_action = argparse.BooleanOptionalAction
        parser.add_argument(
            "--skip-existing",
            default=SKIP_EXISTING,
            action=bool_action,
            help="Skip files that already have a .txt caption file next to them (default: true).",
        )
    except AttributeError:
        # Fallback for older Python
        parser.add_argument(
            "--skip-existing",
            dest="skip_existing",
            action="store_true",
            default=SKIP_EXISTING,
            help="Skip files that already have a .txt caption file next to them (default: true).",
        )
        parser.add_argument(
            "--no-skip-existing",
            dest="skip_existing",
            action="store_false",
            help="Do not skip files that already have a .txt caption file next to them.",
        )

    return parser.parse_args()


def load_prompt_overrides(path: str | None) -> Dict[str, str]:
    """
    Load only prompt variables explicitly assigned in a Python-like file, e.g.:

        IMAGE_USER_PROMPT = \"\"\"...\"\"\"

    Only the following variables are honored:
      - SYSTEM_PROMPT_BASE
      - VIDEO_USER_PROMPT
      - IMAGE_USER_PROMPT
    """
    if not path:
        return {}

    prompt_path = Path(path)
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt override file not found: {prompt_path}")

    source = prompt_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(prompt_path))

    overrides: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue

        var_name = node.targets[0].id
        if var_name not in PROMPT_VARIABLES:
            continue

        try:
            value = ast.literal_eval(node.value)
        except Exception as exc:
            raise ValueError(
                f"Could not parse value for {var_name} in {prompt_path}: {exc}"
            ) from exc

        if not isinstance(value, str):
            raise TypeError(f"{var_name} in {prompt_path} must be a string.")

        overrides[var_name] = value

    return overrides


def build_prompts(trigger_word: str, prompt_file: str | None) -> Dict[str, str]:
    prompts = {
        "SYSTEM_PROMPT_BASE": SYSTEM_PROMPT_BASE,
        "VIDEO_USER_PROMPT": VIDEO_USER_PROMPT,
        "IMAGE_USER_PROMPT": IMAGE_USER_PROMPT,
    }
    prompts.update(load_prompt_overrides(prompt_file))

    # Format only SYSTEM_PROMPT_BASE with the trigger word.
    prompts["SYSTEM_PROMPT_BASE"] = prompts["SYSTEM_PROMPT_BASE"].replace(
        "{CHARACTER_NAME}", trigger_word
    )
    return prompts


def validate_api_key() -> None:
    if not OPENROUTER_API_KEY:
        eprint("ERROR: OPENROUTER_API_KEY is not set.")
        eprint()
        eprint("Set it in your shell, for example:")
        eprint('  export OPENROUTER_API_KEY="your-key-here"')
        sys.exit(1)


def find_supported_files(directory: Path, suffixes: set[str]) -> List[Path]:
    return [
        f for f in sorted(directory.iterdir())
        if f.is_file() and f.suffix.lower() in suffixes
    ]


def validate_args(args: argparse.Namespace) -> Tuple[List[Path], List[Path]]:
    if not args.images and not args.videos:
        eprint("ERROR: You must set at least one of --images or --videos.")
        sys.exit(1)

    image_files: List[Path] = []
    video_files: List[Path] = []

    if args.images:
        if not args.images_dir:
            eprint("ERROR: --images-dir is required when --images is set.")
            sys.exit(1)

        img_dir = Path(args.images_dir)
        if not img_dir.is_dir():
            eprint(f"ERROR: Images directory does not exist: {img_dir}")
            sys.exit(1)

        image_files = find_supported_files(img_dir, IMAGE_EXTENSIONS)
        if not image_files:
            eprint(f"ERROR: No supported images found in: {img_dir}")
            eprint(f"Supported image types: {', '.join(sorted(IMAGE_EXTENSIONS))}")
            sys.exit(1)

    if args.videos:
        if not args.videos_dir:
            eprint("ERROR: --videos-dir is required when --videos is set.")
            sys.exit(1)

        vid_dir = Path(args.videos_dir)
        if not vid_dir.is_dir():
            eprint(f"ERROR: Videos directory does not exist: {vid_dir}")
            sys.exit(1)

        video_files = find_supported_files(vid_dir, VIDEO_EXTENSIONS)
        if not video_files:
            eprint(f"ERROR: No supported videos found in: {vid_dir}")
            eprint(f"Supported video types: {', '.join(sorted(VIDEO_EXTENSIONS))}")
            sys.exit(1)

    return image_files, video_files


def guess_mime_type(path: Path, fallback: str) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or fallback


def file_to_data_url(path: Path, fallback_mime: str) -> str:
    mime_type = guess_mime_type(path, fallback=fallback_mime)
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def extract_text_from_openrouter_response(payload: dict) -> str:
    """
    Tries the standard OpenAI-compatible response shape first:
      choices[0].message.content

    content may be:
      - a string
      - a list of blocks
    """
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"No choices in response: {json.dumps(payload)[:1000]}")

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Common normalized text block
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        text_out = "\n".join(part.strip() for part in parts if part.strip()).strip()
        if text_out:
            return text_out

    raise RuntimeError(
        f"Could not extract text content from response: {json.dumps(payload)[:1000]}"
    )


def openrouter_chat_completion(
    *,
    model: str,
    system_prompt: str,
    user_content: list,
    timeout: int = 180,
) -> str:
    url = f"{OPENROUTER_BASE_URL}/chat/completions"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }

    req = urllib.request.Request(
        url=url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            **({"HTTP-Referer": HTTP_REFERER} if HTTP_REFERER else {}),
            **({"X-Title": X_TITLE} if X_TITLE else {}),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw)
            return extract_text_from_openrouter_response(payload)

    except urllib.error.HTTPError as exc:
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {body_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc}") from exc


def caption_image(model: str, image_path: Path, prompts: Dict[str, str]) -> str:
    image_data_url = file_to_data_url(image_path, fallback_mime="image/png")
    user_content = [
        {"type": "text", "text": prompts["IMAGE_USER_PROMPT"]},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]
    return openrouter_chat_completion(
        model=model,
        system_prompt=prompts["SYSTEM_PROMPT_BASE"],
        user_content=user_content,
        timeout=120,
    )


def caption_video(model: str, video_path: Path, prompts: Dict[str, str]) -> str:
    video_data_url = file_to_data_url(video_path, fallback_mime="video/mp4")
    user_content = [
        {"type": "text", "text": prompts["VIDEO_USER_PROMPT"]},
        {"type": "video_url", "video_url": {"url": video_data_url}},
    ]
    return openrouter_chat_completion(
        model=model,
        system_prompt=prompts["SYSTEM_PROMPT_BASE"],
        user_content=user_content,
        timeout=300,
    )


def clean_caption(caption: str, trigger_word: str) -> str:
    caption = caption.strip()

    # Remove wrapping quotes once
    if len(caption) >= 2 and caption[0] == caption[-1] and caption[0] in {'"', "'"}:
        caption = caption[1:-1].strip()

    # Collapse whitespace
    caption = " ".join(caption.split())

    # Ensure it starts with the trigger word
    if not caption.lower().startswith(trigger_word.lower()):
        print(f"  WARNING: Caption missing trigger word, prepending '{trigger_word}'")
        caption = f"{trigger_word} {caption}"

    return caption


def should_retry(error_text: str) -> bool:
    lower = error_text.lower()
    retry_markers = [
        "429",
        "rate limit",
        "temporarily unavailable",
        "timeout",
        "timed out",
        "overloaded",
        "provider returned error",
        "502",
        "503",
        "504",
    ]
    return any(marker in lower for marker in retry_markers)


def iter_files(
    image_files: Iterable[Path],
    video_files: Iterable[Path],
) -> List[Tuple[str, Path]]:
    out: List[Tuple[str, Path]] = []
    out.extend(("image", p) for p in image_files)
    out.extend(("video", p) for p in video_files)
    return out


def main() -> None:
    args = parse_args()
    validate_api_key()

    image_files, video_files = validate_args(args)
    prompts = build_prompts(args.trigger_word, args.prompts)

    if args.trigger_word == CHARACTER_NAME:
        print(
            f'WARNING: Using default trigger word "{CHARACTER_NAME}". '
            "Set --trigger-word if that is not what you want."
        )

    all_files = iter_files(image_files, video_files)

    if args.skip_existing:
        to_process = [(t, f) for t, f in all_files if not f.with_suffix(".txt").exists()]
        skipped = len(all_files) - len(to_process)
        if skipped > 0:
            print(f"Skipping {skipped} already-captioned files")
    else:
        to_process = all_files
        skipped = 0

    if not to_process:
        print("Nothing to do.")
        print("All selected files already have .txt captions." if args.skip_existing else "No eligible files found.")
        sys.exit(0)

    n_images = sum(1 for t, _ in to_process if t == "image")
    n_videos = sum(1 for t, _ in to_process if t == "video")

    print(f"To caption: {n_images} images + {n_videos} videos = {len(to_process)} total")
    print(f"Trigger word: {args.trigger_word}")
    print(f"Model: {args.model}")
    print(f"Skip existing: {args.skip_existing}")
    if args.images:
        print(f"Images dir: {args.images_dir}")
    if args.videos:
        print(f"Videos dir: {args.videos_dir}")
    if args.prompts:
        print(f"Prompt overrides: {args.prompts}")
    print("-" * 60)

    success = 0
    failed = 0

    for i, (file_type, file_path) in enumerate(to_process, 1):
        caption_path = file_path.with_suffix(".txt")
        label = "IMG" if file_type == "image" else "VID"
        print(f"\n[{i}/{len(to_process)}] [{label}] {file_path.name}")

        max_retries = 5
        for attempt in range(max_retries):
            try:
                if file_type == "image":
                    print("  Captioning image...", end=" ", flush=True)
                    caption = caption_image(args.model, file_path, prompts)
                else:
                    print("  Captioning video...", end=" ", flush=True)
                    caption = caption_video(args.model, file_path, prompts)

                caption = clean_caption(caption, args.trigger_word)
                caption_path.write_text(caption + "\n", encoding="utf-8")

                print("done.")
                print(f"  → {caption[:140]}{'...' if len(caption) > 140 else ''}")
                success += 1

                # Small pacing delay
                if i < len(to_process):
                    time.sleep(2)

                break

            except Exception as exc:
                error_str = str(exc)
                if should_retry(error_str) and attempt < max_retries - 1:
                    wait_time = 15 * (attempt + 1)
                    print(
                        f"\n  Retryable error: {error_str[:220]}"
                        f"\n  Waiting {wait_time}s before retry {attempt + 2}/{max_retries}..."
                    )
                    time.sleep(wait_time)
                    continue

                print(f"\n  ERROR: {error_str}")
                failed += 1
                break

    print("\n" + "=" * 60)
    print(f"Done! {success} captioned, {failed} failed, {skipped} skipped")
    if args.images:
        print(f"Image captions in: {args.images_dir}")
    if args.videos:
        print(f"Video captions in: {args.videos_dir}")


if __name__ == "__main__":
    main()
    