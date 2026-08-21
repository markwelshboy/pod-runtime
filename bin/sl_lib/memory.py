from __future__ import annotations

import math
import re

from .common import SlError

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
