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
