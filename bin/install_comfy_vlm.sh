#!/usr/bin/env bash
# Ollama + OpenCode + optional minimal ComfyUI Ollama node; no PyTorch/Transformers pip changes.
set -euo pipefail

MODEL="${VLM_MODEL:-qwen3-vl:8b}"
COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
MODEL_DIR="${OLLAMA_MODELS:-/workspace/models/ollama}"
INSTALL_OPENCODE=1
INSTALL_NODE=1
START=1
PULL=1

usage() {
  cat <<'EOF'
Usage: bash install_comfy_vlm.sh [OPTIONS]
  --model NAME       Ollama vision model to pull (default: qwen3-vl:8b)
  --comfy-dir PATH   ComfyUI checkout (default: /workspace/ComfyUI)
  --models-dir PATH  Persistent Ollama model storage (default: /workspace/models/ollama)
  --no-opencode      Skip OpenCode interactive skill-aware agent
  --no-node          Skip AB Simple Ollama ComfyUI node
  --no-start         Install only; do not start Ollama (for Docker builds)
  --no-pull          Do not download model weights (for Docker builds)
  -h, --help         Show help

Runs as root in Ubuntu 24.04 / NVIDIA CUDA container. Does NOT modify /opt/venv.
For a Docker build, use --no-start --no-pull and change ENTRYPOINT to
/usr/local/bin/entrypoint-with-vlm (starts Ollama, then original /start_script.sh).
EOF
}
while (($#)); do
  case "$1" in
    --model) MODEL="${2:?missing model}"; shift 2;;
    --comfy-dir) COMFY_DIR="${2:?missing path}"; shift 2;;
    --models-dir) MODEL_DIR="${2:?missing path}"; shift 2;;
    --no-opencode) INSTALL_OPENCODE=0; shift;;
    --no-node) INSTALL_NODE=0; shift;;
    --no-start) START=0; shift;;
    --no-pull) PULL=0; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2;;
  esac
done
if [[ "$(id -u)" != 0 ]]; then
  echo 'ERROR: run this installer as root (typical RunPod/Vast container user).' >&2
  exit 1
fi
if ((PULL && !START)); then
  echo 'ERROR: --no-start requires --no-pull (pulling requires the server).' >&2
  exit 2
fi
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "${DIR}/vlm_skill.py" ]]; then
  echo "ERROR: vlm_skill.py must live beside the installer in ${DIR}" >&2
  exit 1
fi

# Only OS package needed for upstream .tar.zst. No pip/torch/constraints changes.
if ! command -v zstd >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends zstd
  rm -rf /var/lib/apt/lists/*
fi

# Mediapipe etc
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgles2
rm -rf /var/lib/apt/lists/*

command -v curl >/dev/null || { echo 'curl is required' >&2; exit 1; }
command -v git >/dev/null || { echo 'git is required to install the optional ComfyUI node' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 1; }
mkdir -p "$MODEL_DIR" /workspace/logs

if ! command -v ollama >/dev/null 2>&1; then
  [[ "$(uname -m)" == 'x86_64' ]] || { echo 'Only linux/amd64 is supported by this installer' >&2; exit 1; }
  echo '== Installing Ollama directly from official Linux distribution (no systemd) =='
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR:-}"' EXIT
  curl -fL --retry 3 --connect-timeout 30 \
    https://ollama.com/download/ollama-linux-amd64.tar.zst \
    -o "$TMP_DIR/ollama-linux-amd64.tar.zst"
  tar --zstd -xf "$TMP_DIR/ollama-linux-amd64.tar.zst" -C /usr
  rm -rf "$TMP_DIR"
  trap - EXIT
else
  echo '== Ollama already available; leaving installed binary untouched =='
fi
ollama --version || true

# Persistent configuration in a readable shell file, easy to modify on pod.
if [[ ! -f /etc/comfy-vlm.env ]]; then
  cat > /etc/comfy-vlm.env <<EOF
# Local-only API: access via ssh -L 11434:127.0.0.1:11434, never expose unauthenticated
OLLAMA_HOST='127.0.0.1:11434'
OLLAMA_MODELS='${MODEL_DIR}'
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_NUM_PARALLEL=1
OLLAMA_CONTEXT_LENGTH=16384
OLLAMA_NO_CLOUD=1
EOF
else
  echo '== Preserving existing /etc/comfy-vlm.env =='
fi

cat > /usr/local/bin/start-ollama <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ -f /etc/comfy-vlm.env ]] && source /etc/comfy-vlm.env
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/models/ollama}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-16384}"
export OLLAMA_NO_CLOUD="${OLLAMA_NO_CLOUD:-1}"
mkdir -p "$OLLAMA_MODELS" /workspace/logs
if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo 'Ollama is already serving on 127.0.0.1:11434'
  exit 0
fi
nohup /usr/bin/ollama serve > /workspace/logs/ollama.log 2>&1 < /dev/null &
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo 'Ollama is ready on http://127.0.0.1:11434'
    exit 0
  fi
  sleep 1
done
echo 'ERROR: Ollama did not become ready; see /workspace/logs/ollama.log' >&2
exit 1
EOF
chmod +x /usr/local/bin/start-ollama

cat > /usr/local/bin/entrypoint-with-vlm <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
/usr/local/bin/start-ollama
exec /start_script.sh "$@"
EOF
chmod +x /usr/local/bin/entrypoint-with-vlm

install -m 755 "${DIR}/vlm_skill.py" /usr/local/bin/vlm-skill

if ((INSTALL_NODE)); then
  echo '== Installing AB Simple Ollama node (no pip requirements) =='
  NODES="${COMFY_DIR}/custom_nodes"
  if [[ ! -d "$COMFY_DIR" ]]; then
    echo "WARNING: ComfyUI checkout does not exist: ${COMFY_DIR}; skipping node" >&2
  else
    mkdir -p "$NODES"
    if [[ ! -e "$NODES/ComfyUI_Simple_Ollama" ]]; then
      git clone --depth 1 https://github.com/a-und-b/ComfyUI_Simple_Ollama.git "$NODES/ComfyUI_Simple_Ollama"
    else
      echo 'Node already exists; not overwriting it.'
    fi
  fi
fi

if ((INSTALL_OPENCODE)); then
  echo '== Installing OpenCode 2 (native SKILL.md support) =='
  if ! command -v opencode >/dev/null 2>&1; then
    TMP_SCRIPT="$(mktemp)"
    trap 'rm -f "${TMP_SCRIPT:-}"' EXIT
    curl -fL --retry 3 https://opencode.ai/v2/install -o "$TMP_SCRIPT"
    bash "$TMP_SCRIPT"
    rm -f "$TMP_SCRIPT"
    trap - EXIT
    for candidate in "$HOME/.opencode/bin/opencode" "$HOME/.local/bin/opencode" "$HOME/bin/opencode"; do
      if [[ -x "$candidate" ]]; then
        ln -sf "$candidate" /usr/local/bin/opencode
        break
      fi
    done
  fi
  mkdir -p "$HOME/.config/opencode/skills"
  if [[ ! -e "$HOME/.config/opencode/opencode.json" && ! -e "$HOME/.config/opencode/opencode.jsonc" ]]; then
    printf '{"$schema":"https://opencode.ai/config.json","model":"ollama/%s"}\n' "$MODEL" > "$HOME/.config/opencode/opencode.json"
  fi
  if ! command -v opencode >/dev/null 2>&1; then
    echo 'WARNING: OpenCode installed but was not found on PATH; inspect ~/.opencode/bin' >&2
  fi
fi

ollama pull qwen3-vl:8b-instruct

mkdir -p /workspace/models/gaze
hf download py-feat/l2cs \
  l2cs_gaze360_resnet50.safetensors \
  --local-dir /workspace/models/gaze

# A replaceable example; nothing in an existing user's skills is overwritten.
EXAMPLE='/workspace/vlm-skills/image-curation'
mkdir -p "$EXAMPLE/references"
if [[ ! -e "$EXAMPLE/SKILL.md" ]]; then
  cat > "$EXAMPLE/SKILL.md" <<'EOF'
---
name: image-curation
description: Inspect generated images for quality defects and recommended ComfyUI refinement actions.
---
# Image curation
Analyze only the image supplied. Follow references/criteria.md.
Be conservative: do not infer that a detailer is necessary solely because a face or eyes are visible.
If asked for JSON, return a JSON object with keys: summary (string), visible_issues (array of strings), tags (array of strings), recommended_tasks (array of strings), explanation (string).
Use exact tag strings documented in references/criteria.md, and omit tags that are not supported by visible evidence.
EOF
fi
if [[ ! -e "$EXAMPLE/references/criteria.md" ]]; then
  cat > "$EXAMPLE/references/criteria.md" <<'EOF'
# Image-Compare-compatible condition tags
- `no-face`: no usable face is visible.
- `no-eyes`: eyes are not visible or are obstructed.
- `eyes-closed`: visible eyelids are closed.
- `eyes-half-closed`: visible eyelids are partly closed.
- `mouth-open`: lips are visibly parted enough to see an opening.
- `mouth-closed`: lips are visibly closed.

# Refinement suggestions
Only recommend a task when the image has a visible reason for it.
Possible task slugs: `detailer`, `new-seed`, `inpaint`, `upscale`.
Call out skin blotchiness, unnatural facial structures, excessive smoothing,
framing problems, texture artifacts, or accessory defects where actually visible.
Do not claim to know the original prompt, identity, or intended appearance from pixels alone.
EOF
fi

if ((START)); then
  echo '== Starting local-only Ollama server =='
  /usr/local/bin/start-ollama
fi
if ((PULL)); then
  echo "== Pulling ${MODEL} into persistent model store =="
  # The service uses /etc/comfy-vlm.env to set OLLAMA_MODELS.
  ollama pull "$MODEL"
fi

echo
cat <<EOF
Installation complete.
  Ollama endpoint: http://127.0.0.1:11434
  Model cache:     ${MODEL_DIR}
  Start command:   start-ollama
  Batch runner:    vlm-skill --skill '${EXAMPLE}' --images /path/to/images --json
  OpenCode:        opencode  (model: ollama/${MODEL})
  ComfyUI node:    ${COMFY_DIR}/custom_nodes/ComfyUI_Simple_Ollama
  Docker ENTRYPOINT opt-in: ["/usr/local/bin/entrypoint-with-vlm"]

Note: restart ComfyUI after node installation. In a non-Docker install,
re-run 'start-ollama' after a container restart (or switch ENTRYPOINT above).
EOF
