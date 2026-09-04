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

    ~/.config/rent-pod is the canonical location. RENT_POD_CONFIG_DIR may be
    used to override it explicitly.
    """
    env = environ if environ is not None else os.environ
    explicit = (env.get("RENT_POD_CONFIG_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()

    return _base_config_dir(env) / "rent-pod"
