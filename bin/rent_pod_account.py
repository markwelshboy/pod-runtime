#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Mapping

import rent_pod as core

GRAPHQL_URL = os.environ.get("RUNPOD_GRAPHQL_URL", "https://api.runpod.io/graphql")

ACCOUNT_QUERY = """
query rentPodAccountBalance {
  myself {
    clientBalance
    currentSpendPerHr
    spendLimit
  }
}
"""


def graphql_account(api_key: str) -> dict[str, Any]:
    payload = json.dumps({"query": ACCOUNT_QUERY, "variables": {}}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise core.RunPodError(
            f"RunPod GraphQL account query failed: HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise core.RunPodError(f"RunPod GraphQL account query failed: {exc.reason}") from exc

    errors = result.get("errors")
    if errors:
        raise core.RunPodError(f"RunPod GraphQL account errors: {json.dumps(errors)}")
    data = result.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("myself"), dict):
        raise core.RunPodError(f"unexpected RunPod account response: {result!r}")
    return data["myself"]


def format_runway(balance: float, spend_per_hr: float) -> str:
    if spend_per_hr <= 0:
        return "∞ (no current spend)"
    if balance <= 0:
        return "0m"
    total_minutes = max(0, int((balance / spend_per_hr) * 60))
    days, rem = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def show_balance(api_key: str) -> int:
    account = graphql_account(api_key)
    try:
        balance = float(account.get("clientBalance") or 0.0)
        spend = float(account.get("currentSpendPerHr") or 0.0)
        spend_limit = float(account.get("spendLimit") or 0.0)
    except (TypeError, ValueError) as exc:
        raise core.RunPodError(f"unexpected RunPod account numeric fields: {account!r}") from exc

    print("[rent-pod] RunPod account")
    print(f"           balance:          ${balance:.2f}")
    print(f"           current spend:    ${spend:.3f}/hr")
    print(f"           spend limit:      ${spend_limit:.2f}/hr")
    print(f"           runway:           {format_runway(balance, spend)}")
    return 0


def handle_balance_command(
    argv: list[str],
    environ: Mapping[str, str] | None = None,
) -> int | None:
    if "--balance" not in argv:
        return None
    if argv != ["--balance"]:
        extras = [arg for arg in argv if arg != "--balance"]
        raise ValueError(
            "--balance cannot be combined with other options"
            + (f": {' '.join(extras)}" if extras else "")
        )

    env = os.environ if environ is None else environ
    api_key = (env.get("RUNPOD_API_KEY") or "").strip()
    if not api_key:
        print("ERROR: RUNPOD_API_KEY is required for --balance.", file=sys.stderr)
        return 2
    return show_balance(api_key)
