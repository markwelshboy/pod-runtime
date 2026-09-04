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

# These override templates.toml defaults when present.
container_disk_gb = 60
ports = ["22/tcp", "8000/http", "8888/http"]

docker_start_cmd = ["sleep", "infinity"]

[env]
PROJECT = "qwen3-captioning"
HF_HOME = "/workspace/.cache/huggingface"

[secrets]
HF_TOKEN = "huggingface_token"
OPENAI_API_KEY = "openai_key"
```

A local profile must define `image`. A remote profile defines `id`. Defining both is rejected.

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

GPU, GPU count, cloud, CUDA versions, network admission floors, name, and other rental-specific values remain owned by the `rent-pod` command and are layered on top of the local template.

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
