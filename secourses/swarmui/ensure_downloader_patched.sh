#!/usr/bin/env bash
set -euo pipefail

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${SWARMUI_DL_PORT:=7862}"
: "${SWARMUI_DL_HOST:=0.0.0.0}"
: "${SWARMUI_DL_SHARE:=false}"

SRC="${POD_RUNTIME_DIR}/secourses/swarmui/Downloader_Gradio_App.py"
DST="${WORKSPACE}/Downloader_Gradio_App.patched.py"

# Export BEFORE any subprocess that reads env (python below)
export SWARMUI_DL_PORT SWARMUI_DL_HOST SWARMUI_DL_SHARE
export SRC DST

if [[ ! -f "${SRC}" ]]; then
  echo "[ensure_downloader_patched] ERR: Missing source: ${SRC}" >&2
  exit 1
fi

mkdir -p "${WORKSPACE}"

# If destination exists and is newer than source, keep it (fast boots).
if [[ -f "${DST}" && "${DST}" -nt "${SRC}" ]]; then
  echo "[ensure_downloader_patched] Using existing patched file: ${DST}"
  exit 0
fi

echo "[ensure_downloader_patched] Creating patched copy:"
echo "  SRC: ${SRC}"
echo "  DST: ${DST}"

cp -f "${SRC}" "${DST}"

# If upstream already sets server_port in launch(), don't patch.
if grep -qE 'launch\([^)]*server_port\s*=' "${DST}"; then
  echo "[ensure_downloader_patched] Upstream already sets server_port in launch(); leaving unmodified."
  exit 0
fi

# Ensure os imported (best-effort)
if ! grep -qE '^\s*import\s+os\b' "${DST}"; then
  awk '
    BEGIN{added=0}
    {
      if (!added && ($0 ~ /^import / || $0 ~ /^from /)) {
        print $0
        print "import os"
        added=1
        next
      }
      print $0
    }
  ' "${DST}" > "${DST}.tmp" && mv "${DST}.tmp" "${DST}"

  if ! grep -qE '^\s*import\s+os\b' "${DST}"; then
    # Prepend as last resort
    { echo "import os"; cat "${DST}"; } > "${DST}.tmp" && mv "${DST}.tmp" "${DST}"
  fi
fi

# Patch the FIRST ".launch(" occurrence by injecting stable server_name/server_port/share.
python - <<'PY'
import os, re, pathlib, sys

dst = pathlib.Path(os.environ["DST"])
text = dst.read_text(encoding="utf-8", errors="ignore")

# Idempotency: if already injected, skip
if "SWARMUI_DL_PORT" in text and "SWARMUI_DL_HOST" in text and "SWARMUI_DL_SHARE" in text:
    print("[ensure_downloader_patched] Patch already present; skipping.")
    sys.exit(0)

m = re.search(r"\.launch\(\s*", text)
if not m:
    print("[ensure_downloader_patched] WARN: Could not find .launch( to patch; leaving file unchanged.")
    sys.exit(0)

inject = (
    ".launch(\n"
    "            server_name=os.environ.get(\"SWARMUI_DL_HOST\", \"0.0.0.0\"),\n"
    "            server_port=int(os.environ.get(\"SWARMUI_DL_PORT\", \"7862\")),\n"
)


# Replace only the first occurrence
text2 = text[:m.start()] + inject + text[m.end():]
dst.write_text(text2, encoding="utf-8")

print("[ensure_downloader_patched] Injected server_name/server_port/share into .launch()")
PY

echo "[ensure_downloader_patched] Patched ok: ${DST}"
