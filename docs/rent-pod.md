# `rent-pod`: RunPod rental + network qualification

`rent-pod` automates the disposable-development-pod admission loop:

1. Rent a RunPod Pod from an existing template.
2. Apply RunPod's advertised bandwidth floors before allocation.
3. Report the assigned machine, datacenter, location, cost, advertised bandwidth, and SSH endpoint.
4. Avoid recently rejected machine IDs or public IPs before waiting for the container when RunPod exposes that identity early enough.
5. Wait for the container image/startup and SSH mapping.
6. Run the normal `provision` command, including real Hugging Face and PyPI/CDN qualification.
7. If `provision` exits `78` for a critically slow network, record the host locally and terminate the Pod.
8. Retry only when the caller explicitly requests more than one attempt.

The default RunPod template is `86n5dpgf7h`. Override it with `--template` or `RUNPOD_TEMPLATE_ID`.

## Authentication

The helper never stores or prints the RunPod API key. Export it in the local shell:

```bash
export RUNPOD_API_KEY='...'
```

`provision` still requires the normal local `HF_TOKEN`.

## Typical use

Inspect the request without spending money:

```bash
rent-pod 4090 --dry-run
```

Rent one RTX 4090 candidate and keep it only if it passes provisioning/network qualification:

```bash
rent-pod 4090
```

Try up to five candidates, automatically deleting network-rejected candidates before trying again:

```bash
rent-pod 4090 --attempts 5
```

Other built-in aliases include `5090`, `l40s`, `l40`, `5080`, and `3090`. An exact RunPod GPU type string may also be supplied.

After a pod is accepted:

```bash
configure-pod qwen3-captioning --snapshot latest
```

## Defaults

- template: `86n5dpgf7h`
- cloud: `COMMUNITY`
- minimum advertised download: `500 Mbps`
- minimum advertised upload: `100 Mbps`
- startup/SSH timeout: `600 seconds`
- attempts: `1`
- SSH key: `~/.ssh/id_ed25519_runpod`
- rejected-host TTL: `24 hours`
- rejection database: `~/.cache/pod-runtime/rent-pod-rejections.json`

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

Environment overrides:

```text
RUNPOD_API_KEY
RUNPOD_TEMPLATE_ID
RUNPOD_SSH_KEY
RUNPOD_CLOUD_TYPE
RUNPOD_API_BASE
RUNPOD_RENT_STATE_FILE
```
