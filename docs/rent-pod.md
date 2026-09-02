# `rent-pod`: RunPod rental + network qualification

`rent-pod` automates the disposable-development-pod admission loop:

1. Query live RunPod inventory/pricing when requested.
2. Rent a Pod from an existing template.
3. Apply RunPod's advertised bandwidth and optional CUDA floors before allocation.
4. Report the assigned machine, datacenter, location, cost, advertised bandwidth, and SSH endpoint.
5. Avoid recently rejected machine IDs or public IPs before waiting for the container when RunPod exposes that identity early enough.
6. Wait for the container image/startup and SSH mapping.
7. Run the normal `provision` command, including real Hugging Face and PyPI/CDN qualification.
8. If `provision` exits `78` for a critically slow network, record the host locally and terminate the Pod.
9. Retry only when the caller explicitly requests more than one attempt.

The default RunPod template is `86n5dpgf7h`. Override it with `--template`, `RENT_POD_TEMPLATE`, or the older `RUNPOD_TEMPLATE_ID` setting.

## Authentication

The helper never stores or prints the RunPod API key. Export it in the local shell:

```bash
export RUNPOD_API_KEY='...'
```

`provision` still requires the normal local `HF_TOKEN`. `--list` and `--dry-run` do not require `HF_TOKEN`; live `--list` does require `RUNPOD_API_KEY`.

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
rent-pod --list "4090 5090 l40s" --cuda-min 13.0
```

With no GPU list, `--list` displays all RunPod GPU types:

```bash
rent-pod --list
```

The listing uses RunPod's live GraphQL `lowestPrice` availability with the selected pool, public-IP requirement, bandwidth floors, and optional `minCudaVersion`. It shows stock status, current on-demand price, available GPU counts, and the route floor represented by the current offer.

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
rent-pod 4090 --cuda-min 13.0
```

The Pod REST API currently accepts a list of `allowedCudaVersions` rather than a minimum. `rent-pod` derives the allowed list from the requested floor. For example, `--cuda-min 12.8` currently sends `13.0`, `12.9`, and `12.8`; `--cuda-min 13.0` sends only `13.0`.

Try up to five candidates, automatically deleting network-rejected candidates before trying again:

```bash
rent-pod 4090 --attempts 5 --cuda-min 13.0
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
```

Then both listing and rental inherit the CUDA floor automatically:

```bash
rent-pod --list "4090 5090 l40s"
rent-pod 4090
```

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
RENT_POD_POLL_SECONDS
RENT_POD_RETRY_DELAY
RENT_POD_REJECTION_TTL_HOURS
RENT_POD_SSH_KEY
```

Examples:

```bash
export RENT_POD_CUDA_MIN="13.0"
export RENT_POD_CLOUD="SECURE"
export RENT_POD_STARTUP_TIMEOUT="900"
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
- CUDA floor: none unless `--cuda-min` / `RENT_POD_CUDA_MIN` is supplied
- startup/SSH timeout: `600 seconds`
- attempts: `1`
- SSH key: `~/.ssh/id_ed25519_runpod`
- rejected-host TTL: `24 hours`
- rejection database: `~/.cache/pod-runtime/rent-pod-rejections.json`

`--community` is the short override for `--cloud COMMUNITY`. The legacy explicit `--cloud SECURE|COMMUNITY` option remains available.

RunPod's advertised bandwidth is only a scheduler pre-filter. It does not replace the real service-specific qualification performed by `provision`: a machine can advertise gigabit networking while having a pathological route to `files.pythonhosted.org`.

## Failure behavior

A pod is automatically terminated when:

- the same machine ID or public IP was rejected within the configured TTL;
- the container/SSH endpoint does not become usable before `--startup-timeout`; or
- `provision` exits `78`, meaning the real HF/PyPI qualification recommends replacing it.

For a non-network `provision` failure, the pod is deliberately left running for diagnosis. Use `--keep-failed` to keep even network-rejected or startup-timed-out pods.

`Ctrl-C` destroys the in-flight pod by default. `--keep-failed` also disables that cleanup.

## Useful options

```text
--list ["GPU GPU ..."]
--community
--cuda-min VERSION
--attempts N
--min-download MBPS
--min-upload MBPS
--min-disk MB_PER_SEC
--cloud COMMUNITY|SECURE
--startup-timeout SECONDS
--rejection-ttl-hours HOURS
--allow-seen-machine
--keep-failed
--no-provision
--ssh-key PATH
```

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
