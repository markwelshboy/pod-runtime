_hf_manifest_work_bytes() {
  local path="${1:-}"
  [[ -d "$path" ]] || { echo 0; return 0; }
  find "$path" -type f ! -name '*.lock' -printf '%s\n' 2>/dev/null \
    | awk '{s+=$1} END {printf "%.0f\n", s+0}'
}

_hf_manifest_kill_tree() {
  local parent="${1:-}" signal="${2:-TERM}" child
  [[ "$parent" =~ ^[0-9]+$ ]] || return 0
  while IFS= read -r child; do
    [[ "$child" =~ ^[0-9]+$ ]] || continue
    _hf_manifest_kill_tree "$child" "$signal"
  done < <(ps -o pid= --ppid "$parent" 2>/dev/null | awk '{print $1}')
  kill -s "$signal" "$parent" 2>/dev/null || true
}

_hf_manifest_download_item() {
  local item="${1:?item}" state="${2:?state}"
  local row id transport url path repo_type repo_id revision repo_file total work_dir log
  row="$(jq -r '[.id,.transport,.url,.path,.repo_type,.repo_id,.revision,.repo_file,(.total_bytes|tostring),.work_dir,.log] | join("\u001f")' "$item")" || return 1
  IFS=$'\x1f' read -r id transport url path repo_type repo_id revision repo_file total work_dir log <<<"$row"

  mkdir -p -- "$(dirname -- "$path")" "$(dirname -- "$log")"
  rm -rf -- "$work_dir"
  mkdir -p -- "$work_dir"

  {
    echo "[$(date -Is)] start id=$id transport=$transport"
    echo "url=$url"
    echo "path=$path"
    echo "expected_bytes=$total"
  } >>"$log"

  local src="" rc=0 output=""
  if [[ "$transport" == "hf" ]]; then
    local cli
    cli="$(_hf_manifest_cli)" || {
      echo "hf CLI not found" >>"$log"
      return 127
    }

    local -a args=(download "$repo_id" "$repo_file" --revision "$revision" --local-dir "$work_dir")
    [[ -n "$repo_type" && "$repo_type" != "model" ]] && args+=(--repo-type "$repo_type")
    args+=(--quiet)

    output="$(
      HF_XET_HIGH_PERFORMANCE="${HF_XET_HIGH_PERFORMANCE:-1}" \
      HF_HUB_DOWNLOAD_TIMEOUT="${HF_MANIFEST_DOWNLOAD_TIMEOUT:-120}" \
      "$cli" "${args[@]}" 2>>"$log"
    )" || rc=$?
    printf '%s\n' "$output" >>"$log"
    ((rc == 0)) || return "$rc"

    src="$work_dir/$repo_file"
    if [[ ! -f "$src" ]]; then
      local last
      last="$(printf '%s\n' "$output" | tail -n1)"
      [[ -f "$last" ]] && src="$last"
    fi
    if [[ ! -f "$src" ]]; then
      src="$(find "$work_dir" -type f -name "$(basename -- "$path")" ! -path '*/.cache/*' -print -quit 2>/dev/null || true)"
    fi
  else
    src="$work_dir/$(basename -- "$path").part"
    curl -fL --retry 3 --retry-all-errors \
      --connect-timeout "${HF_MANIFEST_METADATA_TIMEOUT:-20}" \
      --max-time 0 \
      -o "$src" "$url" >>"$log" 2>&1 || return $?
  fi

  if [[ -z "$src" || ! -f "$src" ]]; then
    echo "download command succeeded but no source file was found" >>"$log"
    return 1
  fi

  mv -f -- "$src" "$path" || return $?

  local actual
  actual="$(stat -c %s "$path" 2>/dev/null || echo 0)"
  if (( total > 0 && actual != total )); then
    echo "size mismatch: expected=$total actual=$actual" >>"$log"
    return 1
  fi

  if ! _hf_manifest_true "${HF_MANIFEST_KEEP_WORK:-0}"; then
    rm -rf -- "$work_dir"
  fi
  echo "[$(date -Is)] completed bytes=$actual" >>"$log"
  return 0
}

_hf_manifest_controller() {
  local state="${1:?state}"
  set +e
  set +u
  set +o pipefail

  local failures=0 item status bytes rc current_item=""
  _hf_manifest_controller_trap() {
    local sig="${1:-TERM}" current_status="" current_bytes=0
    if [[ -n "$current_item" && -f "$current_item" ]]; then
      current_status="$(jq -r '.status // ""' "$current_item" 2>/dev/null || true)"
      if [[ "$current_status" == "running" ]]; then
        current_bytes="$(_hf_manifest_work_bytes "$(jq -r '.work_dir // ""' "$current_item" 2>/dev/null || true)")"
        _hf_manifest_set_item_status "$current_item" failed "interrupted by $sig" "$current_bytes" || true
      fi
    fi
    _hf_manifest_set_controller_status "$state" stopped "$failures" "interrupted by $sig" || true
    exit 143
  }
  trap '_hf_manifest_controller_trap TERM' TERM
  trap '_hf_manifest_controller_trap INT' INT

  printf '%s\n' "${BASHPID:-$$}" >"$state/controller.pid"
  _hf_manifest_set_controller_status "$state" running 0 "sequential background downloader active"

  while IFS= read -r item || [[ -n "$item" ]]; do
    [[ -f "$item" ]] || continue
    status="$(jq -r '.status // "pending"' "$item" 2>/dev/null)"
    [[ "$status" == "completed" ]] && continue

    current_item="$item"
    _hf_manifest_set_item_status "$item" running "downloading" 0 || true
    _hf_manifest_download_item "$item" "$state"
    rc=$?
    if ((rc == 0)); then
      bytes="$(stat -c %s "$(jq -r '.path' "$item")" 2>/dev/null || echo 0)"
      _hf_manifest_set_item_status "$item" completed "downloaded" "$bytes" || true
    else
      failures=$((failures + 1))
      bytes="$(_hf_manifest_work_bytes "$(jq -r '.work_dir' "$item")")"
      _hf_manifest_set_item_status "$item" failed "download failed with rc=$rc; see item log" "$bytes" || true
    fi
    current_item=""
  done <"$state/items.list"

  if ((failures > 0)); then
    _hf_manifest_set_controller_status "$state" failed "$failures" "completed with failures"
    return 1
  fi

  _hf_manifest_set_controller_status "$state" completed 0 "all manifest items complete"
  return 0
}

hf_download_is_active() {
  local state
  state="$(_hf_manifest_state_dir "${1:-}")"
  local pid="" status=""
  [[ -f "$state/controller.pid" ]] && pid="$(cat "$state/controller.pid" 2>/dev/null || true)"
  [[ -f "$state/controller.json" ]] && status="$(jq -r '.status // ""' "$state/controller.json" 2>/dev/null || true)"
  [[ "$status" == "prepared" || "$status" == "running" ]] \
    && [[ "$pid" =~ ^[0-9]+$ ]] \
    && kill -0 "$pid" 2>/dev/null
}

hf_download_from_manifest() {
  local src="${1:-${MODEL_MANIFEST_URL:-}}"
  local state
  state="$(_hf_manifest_state_dir "${2:-}")"

  if [[ -z "$src" ]]; then
    echo "[hf-manifest] No manifest source supplied and MODEL_MANIFEST_URL is unset." >&2
    return 1
  fi
  command -v curl >/dev/null 2>&1 || { echo "[hf-manifest] curl is required." >&2; return 1; }
  command -v jq >/dev/null 2>&1 || { echo "[hf-manifest] jq is required." >&2; return 1; }
  _hf_manifest_cli >/dev/null || { echo "[hf-manifest] hf CLI is not available." >&2; return 1; }

  if hf_download_is_active "$state"; then
    echo "[hf-manifest] A downloader is already active in $state" >&2
    printf '1\n'
    return 0
  fi

  rm -rf -- "$state"
  mkdir -p -- "$state"
  local manifest="$state/manifest.json"
  if [[ -f "$src" ]]; then
    cp -f -- "$src" "$manifest"
  else
    curl -fsSL "$src" -o "$manifest" || {
      echo "[hf-manifest] Failed to fetch manifest: $src" >&2
      return 1
    }
  fi

  local plan
  plan="$(_hf_manifest_plan "$manifest" "$state")" || {
    echo "[hf-manifest] Failed to prepare manifest state." >&2
    return 1
  }

  local total pending present known unknown
  total="$(jq -r '.total // 0' <<<"$plan")"
  pending="$(jq -r '.pending // 0' <<<"$plan")"
  present="$(jq -r '.already_present // 0' <<<"$plan")"
  known="$(jq -r '.known_total_bytes // 0' <<<"$plan")"
  unknown="$(jq -r '.unknown_sizes // 0' <<<"$plan")"

  echo "[hf-manifest] Prepared $total item(s): pending=$pending already-present=$present"
  echo "[hf-manifest] Known total: $(helpers_human_bytes "$known") across $((total - unknown)) item(s); unknown size=$unknown"

  if ((total == 0 || pending == 0)); then
    _hf_manifest_set_controller_status "$state" completed 0 "nothing to download"
    printf '0\n'
    return 0
  fi

  (
    _hf_manifest_controller "$state"
  ) >>"$state/controller.log" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "$pid" >"$state/controller.pid"
  disown "$pid" 2>/dev/null || true

  echo "[hf-manifest] Background controller started: pid=$pid"
  echo "[hf-manifest] Status: hf_download_show_snapshot"
  echo "[hf-manifest] JSON:   hf_download_status_json"
  printf '1\n'
  return 0
}
