#!/usr/bin/env python3
"""Bootstrap rent-pod HTTP identity, management, templates, env defaults, and lifecycle probes.

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

# Local template-profile discovery is intentionally first: it needs neither a
# RunPod API key nor HF_TOKEN and should never be polluted by rental defaults.
from rent_pod_templates import handle_template_meta_command  # noqa: E402

try:
    template_meta_rc = handle_template_meta_command(sys.argv[1:], os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)
if template_meta_rc is not None:
    raise SystemExit(template_meta_rc)

# Management commands are parsed before persistent rental defaults are injected:
# RENT_POD_CUDA_MIN, cloud, bandwidth floors, template profiles, etc. are
# irrelevant to --show, --status/--watch and --kill.
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
    effective_argv = apply_env_defaults(sys.argv[1:], os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

# Resolve a friendly --template name and merge profile env + per-run --env.
# The friendly name remains in argv for readable CLI output; the real RunPod ID
# is substituted only at the POST /pods API boundary.
from rent_pod_templates import (  # noqa: E402
    apply_template_profile,
    install_core_api_hook,
    install_frontend_hooks,
    print_selected_profile,
)

try:
    effective_argv, template_context = apply_template_profile(effective_argv, os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

sys.argv = [sys.argv[0], *effective_argv]
install_core_api_hook(template_context)

# Swap the core rental wait/qualification display for the live lifecycle-aware
# implementation. The underlying rent/delete/provision behavior remains in
# rent_pod.py; these hooks only enrich how readiness is detected and reported.
from rent_pod_lifecycle import install_core_hooks  # noqa: E402

install_core_hooks()

import rent_pod_frontend as frontend  # noqa: E402

install_frontend_hooks(frontend, template_context)
if "--dry-run" not in effective_argv:
    print_selected_profile(template_context)


if __name__ == "__main__":
    raise SystemExit(frontend.main())
