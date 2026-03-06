#!/usr/bin/env bash
set -euo pipefail

DEFAULT_FILE="/app/ai-toolkit/toolkit/buckets.py"

usage() {
  echo "Usage: $0 WIDTHxHEIGHT [-f /app/ai-toolkit/toolkit/buckets.py]"
  exit 1
}

[[ $# -lt 1 ]] && usage

RES="$1"
shift

FILE="$DEFAULT_FILE"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)
      FILE="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

if [[ ! "$RES" =~ ^([0-9]+)x([0-9]+)$ ]]; then
  echo "❌ Resolution must be WIDTHxHEIGHT (example: 720x1280)"
  exit 1
fi

WIDTH="${BASH_REMATCH[1]}"
HEIGHT="${BASH_REMATCH[2]}"

if (( WIDTH % 8 != 0 || HEIGHT % 8 != 0 )); then
  echo "❌ Width and height must be divisible by 8 (toolkit requirement)"
  exit 1
fi

if [[ ! -f "$FILE" ]]; then
  echo "❌ buckets.py not found: $FILE"
  exit 1
fi

ENTRY="    {\"width\": ${WIDTH}, \"height\": ${HEIGHT}},"

echo "→ Adding bucket ${WIDTH}x${HEIGHT} to $FILE"

if grep -q "\"width\": ${WIDTH}, \"height\": ${HEIGHT}" "$FILE"; then
  echo "✅ Bucket already exists"
  exit 0
fi

BACKUP="${FILE}.bak.$(date +%Y%m%d_%H%M%S)"
cp -a "$FILE" "$BACKUP"

python3 - "$FILE" "$WIDTH" "$HEIGHT" <<'PY'
import sys
from pathlib import Path

file = Path(sys.argv[1])
w = sys.argv[2]
h = sys.argv[3]

text = file.read_text()

entry = f'    {{"width": {w}, "height": {h}}},\n'

start = text.find("resolutions_1024")
if start == -1:
    print("❌ resolutions_1024 list not found")
    sys.exit(1)

lb = text.find("[", start)
depth = 0
end = None

for i, ch in enumerate(text[lb:], start=lb):
    if ch == "[":
        depth += 1
    elif ch == "]":
        depth -= 1
        if depth == 0:
            end = i
            break

if end is None:
    print("❌ Could not locate end of resolutions_1024 list")
    sys.exit(1)

new_text = text[:end] + entry + text[end:]
file.write_text(new_text)

print(f"✅ Inserted {w}x{h} bucket")
PY

echo "📦 Backup saved: $BACKUP"
grep -n "\"width\": ${WIDTH}, \"height\": ${HEIGHT}" "$FILE"