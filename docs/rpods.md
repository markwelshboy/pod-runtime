# `rpods`: reconnect and PixlStash ↔ ComfyUI tunnel

`rpods` lists SSH-ready RunPod Pods and opens a shell to a chosen Pod. Its
`--tunnel pixlstash` mode instead creates a **foreground, bidirectional SSH
tunnel** between PixlStash Desktop on ddraigPC (Windows), the SSH client in
WSL2, and ComfyUI on RunPod.

## Quick start

Start PixlStash Desktop and the selected ComfyUI instance on RunPod, then run:

```bash
rpods --tunnel pixlstash
```

Pick a Pod by number, name, or ID as in regular `rpods`. To skip the selector:

```bash
rpods rp-krea2-wait-2 --tunnel pixlstash
```

Defaults match the previously linked ddraigPC setup:

| Connection | Source | Destination |
| --- | --- | --- |
| ComfyUI forward (`-L`) | WSL `127.0.0.1:47960` (also reachable by Windows) | RunPod `127.0.0.1:8288` (GPU0) |
| PixlStash reverse (`-R`) | RunPod `127.0.0.1:64404` | Currently running Windows PixlStash REST API port (autodetected) |

**Important:** `64404` is the **remote** port already saved in the PixlStash
nodes' ComfyUI settings after linking. It must remain stable even if the
**local** Electron backend selects a new port at the next PixlStash launch.
If you linked a different port in ComfyUI, specify
`--pixlstash-remote-port <that-port>` instead.

The local ComfyUI address configured in PixlStash stays
`http://127.0.0.1:47960/`, regardless of RunPod's changing public IP or
assigned SSH port. The existing Pod selection and API v2 detection choose
the correct remote SSH endpoint.

## How the PixlStash port is discovered

The desktop app's HTTP server chooses an ephemeral local port when it starts.
`rpods` probes `GET /version` and verifies
`{"message":"PixlStash REST API", ...}`, rather than tunneling an arbitrary
service that happens to own a port.

From WSL2 it enumerates Windows loopback listeners using
`powershell.exe Get-NetTCPConnection`, checks native Linux listeners via
`ss`, and also checks the previously linked port and the server's default
port. It **only probes localhost**, and does not expose the PixlStash API
directly on the network.

If automatic discovery fails, obtain the port from the PixlStash desktop
connection error/URL and supply it explicitly:

```bash
rpods --tunnel pixlstash --pixlstash-port 64404
# or: export PIXLSTASH_API_PORT=64404
```

The override is validated against `/version` before starting SSH.

If PixlStash Desktop restarts while the tunnel is running, **restart
`rpods --tunnel pixlstash` too** so the `-R` destination follows its new
local port. The existing remote ComfyUI endpoint stays on the fixed
`64404` port and does not need to change.

## Other ComfyUI / port selections

Use the pod's main ComfyUI on port 8188 while keeping PixlStash's local
address unchanged:

```bash
rpods --tunnel pixlstash --comfy-port 8188
```

Or use a different *local* ComfyUI port:

```bash
rpods --tunnel pixlstash --local-port 18188 --comfy-port 8188
```

This changes PixlStash's configured ComfyUI address to
`http://127.0.0.1:18188/`.

All tunnel options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--tunnel pixlstash` | off | Bidirectional tunnel instead of a shell |
| `--local-port PORT` | `47960` | Windows/WSL local ComfyUI URL port |
| `--comfy-port PORT` | `8288` | Target ComfyUI port **inside** RunPod |
| `--pixlstash-port PORT` | autodetect | Current Windows PixlStash REST API port |
| `--pixlstash-remote-port PORT` | `64404` | Fixed port already linked in the ComfyUI node settings |
| `--ssh-key PATH` | `RENT_POD_SSH_KEY` / `RUNPOD_SSH_KEY` | SSH identity |

## Verification and troubleshooting

The command:

1. Discovers the API on local `/version`.
2. Starts SSH with `-N -T`, loopback-only `-L` and `-R`,
   `ExitOnForwardFailure=yes`, and SSH keepalives.
3. Tests local `http://127.0.0.1:47960/system_stats` (forward).
4. Uses a second SSH session to run `curl` against
   `http://127.0.0.1:64404/version` **inside RunPod** (reverse).
5. Keeps the tunnel in the foreground until `Ctrl+C`.

The remote probe needs `curl` inside the pod; if it fails, the tunnel is
left active for diagnosis (e.g. while ComfyUI starts).

**Already forwarding port 47960?** Close any previous SSH tunnel before
starting `rpods --tunnel pixlstash`. SSH fails with
`ExitOnForwardFailure` if the local or remote bind is occupied.

Manual checks:

```bash
# WSL: local forwarded ComfyUI
curl -sS http://127.0.0.1:47960/system_stats

# RunPod: reverse forwarded Windows PixlStash
curl -sS http://127.0.0.1:64404/version
```

Windows can generally reach the local WSL forwarding through
`localhost` forwarding, as confirmed on ddraigPC. On other hosts,
Windows-to-WSL forwarding may need separate configuration.

**Security:** Each forwarding listener is explicitly bound to
`127.0.0.1`. No public port is opened. The ComfyUI PixlStash API token
remains in its existing node settings and is never printed by `rpods`.
Anyone able to execute code *inside the rented pod* can nevertheless reach
the reverse-forwarded local PixlStash API, so use Pods you trust.

Normal `rpods`, `rpods --list` and `rpods POD_NAME` retain their usual
SSH-shell behavior.


## Ollama / VLM SSH tunnel (RunPod to DdraigPC)

No RunPod HTTP proxy or public port is needed. Ollama provides an
unauthenticated HTTP API and **must remain bound to 127.0.0.1 on the pod**.
The existing rpods SSH connection can forward it to loopback on
DdraigPC while preserving PixlStash-to-ComfyUI connectivity.

### One combined SSH session

~~~bash
rpods --tunnel pixlstash vlm
~~~

Pick the pod as usual. This creates ONE tunnel session with:

| Link | DdraigPC / WSL2 | RunPod |
| --- | --- | --- |
| ComfyUI forward | 127.0.0.1:47960 | 127.0.0.1:8288 |
| Ollama forward | 127.0.0.1:47961 | 127.0.0.1:11434 |
| PixlStash reverse | Current local PixlStash API (autodiscovered) | Fixed 127.0.0.1:64404 |

For Ollama without PixlStash (no desktop app required):

~~~bash
rpods --tunnel vlm
~~~

Target a particular pod without the selector:

~~~bash
rpods rp-krea2-wait-1 --tunnel pixlstash vlm
~~~

Customize ports if needed:

~~~bash
rpods --tunnel pixlstash vlm --ollama-local-port 11500 --ollama-port 11434
~~~

The Ollama local port defaults to **47961** to avoid collisions with
a local Ollama on its usual 11434 port. The command tests Ollama's
/api/version endpoint. If no response, it warns; on the pod, run
start-ollama. The tunnel remains active until Ctrl+C.

Verify from WSL:

~~~bash
curl -fsS http://127.0.0.1:47961/api/version
curl -fsS http://127.0.0.1:47961/api/tags
~~~

A local Image Playground analyzer can use the base address
http://127.0.0.1:47961 as long as the tunnel is active. Forwarding the
API does NOT automatically transfer datasets or start VLM analysis.

### Upload the Image Playground analysis skill ZIP

Download the **VLM + head-pose + gaze benchmark ZIP** from Image Playground
Refine, then, from WSL, upload that ZIP with the same rpods pod selector:

~~~bash
rpods --skills-zip "/path/on/ddraigPC/image-detailer-analysis.zip"
~~~

This uploads and exits. The ZIP is checked locally for known skill and
benchmark paths, unsafe entries and size limits; it is streamed directly
over the selected pod's ordinary SSH connection. Remote Python installs
it under /workspace/vlm-skills. No extra SSH key, public upload endpoint
or separate SCP/VCP configuration is needed.

You can upload before opening the combined tunnel:

~~~bash
rpods --tunnel pixlstash vlm \
  --skills-zip "/path/on/ddraigPC/image-detailer-analysis.zip"
~~~

The upload runs **once** before the long-running foreground tunnel.
An upload failure cancels tunnel startup. Existing files at the same
paths are replaced, but unrelated skill files are left alone.
Keep using VCP for large image datasets and batch results; the direct
rpods ZIP operation is deliberately limited to small skill bundles.

**Storage warning:** The installer uses /workspace/models/ollama and
/workspace/vlm-skills. Those directories are only persistent when backed
by suitable RunPod storage. Replacing an ephemeral pod may still lose
model caches, skills, original images and analysis outputs, regardless
of SSH tunnel settings.

### Provisioning with ENABLE_VLM=true

start.sh now calls the installer **once**. The installer downloads the
selected instruct model just once, and optionally the Gaze360 checkpoint.
The duplicate unconditional pulls previously present in start.sh and
install_comfy_vlm.sh have been removed.

| Variable | Default | Meaning |
| --- | --- | --- |
| ENABLE_VLM | false | Install and start VLM stack |
| VLM_MODEL | qwen3-vl:8b-instruct | Model to pull |
| VLM_INSTALL_GAZE | true | Optional research-only Gaze360 SafeTensors checkpoint |
| VLM_INSTALL_OPENCODE | true | Install OpenCode integration |
| VLM_INSTALL_NODE | true | Install optional ComfyUI Ollama node |

Ollama remains on pod loopback 127.0.0.1:11434. Provisioning checks
/api/version after installation and reports installer failures explicitly,
rather than silently ignoring them. The installer stays idempotent.


## Image Playground: remote batch worker and hybrid image transport

With ENABLE_VLM=true and VLM_ENABLE_WORKER=true (default), pod-runtime
starts the standalone VLM worker on **127.0.0.1:8765**, beside the existing
Ollama server. No custom ComfyUI node or ComfyUI process is involved.

One SSH connection now contains four loopback-only mappings:

| Channel | Local (DdraigPC) | RunPod |
| --- | --- | --- |
| ComfyUI | 127.0.0.1:47960 | 127.0.0.1:8288 |
| Ollama | 127.0.0.1:47961 | 127.0.0.1:11434 |
| Analysis worker | **127.0.0.1:47962** | **127.0.0.1:8765** |
| PixlStash reverse | current desktop API | fixed 127.0.0.1:64404 |

Connection:

~~~bash
rpods --tunnel pixlstash vlm
~~~

Or omit PixlStash entirely:

~~~bash
rpods --tunnel vlm
~~~

Check:

~~~bash
curl -fsS http://127.0.0.1:47962/health
curl -fsS http://127.0.0.1:47961/api/version
~~~

Image Playground → Refine → AI Suggestions now has Analyze selected and
Analyze all kept. Choose transfer mode Auto, Direct, or VCP/Hugging Face,
the VCP target, and whether geometry is enabled. The original images and
sidecars are never modified.

1. Image Playground downsizes selected originals to JPEG 1024px long edge,
   retaining exact mappings and SHA256 digests locally. That is a speed/
   quality tradeoff for analysis, not a substitute for original pixels.
2. For **fewer than 80 images AND under 24 MiB of staged previews**, Auto
   sends one ZIP over the SSH tunnel. No per-image HTTP requests.
3. At **80+ images OR 24+ MiB**, Auto uses the existing named-target VCP
   controller: **DdraigPC → Hugging Face scratch → RunPod**. The worker
   accepts the ZIP in /workspace/vlm-worker/uploads/. VCP's HF scratch
   cleanup runs after successful transfer. The local app requires a
   configured VCP target and rejects a known pod-ID mismatch with the
   worker tunnel. If VCP is unconfigured, Auto falls back to direct
   transfer with a visible warning; explicit VCP mode fails instead.
4. The worker runs /usr/local/bin/vlm-skill (Qwen3-VL V3), followed
   optionally by MediaPipe head pose, L2CS gaze and fusion if corresponding
   models/dependencies are available. If geometry cannot run, Qwen
   condition suggestions still return.
5. Worker status/progress is returned via GET /jobs/<id>, and the final
   **small JSON** via GET /jobs/<id>/results (no large RunPod→home transfer).
   Image Playground saves results in its local
   DATA_DIR/vlm_jobs/<id>/results.json then imports them as **pending
   suggestions**. Previously accepted tags or suggestions are not
   overwritten.
6. Review/correct/accept tags in Image Playground. Only accepted tags
   go into ComfyUI sidecars. No automatic detailer launch.

If the pod uses an older pod-runtime, update the runtime and restart the
pod or start the worker explicitly (assuming installed):

~~~bash
/opt/venv/bin/python /usr/local/bin/vlm-worker --root /workspace/vlm-worker --port 8765
~~~

The worker is stdlib-only; geometry tools run under /opt/venv/bin/python
when installed. It loads the skills ZIP from /workspace/vlm-skills,
uploaded via rpods --skills-zip. Active skill:
image-detailer-analysis (V3). MediaPipe task model:
 /workspace/models/mediapipe/face_landmarker.task
L2CS SafeTensors checkpoint:
 /workspace/models/gaze/l2cs_gaze360_resnet50.safetensors

**HF privacy caution:** VCP stages images to the configured HF scratch
dataset. Use a PRIVATE scratch repository with access controls, and
verify retention/cleanup. Interrupted transfers may leave a scratch
artifact needing manual deletion. Confirm that the named VCP target
points to the same pod as the tunnel; pod-ID comparison is performed
when both sides report IDs.

Image Playground retains local results across pod replacements.
Pod-side /workspace/vlm-worker survives only if backed by persistent
storage. Interrupted jobs are marked interrupted on worker startup.

### Python interpreter selection on venv-only GPU containers

ComfyUI GPU images often provide `/opt/venv/bin/python` without a
`python3` executable on the SSH command PATH. The skills-ZIP uploader
now probes an executable Python >=3.10, preferring
`/opt/venv/bin/python` and falling back to common system interpreters.
Neither `rpods --skills-zip` nor the remote unpacker needs a globally
installed `python3`.

The VLM installer uses the same preference and patches the *installed*
`/usr/local/bin/vlm-skill` shebang to that interpreter, so the CLI
also works when invoked directly. The standalone worker uses that
validated interpreter for its service process and its Qwen subprocess;
geometry uses `/opt/venv/bin/python` by default. You can explicitly set
`VLM_PYTHON` for the installer or `VLM_WORKER_PYTHON` for the worker
when your image uses a different interpreter. Both must be Python >=3.10.

To check an existing pod before restarting the VLM worker:

~~~bash
/opt/venv/bin/python --version
head -n 1 /usr/local/bin/vlm-skill
curl -fsS http://127.0.0.1:8765/health
~~~

If the installed runner still uses an `env python3` shebang, re-run the
updated VLM installer; the current pod's automatic provision/start phase
may have run before this fix. For immediate recovery, launch the worker
with the explicit venv interpreter as shown above. Never expose its
unauthenticated HTTP endpoint on a public RunPod port.

### Dual-image batch format: original-pixel head crop + full-frame geometry

Updated Image Playground sends a v2 ZIP containing up to two JPEGs
per opaque image ID. The first, under faces/, is an expanded 768px
head crop made from ORIGINAL full-resolution source pixels on
DdraigPC. The second, under images/, is the existing 1024px
full-scene preview. Qwen3-VL uses faces/ if the head was detected;
YuNet/MediaPipe and L2CS use the full-scene images/ as before.
For genuine YuNet misses Qwen uses the same full-scene fallback.

The worker checks each face/full-frame SHA256, rejected unlisted
members and sizes, and builds qwen_images/ as hardlinks to avoid
a second disk copy. Legacy v1 single-image ZIPs remain accepted
and run as before. Per-image crop status is returned as read-only
analysis_input metadata and crop_counts are available in the worker
job status. No new ComfyUI node is required.

For upgrades to an already-running pod, update pod-runtime, replace
/usr/local/bin/vlm-worker and restart its process on loopback port
8765. This does not modify Ollama or existing stored jobs.
The VLM worker's dependency remains Python standard library only:
YuNet/Pillow/OpenCV are used during ORIGINAL-PIXEL staging on
DdraigPC, while the existing pod geometry scripts keep their
independent /opt/venv environment.
