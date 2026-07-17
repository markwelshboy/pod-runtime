#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the workflow currently active in a ComfyUI browser tab")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-age", type=float, default=10.0)
    args = parser.parse_args()

    url = args.comfy_url.rstrip("/") + "/pod_runtime/workflow_bridge/current"
    request = urllib.request.Request(url, headers={"User-Agent": "pod-runtime-current-workflow/1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"workflow bridge returned HTTP {error.code}: {detail}") from error
    except Exception as error:
        raise RuntimeError(
            f"could not contact workflow bridge at {url}: {error}. "
            "Install the pod-runtime workflow bridge, restart ComfyUI, and focus the desired browser tab."
        ) from error

    workflow = payload.get("workflow") if isinstance(payload, dict) else None
    if not isinstance(workflow, dict):
        raise RuntimeError("workflow bridge response did not contain a workflow object")

    age = float(payload.get("age_seconds", 1e9))
    if age > args.max_age:
        raise RuntimeError(
            f"active workflow publication is stale ({age:.1f}s old). "
            "Focus the desired ComfyUI tab and retry."
        )

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(workflow, indent=2) + "\n")
    temporary.replace(output)

    print(f"Active workflow : {payload.get('title') or 'untitled'}")
    print(f"Browser client  : {payload.get('client_id') or '-'}")
    print(f"Publication age : {age:.1f}s")
    print(f"Workflow file   : {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"current ComfyUI workflow: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
