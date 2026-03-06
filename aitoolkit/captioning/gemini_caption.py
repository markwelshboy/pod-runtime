#!/usr/bin/env python3
"""
OpenRouter (Gemini Flash) Auto-Captioner for WAN Character LoRA — IMAGES ONLY
============================================================================

Goal:
- Generate short, consistent captions for a WAN character LoRA.
- Light on pose/geometry (you can add pose tokens manually where needed).
- Strong on controllable variables you WANT to toggle later (e.g., glasses/hat/nail polish) IF visible.
- Optional dataset-level "repeated background" tagging via clustering + a human-edited labels file.

How it works:
1) For each image (one API call per image):
   - Ask Gemini for a short caption starting with "{CHARACTER_NAME} woman ..."
   - Focus mainly on facial expression (esp. smile types) and optional accessories if visible.
2) Clean/normalize the caption (remove labels, clamp whitespace, normalize "smiling expression" -> "smile", etc.)
3) Background clustering (border-hash) detects repeated backdrops.
   - If a cluster has >= MIN_CLUSTER_SIZE images, you can label it in background_labels.json
   - Script appends that label to captions for images in that cluster.

Install:
  python -m pip install requests Pillow

Set API key (PowerShell):
  $env:OPENROUTER_API_KEY="YOUR_KEY"

Run:
  python caption_openrouter_images_wanchar.py
"""

import os
import sys
import time
import json
import base64
import mimetypes
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

import requests
from PIL import Image

# =============================================================================
# CONFIG — EDIT THESE
# =============================================================================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "INSERT_YOUR_OPENROUTER_API_KEY_HERE")

#IMAGES_DIR = r"/workspace/trainingimages/1024x1024"  # <-- Your images folder
IMAGES_DIR = r"/workspace/trainingimages"  # <-- Your images folder
CHARACTER_NAME = "5H1V"                 # <-- change

# OpenRouter model id (Gemini Flash 2.0)
MODEL = "google/gemini-2.0-flash-001"

# Skip images that already have a .txt caption file
SKIP_EXISTING = False

# File extensions to process
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# Request/retry knobs
MAX_RETRIES = 5
SLEEP_BETWEEN_REQUESTS_SEC = 0.5
TEMPERATURE = 0.25
TIMEOUT_SEC = 120

# Background clustering knobs
ENABLE_BACKGROUND_CLUSTERING = True
MIN_CLUSTER_SIZE = 6          # only clusters with >= this size are considered "repeated"
BORDER_PCT = 0.14             # how much of the border to treat as background proxy (portraits: 0.10–0.18)
MAX_HAMMING_DIST = 8          # clustering tolerance for dhash; 6–10 typical

# Background labels file (you edit this)
BACKGROUND_LABELS_JSON = "background_labels.json"  # saved in IMAGES_DIR

# Optional OpenRouter attribution headers
OPENROUTER_HTTP_REFERER = os.environ.get("OPENROUTER_HTTP_REFERER", "")
OPENROUTER_APP_TITLE = os.environ.get("OPENROUTER_APP_TITLE", "captionator")

SYSTEM_PROMPT = f"""
You generate short captions for a WAN character LoRA training dataset.

Hard requirements:
- Output ONLY the caption text (no quotes, no labels).
- Exactly ONE sentence, 15–40 words.
- Must start with "{CHARACTER_NAME} woman".
- Must include EXACTLY ONE facial expression term from this list:
  neutral expression, closed-mouth smile, slight smile, soft smile, beaming smile, broad smile, toothy smile, laughing, shocked, relaxed, content, angry, sad (No order implied, pick the most appropriate)
- Must include additional detail from the allowed lists below.

Allowed additional detail:
A) Gesture/pose: head tilted slightly to the left/right, hand on/touching/resting on [insert body part], arms relaxed at sides, fingers on/touching/resting on [insert body part], hand on breast etc. (These are just examples, no order implied)
B) Hair position (no color): hair tucked behind one ear, hair over one shoulder, hair pulled back, hair parted on left/right, messy hair, damp/wet hair (also allowable is a short mix of these - messy hair parted on the left for example)
C) Accessory: wearing glasses/sunglasses, wearing earrings, earing visible on left/right ear (if visible), wearing a necklace, wearing a hat, wearing a scarf etc. (These are just examples, no order implied)
D) Prop: holding a phone, holding a cup, etc. (These are just examples, no order implied)

Select 2–3 details total, choosing what is most visually salient.

Salience priority for gesture/hair/accessories/props:
prop in hand(s) > glasses > hat/scarf > large jewelry (exclude wedding/engagement rings) > hair position/style > makeup/nail polish.
Only mention hair position/style if no higher-priority item is clearly visible.

Do NOT describe:
- identity traits or physical appearance (hair color, eye color, skin tone, facial features, body shape)
- clothing colors
- background/setting unless directly interacted with
- camera view/angle/framing terms

Never output the phrase "smiling expression".
""".strip()

USER_PROMPT = "Caption this image."

# =============================================================================
# VALIDATION / FILE COLLECTION
# =============================================================================

def die(msg: str, code: int = 1):
    print(msg)
    sys.exit(code)

def validate_config():
    if "INSERT" in OPENROUTER_API_KEY:
        die("ERROR: OPENROUTER_API_KEY not set.\nPowerShell: $env:OPENROUTER_API_KEY=\"your-key-here\"")

    if not IMAGES_DIR or not os.path.isdir(IMAGES_DIR):
        die(f"ERROR: IMAGES_DIR not found: {IMAGES_DIR}")

def collect_images() -> List[Path]:
    img_dir = Path(IMAGES_DIR)
    return [p for p in sorted(img_dir.iterdir()) if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]

# =============================================================================
# OPENROUTER API (image -> data URL)
# =============================================================================

def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"

def file_to_data_url(path: Path) -> str:
    mime = guess_mime(path)
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def openrouter_chat(messages, temperature=TEMPERATURE, timeout=TIMEOUT_SEC) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if OPENROUTER_HTTP_REFERER:
        headers["HTTP-Referer"] = OPENROUTER_HTTP_REFERER
    if OPENROUTER_APP_TITLE:
        headers["X-OpenRouter-Title"] = OPENROUTER_APP_TITLE

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:400]}")

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

def caption_image(image_path: Path) -> str:
    image_url = file_to_data_url(image_path)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": USER_PROMPT},
            ],
        },
    ]
    return openrouter_chat(messages)

# =============================================================================
# CAPTION CLEAN / NORMALIZE
# =============================================================================

LABEL_PREFIX_RE = re.compile(r"^\s*(sentence\s*\d+\s*:\s*|shot\s*:\s*|action\s*:\s*|setting\s*:\s*)", re.I)

def normalize_caption(caption: str, character_name: str) -> str:
    """
    Make captions consistent and dataset-friendly.
    - strip quotes / labels
    - collapse whitespace
    - normalize awkward phrasing ("smiling expression" -> "smile")
    - enforce "{CHAR} woman" prefix
    - force single sentence (rudimentary) by removing extra sentence terminators
    """
    c = caption.strip()

    # Remove wrapping quotes
    if (c.startswith('"') and c.endswith('"')) or (c.startswith("'") and c.endswith("'")):
        c = c[1:-1].strip()

    # Remove leading label prefixes repeatedly if present
    for _ in range(3):
        c2 = LABEL_PREFIX_RE.sub("", c).strip()
        if c2 == c:
            break
        c = c2

    # Collapse whitespace/newlines
    c = " ".join(c.split())

    # Normalize "smiling expression" variants
    c = re.sub(r"\bwith a smiling expression\b", "with a smile", c, flags=re.I)
    c = re.sub(r"\bwith an? smiling expression\b", "with a smile", c, flags=re.I)
    c = re.sub(r"\bsmiling expression\b", "smile", c, flags=re.I)

    # Enforce prefix "{CHAR} woman"
    prefix = f"{character_name} woman"
    if not c.lower().startswith(prefix.lower()):
        # If it starts with the character only, insert "woman"
        if c.lower().startswith(character_name.lower()):
            rest = c[len(character_name):].lstrip(" ,")
            c = f"{character_name} woman {rest}".strip()
        else:
            c = f"{character_name} woman {c}".strip()

    # Force exactly one sentence-ish:
    # If model produced multiple sentences, merge them with commas (keeps it one sentence).
    parts = re.split(r"[.!?]+\s*", c)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        c = ", ".join(parts)

    # Ensure final period
    if c and c[-1] not in ".!?":
        c += "."

    return c

# =============================================================================
# BACKGROUND CLUSTERING (brick-wall trick)
# =============================================================================

def dhash_hex(img: Image.Image, hash_size: int = 8) -> str:
    img = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    diff_bits = []
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            diff_bits.append(1 if left > right else 0)
    value = 0
    for bit in diff_bits:
        value = (value << 1) | bit
    width = (hash_size * hash_size + 3) // 4
    return f"{value:0{width}x}"

def hamming_hex(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()

def background_signature(image_path: Path, border_pct: float = BORDER_PCT) -> str:
    """
    Hash the top+bottom border strips as a proxy for background.
    Works best for portraits/headshots where borders contain background.
    """
    im = Image.open(image_path).convert("RGB")
    w, h = im.size
    by = max(1, int(h * border_pct))

    top = im.crop((0, 0, w, by))
    bottom = im.crop((0, h - by, w, h))

    tb = Image.new("RGB", (w, by * 2))
    tb.paste(top, (0, 0))
    tb.paste(bottom, (0, by))

    return dhash_hex(tb, hash_size=8)

def cluster_backgrounds(image_paths: List[Path],
                        max_dist: int = MAX_HAMMING_DIST,
                        min_cluster_size: int = MIN_CLUSTER_SIZE) -> Tuple[Dict[Path, int], Dict[int, List[Path]]]:
    sigs = {p: background_signature(p) for p in image_paths}

    # greedy clusters: cluster_id -> {"rep": signature, "items": [paths]}
    clusters: Dict[int, Dict[str, object]] = {}
    img_to_cluster: Dict[Path, int] = {}
    next_id = 1

    for p in image_paths:
        s = sigs[p]
        assigned = None
        for cid, c in clusters.items():
            rep = c["rep"]  # type: ignore[assignment]
            if hamming_hex(s, rep) <= max_dist:
                assigned = cid
                c["items"].append(p)  # type: ignore[index]
                break
        if assigned is None:
            clusters[next_id] = {"rep": s, "items": [p]}
            assigned = next_id
            next_id += 1
        img_to_cluster[p] = assigned

    repeated = {cid: c["items"] for cid, c in clusters.items() if len(c["items"]) >= min_cluster_size}  # type: ignore[index]
    return img_to_cluster, repeated

def load_background_labels(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_background_labels(path: Path, labels: Dict[str, str]) -> None:
    path.write_text(json.dumps(labels, indent=2), encoding="utf-8")

def append_background_label(caption: str, label: str) -> str:
    """
    Append a background clause as a weak tag.
    label should be like: "in front of a brick wall" / "against a textured wall"
    """
    lab = label.strip().strip(",").strip()
    if not lab:
        return caption

    c = caption.rstrip()
    if c.endswith("."):
        c = c[:-1]

    # Avoid double-adding if already present
    if lab.lower() in c.lower():
        return c + "."

    return f"{c}, {lab}."

# =============================================================================
# MAIN
# =============================================================================

def main():
    validate_config()

    images = collect_images()
    if not images:
        die(f"No images found in {IMAGES_DIR} (extensions: {', '.join(sorted(IMAGE_EXTENSIONS))})", code=0)

    # Filter already-captioned
    if SKIP_EXISTING:
        to_process = [p for p in images if not p.with_suffix(".txt").exists()]
        skipped = len(images) - len(to_process)
        if skipped:
            print(f"Skipping {skipped} already-captioned images")
    else:
        to_process = images

    # Background clustering setup
    img_to_cluster: Dict[Path, int] = {}
    repeated_clusters: Dict[int, List[Path]] = {}
    bg_labels: Dict[str, str] = {}

    labels_path = Path(IMAGES_DIR) / BACKGROUND_LABELS_JSON

    if ENABLE_BACKGROUND_CLUSTERING and images:
        print("\nBackground clustering (dataset-level):")
        img_to_cluster, repeated_clusters = cluster_backgrounds(images)

        if repeated_clusters:
            print("Repeated background clusters (size >= "
                  f"{MIN_CLUSTER_SIZE}):")
            for cid, items in sorted(repeated_clusters.items(), key=lambda x: -len(x[1])):
                print(f"  cluster {cid}: {len(items)} images")

            # Create starter labels file if missing
            if not labels_path.exists():
                starter = {str(cid): "" for cid in repeated_clusters.keys()}
                save_background_labels(labels_path, starter)
                print(f"\nCreated starter labels file: {labels_path}")
                print('Edit it to add labels, e.g. {"3": "in front of a brick wall"}')
                print("Re-run to apply labels.\n")

            bg_labels = load_background_labels(labels_path)
        else:
            print("No repeated background clusters detected.\n")

    print(f"To caption: {len(to_process)} images")
    print(f"Character: {CHARACTER_NAME}")
    print(f"Model: {MODEL}")
    print("-" * 60)

    success = 0
    failed = 0

    for i, img_path in enumerate(to_process, 1):
        caption_path = img_path.with_suffix(".txt")
        print(f"\n[{i}/{len(to_process)}] {img_path.name}")

        for attempt in range(MAX_RETRIES):
            try:
                print("  Captioning...", end=" ", flush=True)
                raw = caption_image(img_path)
                cap = normalize_caption(raw, CHARACTER_NAME)

                # Apply background label (if any)
                if ENABLE_BACKGROUND_CLUSTERING and repeated_clusters and bg_labels:
                    cid = img_to_cluster.get(img_path)
                    if cid is not None:
                        label = bg_labels.get(str(cid), "").strip()
                        if label:
                            cap = append_background_label(cap, label)

                caption_path.write_text(cap, encoding="utf-8")
                print("done.")
                print(f"  → {cap[:160]}{'...' if len(cap) > 160 else ''}")
                success += 1

                if i < len(to_process):
                    time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)
                break

            except Exception as e:
                msg = str(e)
                if "HTTP 429" in msg or "rate" in msg.lower() or "quota" in msg.lower():
                    wait = 5 * (attempt + 1)
                    print(f"\n  Rate limited. Waiting {wait}s... (attempt {attempt+1}/{MAX_RETRIES})")
                    time.sleep(wait)
                    if attempt == MAX_RETRIES - 1:
                        print("  FAILED after retries")
                        failed += 1
                else:
                    print(f"\n  ERROR: {e}")
                    failed += 1
                    break

    print("\n" + "=" * 60)
    print(f"Done! {success} captioned, {failed} failed, {len(images) - len(to_process)} skipped")
    print(f"Captions in: {IMAGES_DIR}")
    if ENABLE_BACKGROUND_CLUSTERING and repeated_clusters:
        print(f"Background labels file: {labels_path}")

if __name__ == "__main__":
    main()