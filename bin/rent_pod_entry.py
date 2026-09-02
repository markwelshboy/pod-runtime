#!/usr/bin/env python3
"""Bootstrap rent-pod HTTP identity and persistent environment defaults.

RunPod's API is fronted by Cloudflare. Python urllib's implicit
``Python-urllib/x.y`` User-Agent can be rejected by Cloudflare Browser Integrity
Check with error 1010 before the request reaches RunPod. Install one explicit
client identity before importing the rent-pod frontend so both GraphQL and REST
urllib calls inherit it.
"""
from __future__ import annotations

import os
import sys
import urllib.request

from rent_pod_env import apply_env_defaults

USER_AGENT = os.environ.get(
    "RUNPOD_USER_AGENT",
    "pod-runtime-rent-pod/1.0 (Linux; Python)",
)

opener = urllib.request.build_opener()
opener.addheaders = [("User-Agent", USER_AGENT)]
urllib.request.install_opener(opener)

try:
    sys.argv = [sys.argv[0], *apply_env_defaults(sys.argv[1:], os.environ)]
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

from rent_pod_frontend import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
