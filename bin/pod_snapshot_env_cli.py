#!/usr/bin/env python3
from __future__ import annotations

import sys

import pod_env_state
import pod_history_state
import pod_snapshot_cli
import pod_snapshot_display
import pod_state as core

pod_env_state.install_core_hooks(core)
pod_history_state.install_core_hooks(core)
pod_snapshot_display.install_cli_hooks(pod_snapshot_cli)


if __name__ == "__main__":
    raise SystemExit(pod_snapshot_cli.main(sys.argv[1:]))
