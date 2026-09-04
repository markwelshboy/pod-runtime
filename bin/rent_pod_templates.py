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
from rent_pod_config import config_root

DEFAULT_TEMPLATE_ID = os.environ.get("RUNPOD_TEMPLATE_ID", "86n5dpgf7h")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_REF_RE = re.compile(r"^\{\{\s*RUNPOD_SECRET_([^{}\s]+)\s*\}\}$")
SENSITIVE_ENV_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL)", re.I
)

LOCAL_FIELD_MAP = {
    "container_disk_gb": "containerDiskInGb",
    "volume_gb": "volumeInGb",
    "volume_mount_path": "volumeMountPath",
    "ports": "ports",
    "docker_args": "dockerArgs",
    "min_vcpu_count": "minVcpuCount",
    "min_memory_gb": "minMemoryInGb",
    "network_volume_id": "networkVolumeId",
}


@dataclass(frozen=True)
class TemplateProfile:
    name: str
    template_id: str | None = None
    description: str = ""
    env: dict[str, str] = field(default_factory=dict)
    secret_env: dict[str, str] = field(default_factory=dict)
    pod: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None
    builtin: bool = False

    @property
    def kind(self) -> str:
        return "local" if self.pod else "remote"


@dataclass(frozen=True)
class TemplateRegistry:
    path: Path
    template_dir: Path
    profiles: dict[str, TemplateProfile]
    default_name: str | None = None
    file_exists: bool = False


@dataclass(frozen=True)
class TemplateContext:
    requested: str
    template_id: str | None
    profile_name: str | None
    description: str
    env: dict[str, str]
    secret_env: dict[str, str] = field(default_factory=dict)
    pod: dict[str, Any] = field(default_factory=dict)
    config_path: Path = Path("templates.toml")
    source: Path | None = None

    @property
    def kind(self) -> str:
        return "local" if self.pod else "remote"


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    explicit = (env.get("RENT_POD_TEMPLATES_FILE") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return config_root(env) / "templates.toml"


def _template_dir(
    cfg: Path,
    data: Mapping[str, Any],
    environ: Mapping[str, str],
) -> Path:
    explicit = (environ.get("RENT_POD_TEMPLATE_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    raw = data.get("template_dir", "templates")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"template_dir must be a non-empty string in {cfg}")
    path = Path(raw).expanduser()
    return path if path.is_absolute() else cfg.parent / path


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


def _normalize_secrets(raw: Any, where: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be a TOML table")
    result: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key).strip()
        if not ENV_KEY_RE.match(key_text):
            raise ValueError(f"invalid environment variable name {key_text!r} in {where}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}.{key_text} must be a non-empty RunPod secret name")
        result[key_text] = value.strip()
    return result


def runpod_secret_ref(secret_name: str) -> str:
    return f"{{{{ RUNPOD_SECRET_{secret_name} }}}}"


def _env_with_secrets(
    env: Mapping[str, str],
    secrets: Mapping[str, str],
) -> dict[str, str]:
    result = dict(env)
    for key, secret_name in secrets.items():
        result[key] = runpod_secret_ref(secret_name)
    return result


def _normalize_ports(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} must be a non-empty array of strings")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{where} entries must be non-empty strings")
        result.append(item.strip())
    return result


def _normalize_nonnegative_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where} must be a non-negative integer")
    return value


def _local_payload(raw: Mapping[str, Any], where: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    image = raw.get("image")
    if image is not None:
        if not isinstance(image, str) or not image.strip():
            raise ValueError(f"{where}.image must be a non-empty string")
        result["imageName"] = image.strip()

    for key, api_key in LOCAL_FIELD_MAP.items():
        if key not in raw:
            continue
        value = raw[key]
        if key in {"container_disk_gb", "volume_gb", "min_vcpu_count", "min_memory_gb"}:
            result[api_key] = _normalize_nonnegative_int(value, f"{where}.{key}")
        elif key == "ports":
            result[api_key] = _normalize_ports(value, f"{where}.{key}")
        elif key in {"volume_mount_path", "docker_args", "network_volume_id"}:
            if not isinstance(value, str):
                raise ValueError(f"{where}.{key} must be a string")
            result[api_key] = value.strip()
    return result


def _parse_profile(
    name: str,
    raw: Any,
    where: str,
    source: Path,
    defaults: Mapping[str, Any] | None = None,
) -> TemplateProfile:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be a TOML table")

    description = raw.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError(f"{where}.description must be a string")

    template_id = raw.get("id")
    if template_id is not None and (
        not isinstance(template_id, str) or not template_id.strip()
    ):
        raise ValueError(f"{where}.id must be a non-empty string")

    default_map = dict(defaults or {})
    merged_local = dict(default_map)
    for key in ("image", *LOCAL_FIELD_MAP.keys()):
        if key in raw:
            merged_local[key] = raw[key]
    pod = _local_payload(merged_local, where)

    has_local = "imageName" in pod
    has_remote = template_id is not None
    if has_local and has_remote:
        raise ValueError(f"{where} cannot contain both id and image")
    if not has_local and not has_remote:
        raise ValueError(
            f"{where} must define either id (RunPod template) or image (local template)"
        )

    default_env = _normalize_env(default_map.get("env"), f"{where}.defaults.env")
    default_secrets = _normalize_secrets(
        default_map.get("secrets"), f"{where}.defaults.secrets"
    )
    profile_env = _normalize_env(raw.get("env"), f"{where}.env")
    profile_secrets = _normalize_secrets(raw.get("secrets"), f"{where}.secrets")

    env = {**default_env, **profile_env}
    secret_env = {**default_secrets, **profile_secrets}
    # More-specific profile values replace defaults regardless of whether the
    # value is a plain env setting or a RunPod secret binding.
    for key in profile_env:
        secret_env.pop(key, None)
    for key in profile_secrets:
        env.pop(key, None)

    return TemplateProfile(
        name=name,
        template_id=template_id.strip() if isinstance(template_id, str) else None,
        description=description.strip(),
        env=env,
        secret_env=secret_env,
        pod=pod if has_local else {},
        source=source,
        builtin=False,
    )


def _read_toml(path: Path, label: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} {path} did not contain a TOML table")
    return data


def load_registry(
    environ: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> TemplateRegistry:
    env = environ if environ is not None else os.environ
    cfg = (path or config_path(env)).expanduser()

    profiles: dict[str, TemplateProfile] = {
        "default": TemplateProfile(
            name="default",
            template_id=(env.get("RUNPOD_TEMPLATE_ID") or DEFAULT_TEMPLATE_ID).strip(),
            description="Legacy/default RunPod template",
            source=cfg,
            builtin=True,
        )
    }
    default_name: str | None = None
    data: dict[str, Any] = {}
    file_exists = cfg.is_file()

    if file_exists:
        data = _read_toml(cfg, "template registry")
        version = data.get("version", 1)
        if version not in {1, 2}:
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
            profiles[name] = _parse_profile(
                name,
                raw_profile,
                f"templates.{name}",
                cfg,
                None,
            )

    template_dir = _template_dir(cfg, data, env)
    raw_defaults = data.get("defaults", {})
    if raw_defaults is None:
        raw_defaults = {}
    if not isinstance(raw_defaults, dict):
        raise ValueError(f"defaults must be a TOML table in {cfg}")

    if template_dir.is_dir():
        for template_file in sorted(template_dir.glob("*.toml")):
            name = template_file.stem
            if name in profiles:
                raise ValueError(
                    f"duplicate template profile {name!r}: defined in {cfg} and {template_file}"
                )
            raw = _read_toml(template_file, "template file")
            profiles[name] = _parse_profile(
                name,
                raw,
                name,
                template_file,
                raw_defaults,
            )

    if default_name is not None and default_name not in profiles:
        raise ValueError(
            f"default template {default_name!r} is not defined in {cfg} or {template_dir}; "
            f"known profiles: {', '.join(sorted(profiles))}"
        )

    return TemplateRegistry(cfg, template_dir, profiles, default_name, file_exists)


def print_registry(registry: TemplateRegistry) -> int:
    if registry.file_exists:
        status = "loaded"
    elif registry.template_dir.is_dir():
        status = "registry not found; directory profiles loaded"
    else:
        status = "not found; built-in default only"
    print(f"[rent-pod] Template registry: {registry.path} ({status})")
    print(f"[rent-pod] Template directory: {registry.template_dir}")
    print()
    print(f"{'NAME':<30} {'DEFAULT':<7} {'TYPE':<7} SOURCE")
    print("-" * 100)
    for name in sorted(registry.profiles):
        profile = registry.profiles[name]
        marker = "yes" if registry.default_name == name else ""
        if profile.kind == "local":
            source = str(profile.pod.get("imageName") or profile.source or "-")
        else:
            source = str(profile.template_id or "-")
        print(f"{name:<30.30} {marker:<7} {profile.kind:<7} {source}")
        if profile.description:
            print(f"  {profile.description}")
        if profile.env or profile.secret_env:
            keys = sorted(set(profile.env) | set(profile.secret_env))
            print(f"  env: {', '.join(keys)}")
    if not registry.file_exists and not registry.template_dir.is_dir():
        print()
        print("[rent-pod] Add defaults/remote profiles in ~/.config/rentpod/templates.toml")
        print("[rent-pod] Add local templates in ~/.config/rentpod/templates/*.toml")
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
    env_map = environ if environ is not None else os.environ
    registry = load_registry(env_map)
    forwarded, cli_specs = _extract_env_args(argv)
    cli_env = parse_env_specs(cli_specs)

    requested, _index, _inline = _template_option(forwarded)
    if requested is None and registry.default_name:
        requested = registry.default_name
        forwarded.extend(["--template", requested])

    if requested is None:
        requested = env_map.get("RUNPOD_TEMPLATE_ID", DEFAULT_TEMPLATE_ID)

    requested = str(requested).strip()
    profile = registry.profiles.get(requested)
    template_id = profile.template_id if profile else requested
    profile_env = dict(profile.env) if profile else {}
    secret_env = dict(profile.secret_env) if profile else {}
    effective_env = _env_with_secrets(profile_env, secret_env)
    effective_env.update(cli_env)

    context = TemplateContext(
        requested=requested,
        template_id=template_id,
        profile_name=profile.name if profile else None,
        description=profile.description if profile else "",
        env=effective_env,
        secret_env=secret_env,
        pod=dict(profile.pod) if profile else {},
        config_path=registry.path,
        source=profile.source if profile else None,
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


def apply_context_to_payload(
    payload: dict[str, Any],
    context: TemplateContext,
) -> dict[str, Any]:
    result = dict(payload)
    if result.get("templateId") == context.requested:
        if context.kind == "local":
            result.pop("templateId", None)
            result.update(context.pod)
        elif context.template_id:
            result["templateId"] = context.template_id

    if context.env:
        existing = result.get("env")
        merged: dict[str, str] = {}
        if isinstance(existing, dict):
            merged.update({str(k): str(v) for k, v in existing.items()})
        merged.update(context.env)
        result["env"] = merged
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
            payload = apply_context_to_payload(payload, context)
        return original(api_key, method, path, payload)

    core.api_request = api_request


def _display_env_value(key: str, value: str) -> str:
    match = SECRET_REF_RE.match(value.strip())
    if match:
        return f"<RunPod secret:{match.group(1)}>"
    if SENSITIVE_ENV_RE.search(key):
        return "<set>"
    return value


def install_frontend_hooks(frontend: Any, context: TemplateContext) -> None:
    original_dry_run = frontend.dry_run

    def dry_run(forwarded: list[str], cuda_min: str | None) -> int:
        if context.kind == "local":
            args = core.build_parser().parse_args(forwarded)
            args.gpu = core.resolve_gpu(args.gpu_alias)
            preview: dict[str, Any] = {
                "name": args.name or "podlet-<gpu>-<timestamp>-a1",
                "templateId": context.requested,
                "gpuTypeIds": [args.gpu],
                "gpuCount": 1,
                "gpuTypePriority": "availability",
                "supportPublicIp": True,
                "minDownloadMbps": args.min_download,
                "minUploadMbps": args.min_upload,
                "cloudType": args.cloud,
            }
            if args.min_disk is not None:
                preview["minDiskBandwidthMBps"] = args.min_disk
            allowed = frontend.allowed_cuda_versions(cuda_min)
            if allowed:
                preview["allowedCudaVersions"] = allowed
            preview = apply_context_to_payload(preview, context)
            print(frontend.json.dumps(preview, indent=2, sort_keys=True))
            rc = 0
        else:
            resolved = _replace_template_arg(
                forwarded,
                context.requested,
                context.template_id or context.requested,
            )
            rc = original_dry_run(resolved, cuda_min)

        if context.profile_name:
            print(f"[rent-pod] Template profile: {context.profile_name} ({context.kind})")
            if context.description:
                print(f"[rent-pod] Description:      {context.description}")
            if context.source:
                print(f"[rent-pod] Source:           {context.source}")
        if context.env:
            print("[rent-pod] Pod env overrides:")
            for key, value in sorted(context.env.items()):
                print(f"           {key}={_display_env_value(key, value)}")
        return rc

    frontend.dry_run = dry_run


def print_selected_profile(context: TemplateContext) -> None:
    if context.profile_name:
        suffix = f" — {context.description}" if context.description else ""
        print(
            f"[rent-pod] Template profile:      {context.profile_name} "
            f"({context.kind}){suffix}"
        )
        if context.kind == "remote":
            print(f"[rent-pod] RunPod template ID:    {context.template_id}")
        else:
            print(f"[rent-pod] Container image:       {context.pod.get('imageName')}")
        if context.source:
            print(f"[rent-pod] Template source:       {context.source}")
    if context.env:
        print(f"[rent-pod] Pod env overrides:     {len(context.env)}")
        for key, value in sorted(context.env.items()):
            print(f"           {key}={_display_env_value(key, value)}")
