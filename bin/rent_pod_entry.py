#!/usr/bin/env python3
"""Bootstrap rent-pod HTTP identity, management, templates, queueing, and lifecycle probes.

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

from rent_pod_cli import handle_help_command, normalize_cuda_option  # noqa: E402

help_rc = handle_help_command(sys.argv[1:])
if help_rc is not None:
    raise SystemExit(help_rc)

try:
    public_argv = normalize_cuda_option(sys.argv[1:])
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

import rent_pod_queue as queue_handoff  # noqa: E402

try:
    queue_meta_rc = queue_handoff.handle_queue_meta_command(public_argv, os.environ)
    if queue_meta_rc is not None:
        raise SystemExit(queue_meta_rc)
    public_argv, queue_request = queue_handoff.consume_queue_args(public_argv, os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

import rent_pod_startup as startup_handoff  # noqa: E402
import rent_pod_cuda_profile as cuda_profile_handoff  # noqa: E402
import rent_pod_naming as naming_handoff  # noqa: E402
import rent_pod_templates as template_profiles  # noqa: E402

startup_handoff.register_template_option(template_profiles)
cuda_profile_handoff.register_template_option(template_profiles)
naming_handoff.register_template_option(template_profiles)

import rent_pod_api_v2 as api_v2_handoff  # noqa: E402

api_v2_handoff.install_core_hooks()

from rent_pod_templates import handle_template_meta_command  # noqa: E402

try:
    template_meta_rc = handle_template_meta_command(public_argv, os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)
if template_meta_rc is not None:
    raise SystemExit(template_meta_rc)

from rent_pod_account import handle_balance_command  # noqa: E402

try:
    balance_rc = handle_balance_command(public_argv, os.environ)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(1)
if balance_rc is not None:
    raise SystemExit(balance_rc)

import rent_pod_ssh_phases as ssh_phases  # noqa: E402

ssh_phases.install_management_hooks()

from rent_pod_manage import parse_management_args, run_management  # noqa: E402

try:
    management = parse_management_args(public_argv)
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
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

from rent_pod_env import apply_env_defaults  # noqa: E402
import rent_pod_vcp as vcp_handoff  # noqa: E402

try:
    effective_argv = apply_env_defaults(public_argv, os.environ)
    queued_launch_argv = list(effective_argv) if queue_request is not None else None
    effective_argv, cli_startup_command = startup_handoff.consume_startup_args(
        effective_argv
    )
    effective_argv, ssh_exposure_timeout = ssh_phases.consume_ssh_phase_args(
        effective_argv, os.environ
    )
    effective_argv, vcp_enabled = vcp_handoff.consume_vcp_args(effective_argv)
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

from rent_pod_templates import (  # noqa: E402
    apply_context_to_payload,
    apply_template_profile,
    install_core_api_hook,
    print_selected_profile,
)


def _has_option(argv: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(name + "=") for arg in argv)


def _option_value(argv: list[str], name: str) -> str | None:
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


try:
    effective_argv, template_context = apply_template_profile(effective_argv, os.environ)
    effective_argv = cuda_profile_handoff.apply_template_cuda(
        public_argv,
        effective_argv,
        template_context,
        os.environ,
    )
    startup_command, startup_source = startup_handoff.resolve_startup_command(
        cli_startup_command,
        template_context,
    )
    list_requested = any(
        arg == "--list"
        or arg.startswith("--list=")
        or arg == "--list-all"
        or arg.startswith("--list-all=")
        for arg in effective_argv
    )
    if list_requested or queue_request is not None:
        resolved_pod_name = None
        naming_source = None
    else:
        effective_argv, resolved_pod_name, naming_source = (
            naming_handoff.apply_template_naming(
                effective_argv,
                template_context,
                os.environ.get("RUNPOD_API_KEY", "").strip(),
                resolve_collisions="--dry-run" not in effective_argv,
            )
        )
    rent_name = vcp_handoff.requested_name(effective_argv)

    if queued_launch_argv is not None:
        if not _has_option(queued_launch_argv, "--template"):
            queued_launch_argv.extend(["--template", template_context.requested])
        cuda_value = _option_value(effective_argv, "--cuda-min")
        if cuda_value and not _has_option(queued_launch_argv, "--cuda-min"):
            queued_launch_argv.extend(["--cuda-min", cuda_value])
        if startup_command and not _has_option(queued_launch_argv, "--startup"):
            queued_launch_argv.extend(["--startup", startup_command])
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)


def _requires_provision_hf(argv: list[str]) -> bool:
    if "--dry-run" in argv or "--no-provision" in argv:
        return False
    if any(
        arg == "--list"
        or arg.startswith("--list=")
        or arg == "--list-all"
        or arg.startswith("--list-all=")
        for arg in argv
    ):
        return False
    return True


if _requires_provision_hf(effective_argv):
    local_hf = (os.environ.get("HF_TOKEN") or "").strip()
    remote_hf = (
        (template_context.env.get("HF_TOKEN") or "").strip()
        or (template_context.env.get("HUGGINGFACE_HUB_TOKEN") or "").strip()
    )
    if not local_hf and not remote_hf:
        print(
            "ERROR: no Hugging Face credential is available for provisioning. "
            "Set local HF_TOKEN or map HF_TOKEN/HUGGINGFACE_HUB_TOKEN in the "
            "selected template (prefer [secrets] with a RunPod secret name).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not local_hf and remote_hf:
        print("[rent-pod] HF credential:          template/RunPod environment")

sys.argv = [sys.argv[0], *effective_argv]
install_core_api_hook(template_context)

from rent_pod_lifecycle import install_core_hooks  # noqa: E402

install_core_hooks()
ssh_phases.install_core_hook(ssh_exposure_timeout)
vcp_handoff.install_core_hooks(vcp_enabled, rent_name)
startup_handoff.install_core_hook(startup_command)

import rent_pod_frontend as frontend  # noqa: E402
from rent_pod_gpu_aliases import install_core_gpu_resolver  # noqa: E402

try:
    install_core_gpu_resolver(
        os.environ.get("RUNPOD_API_KEY", "").strip(),
        os.environ,
    )
except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2)

frontend.set_create_context_hook(
    lambda payload: apply_context_to_payload(payload, template_context)
)
api_v2_handoff.install_frontend_hooks(frontend)


def _print_naming_selection() -> None:
    if naming_source != "template" or not resolved_pod_name:
        return
    suffix = (
        " (base name; live collision check occurs when renting)"
        if "--dry-run" in effective_argv
        else ""
    )
    print(f"[rent-pod] Pod name:               {resolved_pod_name}{suffix}")


def _print_startup_selection() -> None:
    if not startup_command:
        return
    source = startup_source or "configured"
    suffix = "; skipped by --no-provision" if "--no-provision" in effective_argv else ""
    print(f"[rent-pod] Post-provision startup: {startup_command}")
    print(f"           source: {source}{suffix}")


def _queue_probe() -> dict[str, object]:
    forwarded, options = frontend.split_frontend_args(effective_argv)
    cloud, forwarded = frontend.cloud_from_args(forwarded, bool(options["community"]))
    cuda_min = frontend.validate_cuda_version(options["cuda_min"])
    args = frontend.core.build_parser().parse_args(forwarded)
    gpu_id = frontend.core.resolve_gpu(args.gpu_alias)
    return {
        "gpu_id": gpu_id,
        "gpu_label": args.gpu_alias,
        "cloud": cloud,
        "cuda_min": cuda_min,
        "min_download": args.min_download,
        "min_upload": args.min_upload,
        "min_disk": args.min_disk,
    }


_base_dry_run = frontend.dry_run


def _dry_run_with_profile(forwarded: list[str], cuda_min: str | None) -> int:
    rc = _base_dry_run(forwarded, cuda_min)
    print_selected_profile(template_context)
    _print_naming_selection()
    _print_startup_selection()
    return rc


frontend.dry_run = _dry_run_with_profile

if "--dry-run" not in effective_argv:
    print_selected_profile(template_context)
    _print_naming_selection()
    _print_startup_selection()
if vcp_enabled:
    suffix = f" as target {rent_name}" if rent_name else " as a named target"
    print(f"[rent-pod] VCP auto-config:       enabled after successful provision{suffix}")

if queue_request is not None:
    assert queued_launch_argv is not None
    try:
        raise SystemExit(
            queue_handoff.enqueue_request(
                queued_launch_argv,
                queue_request,
                _queue_probe(),
                os.environ,
            )
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(frontend.main())
