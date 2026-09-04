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

# Account balance is also a meta/management command: it must not inherit rental
# defaults and needs only RUNPOD_API_KEY, never HF_TOKEN.
from rent_pod_account import handle_balance_command  # noqa: E402

try:
    balance_rc = handle_balance_command(sys.argv[1:], os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(1)
if balance_rc is not None:
    raise SystemExit(balance_rc)

# Upgrade --status/--watch before management dispatch so they use the same TCP,
# SSH-banner and authenticated-SSH phases as the live rental path.
import rent_pod_ssh_phases as ssh_phases  # noqa: E402

ssh_phases.install_management_hooks()

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
import rent_pod_vcp as vcp_handoff  # noqa: E402

try:
    effective_argv = apply_env_defaults(sys.argv[1:], os.environ)
    effective_argv, ssh_exposure_timeout = ssh_phases.consume_ssh_phase_args(
        effective_argv, os.environ
    )
    effective_argv, vcp_enabled = vcp_handoff.consume_vcp_args(effective_argv)
    rent_name = vcp_handoff.requested_name(effective_argv)
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

# Install the lifecycle display first, then replace only its readiness wait with
# the more detailed direct-SSH phase probe. Provision/identity display hooks stay
# owned by rent_pod_lifecycle. VCP wraps those final hooks so its handoff always
# receives the endpoint that actually passed authenticated SSH.
from rent_pod_lifecycle import install_core_hooks  # noqa: E402

install_core_hooks()
ssh_phases.install_core_hook(ssh_exposure_timeout)
vcp_handoff.install_core_hooks(vcp_enabled, rent_name)

import rent_pod_frontend as frontend  # noqa: E402

install_frontend_hooks(frontend, template_context)
if "--dry-run" not in effective_argv:
    print_selected_profile(template_context)
if vcp_enabled:
    suffix = f" as target {rent_name}" if rent_name else " as a named target"
    print(f"[rent-pod] VCP auto-config:       enabled after successful provision{suffix}")


if __name__ == "__main__":
    raise SystemExit(frontend.main())
