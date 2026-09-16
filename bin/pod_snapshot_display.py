#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

_installed = False


def install_cli_hooks(cli: Any) -> None:
    """Show the full snapshot ID in human-readable snapshot listings."""
    global _installed
    if _installed:
        return

    def print_snapshot_list(snapshots: list[dict[str, Any]], template_name: str) -> None:
        if not snapshots:
            print(f"No snapshots found for {template_name}.")
            return

        id_width = max(
            len("SNAPSHOT ID"),
            *(len(str(meta.get("id") or "?")) for meta in snapshots),
        )

        print(f"Snapshots for {template_name}\n")
        print(
            f" #  {'SNAPSHOT ID':{id_width}}  CREATED          AGE      "
            "NAME                              TAGS"
        )
        print(
            f"--  {'-' * id_width}  ---------------  -------  "
            "--------------------------------  ------------------------"
        )

        for idx, meta in enumerate(snapshots, 1):
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
                f"{idx:2d}{star} {sid:{id_width}}  {cli.human_created(dt):15}  "
                f"{cli.human_age(dt):7}  {name:32}  {tags or '-'}"
            )
            if j["next"]:
                nxt = j["next"]
                if len(nxt) > 100:
                    nxt = nxt[:97] + "..."
                print(f"     {'':{id_width}}  Next: {nxt}")
        print()

    cli.print_snapshot_list = print_snapshot_list
    _installed = True
