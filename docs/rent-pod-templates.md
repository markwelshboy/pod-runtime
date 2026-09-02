# `rent-pod` named template profiles

`rent-pod` can map human-readable local profile names to RunPod template IDs.
The default registry location follows XDG conventions:

```text
~/.config/rent-pod/templates.toml
```

Set `RENT_POD_TEMPLATES_FILE` to use another file. If `XDG_CONFIG_HOME` is set,
the default is `$XDG_CONFIG_HOME/rent-pod/templates.toml`.

The registry is local configuration; it does not contain the RunPod API key.

## Example

```toml
version = 1
default = "comfyui-inference-lite"

[templates.comfyui-inference]
id = "replace-with-runpod-template-id"
description = "Full ComfyUI inference image"

[templates.comfyui-inference.env]
ENABLE_SAGE_UPLOAD = true
MINMAX = true

[templates.comfyui-inference-lite]
id = "86n5dpgf7h"
description = "Lean ComfyUI inference image"

[templates.comfyui-inference-lite.env]
ENABLE_SAGE_UPLOAD = false
MINMAX = false
```

TOML strings, numbers, and booleans in an `env` table are converted to strings
before they are sent in the Pod create request.

`default` is optional. When present, a rental without an explicit `--template`
uses that profile. Without a registry/default, the legacy RunPod template ID
`86n5dpgf7h` remains the fallback.

## Commands

List local profiles:

```bash
rent-pod --list-templates
```

Rent using a friendly profile name:

```bash
rent-pod --template comfyui-inference-lite
```

The usual positional GPU selection still works:

```bash
rent-pod 5090 --template comfyui-inference-lite
```

A raw RunPod template ID remains valid for backwards compatibility:

```bash
rent-pod 4090 --template 86n5dpgf7h
```

Override/add Pod environment variables for one rental:

```bash
rent-pod --template comfyui-inference-lite \
  --env "ENABLE_SAGE_UPLOAD=true;MINMAX=false"
```

`--env` can also be repeated:

```bash
rent-pod --template comfyui-inference-lite \
  --env ENABLE_SAGE_UPLOAD=true \
  --env MINMAX=false
```

Environment precedence is:

```text
RunPod template's normal configuration
        ↓
local profile env sent with the create request
        ↓
per-run --env values
```

Within the local create request, later/per-run values win. RunPod receives the
result as the Pod create `env` map together with the resolved `templateId`.

`--dry-run` resolves the friendly profile to its real template ID and prints the
effective environment overrides without creating a paid Pod.

## Built-in profile

Even when the TOML file does not exist, `rent-pod --list-templates` exposes a
built-in profile named `default`, mapped to `RUNPOD_TEMPLATE_ID` when set or
`86n5dpgf7h` otherwise. A local `[templates.default]` entry can replace it.
