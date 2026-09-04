# rent-pod GPU names and aliases

`rent-pod` accepts four forms of GPU selector:

1. Built-in short aliases such as `4090`, `5090`, and `l40s`.
2. Exact display names printed in the left column of `rent-pod --list`, such as `RTX PRO 6000`.
3. User-defined aliases from `~/.config/rent-pod/gpu-aliases.toml`.
4. Exact RunPod GPU IDs, such as `NVIDIA RTX PRO 6000 Blackwell Server Edition`.

Display names containing spaces must be quoted:

```bash
rent-pod "RTX PRO 6000"
rent-pod "A100 PCIe"
rent-pod "H100 SXM"
```

When a RunPod API key is available, display names are resolved live through the RunPod GPU inventory before Pod creation. This keeps the human-facing names shown by `rent-pod --list` directly reusable as rental selectors.

## Local aliases

Create:

```text
~/.config/rent-pod/gpu-aliases.toml
```

For example:

```toml
[aliases]
pro6000 = "RTX PRO 6000"
a100 = "A100 PCIe"
h100 = "H100 SXM"
```

Then:

```bash
rent-pod pro6000
rent-pod a100
rent-pod h100
```

Alias names are case-insensitive and may contain letters, numbers, `.`, `_`, and `-`. Alias targets may be either display names from `rent-pod --list` or exact RunPod GPU IDs.

User aliases are applied before the built-in alias table, so a local alias can intentionally override a built-in alias.

To use a different file, set:

```bash
export RENT_POD_GPU_ALIASES_FILE=/path/to/gpu-aliases.toml
```

An example configuration is shipped as `docs/rent-pod-gpu-aliases.example.toml`.
