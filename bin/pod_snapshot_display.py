#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_installed = False


def _display_timezone():
    """Return the local timezone used for human-readable snapshot timestamps.

    Prefer the runtime's explicit timezone settings so pod/local displays agree,
    then fall back to the host timezone. This keeps stored snapshot timestamps in
    UTC while presenting them in the operator's local PST/PDT-style clock.
    """
    for raw in (
        os.environ.get("SNAPSHOT_DISPLAY_TIMEZONE"),
        os.environ.get("POD_TIMEZONE"),
        os.environ.get("TZ"),
    ):
        name = (raw or "").strip()
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass

    try:
        name = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if name:
            return ZoneInfo(name)
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass

    return datetime.now().astimezone().tzinfo or timezone.utc


def _human_created_local(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    local = dt.astimezone(_display_timezone())
    zone = local.tzname() or local.strftime("%z") or "local"
    return f"{local.strftime('%b %d %H:%M')} {zone}"


def install_cli_hooks(cli: Any) -> None:
    """Show full snapshot IDs and local-time timestamps in human listings."""
    global _installed
    if _installed:
        return

    def print_snapshot_detail(meta: dict[str, Any], template_name: str) -> None:
        j = cli.journal(meta, template_name)
        dt = cli.parse_created(meta)
        print()
        print("Snapshot")
        print(f"  ID:       {meta.get('id', '?')}")
        print(f"  Name:     {j['name'] or '[no description]'}")
        print(f"  Created:  {_human_created_local(dt)} ({cli.human_age(dt)} ago)")
        print(f"  Size:     {cli.human_bytes((meta.get('tar') or {}).get('bytes'))}")
        print(f"  Tags:     {', '.join(j['tags']) if j['tags'] else '-'}")
        print(f"  Pinned:   {'yes' if j['pinned'] else 'no'}")
        if j["parent_snapshot"]:
            print(f"  Parent:   {j['parent_snapshot']}")
        print()
        print("  Why:")
        print(f"    {j['note'] or '-'}")
        print()
        print("  Next:")
        print(f"    {j['next'] or '-'}")
        print()

    def print_snapshot_list(snapshots: list[dict[str, Any]], template_name: str) -> None:
        if not snapshots:
            print(f"No snapshots found for {template_name}.")
            return

        id_width = max(
            len("SNAPSHOT ID"),
            *(len(str(meta.get("id") or "?")) for meta in snapshots),
        )
        created_values = [_human_created_local(cli.parse_created(meta)) for meta in snapshots]
        created_width = max(len("CREATED"), *(len(value) for value in created_values))
        age_width = 7
        name_column = 4 + id_width + 2 + created_width + 2 + age_width + 2

        print(f"Snapshots for {template_name}\n")
        print(
            f" #  {'SNAPSHOT ID':{id_width}}  {'CREATED':{created_width}}  {'AGE':{age_width}}  "
            "NAME                              TAGS"
        )
        print(
            f"--  {'-' * id_width}  {'-' * created_width}  {'-' * age_width}  "
            "--------------------------------  ------------------------"
        )

        for idx, (meta, created) in enumerate(zip(snapshots, created_values), 1):
            dt = cli.parse_created(meta)
            j = cli.journal(meta, template_name)
            star = "★" if j["pinned"] else " "
            sid = str(meta.get("id") or "?")
            name = cli.display_name(meta, template_name)
            if len(name) > 32:
                name = name[:29] + "..."
            tags = ",".join(j["tags"])
            if len(tags) > 24:
                tags = tags[:21] + "..."
            print(
                f"{idx:2d}{star} {sid:{id_width}}  {created:{created_width}}  "
                f"{cli.human_age(dt):{age_width}}  {name:32}  {tags or '-'}"
            )
            if j["next"]:
                nxt = j["next"]
                if len(nxt) > 100:
                    nxt = nxt[:97] + "..."
                print(" " * name_column + f"Next: {nxt}")
        print()

    cli.print_snapshot_detail = print_snapshot_detail
    cli.print_snapshot_list = print_snapshot_list
    _installed = True
