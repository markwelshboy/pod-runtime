# `vcp` — Hugging Face accelerated local↔pod copy

`vcp` copies files and directories between the machine where it is run and a configured SSH target. It uses a Hugging Face dataset as a temporary high-speed hop.

The command is intentionally **local-controller only**: run it on ddraig (or another machine that can SSH to the pod). The pod never needs an SSH route back to the local machine.

## Path syntax

Remote paths are prefixed with `r:` and must be absolute:

```bash
r:/workspace/report.txt
r:/workspace/logs
```

Paths without `r:` are local paths and can be relative or absolute.

All source operands for one copy must be on the same side, and the destination must be on the other side.

## Named SSH targets

VCP can keep multiple pod SSH endpoints in `~/.config/vcp/config.json` rather than treating the remote as a singleton.

Configure named targets:

```bash
vcp config l40development ssh -i ~/.ssh/id_ed25519_runpod -p 12234 root@199.199.88.88
vcp config rtx6000comfy ssh -i ~/.ssh/id_ed25519_runpod -p 13345 root@200.100.50.25
```

List them:

```bash
vcp targets
```

Set the persistent active target:

```bash
vcp target l40development
```

Show the current active target:

```bash
vcp target
```

Normal transfers use the active target:

```bash
vcp r:/workspace/report.txt .
```

Or select a target for one operation without changing the active target:

```bash
vcp --target rtx6000comfy r:/workspace/report.txt .
```

Inspect or remove an individual target:

```bash
vcp config l40development show
vcp config l40development remove
```

A target entry can also contain metadata such as a RunPod pod ID, provider, machine ID, and description. `rent-pod --vcp` populates that metadata automatically.

The previous single-endpoint form remains supported for backward compatibility:

```bash
vcp config ssh -i ~/.ssh/id_ed25519 -p 12234 root@199.199.88.88
```

When no named active target exists, VCP falls back to that legacy top-level SSH endpoint.

Inspect the current configuration and target registry:

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

## `rent-pod` integration

A successful `rent-pod` direct-SSH admission always prints the exact named VCP configuration command for the endpoint that actually passed authenticated SSH. Supplying a RunPod name makes the handoff especially readable:

```bash
rent-pod l40s --name comfydev --template comfyui-inference
```

For example:

```text
[rent-pod] VCP target:
           vcp config comfydev ssh -i /home/user/.ssh/id_ed25519_runpod -p 13479 root@64.247.206.216
           vcp target comfydev
```

This uses the proven live endpoint rather than assuming a later REST port mapping is authoritative. It is only printed after authenticated direct SSH works.

To register that target automatically after the pod also passes normal provision and HF/PyPI network qualification, add `--vcp`:

```bash
rent-pod l40s --name comfydev --template comfyui-inference --vcp
```

On success VCP stores a `comfydev` target containing the working SSH arguments plus the RunPod pod ID and available machine metadata, and makes it the active target. The automatic mutation is deliberately deferred until provision succeeds, so a pod that is subsequently rejected and deleted never replaces the existing active target. A VCP configuration failure is reported as a warning and does not reject or delete an otherwise accepted paid pod.

If `--name` is omitted, `rent-pod` uses a stable available pod identifier for the VCP target name.

`--vcp` only configures the SSH target. It does not copy or persist a Hugging Face token: VCP continues to use the local controller's `HF_TOKEN` ephemerally when an actual transfer runs.

## Copy from pod to local

```bash
vcp r:/workspace/report.txt r:/workspace/logs .
```

The local controller:

1. SSHes to the selected pod.
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
3. SSHes to the selected pod.
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

The repository-root `vcp` wrapper resolves the repository location, loads the existing HFF virtual environment from `helpers_shell.sh`, and executes the target-aware `bin/vcp_entry.py`, which delegates transfers to `bin/vcp.py`.

If the `pod-runtime` repository root is already on `PATH`, simply run `vcp`. Otherwise link it once:

```bash
ln -sfn ~/git/pod-runtime/vcp ~/.local/bin/vcp
```
