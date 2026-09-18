#!/usr/bin/env python3
from __future__ import annotations

import secrets
import string
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - local CLI targets py3.11+
    raise RuntimeError("rent-pod naming profiles require Python 3.11+ (tomllib)") from exc

import rent_pod as core

SUPPORTED_COLLISIONS = {"increment", "allow", "error"}
SUPPORTED_FIELDS = {"pattern", "collision"}
SUPPORTED_TOKENS = {"template", "uid", "date"}


def register_template_option(template_module: Any) -> None:
    """Allow ``[naming]`` as rent-pod control-plane template metadata."""
    keys = getattr(template_module, "LOCAL_KEYS", None)
    if not isinstance(keys, set):
        raise RuntimeError("rent-pod template parser does not expose LOCAL_KEYS")
    keys.add("naming")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read template naming metadata from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"template naming metadata in {path} is not a TOML table")
    return data


def _naming_table(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a TOML table")
    unknown = sorted(set(value) - SUPPORTED_FIELDS)
    if unknown:
        raise ValueError(
            f"unknown naming option(s) in {where}: {', '.join(unknown)}"
        )
    return dict(value)


def _normalize_naming(raw: Mapping[str, Any], where: str) -> dict[str, str] | None:
    pattern_raw = raw.get("pattern")
    if pattern_raw is None:
        return None
    if not isinstance(pattern_raw, str) or not pattern_raw.strip():
        raise ValueError(f"{where}.pattern must be a non-empty string")
    pattern = pattern_raw.strip()

    collision_raw = raw.get("collision", "increment")
    if not isinstance(collision_raw, str) or not collision_raw.strip():
        raise ValueError(f"{where}.collision must be a non-empty string")
    collision = collision_raw.strip().lower()
    if collision not in SUPPORTED_COLLISIONS:
        choices = ", ".join(sorted(SUPPORTED_COLLISIONS))
        raise ValueError(f"{where}.collision must be one of: {choices}")

    # Validate field names now so a malformed pattern fails before any paid API call.
    formatter = string.Formatter()
    for _literal, field_name, format_spec, conversion in formatter.parse(pattern):
        if field_name is None:
            continue
        if format_spec or conversion:
            raise ValueError(
                f"{where}.pattern does not support format specs or conversions: {pattern!r}"
            )
        if field_name == "pod-id":
            raise ValueError(
                f"{where}.pattern cannot use {{pod-id}} because the Pod ID does not "
                "exist until after creation; use {{uid}} instead"
            )
        if field_name not in SUPPORTED_TOKENS:
            choices = ", ".join(f"{{{name}}}" for name in sorted(SUPPORTED_TOKENS))
            raise ValueError(
                f"unsupported naming token {{{field_name}}} in {where}.pattern; "
                f"supported tokens: {choices}"
            )

    return {"pattern": pattern, "collision": collision}


def template_naming(context: Any) -> dict[str, str] | None:
    """Return selected profile naming metadata, including directory defaults."""
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
        naming = _naming_table(raw.get("naming"), f"templates.{profile_name}.naming")
        return _normalize_naming(naming, f"templates.{profile_name}.naming")

    # Directory-backed local profile: [defaults.naming] is inherited and the
    # per-template [naming] table overrides individual default keys.
    merged: dict[str, Any] = {}
    if config.is_file():
        cfg = _read_toml(config)
        defaults = cfg.get("defaults") or {}
        if isinstance(defaults, dict):
            merged.update(_naming_table(defaults.get("naming"), "defaults.naming"))

    if source.is_file():
        raw = _read_toml(source)
        if "naming" in raw:
            merged.update(
                _naming_table(raw.get("naming"), f"{profile_name}.naming")
            )

    return _normalize_naming(merged, f"{profile_name}.naming")


def render_pattern(
    pattern: str,
    context: Any,
    *,
    uid: str | None = None,
    now: datetime | None = None,
) -> str:
    template = str(
        getattr(context, "profile_name", None)
        or getattr(context, "requested", None)
        or "pod"
    )
    values = {
        "template": template,
        "uid": uid or secrets.token_hex(3),
        "date": (now or datetime.now().astimezone()).strftime("%Y%m%d"),
    }
    try:
        rendered = pattern.format_map(values).strip()
    except (KeyError, ValueError) as exc:  # defensive: validated by _normalize_naming
        raise ValueError(f"invalid naming pattern {pattern!r}: {exc}") from exc
    if not rendered:
        raise ValueError("naming pattern rendered an empty Pod name")
    return rendered


def existing_pod_names(api_key: str) -> set[str]:
    result = core.api_request(api_key, "GET", "/pods")
    if not isinstance(result, list):
        raise core.RunPodError(f"unexpected pods response while resolving Pod name: {result!r}")
    return {
        str(pod.get("name") or "").strip()
        for pod in result
        if isinstance(pod, dict) and str(pod.get("name") or "").strip()
    }


def increment_name(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    suffix = 1
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def _name_option(argv: list[str]) -> str | None:
    value: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--name":
            if i + 1 >= len(argv):
                raise ValueError("--name requires a Pod name")
            value = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--name="):
            value = arg.split("=", 1)[1]
        i += 1
    return value


def apply_template_naming(
    argv: list[str],
    context: Any,
    environ: Mapping[str, str],
    *,
    resolve_collision: bool = True,
    uid: str | None = None,
    now: datetime | None = None,
) -> tuple[list[str], dict[str, str] | None]:
    """Inject a template-derived ``--name`` unless the CLI already supplied one.

    When ``resolve_collision`` is false (dry-run), the base rendered name is
    injected without listing account Pods. Real rentals resolve the configured
    collision policy before either REST or GraphQL Pod creation sees the name.
    """
    explicit = _name_option(argv)
    if explicit is not None:
        return list(argv), {
            "name": explicit,
            "base": explicit,
            "source": "CLI",
            "collision": "explicit",
        }

    naming = template_naming(context)
    if naming is None:
        return list(argv), None

    base = render_pattern(naming["pattern"], context, uid=uid, now=now)
    collision = naming["collision"]
    final = base

    if resolve_collision and collision != "allow":
        api_key = (environ.get("RUNPOD_API_KEY") or "").strip()
        if not api_key:
            raise ValueError(
                "RUNPOD_API_KEY is required to resolve template Pod naming collisions"
            )
        existing = existing_pod_names(api_key)
        if collision == "increment":
            final = increment_name(base, existing)
        elif collision == "error" and base in existing:
            raise ValueError(
                f"Pod name {base!r} already exists and naming.collision = \"error\""
            )

    result = [*argv, "--name", final]
    return result, {
        "name": final,
        "base": base,
        "source": "template",
        "collision": collision,
        "deferred": "true" if not resolve_collision and collision != "allow" else "false",
    }
