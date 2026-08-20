# `vcp` — Hugging Face accelerated local↔pod copy

`vcp` copies files and directories between the machine where it is run and one configured SSH remote. It uses a Hugging Face dataset as a temporary high-speed hop.

The command is intentionally **local-controller only**: run it on ddraig (or another machine that can SSH to the pod). The pod never needs an SSH route back to the local machine.

## Path syntax

Remote paths are prefixed with `r:` and must be absolute:

```bash
r:/workspace/report.txt
r:/workspace/logs
```

Paths without `r:` are local paths and can be relative or absolute.

All source operands for one copy must be on the same side, and the destination must be on the other side.

## Configure the SSH remote

The SSH arguments are stored exactly as supplied in `~/.config/vcp/config.json`:

```bash
vcp config ssh -i ~/.ssh/id_ed25519 -p 12234 root@199.199.88.88
```

Inspect the current configuration:

```bash
vcp config show
```

The default scratch dataset is:

```text
markwelshboyx/hf-scratchpad
```

Override it persistently:

```bash
vcp config hf-repo markwelshboyx/hf-scratchpad
```

Or per shell with `VCP_HF_REPO`.

`HF_TOKEN` must be available on the local/controller machine. `bin/vcp.py` supplies that same credential ephemerally to the remote Hugging Face operation through the encrypted SSH stdin stream, after the pod runtime environment and `helpers_shell.sh` have been loaded. The token is not placed in SSH argv, written to `~/.config/vcp/config.json`, or persisted to a file on the pod.

## Copy from pod to local

```bash
vcp r:/workspace/report.txt r:/workspace/logs .
```

The local controller:

1. SSHes to the pod.
2. Creates a plain `.tar` under `/workspace/.vcp/` containing `report.txt` and `logs/`.
3. Uses the pod's existing `hff` tooling plus the controller-supplied HF credential to upload that tar to the scratch dataset.
4. Downloads the tar locally with `bin/hff.py`.
5. Extracts to a temporary directory and runs normal `cp -a` into the requested destination.
6. Removes the temporary Hugging Face object.

No SSH connection from the pod back to the local machine is involved.

## Copy from local to pod

```bash
vcp interestingdirectory/ r:/workspace/
```

The local controller:

1. Creates a plain local tar.
2. Uploads it with `bin/hff.py`.
3. SSHes to the pod.
4. Uses the pod's `hff` tooling plus the controller-supplied HF credential to download it.
5. Extracts it and uses `cp -a` into `/workspace/`.
6. Removes the temporary Hugging Face object.

Multiple local sources work too:

```bash
vcp image1.png image2.png captions/ r:/workspace/training/
```

## Transfer timing

Successful copies end with a timing summary. Remote commands emit internal timing markers for the individual tar/HF/copy stages; the local controller consumes those markers and does not show them directly.

A pod-to-local transfer looks like:

```text
[vcp] Transfer summary:
[vcp]   Remote pack                 2.80s    767.0 MB/s
[vcp]   HF upload (remote)         20.50s    104.8 MB/s
[vcp]   HF download (local)        25.20s     85.2 MB/s
[vcp]   Extract/copy (local)        8.90s    241.5 MB/s
[vcp]   HF cleanup                  1.10s
[vcp]   Total                      65.70s
[vcp]   Effective throughput       32.7 MB/s
```

Stage throughput is based on the logical tar size. For Xet-deduplicated uploads this is deliberately a logical rate: Hugging Face's own `New Data Upload` progress remains the authoritative view of how many novel bytes were physically uploaded.

The total includes SSH/bootstrap overhead, Hugging Face transaction overhead, reconstruction, local/remote copy work, and scratch cleanup. Effective throughput is the logical archive size divided by total wall-clock time.

## Scratch retention

Scratch objects are deleted automatically after the copy attempt completes. To keep one for troubleshooting:

```bash
vcp --keep interestingdirectory/ r:/workspace/
```

The staged object lives under `vcp/<timestamp>_<random>.tar` in the scratch dataset.

## Environment variables

- `HF_TOKEN` — required on the local/controller machine and used for both HF legs.
- `VCP_HF_REPO` — override the scratch dataset repository.
- `VCP_CONFIG` — override the local config file (default `~/.config/vcp/config.json`).
- `VCP_TMP_DIR` — override local temporary archive/extract storage (default `~/.cache/vcp`).
- `VCP_HFF_PY` — override the local `hff.py` path.
- `VCP_TRACEBACK=1` — show Python tracebacks while debugging.

## Installation / PATH

The repository-root `vcp` wrapper only resolves the repository location, loads the existing HFF virtual environment from `helpers_shell.sh`, and executes `bin/vcp.py`.

If the `pod-runtime` repository root is already on `PATH`, simply run `vcp`. Otherwise link it once:

```bash
ln -sfn ~/git/pod-runtime/vcp ~/.local/bin/vcp
```
