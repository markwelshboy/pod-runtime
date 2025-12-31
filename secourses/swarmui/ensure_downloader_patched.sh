#!/usr/bin/env bash
set -euo pipefail

: "${WORKSPACE:=/workspace}"
: "${POD_RUNTIME_DIR:=/workspace/pod-runtime}"

: "${SWARMUI_DL_PORT:=7862}"
: "${SWARMUI_DL_HOST:=0.0.0.0}"
: "${SWARMUI_DL_SHARE:=false}"

BASE="${POD_RUNTIME_DIR}/secourses/swarmui"

SRC_APP="${BASE}/Downloader_Gradio_App.py"

DST_APP="${WORKSPACE}/Downloader_Gradio_App.patched.py"

echo "[ensure_downloader_patched] Staging downloader into ${WORKSPACE}"
mkdir -p "${WORKSPACE}"

[[ -f "${SRC_APP}" ]] || { echo "[ensure_downloader_patched] ERR: Missing ${SRC_APP}" >&2; exit 1; }

# Fast path: keep existing patched file if newer than source app
if [[ -f "${DST_APP}" && "${DST_APP}" -nt "${SRC_APP}" ]]; then
  echo "[ensure_downloader_patched] Using existing patched file: ${DST_APP}"
  exit 0
fi

echo "[ensure_downloader_patched] Creating patched copy:"
echo "  SRC: ${SRC_APP}"
echo "  DST: ${DST_APP}"
cp -f "${SRC_APP}" "${DST_APP}"

# If upstream already sets server_port in launch(), don't patch.
if grep -qE 'launch\([^)]*server_port\s*=' "${DST_APP}"; then
  echo "[ensure_downloader_patched] Upstream already sets server_port in launch(); leaving unmodified."
  exit 0
fi

# Ensure os imported (best-effort)
if ! grep -qE '^\s*import\s+os\b' "${DST_APP}"; then
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
  ' "${DST_APP}" > "${DST_APP}.tmp" && mv "${DST_APP}.tmp" "${DST_APP}"
fi

# Patch the FIRST ".launch(" occurrence by injecting stable server_name/server_port.
# NOTE: do NOT inject share= here (you previously hit "keyword repeated: share").
export DST_APP
python - <<'PY'
import os, re, pathlib, sys

dst = pathlib.Path(os.environ["DST_APP"])
text = dst.read_text(encoding="utf-8", errors="ignore")

# Idempotency
if "SWARMUI_DL_PORT" in text and "SWARMUI_DL_HOST" in text:
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

text2 = text[:m.start()] + inject + text[m.end():]
dst.write_text(text2, encoding="utf-8")
print("[ensure_downloader_patched] Injected server_name/server_port into .launch()")
PY

echo "[ensure_downloader_patched] Patched ok:"
echo "  APP : ${DST_APP}"
