from __future__ import annotations

import math
import re

from .common import SlError, _ssh

MEMORY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|mb|mib|g|gb|gib)\s*$", re.IGNORECASE)


def parse_memory_mib(value: str) -> int:
    """Parse a human GPU-memory requirement into MiB.

    G/GB/GiB are treated as 1024 MiB; M/MB/MiB are treated as MiB.
    A suffix is required so an accidental bare number cannot be misread.
    """
    match = MEMORY_RE.fullmatch(value)
    if not match:
        raise SlError("memory must include M or G units, e.g. --mem 18000M or --mem 18G")
    amount = float(match.group(1))
    if amount <= 0:
        raise SlError("memory requirement must be greater than zero")
    unit = match.group(2).lower()
    mib = amount * 1024 if unit.startswith("g") else amount
    result = int(math.ceil(mib))
    if result <= 0:
        raise SlError("memory requirement must be greater than zero")
    return result


def format_memory_mib(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 1024 and value % 1024 == 0:
        return f"{value // 1024} GiB"
    if value >= 1024:
        return f"{value / 1024:.1f} GiB"
    return f"{value} MiB"


def remote_gpu_total_mib() -> int:
    result = _ssh(
        "command -v nvidia-smi >/dev/null 2>&1 || exit 127\n"
        "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1\n",
        capture=True,
        check=False,
    )
    if result.returncode == 127:
        raise SlError("--mem requested but nvidia-smi is unavailable on the worker")
    if result.returncode != 0:
        raise SlError("could not query worker GPU memory with nvidia-smi")
    raw = (result.stdout or "").strip().splitlines()
    if not raw or not raw[0].strip().isdigit():
        raise SlError(f"could not parse worker GPU memory total: {result.stdout!r}")
    return int(raw[0].strip())


def ensure_remote_capacity(required_mib: int) -> int:
    total_mib = remote_gpu_total_mib()
    if required_mib > total_mib:
        raise SlError(
            f"memory requirement {format_memory_mib(required_mib)} exceeds worker GPU total "
            f"{format_memory_mib(total_mib)}"
        )
    return total_mib
