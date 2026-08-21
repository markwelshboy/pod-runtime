# sl:name seedvr2
# sl:description Standalone tiled SeedVR2 batch upscale/restoration
# sl:input 1
# sl:output 2
# sl:setup-version 1

sl_prepare() {
  local cache="$SL_CACHE_DIR/seedvr2-tile"
  local repo="$cache/repo"
  local venv="$cache/venv"
  local branch="agent/standalone-tiled-cli"
  local py="${PYTHON:-python3}"

  mkdir -p "$cache"
  if [[ ! -d "$repo/.git" ]]; then
    git clone https://github.com/markwelshboy/seedvr2-tile.git "$repo"
  else
    git -C "$repo" fetch origin "$branch"
  fi
  git -C "$repo" checkout "$branch"
  git -C "$repo" reset --hard "origin/$branch"

  if [[ ! -x "$venv/bin/python" ]]; then
    "$py" -m venv "$venv"
  fi
  # shellcheck disable=SC1090
  source "$venv/bin/activate"
  unset PIP_CONSTRAINT PIP_BUILD_CONSTRAINT
  python -m pip install -e "$repo"
}

sl_setup() {
  local venv="$SL_CACHE_DIR/seedvr2-tile/venv"
  # shellcheck disable=SC1090
  source "$venv/bin/activate"
  unset PIP_CONSTRAINT PIP_BUILD_CONSTRAINT
  seedvr2-tile setup --install-deps --fbcnn
}

sl_run() {
  local repo="$SL_CACHE_DIR/seedvr2-tile/repo"
  local venv="$SL_CACHE_DIR/seedvr2-tile/venv"
  # shellcheck disable=SC1090
  source "$venv/bin/activate"
  cd "$repo"
  seedvr2-tile "$SL_ARG_1" "$SL_ARG_2" "${SL_EXTRA_ARGS[@]}"
}
