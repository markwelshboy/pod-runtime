#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - local CLI targets py3.11+
    raise RuntimeError("rent-pod startup profiles require Python 3.11+ (tomllib)") from exc

import rent_pod as core

DEFAULT_REMOTE_RUNTIME_DIR = "/workspace/pod-runtime"


def register_template_option(template_module: Any) -> None:
    """Allow ``startup`` as rent-pod control-plane template metadata.

    The existing template parser uses LOCAL_KEYS as its accepted top-level key
    set. ``startup`` is deliberately *not* translated into the RunPod Pod-create
    payload; this module consumes it after the selected profile is resolved.
    Keeping the registration here avoids mixing a post-provision action with
    container settings such as docker_start_cmd.
    """
    keys = getattr(template_module, "LOCAL_KEYS", None)
    if not isinstance(keys, set):
        raise RuntimeError("rent-pod template parser does not expose LOCAL_KEYS")
    keys.add("startup")


def consume_startup_args(argv: list[str]) -> tuple[list[str], str | None]:
    """Strip the frontend-only --startup option and return its command."""
    forwarded: list[str] = []
    command: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--startup":
            if command is not None:
                raise ValueError("--startup may only be specified once")
            if i + 1 >= len(argv):
                raise ValueError("--startup requires a remote command")
            value = argv[i + 1].strip()
            if not value:
                raise ValueError("--startup requires a non-empty remote command")
            command = value
            i += 2
            continue
        if arg.startswith("--startup="):
            if command is not None:
                raise ValueError("--startup may only be specified once")
            value = arg.split("=", 1)[1].strip()
            if not value:
                raise ValueError("--startup requires a non-empty remote command")
            command = value
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return forwarded, command


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read template startup metadata from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"template startup metadata in {path} is not a TOML table")
    return data


def _normalize_startup(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a non-empty string")
    return value.strip()


def template_startup_command(context: Any) -> str | None:
    """Read startup metadata for the selected template profile.

    Directory profiles store it at the top level of the per-template TOML file.
    Inline/remote profiles store it in [templates.NAME]. A [defaults] startup is
    also supported for directory profiles and is overridden by the template.
    """
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
        return _normalize_startup(raw.get("startup"), f"templates.{profile_name}.startup")

    startup: str | None = None
    if config.is_file():
        cfg = _read_toml(config)
        defaults = cfg.get("defaults") or {}
        if isinstance(defaults, dict):
            startup = _normalize_startup(defaults.get("startup"), "defaults.startup")

    if source.is_file():
        raw = _read_toml(source)
        if "startup" in raw:
            startup = _normalize_startup(raw.get("startup"), f"{profile_name}.startup")
    return startup


def resolve_startup_command(cli_command: str | None, context: Any) -> tuple[str | None, str | None]:
    """Return (command, source), with CLI taking precedence over template."""
    if cli_command is not None:
        return cli_command.strip(), "CLI"
    command = template_startup_command(context)
    if command:
        return command, "template"
    return None, None


def remote_runtime_dir(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return (
        (env.get("RENT_POD_REMOTE_RUNTIME_DIR") or "").strip()
        or (env.get("RUNTIME_DIR") or "").strip()
        or DEFAULT_REMOTE_RUNTIME_DIR
    )


def build_remote_startup(command: str, runtime_dir: str | None = None) -> str:
    """Build the remote Bash bootstrap used for a post-provision command."""
    runtime = runtime_dir or remote_runtime_dir()
    bootstrap = "\n".join(
        [
            "set -eo pipefail",
            f"export POD_RUNTIME_DIR={shlex.quote(runtime)}",
            'export repo_root="$POD_RUNTIME_DIR"',
            'if [[ -f /etc/rp_environment ]]; then source /etc/rp_environment; fi',
            'if [[ -f "$POD_RUNTIME_DIR/.env" ]]; then source "$POD_RUNTIME_DIR/.env"; fi',
            'if [[ -f /root/.secrets/env.current ]]; then source /root/.secrets/env.current; fi',
            'if [[ -f /root/.secrets/env.provisioned ]]; then source /root/.secrets/env.provisioned; fi',
            'export PATH="$POD_RUNTIME_DIR:$POD_RUNTIME_DIR/bin:$PATH"',
            'if [[ -f "$POD_RUNTIME_DIR/helpers.sh" ]]; then export BASH_ENV="$POD_RUNTIME_DIR/helpers.sh"; fi',
            "cd /workspace",
            f"exec bash -c {shlex.quote(command)}",
        ]
    )
    return f"bash -c {shlex.quote(bootstrap)}"


def run_startup_command(
    identity: dict[str, Any],
    key: str,
    command: str,
    *,
    runtime_dir: str | None = None,
) -> int:
    if not identity.get("public_ip") or not identity.get("ssh_port"):
        raise ValueError("cannot run startup command without a proven direct SSH endpoint")
    print(f"[rent-pod] Running post-provision startup: {command}")
    remote = build_remote_startup(command, runtime_dir)
    return subprocess.run(core.ssh_command(identity, key, remote)).returncode


def install_core_hook(command: str | None) -> None:
    """Run command after successful provision, before rent-pod reports ACCEPTED.

    A startup failure is not an admission/network failure: the machine has
    already provisioned successfully. Raise SystemExit so core's rejection and
    cleanup paths are bypassed and the paid Pod is left running for diagnosis.
    """
    if not command:
        return
    original_run_provision = core.run_provision

    def run_provision(identity: dict[str, Any], key: str) -> int:
        rc = original_run_provision(identity, key)
        if rc != 0:
            return rc
        try:
            startup_rc = run_startup_command(identity, key, command)
        except KeyboardInterrupt:
            print(
                "\n[rent-pod] Startup interrupted; provisioned pod remains running.",
                file=sys.stderr,
            )
            raise SystemExit(130)
        if startup_rc != 0:
            print(
                f"[rent-pod] Startup command failed rc={startup_rc}; "
                "provisioned pod remains running for diagnosis.",
                file=sys.stderr,
            )
            raise SystemExit(startup_rc)
        print("[rent-pod] Post-provision startup completed.")
        return 0

    core.run_provision = run_provision
