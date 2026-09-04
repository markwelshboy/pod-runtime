#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import TextIO


def normalize_cuda_option(argv: list[str]) -> list[str]:
    """Translate the public --min-cuda spelling to the legacy internal flag.

    rent_pod_frontend historically consumed --cuda-min before delegating to the
    low-level rental parser.  Keep that internal contract for compatibility, but
    expose --min-cuda alongside the other --min-* selection floors.
    """
    result: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--min-cuda":
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise ValueError("--min-cuda requires a version, e.g. --min-cuda 12.8")
            result.extend(["--cuda-min", argv[i + 1]])
            i += 2
            continue
        if arg.startswith("--min-cuda="):
            value = arg.split("=", 1)[1].strip()
            if not value:
                raise ValueError("--min-cuda requires a version, e.g. --min-cuda 12.8")
            result.append(f"--cuda-min={value}")
            i += 1
            continue
        result.append(arg)
        i += 1
    return result


def print_help(stream: TextIO = sys.stdout) -> None:
    print(
        """rent-pod — rent, qualify, and provision disposable RunPod GPU pods

Usage:
  rent-pod [GPU] [options]
  rent-pod --list [\"GPU GPU ...\"] [selection options]
  rent-pod --list-templates
  rent-pod --balance
  rent-pod --show
  rent-pod --status POD_ID
  rent-pod --watch POD_ID
  rent-pod --kill POD_ID
  rent-pod --kill-all [--yes|-y|--force]

GPU may be an alias such as 4090, 5090, l40s, l40, 5080, or 3090, or an
exact RunPod GPU type. The default GPU is 4090 and the default cloud is SECURE.

Selection floors:
  --min-cuda VERSION       Require CUDA VERSION or newer. For Pod creation this
                           is translated into RunPod allowedCudaVersions; for
                           --list it is sent as minCudaVersion.
  --min-download MBPS      Minimum advertised download bandwidth (default: 500).
  --min-upload MBPS        Minimum advertised upload bandwidth (default: 100).
  --min-disk MB_PER_SEC    Minimum advertised disk throughput, when specified.
  --community              Use Community Cloud for this request.
  --cloud SECURE|COMMUNITY Explicit cloud pool (default: SECURE).

Template / Pod configuration:
  --template NAME|ID       Friendly profile from ~/.config/rent-pod/templates.toml
                           or a raw RunPod template ID.
  --name NAME              Name assigned to the rented Pod.
  --env KEY=VALUE          Per-run template environment override. Repeatable;
                           a quoted ';'-separated list is also accepted.
  --list-templates         Show local friendly template profiles and descriptions.

Rental / admission:
  --attempts N             Number of paid candidates to try (default: 1).
  --startup-timeout SEC    Max wait for image/container runtime (default: 900).
  --ssh-exposure-timeout SEC
                           Max wait after runtime for usable direct SSH (default: 180).
  --poll-seconds SEC       Startup polling interval (default: 5).
  --retry-delay SEC        Delay between attempts (default: 5).
  --rejection-ttl-hours H  Remember rejected machine/IP identities (default: 24).
  --ssh-key PATH           SSH private key for the Pod.
  --allow-seen-machine     Permit a recently rejected machine/IP.
  --keep-failed            Keep candidates that would normally be auto-deleted.
  --no-provision           Stop after SSH readiness; do not run provision.
  --dry-run                Show the Pod-create payload without renting anything.

Inventory / account / management:
  --list [\"GPU ...\"]     Show live availability/pricing for selected or all GPUs.
  --balance                Show account balance, current $/hr spend, spend limit,
                           and estimated runway at the current burn rate.
  --show                   List Pods on the account.
  --status POD_ID          Show one lifecycle snapshot.
  --watch POD_ID           Watch lifecycle until SSH is ready; never deletes.
  --kill POD_ID            Permanently delete one Pod.
  --kill-all               Permanently delete all Pods; interactive by default.
  --yes, -y, --force       Confirm --kill-all non-interactively.

Persistent defaults use RENT_POD_* environment variables. In particular,
RENT_POD_CUDA_MIN supplies the default for --min-cuda. Command-line values win.

Compatibility:
  --cuda-min VERSION       Legacy alias for --min-cuda; accepted but deprecated.

  -h, --help               Show this help.
""",
        file=stream,
        end="",
    )


def handle_help_command(argv: list[str]) -> int | None:
    if "--help" in argv or "-h" in argv or argv == ["help"]:
        print_help()
        return 0
    return None
