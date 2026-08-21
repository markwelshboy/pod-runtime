# sl:name smoke
# sl:description SL transport, lifecycle, logging, and output smoke test
# sl:input 1
# sl:output 2
# sl:setup-version 1

sl_run() {
  mkdir -p "$SL_ARG_2"
  cp -a -- "$SL_ARG_1" "$SL_ARG_2/"
  {
    printf 'sl smoke job %s\n' "$SL_JOB_ID"
    printf 'input: %s\n' "$SL_ARG_1"
    printf 'output: %s\n' "$SL_ARG_2"
    printf 'extra args:'
    printf ' <%s>' "${SL_EXTRA_ARGS[@]}"
    printf '\n'
  } > "$SL_ARG_2/sl-smoke.txt"
}
