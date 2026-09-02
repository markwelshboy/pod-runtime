#!/usr/bin/env python3
"""HTTP bootstrap for rent-pod.

RunPod's API is fronted by Cloudflare. Python urllib's implicit
``Python-urllib/x.y`` User-Agent can be rejected by Cloudflare Browser Integrity
Check with error 1010 before the request reaches RunPod. Install one explicit
client identity before importing the rent-pod frontend so both GraphQL and REST
urllib calls inherit it.
"""
from __future__ import annotations

import os
import urllib.request

USER_AGENT = os.environ.get(
    "RUNPOD_USER_AGENT",
    "pod-runtime-rent-pod/1.0 (Linux; Python)",
)

opener = urllib.request.build_opener()
opener.addheaders = [("User-Agent", USER_AGENT)]
urllib.request.install_opener(opener)

from rent_pod_frontend import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
