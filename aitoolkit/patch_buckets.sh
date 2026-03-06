#!/usr/bin/env bash
set -euo pipefail

DEFAULT_FILE="/app/ai-toolkit/toolkit/buckets.py"
ADD_ROTATED=1

usage() {
  cat <<EOF
Usage:
  $0 WIDTHxHEIGHT [-f FILE] [--no-rotated]

Examples:
  $0 720x1280
  $0 720x1280 -f /app/ai-toolkit/toolkit/buckets.py
  $0 720x1280 --no-rotated
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
    --no-rotated)
      ADD_ROTATED=0
      shift
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

python3 - "$FILE" "$WIDTH" "$HEIGHT" "$ADD_ROTATED" <<'PY'
import re
import sys
from pathlib import Path

file = Path(sys.argv[1])
w = int(sys.argv[2])
h = int(sys.argv[3])
add_rotated = bool(int(sys.argv[4]))

text = file.read_text(encoding="utf-8")

m = re.search(r'(^\s*resolutions_1024\s*:[^=\n]*=\s*\[)', text, re.M)
if not m:
    print("❌ Could not find resolutions_1024 assignment")
    sys.exit(1)

list_start = m.end() - 1  # the '[' in '= ['

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

def has_bucket(txt, bw, bh):
    pat = re.compile(r'\{\s*"width"\s*:\s*%d\s*,\s*"height"\s*:\s*%d\s*\}' % (bw, bh))
    return bool(pat.search(txt))

to_add = []
if not has_bucket(text, w, h):
    to_add.append((w, h))

if add_rotated and w != h and not has_bucket(text, h, w):
    to_add.append((h, w))

if not to_add:
    print("✅ Bucket(s) already present")
    sys.exit(0)

widescreen_anchor = '    {"width": 1280, "height": 768},\n'
portrait_anchor = '    {"width": 768, "height": 1280},\n'

for bw, bh in to_add:
    entry = f'    {{"width": {bw}, "height": {bh}}},\n'
    inserted = False

    if bw > bh and widescreen_anchor in text:
        text = text.replace(widescreen_anchor, widescreen_anchor + entry, 1)
        inserted = True
    elif bh > bw and portrait_anchor in text:
        text = text.replace(portrait_anchor, portrait_anchor + entry, 1)
        inserted = True

    if not inserted:
        text = text[:list_end] + entry + text[list_end:]
        list_end += len(entry)

file.write_text(text, encoding="utf-8")

added_str = ", ".join(f"{bw}x{bh}" for bw, bh in to_add)
print(f"✅ Inserted bucket(s): {added_str}")
PY

echo "📦 Backup saved to: $BACKUP"
echo "🔎 Verification:"
grep -nE "\"width\":[[:space:]]*(${WIDTH}|${HEIGHT}),[[:space:]]*\"height\":[[:space:]]*(${WIDTH}|${HEIGHT})" "$FILE" || true