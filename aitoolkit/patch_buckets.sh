#!/usr/bin/env bash
set -euo pipefail

DEFAULT_FILE="/app/ai-toolkit/toolkit/buckets.py"

usage() {
  cat <<EOF
Usage:
  $0 WIDTHxHEIGHT [-f /app/ai-toolkit/toolkit/buckets.py]

Examples:
  $0 720x1280
  $0 720x1280 -f /app/ai-toolkit/toolkit/buckets.py
EOF
  exit 1
}

[[ $# -lt 1 ]] && usage

RES=""
FILE="$DEFAULT_FILE"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)
      [[ $# -ge 2 ]] || usage
      FILE="$2"
      shift 2
      ;;
    -*)
      usage
      ;;
    *)
      if [[ -z "$RES" ]]; then
        RES="$1"
        shift
      else
        usage
      fi
      ;;
  esac
done

[[ -n "$RES" ]] || usage

if [[ ! "$RES" =~ ^([0-9]+)x([0-9]+)$ ]]; then
  echo "❌ Resolution must be WIDTHxHEIGHT, e.g. 720x1280" >&2
  exit 1
fi

WIDTH="${BASH_REMATCH[1]}"
HEIGHT="${BASH_REMATCH[2]}"

if (( WIDTH % 8 != 0 || HEIGHT % 8 != 0 )); then
  echo "❌ Width and height must both be divisible by 8" >&2
  exit 1
fi

if [[ ! -f "$FILE" ]]; then
  echo "❌ File not found: $FILE" >&2
  exit 1
fi

BACKUP="${FILE}.bak.$(date +%Y%m%d_%H%M%S)"
cp -a "$FILE" "$BACKUP"

python3 - "$FILE" "$WIDTH" "$HEIGHT" <<'PY'
import re
import sys
from pathlib import Path

file = Path(sys.argv[1])
w = int(sys.argv[2])
h = int(sys.argv[3])

text = file.read_text(encoding="utf-8")

entry_re = re.compile(r'\{\s*"width"\s*:\s*%d\s*,\s*"height"\s*:\s*%d\s*\}' % (w, h))
if entry_re.search(text):
    print(f"✅ Bucket already exists: {w}x{h}")
    sys.exit(0)

# Find the resolutions_1024 assignment line, not the List[...] type annotation.
m = re.search(r'(^\s*resolutions_1024\s*:[^=\n]*=\s*\[)', text, re.M)
if not m:
    print("❌ Could not find resolutions_1024 assignment")
    sys.exit(1)

list_start = m.end() - 1  # points at the '[' in '= ['

# Find the matching closing bracket for this list
depth = 0
list_end = None
for i in range(list_start, len(text)):
    ch = text[i]
    if ch == '[':
        depth += 1
    elif ch == ']':
        depth -= 1
        if depth == 0:
            list_end = i
            break

if list_end is None:
    print("❌ Could not find end of resolutions_1024 list")
    sys.exit(1)

entry = f'    {{"width": {w}, "height": {h}}},\n'

# Nice placement:
# 1) after same-orientation nearby anchor if present
# 2) otherwise before closing ]
portrait_anchor = '    {"width": 768, "height": 1280},\n'
landscape_anchor = '    {"width": 1280, "height": 768},\n'

inserted = False

if h > w and portrait_anchor in text:
    text = text.replace(portrait_anchor, portrait_anchor + entry, 1)
    inserted = True
elif w > h and landscape_anchor in text:
    text = text.replace(landscape_anchor, landscape_anchor + entry, 1)
    inserted = True

if not inserted:
    text = text[:list_end] + entry + text[list_end:]

file.write_text(text, encoding="utf-8")
print(f"✅ Inserted bucket: {w}x{h}")
PY

echo "📦 Backup saved to: $BACKUP"
echo "🔎 Verification:"
grep -nE "\"width\":[[:space:]]*${WIDTH},[[:space:]]*\"height\":[[:space:]]*${HEIGHT}" "$FILE" || true