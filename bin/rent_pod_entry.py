#!/usr/bin/env python3
"""Bootstrap rent-pod HTTP identity, management commands, and env defaults.

RunPod's API is fronted by Cloudflare. Python urllib's implicit
``Python-urllib/x.y`` User-Agent can be rejected by Cloudflare Browser Integrity
Check with error 1010 before the request reaches RunPod. Install one explicit
client identity before importing code that talks to RunPod.
"""
from __future__ import annotations

import os
import sys
import urllib.request

USER_AGENT = os.environ.get(
    "RUNPOD_USER_AGENT",
    "pod-runtime-rent-pod/1.0 (Linux; Python)",
)

opener = urllib.request.build_opener()
opener.addheaders = [("User-Agent", USER_AGENT)]
urllib.request.install_opener(opener)

# Management commands are parsed before persistent rental defaults are injected:
# RENT_POD_CUDA_MIN, cloud, bandwidth floors, etc. are irrelevant to --show and
# --kill and must not make those commands look like mixed-mode invocations.
from rent_pod_manage import parse_management_args, run_management  # noqa: E402

try:
    management = parse_management_args(sys.argv[1:])
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

if management is not None:
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not api_key:
        print("ERROR: RUNPOD_API_KEY is required for pod management.", file=sys.stderr)
        raise SystemExit(2)
    try:
        raise SystemExit(run_management(api_key, management))
    except Exception as exc:
        # Preserve the concise CLI error style used by the rental frontend.
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

from rent_pod_env import apply_env_defaults  # noqa: E402

try:
    sys.argv = [sys.argv[0], *apply_env_defaults(sys.argv[1:], os.environ)]
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

from rent_pod_frontend import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
