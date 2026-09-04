#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def _base_config_dir(environ: Mapping[str, str]) -> Path:
    xdg = (environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser()
    home = (environ.get("HOME") or "").strip()
    if home:
        return Path(home).expanduser() / ".config"
    return Path("~/.config").expanduser()


def config_root(environ: Mapping[str, str] | None = None) -> Path:
    """Return the rent-pod config root.

    ~/.config/rentpod is the canonical location.  For compatibility, an
    existing ~/.config/rent-pod directory is used when the canonical directory
    does not yet exist.  RENT_POD_CONFIG_DIR always wins when explicitly set.
    """
    env = environ if environ is not None else os.environ
    explicit = (env.get("RENT_POD_CONFIG_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()

    base = _base_config_dir(env)
    canonical = base / "rentpod"
    legacy = base / "rent-pod"
    if canonical.exists() or not legacy.exists():
        return canonical
    return legacy
