#!/usr/bin/env python3
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Formatter
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - local CLI targets py3.11+
    raise RuntimeError("rent-pod naming profiles require Python 3.11+ (tomllib)") from exc

import rent_pod as core


@dataclass(frozen=True)
class NamingConfig:
    pattern: str
    collision: str = "increment"


def register_template_option(template_module: Any) -> None:
    """Allow [naming] as rent-pod control-plane template metadata."""
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


def _normalize_naming(raw: Any, where: str) -> NamingConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be a TOML table")

    unknown = sorted(set(raw) - {"pattern", "collision"})
    if unknown:
        raise ValueError(f"unknown naming option(s) in {where}: {', '.join(unknown)}")

    pattern = raw.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError(f"{where}.pattern must be a non-empty string")
    pattern = pattern.strip()

    collision = raw.get("collision", "increment")
    if not isinstance(collision, str) or not collision.strip():
        raise ValueError(f"{where}.collision must be a non-empty string")
    collision = collision.strip().lower()
    if collision != "increment":
        raise ValueError(f"{where}.collision currently supports only \"increment\"")

    allowed_fields = {"template", "date", "uid"}
    for _literal, field_name, _format_spec, _conversion in Formatter().parse(pattern):
        if field_name is not None and field_name not in allowed_fields:
            raise ValueError(
                f"unknown naming placeholder {{{field_name}}} in {where}.pattern; "
                "supported placeholders: {template}, {date}, {uid}"
            )
    return NamingConfig(pattern=pattern, collision=collision)


def template_naming_config(context: Any) -> NamingConfig | None:
    """Return naming metadata for the selected template, including directory defaults."""
    profile_name = getattr(context, "profile_name", None)
    source_raw = getattr(context, "source", None)
    config_raw = getattr(context, "config_path", None)
    if not profile_name or source_raw is None:
        return None

    source = Path(source_raw).expanduser()
    config = Path(config_raw).expanduser() if config_raw is not None else source

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
        return _normalize_naming(raw.get("naming"), f"templates.{profile_name}.naming")

    naming: NamingConfig | None = None
    if config.is_file():
        cfg = _read_toml(config)
        defaults = cfg.get("defaults") or {}
        if isinstance(defaults, dict):
            naming = _normalize_naming(defaults.get("naming"), "defaults.naming")

    if source.is_file():
        raw = _read_toml(source)
        if "naming" in raw:
            naming = _normalize_naming(raw.get("naming"), f"{profile_name}.naming")
    return naming


def _option_value(argv: list[str], name: str) -> str | None:
    value: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == name:
            if i + 1 >= len(argv):
                raise ValueError(f"{name} requires a value")
            value = argv[i + 1].strip()
            if not value:
                raise ValueError(f"{name} requires a non-empty value")
            i += 2
            continue
        if arg.startswith(name + "="):
            value = arg.split("=", 1)[1].strip()
            if not value:
                raise ValueError(f"{name} requires a non-empty value")
        i += 1
    return value


def render_pattern(
    pattern: str,
    context: Any,
    *,
    now: datetime | None = None,
    uid: str | None = None,
) -> str:
    rendered = pattern.format(
        template=str(getattr(context, "profile_name", None) or getattr(context, "requested", "pod")),
        date=(now or datetime.now()).strftime("%Y%m%d"),
        uid=(uid or uuid.uuid4().hex[:6]),
    ).strip()
    if not rendered:
        raise ValueError("rendered Pod name is empty")
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


def apply_template_naming(
    argv: list[str],
    context: Any,
    api_key: str,
    *,
    resolve_collisions: bool,
) -> tuple[list[str], str | None, str | None]:
    """Apply naming precedence: explicit --name > template naming > core default."""
    explicit = _option_value(argv, "--name")
    if explicit is not None:
        return list(argv), explicit, "CLI"

    naming = template_naming_config(context)
    if naming is None:
        return list(argv), None, None

    base = render_pattern(naming.pattern, context)
    chosen = base
    if resolve_collisions and naming.collision == "increment":
        if not api_key:
            raise ValueError("RUNPOD_API_KEY is required to resolve template Pod-name collisions")
        chosen = increment_name(base, existing_pod_names(api_key))

    return [*argv, "--name", chosen], chosen, "template"
