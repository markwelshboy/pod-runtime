# `sl` — durable GPU jobs on an existing pod

`sl` turns the SSH remote already configured for `vcp` into a small durable job worker. Bulk inputs and outputs move through `vcp`/Hugging Face; control, status and logs use SSH.

The intent is a pseudo-serverless workflow for an already-running RunPod/Vast worker: invoke a local command, stage data, run GPU work detached from the SSH connection, retrieve outputs, and retain job history/logs.

## Transport and configuration

`sl` deliberately reuses `vcp`'s SSH configuration rather than maintaining a second pod endpoint:

```bash
vcp config ssh -i ~/.ssh/id_ed25519_runpod -p 14349 root@202.181.159.220
sl config show
```

`sl config show` reports the inherited transport plus its own settings. Defaults:

```text
remote root:  /workspace/.sl
command dir:  <pod-runtime>/commands/sl
state dir:    ~/.local/state/sl/jobs
cleanup:      successful
runtime repo: https://github.com/markwelshboy/pod-runtime.git
runtime ref:  main
```

Adjust them with:

```bash
sl config remote-root /workspace/.sl
sl config command-dir ~/my-sl-commands
sl config state-dir ~/.local/state/sl/jobs
sl config cleanup never|successful|always
sl config runtime-repo https://github.com/markwelshboy/pod-runtime.git
sl config runtime-ref main
```

## Command definitions

A `.cmd` file declares which positional operands are local inputs and which are worker outputs. The body defines `sl_run`, with optional `sl_prepare` (every job) and `sl_setup` (only when the setup-version changes).

```bash
# sl:name example
# sl:description Example GPU command
# sl:input 1
# sl:output 2
# sl:setup-version 1
# sl:memcheck

sl_prepare() {
    : # cheap/idempotent preparation every run
}

sl_setup() {
    : # expensive cold setup; cached by setup-version
}

sl_run() {
    some-command "$SL_ARG_1" "$SL_ARG_2" "${SL_EXTRA_ARGS[@]}"
}
```

Inputs are staged under a job-specific `input/argN/` directory. Output operands are safe relative paths rooted below the job's `output/` directory. Arguments after `--` are preserved as an argv array; `sl` does not `eval` an option string.

`# sl:memcheck` declares that a command can be scheduled on free GPU memory with `--mem`. A blank directive has no default threshold, so omitting `--mem` proceeds normally. A command may optionally declare a default such as `# sl:memcheck 18G`; a caller-supplied `--mem` overrides that default.

Useful variables inside commands:

```text
SL_JOB_ID
SL_JOB_DIR
SL_INPUT_DIR
SL_OUTPUT_DIR
SL_WORK_DIR
SL_CACHE_DIR
SL_COMMAND_CACHE
SL_RUNTIME_DIR
SL_ARG_1, SL_ARG_2, ...
SL_EXTRA_ARGS[]
SL_MEMORY_REQUIRED_MIB   (set only when a memory gate is active)
SL_MEMORY_FREE_MIB       (updated while waiting)
```

Before a command is sourced, the worker maintains a dedicated cached clone of `pod-runtime` at `/workspace/.sl/runtime/pod-runtime`, sources the full `helpers.sh` runtime entrypoint (core/session/network/HF/manifest/git helpers), and exposes the normal pod-runtime helpers/accelerators to the job. A controller `HF_TOKEN`, when present, is passed only in the detached process environment and is not written into `run.sh` or job metadata.

## GPU memory scheduling

For commands declaring `# sl:memcheck`, request a minimum amount of **free GPU VRAM** before `sl_run` begins:

```bash
sl run --mem 18G seedvr2 input/ output/ -- --scale 2
sl run --detach --mem 18000M seedvr2 input/ output/ -- --scale 2
```

Accepted units are `M`, `MB`, `MiB`, `G`, `GB`, and `GiB`. `G`/`GB`/`GiB` are treated as 1024 MiB. A unit suffix is required to avoid ambiguous commands such as `--mem 18`.

The job remains durable while waiting. Command preparation and cached setup are allowed to finish first; immediately before `sl_run`, the worker checks the first GPU reported by `nvidia-smi`:

```text
PREPARING
    ↓
WAITING_FOR_MEMORY
    ↓
RUNNING
```

While waiting, the worker polls every 5 seconds and logs progress roughly every 30 seconds. `sl tail JOB` therefore shows the queue-like wait without requiring the submitting shell to remain connected. `sl status JOB` reports both the latest free VRAM and the required threshold.

If the requested memory exceeds the GPU's total VRAM, the job fails immediately rather than waiting forever. If no `--mem` value and no command default are present, there is no memory check.

The initial implementation checks the first GPU reported by `nvidia-smi`, matching the current single-GPU pod model. A future multi-GPU scheduler can add explicit device selection.

## Smoke test

A built-in `smoke` command exercises the complete `sl` transport/lifecycle/log/output path without installing a GPU workload:

```bash
mkdir -p /tmp/sl-in
printf 'hello from sl\n' > /tmp/sl-in/hello.txt

sl run smoke /tmp/sl-in sl-smoke-out --output-dir /tmp -- --alpha "two words"

cat /tmp/sl-smoke-out/sl-smoke.txt
cat /tmp/sl-smoke-out/sl-in/hello.txt
```

It also declares `# sl:memcheck`, so the scheduler can be exercised independently of SeedVR2:

```bash
sl run --mem 1G smoke /tmp/sl-in sl-smoke-out --output-dir /tmp
```

Use this first on a new worker to validate SSH, `vcp`, detached execution, log/status handling, output retrieval, memory gating, and successful-workspace cleanup.

## SeedVR2

The built-in first command is `commands/sl/seedvr2.cmd`. It declares `# sl:memcheck`, maintains a warm checkout/venv under `/workspace/.sl/cache/seedvr2-tile`, installs the standalone tiled CLI, runs the SeedVR2/FBCNN setup once per command setup-version, and then executes the requested batch.

```bash
sl run --mem 18G seedvr2 \
  ~/images/toprocess/ \
  seedvr2_out/ \
  --output-dir . \
  -- \
  --config examples/lowlight-jpeg-naturalize.json \
  --seed 43
```

If `--mem` is omitted, SeedVR2 proceeds without waiting; the command definition intentionally does not impose a default threshold because different models/options have different VRAM requirements.

The original shorthand is also accepted:

```bash
sl --command seedvr2.cmd --mem 18G ~/images/toprocess/ seedvr2_out/ -- \
  --config examples/lowlight-jpeg-naturalize.json --seed 43
```

## Durable execution

All jobs are launched detached on the worker. Synchronous `sl run` simply follows the durable job until it exits, then fetches declared outputs.

```bash
sl run seedvr2 input/ output/ -- --scale 2
```

Return immediately instead:

```bash
sl run --detach seedvr2 input/ output/ -- --scale 2
```

The command prints a job ID such as:

```text
20260820_174800_a31f84c2
```

Closing the terminal or losing the SSH connection does not terminate the worker process. This includes jobs waiting in `WAITING_FOR_MEMORY`.

## Jobs, status and logs

```bash
sl jobs
sl status 20260820_174800_a31f84c2
```

Show the entire log:

```bash
sl logs 20260820_174800_a31f84c2
sl logs -f 20260820_174800_a31f84c2
```

Tail the last 100 lines and follow by default:

```bash
sl tail 20260820_174800_a31f84c2
sl tail -n 500 20260820_174800_a31f84c2
sl tail --no-follow 20260820_174800_a31f84c2
```

Synchronous jobs, and detached jobs that you later inspect with `status`/`logs`/`tail` or retrieve with `fetch`, mirror their small metadata/log files under `~/.local/state/sl/jobs/JOB/`. Once mirrored, that retained history survives destruction of the GPU pod. A detached job cannot keep syncing after the local `sl` process has exited, so inspect/fetch it before destroying the pod if you want the completed remote log retained locally.

## Fetch, cleanup and purge

Detached jobs can be fetched later:

```bash
sl fetch 20260820_174800_a31f84c2
sl fetch --output-dir ~/results 20260820_174800_a31f84c2
```

`sl clean JOB` removes only heavy remote data (`input/`, `output/`, `work/`) and intentionally retains the manifest, status, command snapshot, runner and log:

```bash
sl clean 20260820_174800_a31f84c2
```

`sl purge JOB` deletes the remote record and its local retained history. Running or memory-waiting jobs are protected unless `--force` is supplied:

```bash
sl purge 20260820_174800_a31f84c2
sl purge --force 20260820_174800_a31f84c2
```

With the default `cleanup=successful`, a synchronous successful run fetches outputs and cleans heavy workspace while retaining logs/metadata. Failed jobs keep their workspace for diagnosis.
