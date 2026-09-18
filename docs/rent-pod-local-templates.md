# Local `rent-pod` templates

`rent-pod` supports two template modes:

- **remote** profiles point at an existing RunPod template ID;
- **local** profiles describe the Pod directly and are expanded into the REST `POST /pods` request without creating or saving a RunPod template.

The canonical local config layout is:

```text
~/.config/rentpod/
├── templates.toml
├── gpu-aliases.toml
└── templates/
    ├── qwen3-captioning.toml
    ├── seedvr2-studio.toml
    └── comfyui-krea2.toml
```

For backward compatibility, if `~/.config/rentpod` does not exist but the old `~/.config/rent-pod` directory does, `rent-pod` continues to use the old directory. `RENT_POD_CONFIG_DIR` overrides the config root. `RENT_POD_TEMPLATES_FILE` and `RENT_POD_TEMPLATE_DIR` can override the registry and local-template directory independently.

## `templates.toml`

Keep global defaults and aliases for existing RunPod templates here:

```toml
version = 2
default = "qwen3-captioning"
template_dir = "templates"

[defaults]
container_disk_gb = 40
volume_gb = 100
volume_mount_path = "/workspace"
ports = ["22/tcp"]

[defaults.naming]
collision = "increment"

[defaults.env]
HF_XET_HIGH_PERFORMANCE = "1"

[defaults.secrets]
HF_TOKEN = "huggingface_token"

# Existing RunPod template: still supported.
[templates.legacy-comfy]
id = "abc123def4"
description = "Existing RunPod GUI template"

[templates.legacy-comfy.secrets]
HF_TOKEN = "huggingface_token"
```

`[defaults]`, `[defaults.env]`, and `[defaults.secrets]` are inherited by directory-backed local templates. A local template file overrides a default with the same key.

## Local template files

The filename is the profile name, so this file:

```text
~/.config/rentpod/templates/qwen3-captioning.toml
```

is selected with:

```bash
rent-pod l40s --template qwen3-captioning
```

Example:

```toml
description = "Qwen3 captioning development pod"
image = "runpod/pytorch:latest"

# Admission requirement: do not rent a host below this CUDA version.
min_cuda = "13.0"

# These override templates.toml defaults when present.
container_disk_gb = 60
ports = ["22/tcp", "8000/http", "8888/http"]

docker_start_cmd = ["sleep", "infinity"]

[naming]
pattern = "q3c"

[env]
PROJECT = "qwen3-captioning"
HF_HOME = "/workspace/.cache/huggingface"

[secrets]
HF_TOKEN = "huggingface_token"
OPENAI_API_KEY = "openai_key"
```

A local profile must define `image`. A remote profile defines `id`. Defining both is rejected.

### Pod naming

A template can define a human-readable Pod name independently of its RunPod
template ID or container image:

```toml
[naming]
pattern = "q3c"
collision = "increment"
```

With no existing collision, the Pod is named `q3c`. If `q3c` already
exists, rent-pod checks the account inventory before creation and selects the
first free suffix: `q3c-1`, `q3c-2`, and so on. RunPod itself permits
duplicate names; this uniqueness policy is intentionally enforced by rent-pod.

Directory-backed templates may inherit naming defaults from `templates.toml`:

```toml
[defaults.naming]
collision = "increment"
```

The per-template `[naming]` table overrides individual default keys.
`collision` supports `increment` (default), `allow`, and `error`.

Patterns may use `{template}`, `{uid}`, and `{date}`:

```toml
[naming]
pattern = "{template}-{uid}"
```

`{uid}` is a locally generated six-hex-character identifier. `{date}` uses
local `YYYYMMDD`. `{pod-id}` is deliberately unsupported because the RunPod
Pod ID does not exist until after the create request has already supplied the
name.

An explicit `--name NAME` always wins over template naming. During
`--dry-run`, rent-pod renders the base name without querying account Pods; the
collision check is performed only for a real launch.

### CUDA admission floor

`min_cuda` is rent-pod admission metadata, not a container environment variable or a REST `POST /pods` field. When present, `rent-pod` uses RunPod GraphQL `minCudaVersion` for both candidate selection and Pod creation, so the template cannot be scheduled onto a machine below that CUDA floor.

It can be specified on a directory-backed local template, inherited from `[defaults]`, or placed on an inline/remote `[templates.NAME]` profile. Keep it quoted as a version string:

```toml
min_cuda = "13.0"
```

CUDA precedence is:

```text
RENT_POD_CUDA_MIN
        ↓
template/default min_cuda
        ↓
--min-cuda VERSION
```

In other words, an explicit CLI value wins; otherwise the selected template wins over the controller-wide environment default. Templates without `min_cuda` retain the existing `RENT_POD_CUDA_MIN` behavior.

Supported local Pod fields are:

| TOML key | RunPod `POST /pods` field |
| --- | --- |
| `image` | `imageName` |
| `container_disk_gb` | `containerDiskInGb` |
| `volume_gb` | `volumeInGb` |
| `volume_mount_path` | `volumeMountPath` |
| `ports` | `ports` |
| `docker_entrypoint` | `dockerEntrypoint` |
| `docker_start_cmd` | `dockerStartCmd` |
| `min_vcpu_per_gpu` | `minVCPUPerGPU` |
| `min_ram_per_gpu_gb` | `minRAMPerGPU` |
| `network_volume_id` | `networkVolumeId` |
| `container_registry_auth_id` | `containerRegistryAuthId` |
| `global_networking` | `globalNetworking` |

GPU, GPU count, cloud, network admission floors, name, and other rental-specific values remain owned by the `rent-pod` command and are layered on top of the local template. `min_cuda` is the exception deliberately supported as template admission metadata because it describes an image/runtime compatibility requirement rather than a particular rental request.

## RunPod secrets

Never put secret values in these files. Create the secret in the RunPod account, then map the desired container environment variable to the **secret name**:

```toml
[secrets]
HF_TOKEN = "huggingface_token"
CIVITAI_TOKEN = "civitai_token"
```

At the Pod-create boundary `rent-pod` converts those to RunPod's native references:

```text
HF_TOKEN={{ RUNPOD_SECRET_huggingface_token }}
CIVITAI_TOKEN={{ RUNPOD_SECRET_civitai_token }}
```

RunPod substitutes the encrypted values when the Pod starts. `rent-pod` logs the binding as a secret reference rather than displaying a value.

A one-off `--env KEY=VALUE` still overrides a profile/default value, including a secret binding, but sensitive-looking environment names are masked in `rent-pod` status output.

## Inspect before renting

List local and remote profiles:

```bash
rent-pod --list-templates
```

Inspect the complete Pod-create request without spending money:

```bash
rent-pod l40s --template qwen3-captioning --dry-run
```

For a local template, the dry-run payload contains `imageName` and the direct Pod settings and does **not** contain a `templateId`. Secret references appear only as `{{ RUNPOD_SECRET_name }}` placeholders, never as secret values.
