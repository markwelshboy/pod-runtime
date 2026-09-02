#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Mapping


VALUE_DEFAULTS = (
    ("--cuda-min", "RENT_POD_CUDA_MIN"),
    ("--template", "RENT_POD_TEMPLATE"),
    ("--min-download", "RENT_POD_MIN_DOWNLOAD"),
    ("--min-upload", "RENT_POD_MIN_UPLOAD"),
    ("--min-disk", "RENT_POD_MIN_DISK"),
    ("--startup-timeout", "RENT_POD_STARTUP_TIMEOUT"),
    ("--poll-seconds", "RENT_POD_POLL_SECONDS"),
    ("--retry-delay", "RENT_POD_RETRY_DELAY"),
    ("--rejection-ttl-hours", "RENT_POD_REJECTION_TTL_HOURS"),
    ("--ssh-key", "RENT_POD_SSH_KEY"),
)


def option_present(argv: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in argv)


def bool_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def apply_env_defaults(argv: list[str], environ: Mapping[str, str]) -> list[str]:
    """Apply persistent RENT_POD_* defaults without overriding CLI arguments.

    Paid-control switches such as --attempts and --keep-failed intentionally do
    not have environment defaults; they remain explicit per invocation.
    """
    result = list(argv)

    for option, env_name in VALUE_DEFAULTS:
        value = (environ.get(env_name) or "").strip()
        if value and not option_present(result, option):
            result.extend([option, value])

    # Pool selection has two persistent forms. RENT_POD_CLOUD is the canonical
    # value; RENT_POD_COMMUNITY=true is a convenient shorthand matching the CLI.
    cli_pool_explicit = option_present(result, "--cloud") or "--community" in result
    if not cli_pool_explicit:
        cloud = (environ.get("RENT_POD_CLOUD") or "").strip().upper()
        community = bool_true(environ.get("RENT_POD_COMMUNITY"))
        if cloud:
            if cloud not in {"SECURE", "COMMUNITY"}:
                raise ValueError(
                    "RENT_POD_CLOUD must be SECURE or COMMUNITY "
                    f"(got {cloud!r})"
                )
            if community and cloud != "COMMUNITY":
                raise ValueError(
                    "RENT_POD_COMMUNITY=true conflicts with RENT_POD_CLOUD=SECURE"
                )
            result.extend(["--cloud", cloud])
        elif community:
            result.append("--community")

    return result
