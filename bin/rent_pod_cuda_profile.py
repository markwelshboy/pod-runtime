#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - local CLI targets py3.11+
    raise RuntimeError("rent-pod CUDA template metadata requires Python 3.11+ (tomllib)") from exc


def register_template_option(template_module: Any) -> None:
    """Allow ``min_cuda`` as rent-pod template admission metadata.

    ``min_cuda`` is deliberately not translated into the REST Pod payload. The
    rental frontend consumes it as RunPod GraphQL ``minCudaVersion`` so a
    template cannot accidentally land on a host that is too old for its image.
    """
    keys = getattr(template_module, "LOCAL_KEYS", None)
    if not isinstance(keys, set):
        raise RuntimeError("rent-pod template parser does not expose LOCAL_KEYS")
    keys.add("min_cuda")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read template CUDA metadata from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"template CUDA metadata in {path} is not a TOML table")
    return data


def _normalize_min_cuda(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a non-empty string such as \"13.0\"")
    text = value.strip()
    try:
        parts = tuple(int(part) for part in text.split("."))
    except ValueError as exc:
        raise ValueError(f"invalid CUDA version in {where}: {value!r}") from exc
    if not parts or any(part < 0 for part in parts):
        raise ValueError(f"invalid CUDA version in {where}: {value!r}")
    return text


def template_min_cuda(context: Any) -> str | None:
    """Return the selected profile's CUDA floor, including directory defaults."""
    profile_name = getattr(context, "profile_name", None)
    source_raw = getattr(context, "source", None)
    config_raw = getattr(context, "config_path", None)
    if not profile_name or source_raw is None:
        return None

    source = Path(source_raw).expanduser()
    config = Path(config_raw).expanduser() if config_raw is not None else source

    # Inline/remote profile stored under [templates.NAME] in templates.toml.
    if source == config:
        if not source.is_file():
            return None
        data = _read_toml(source)
        profiles = data.get("templates") or {}
        if not isinstance(profiles, dict):
            return None
        raw = profiles.get(str(profile_name))
        if not isinstance(raw, dict):
            return None
        return _normalize_min_cuda(raw.get("min_cuda"), f"templates.{profile_name}.min_cuda")

    # Directory-backed local profile: [defaults].min_cuda is inherited and the
    # per-template value overrides it.
    cuda_min: str | None = None
    if config.is_file():
        cfg = _read_toml(config)
        defaults = cfg.get("defaults") or {}
        if isinstance(defaults, dict):
            cuda_min = _normalize_min_cuda(defaults.get("min_cuda"), "defaults.min_cuda")

    if source.is_file():
        raw = _read_toml(source)
        if "min_cuda" in raw:
            cuda_min = _normalize_min_cuda(raw.get("min_cuda"), f"{profile_name}.min_cuda")
    return cuda_min


def _cuda_arg_value(argv: list[str]) -> str | None:
    value: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in {"--cuda-min", "--min-cuda"}:
            if i + 1 >= len(argv):
                raise ValueError(f"{arg} requires a CUDA version")
            value = _normalize_min_cuda(argv[i + 1], arg)
            i += 2
            continue
        if arg.startswith("--cuda-min=") or arg.startswith("--min-cuda="):
            value = _normalize_min_cuda(arg.split("=", 1)[1], arg.split("=", 1)[0])
        i += 1
    return value


def _replace_cuda_arg(argv: list[str], value: str) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in {"--cuda-min", "--min-cuda"}:
            if i + 1 >= len(argv):
                raise ValueError(f"{arg} requires a CUDA version")
            i += 2
            continue
        if arg.startswith("--cuda-min=") or arg.startswith("--min-cuda="):
            i += 1
            continue
        result.append(arg)
        i += 1
    result.extend(["--cuda-min", value])
    return result


def apply_template_cuda(
    public_argv: list[str],
    effective_argv: list[str],
    context: Any,
    environ: Mapping[str, str],
) -> list[str]:
    """Apply CUDA-floor precedence: CLI > selected template > environment.

    ``effective_argv`` has already passed through ``apply_env_defaults``, so a
    RENT_POD_CUDA_MIN value may already be present as ``--cuda-min``. We only
    replace that value when the user did not explicitly provide a CUDA floor.
    """
    explicit_cli = _cuda_arg_value(public_argv)
    if explicit_cli is not None:
        return list(effective_argv)

    profile_cuda = template_min_cuda(context)
    if profile_cuda is not None:
        return _replace_cuda_arg(effective_argv, profile_cuda)

    # No template requirement: preserve the existing environment/default path.
    # Validate an injected value here too so all sources share the same syntax.
    existing = _cuda_arg_value(effective_argv)
    if existing is not None:
        return _replace_cuda_arg(effective_argv, existing)

    env_cuda = (environ.get("RENT_POD_CUDA_MIN") or "").strip()
    if env_cuda:
        return _replace_cuda_arg(
            effective_argv,
            _normalize_min_cuda(env_cuda, "RENT_POD_CUDA_MIN") or env_cuda,
        )
    return list(effective_argv)
