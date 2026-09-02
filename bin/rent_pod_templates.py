#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - local CLI targets py3.11+
    raise RuntimeError("rent-pod template profiles require Python 3.11+ (tomllib)") from exc

import rent_pod as core

DEFAULT_TEMPLATE_ID = os.environ.get("RUNPOD_TEMPLATE_ID", "86n5dpgf7h")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class TemplateProfile:
    name: str
    template_id: str
    description: str = ""
    env: dict[str, str] = field(default_factory=dict)
    builtin: bool = False


@dataclass(frozen=True)
class TemplateRegistry:
    path: Path
    profiles: dict[str, TemplateProfile]
    default_name: str | None = None
    file_exists: bool = False


@dataclass(frozen=True)
class TemplateContext:
    requested: str
    template_id: str
    profile_name: str | None
    description: str
    env: dict[str, str]
    config_path: Path


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = environ or os.environ
    explicit = (env.get("RENT_POD_TEMPLATES_FILE") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    xdg = (env.get("XDG_CONFIG_HOME") or "").strip()
    base = Path(xdg).expanduser() if xdg else Path("~/.config").expanduser()
    return base / "rent-pod" / "templates.toml"


def _env_scalar(value: Any, where: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"{where} must be a string, number, or boolean")


def _normalize_env(raw: Any, where: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be a TOML table")
    result: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key).strip()
        if not ENV_KEY_RE.match(key_text):
            raise ValueError(f"invalid environment variable name {key_text!r} in {where}")
        result[key_text] = _env_scalar(value, f"{where}.{key_text}")
    return result


def load_registry(
    environ: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> TemplateRegistry:
    env = environ or os.environ
    cfg = (path or config_path(env)).expanduser()

    profiles: dict[str, TemplateProfile] = {
        "default": TemplateProfile(
            name="default",
            template_id=(env.get("RUNPOD_TEMPLATE_ID") or DEFAULT_TEMPLATE_ID).strip(),
            description="Legacy/default RunPod template",
            builtin=True,
        )
    }
    default_name: str | None = None

    if not cfg.is_file():
        return TemplateRegistry(cfg, profiles, default_name, False)

    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read template registry {cfg}: {exc}") from exc

    version = data.get("version", 1)
    if version != 1:
        raise ValueError(f"unsupported template registry version {version!r} in {cfg}")

    raw_default = data.get("default")
    if raw_default is not None:
        if not isinstance(raw_default, str) or not raw_default.strip():
            raise ValueError(f"default must be a non-empty template name in {cfg}")
        default_name = raw_default.strip()

    raw_profiles = data.get("templates", {})
    if not isinstance(raw_profiles, dict):
        raise ValueError(f"templates must be a TOML table in {cfg}")

    for raw_name, raw_profile in raw_profiles.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError(f"template profile names cannot be empty in {cfg}")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"templates.{name} must be a TOML table")
        template_id = raw_profile.get("id")
        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError(f"templates.{name}.id must be a non-empty string")
        description = raw_profile.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise ValueError(f"templates.{name}.description must be a string")
        profiles[name] = TemplateProfile(
            name=name,
            template_id=template_id.strip(),
            description=description.strip(),
            env=_normalize_env(raw_profile.get("env"), f"templates.{name}.env"),
            builtin=False,
        )

    if default_name is not None and default_name not in profiles:
        raise ValueError(
            f"default template {default_name!r} is not defined in {cfg}; "
            f"known profiles: {', '.join(sorted(profiles))}"
        )

    return TemplateRegistry(cfg, profiles, default_name, True)


def print_registry(registry: TemplateRegistry) -> int:
    status = "loaded" if registry.file_exists else "not found; built-in default only"
    print(f"[rent-pod] Template registry: {registry.path} ({status})")
    print()
    print(f"{'NAME':<30} {'DEFAULT':<7} {'RUNPOD TEMPLATE':<18} DESCRIPTION")
    print("-" * 96)
    for name in sorted(registry.profiles):
        profile = registry.profiles[name]
        marker = "yes" if registry.default_name == name else ""
        print(
            f"{name:<30.30} {marker:<7} {profile.template_id:<18.18} "
            f"{profile.description or '-'}"
        )
        if profile.env:
            env_text = "; ".join(f"{key}={value}" for key, value in sorted(profile.env.items()))
            print(f"  env: {env_text}")
    if not registry.file_exists:
        print()
        print("[rent-pod] Add friendly profiles in ~/.config/rent-pod/templates.toml")
    return 0


def handle_template_meta_command(
    argv: list[str],
    environ: Mapping[str, str] | None = None,
) -> int | None:
    if "--list-templates" not in argv:
        return None
    if argv != ["--list-templates"]:
        extras = [arg for arg in argv if arg != "--list-templates"]
        raise ValueError(
            "--list-templates cannot be combined with other options"
            + (f": {' '.join(extras)}" if extras else "")
        )
    return print_registry(load_registry(environ))


def parse_env_specs(specs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for spec in specs:
        for item in spec.split(";"):
            item = item.strip()
            if not item:
                continue
            if "=" not in item:
                raise ValueError(
                    f"invalid --env item {item!r}; expected KEY=VALUE "
                    "(multiple values may be separated with ';')"
                )
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not ENV_KEY_RE.match(key):
                raise ValueError(f"invalid environment variable name in --env: {key!r}")
            result[key] = value
    return result


def _extract_env_args(argv: list[str]) -> tuple[list[str], list[str]]:
    forwarded: list[str] = []
    specs: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--env":
            if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                raise ValueError("--env requires KEY=VALUE or a quoted ';'-separated list")
            specs.append(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--env="):
            specs.append(arg.split("=", 1)[1])
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return forwarded, specs


def _template_option(argv: list[str]) -> tuple[str | None, int | None, bool]:
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--template":
            if i + 1 >= len(argv):
                raise ValueError("--template requires a profile name or RunPod template ID")
            return argv[i + 1], i + 1, False
        if arg.startswith("--template="):
            return arg.split("=", 1)[1], i, True
        i += 1
    return None, None, False


def apply_template_profile(
    argv: list[str],
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], TemplateContext]:
    registry = load_registry(environ)
    forwarded, cli_specs = _extract_env_args(argv)
    cli_env = parse_env_specs(cli_specs)

    requested, index, inline = _template_option(forwarded)
    if requested is None and registry.default_name:
        requested = registry.default_name
        forwarded.extend(["--template", requested])
        index = len(forwarded) - 1
        inline = False

    if requested is None:
        requested = (environ or os.environ).get("RUNPOD_TEMPLATE_ID", DEFAULT_TEMPLATE_ID)

    requested = str(requested).strip()
    profile = registry.profiles.get(requested)
    template_id = profile.template_id if profile else requested
    profile_env = dict(profile.env) if profile else {}
    effective_env = {**profile_env, **cli_env}

    # Keep the friendly alias in argv so normal rent-pod output says
    # "Template: comfyui-inference-lite". The POST hook below swaps in the real
    # RunPod template ID only at the API boundary.
    context = TemplateContext(
        requested=requested,
        template_id=template_id,
        profile_name=profile.name if profile else None,
        description=profile.description if profile else "",
        env=effective_env,
        config_path=registry.path,
    )
    return forwarded, context


def _replace_template_arg(argv: list[str], requested: str, template_id: str) -> list[str]:
    result = list(argv)
    i = 0
    while i < len(result):
        arg = result[i]
        if arg == "--template" and i + 1 < len(result):
            if result[i + 1] == requested:
                result[i + 1] = template_id
            return result
        if arg.startswith("--template="):
            if arg.split("=", 1)[1] == requested:
                result[i] = f"--template={template_id}"
            return result
        i += 1
    return result


def install_core_api_hook(context: TemplateContext) -> None:
    original = core.api_request

    def api_request(
        api_key: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if method.upper() == "POST" and path == "/pods" and isinstance(payload, dict):
            payload = dict(payload)
            if payload.get("templateId") == context.requested:
                payload["templateId"] = context.template_id
            if context.env:
                existing = payload.get("env")
                merged: dict[str, str] = {}
                if isinstance(existing, dict):
                    merged.update({str(k): str(v) for k, v in existing.items()})
                merged.update(context.env)
                payload["env"] = merged
        return original(api_key, method, path, payload)

    core.api_request = api_request


def install_frontend_hooks(frontend: Any, context: TemplateContext) -> None:
    original_dry_run = frontend.dry_run

    def dry_run(forwarded: list[str], cuda_min: str | None) -> int:
        resolved = _replace_template_arg(forwarded, context.requested, context.template_id)
        rc = original_dry_run(resolved, cuda_min)
        if context.profile_name:
            print(f"[rent-pod] Template profile: {context.profile_name}")
            if context.description:
                print(f"[rent-pod] Description:      {context.description}")
        if context.env:
            print("[rent-pod] Pod env overrides:")
            for key, value in sorted(context.env.items()):
                print(f"           {key}={value}")
        return rc

    frontend.dry_run = dry_run


def print_selected_profile(context: TemplateContext) -> None:
    if context.profile_name:
        suffix = f" — {context.description}" if context.description else ""
        print(f"[rent-pod] Template profile:      {context.profile_name}{suffix}")
        print(f"[rent-pod] RunPod template ID:    {context.template_id}")
    if context.env:
        print(f"[rent-pod] Pod env overrides:     {len(context.env)}")
        for key, value in sorted(context.env.items()):
            print(f"           {key}={value}")
