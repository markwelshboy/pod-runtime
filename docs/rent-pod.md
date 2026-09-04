# `rent-pod`: RunPod rental + network qualification

`rent-pod` automates the disposable-development-pod admission loop:

1. Query live RunPod inventory/pricing when requested.
2. Rent a Pod from an existing template.
3. Apply RunPod's advertised bandwidth and optional CUDA floors before allocation.
4. Report the assigned machine, datacenter, location, cost, advertised bandwidth, and SSH endpoint.
5. Avoid recently rejected machine IDs or public IPs before waiting for the container when RunPod exposes that identity early enough.
6. Track startup through RunPod's REST machine state plus GraphQL runtime/port telemetry.
7. Distinguish direct-TCP exposure, SSH-banner readiness, and authenticated SSH before provisioning.
8. Run the normal `provision` command, including real Hugging Face and PyPI/CDN qualification.
9. If `provision` exits `78` for a critically slow network, record the host locally and terminate the Pod.
10. Retry only when the caller explicitly requests more than one attempt.
11. Show account balance/runway and show, watch, and delete Pods from the same CLI.

The default RunPod template is `86n5dpgf7h`. Override it with `--template`, `RENT_POD_TEMPLATE`, or the older `RUNPOD_TEMPLATE_ID` setting.

## Authentication

The helper never stores or prints the RunPod API key. Export it in the local shell:

```bash
export RUNPOD_API_KEY='...'
```

`provision` still requires the normal local `HF_TOKEN`. `--list`, `--balance`, `--show`, `--status`, `--watch`, `--kill`, `--kill-all`, `--help`, and `--dry-run` do not require `HF_TOKEN`; live RunPod operations require `RUNPOD_API_KEY`.

## Live availability and pricing

The default pool is Secure Cloud. Query selected GPUs with the same 500/100 Mbps route floors used for rental:

```bash
rent-pod --list "4090 5090 l40s"
```

Query Community Cloud instead:

```bash
rent-pod --community --list "4090 5090 l40s"
```

Add a CUDA floor to the availability query:

```bash
rent-pod --list "4090 5090 l40s" --min-cuda 13.0
```

With no GPU list, `--list` displays all RunPod GPU types:

```bash
rent-pod --list
```

The listing uses RunPod's live GraphQL `lowestPrice` availability with the selected pool, public-IP requirement, bandwidth floors, and optional `minCudaVersion`. It shows stock status, current on-demand price, available GPU counts, and the route floor represented by the current offer.

## Account balance

Show the prepaid RunPod balance and current account-wide burn rate:

```bash
rent-pod --balance
```

The command uses RunPod's GraphQL `myself` account fields and reports:

```text
[rent-pod] RunPod account
           balance:          $18.42
           current spend:    $0.740/hr
           spend limit:      $80.00/hr
           runway:           1d 0h 53m
```

`runway` is `balance / currentSpendPerHr`. If RunPod reports no current spend, it is shown as `∞ (no current spend)`. `--balance` is read-only, requires only `RUNPOD_API_KEY`, and cannot be combined with rental options.

## Pod management

Show every Pod currently on the RunPod account:

```bash
rent-pod --show
```

The table includes the Pod ID, name, desired status, GPU, hourly cost, datacenter, and SSH endpoint when RunPod exposes them.

Take one live lifecycle snapshot of a Pod:

```bash
rent-pod --status <POD_ID>
```

Continuously watch startup until SSH is reachable:

```bash
rent-pod --watch <POD_ID>
```

`--watch` is observational only. Ctrl-C stops the watch and never deletes, stops, or provisions the Pod.

Permanently delete one Pod:

```bash
rent-pod --kill <POD_ID>
```

Permanently delete every Pod on the account:

```bash
rent-pod --kill-all
```

`--kill-all` is intentionally interactive and requires typing `DELETE ALL`. For deliberate non-interactive cleanup:

```bash
rent-pod --kill-all --yes
```

`-y` and `--force` are accepted aliases for `--yes` on `--kill-all`. These management commands are independent of the rental CUDA/cloud/bandwidth defaults.

## Startup lifecycle display

RunPod's REST Pod response identifies the allocated machine but does not expose live container runtime telemetry. `rent-pod` therefore mirrors RunPod's own current CLI architecture: REST supplies the Pod/machine state and a small GraphQL `myself.pods` side-call supplies `runtime.uptimeInSeconds` and live runtime ports.

A normal rental now progresses through output like:

```text
[rent-pod] Pod allocated
           pod: m6ona2ghiq29f6
           machine: a601chw8r0jh
           advertised: 4752↓ / 10072↑ Mbps
           disk: 3276 MB/s
           cost: $0.740/hr

[rent-pod] STARTING   00:18   (14:42 startup remaining)
           image/container runtime: waiting
           public IP: pending
           SSH mapping: pending

[rent-pod] CONTAINER  01:04   (02:58 SSH exposure remaining)
           runtime uptime: 00:02
           public IP: pending
           SSH mapping: pending

[rent-pod] NETWORK    01:11   (02:51 SSH exposure remaining)
           runtime uptime: 00:09
           public IP: 123.x.x.x
           SSH mapping: 123.x.x.x:38192
           TCP/38192: pending
           SSH banner: pending
           SSH auth: not probed

[rent-pod] NETWORK    01:18   (02:44 SSH exposure remaining)
           runtime uptime: 00:16
           public IP: 123.x.x.x
           SSH mapping: 123.x.x.x:38192
           TCP/38192: reachable
           SSH banner: pending
           SSH auth: not probed

[rent-pod] SSH        01:24   (02:38 SSH exposure remaining)
           runtime uptime: 00:22
           public IP: 123.x.x.x
           SSH mapping: 123.x.x.x:38192
           TCP/38192: reachable
           SSH banner: ready
           SSH auth: pending

[rent-pod] SSH        01:31   (02:31 SSH exposure remaining)
           runtime uptime: 00:29
           public IP: 123.x.x.x
           SSH mapping: 123.x.x.x:38192
           TCP/38192: reachable
           SSH banner: ready
           SSH auth: ready
[rent-pod] SSH is ready.

[rent-pod] QUALIFYING 01:31
           HF/CDN: pending
           PyPI/CDN: pending
```

The lifecycle states mean:

- `STARTING`: RunPod has allocated the Pod/machine but GraphQL still reports `runtime: null`; this covers image pull, extraction, container creation, and boot because RunPod exposes no finer public enum for those phases.
- `CONTAINER`: runtime telemetry exists, so the container is alive, but a public direct-SSH mapping is not yet exposed.
- `NETWORK`: a public mapping for container TCP/22 exists. `rent-pod` separately tests whether the external TCP mapping is actually reachable and whether an SSH server banner is present.
- `SSH`: an SSH banner is visible; authenticated SSH is then tested using the configured key.
- `QUALIFYING`: authenticated SSH is usable and the normal `provision` HF/PyPI qualification is starting.

RunPod can change the external mapping for container port 22 while a Pod is starting. `rent-pod` therefore probes both the current GraphQL runtime mapping and any different REST mapping, and retains recently seen mappings for 90 seconds. If an older mapping becomes usable while API surfaces are reconciling, it can still be selected for provisioning.

State transitions print immediately. An unchanged state prints a heartbeat every 60 seconds, so a long image pull or SSH-exposure delay is visible without dumping a block every five seconds.

If the GraphQL runtime side-call temporarily fails, `rent-pod` degrades to REST state and reports the runtime-probe error rather than treating the Pod as dead.

## Two-stage startup timeout policy

Startup now has two separate clocks:

1. Before runtime exists, `--startup-timeout` / `RENT_POD_STARTUP_TIMEOUT` controls how long an image/container may take to appear. The default is 900 seconds (15 minutes).
2. Once GraphQL reports a live runtime, image/container startup has succeeded. The startup clock is replaced by a shorter direct-SSH exposure clock controlled by `--ssh-exposure-timeout` / `RENT_POD_SSH_EXPOSURE_TIMEOUT`. The default is 180 seconds (3 minutes).

The SSH-exposure clock is based on RunPod's reported `runtime.uptimeInSeconds`, so a delayed polling/API response does not grant an already-running container a fresh three-minute window.

If runtime never appears, the rejection reason is `startup-timeout`. If runtime is alive but direct authenticated SSH never becomes usable, the rejection reason is `ssh-exposure-timeout`.

## Typical use

Inspect the request without spending money:

```bash
rent-pod 4090 --dry-run
```

Rent one RTX 4090 candidate from Secure Cloud and keep it only if it passes provisioning/network qualification:

```bash
rent-pod 4090
```

Use Community Cloud for one rental:

```bash
rent-pod --community 4090
```

Require CUDA 13.0 or newer:

```bash
rent-pod 4090 --min-cuda 13.0
```

Override the post-container SSH exposure window for one rental:

```bash
rent-pod l40s --ssh-exposure-timeout 240
```

The Pod REST API currently accepts a list of `allowedCudaVersions` rather than a minimum. `rent-pod` derives the allowed list from the requested floor. For example, `--min-cuda 12.8` currently sends `13.0`, `12.9`, and `12.8`; `--min-cuda 13.0` sends only `13.0`. The older `--cuda-min` spelling remains accepted as a deprecated compatibility alias.

Try up to five candidates, automatically deleting network-rejected candidates before trying again:

```bash
rent-pod 4090 --attempts 5 --min-cuda 13.0
```

Other built-in aliases include `5090`, `l40s`, `l40`, `5080`, and `3090`. An exact RunPod GPU type string may also be supplied.

After a pod is accepted:

```bash
configure-pod qwen3-captioning --snapshot latest
```

## Persistent environment defaults

Shell variable names cannot contain `-`, so use the `RENT_POD_*` namespace. Command-line options always override these values.

For example:

```bash
export RENT_POD_CUDA_MIN="13.0"
export RENT_POD_MIN_DOWNLOAD="500"
export RENT_POD_MIN_UPLOAD="100"
export RENT_POD_SSH_EXPOSURE_TIMEOUT="180"
```

Then both listing and rental inherit the normal selection defaults, while the SSH exposure value is applied when a rented Pod reaches live-container state.

Available persistent defaults:

```text
RENT_POD_CUDA_MIN
RENT_POD_TEMPLATE
RENT_POD_CLOUD                 # SECURE or COMMUNITY
RENT_POD_COMMUNITY             # true/yes/1/on shorthand
RENT_POD_MIN_DOWNLOAD
RENT_POD_MIN_UPLOAD
RENT_POD_MIN_DISK
RENT_POD_STARTUP_TIMEOUT
RENT_POD_SSH_EXPOSURE_TIMEOUT
RENT_POD_POLL_SECONDS
RENT_POD_RETRY_DELAY
RENT_POD_REJECTION_TTL_HOURS
RENT_POD_SSH_KEY
```

Examples:

```bash
export RENT_POD_CUDA_MIN="13.0"
export RENT_POD_CLOUD="SECURE"
export RENT_POD_STARTUP_TIMEOUT="1200"
export RENT_POD_SSH_EXPOSURE_TIMEOUT="180"
```

or, for a shell/profile that normally uses Community Cloud:

```bash
export RENT_POD_COMMUNITY=true
```

`--attempts`, `--keep-failed`, and `--no-provision` intentionally remain CLI-only because they directly affect paid retry/cleanup behavior.

## Defaults

- template: `86n5dpgf7h`
- cloud: `SECURE`
- minimum advertised download: `500 Mbps`
- minimum advertised upload: `100 Mbps`
- CUDA floor: none unless `--min-cuda` / `RENT_POD_CUDA_MIN` is supplied
- pre-container startup timeout: `900 seconds` (15 minutes)
- post-container direct-SSH exposure timeout: `180 seconds` (3 minutes)
- recently seen SSH mapping grace: `90 seconds`
- attempts: `1`
- SSH key: `~/.ssh/id_ed25519_runpod`
- rejected-host TTL: `24 hours`
- rejection database: `~/.cache/pod-runtime/rent-pod-rejections.json`

The 15-minute startup default is intentionally longer than the original 10-minute limit because an uncached RunPod image can spend much of the first 5–10 minutes downloading/extracting before runtime exists. Once runtime appears, the shorter SSH-exposure policy avoids spending another 15 minutes on a Pod whose container is alive but whose direct SSH/NAT path is broken.

`--community` is the short override for `--cloud COMMUNITY`. The legacy explicit `--cloud SECURE|COMMUNITY` option remains available.

RunPod's advertised bandwidth is only a scheduler pre-filter. It does not replace the real service-specific qualification performed by `provision`: a machine can advertise gigabit networking while having a pathological route to `files.pythonhosted.org`.

## Failure behavior

A pod is automatically terminated when:

- the same machine ID or public IP was rejected within the configured TTL;
- runtime never appears before `--startup-timeout`;
- runtime is alive but direct authenticated SSH does not become usable before `--ssh-exposure-timeout`; or
- `provision` exits `78`, meaning the real HF/PyPI qualification recommends replacing it.

For a non-network `provision` failure, the pod is deliberately left running for diagnosis. Use `--keep-failed` to keep even network-rejected, startup-timed-out, or SSH-exposure-timed-out pods.

`Ctrl-C` destroys the in-flight pod by default. `--keep-failed` also disables that cleanup.

## Useful options

```text
--list ["GPU GPU ..."]
--balance
--show
--status POD_ID
--watch POD_ID
--kill POD_ID
--kill-all [--yes|-y|--force]
--community
--min-cuda VERSION
--attempts N
--min-download MBPS
--min-upload MBPS
--min-disk MB_PER_SEC
--cloud COMMUNITY|SECURE
--startup-timeout SECONDS
--ssh-exposure-timeout SECONDS
--rejection-ttl-hours HOURS
--allow-seen-machine
--keep-failed
--no-provision
--ssh-key PATH
```

`--cuda-min VERSION` remains accepted as a deprecated compatibility alias for `--min-cuda VERSION`.

Other environment/configuration variables retained for compatibility or API plumbing:

```text
RUNPOD_API_KEY
RUNPOD_TEMPLATE_ID
RUNPOD_SSH_KEY
RUNPOD_API_BASE
RUNPOD_GRAPHQL_URL
RUNPOD_RENT_STATE_FILE
RUNPOD_USER_AGENT
```
