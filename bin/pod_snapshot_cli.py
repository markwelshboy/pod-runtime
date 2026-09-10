#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, NoReturn

import pod_state as core

PICK_SNAPSHOT = "__PICK_SNAPSHOT__"
JOURNAL_SCHEMA_VERSION = 1


class SnapshotCliError(RuntimeError):
    pass


def die(message: str, code: int = 1) -> NoReturn:
    print(f"[snapshot] ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def warn(message: str) -> None:
    print(f"[snapshot] WARN: {message}", file=sys.stderr)


def info(message: str) -> None:
    print(f"[snapshot] {message}")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc_string() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_template_arg(args: argparse.Namespace) -> str:
    positional = getattr(args, "template", None)
    option = getattr(args, "template_opt", "")
    if positional and option and positional != option:
        raise SnapshotCliError("template specified twice with different values")
    value = option or positional
    if not value:
        raise SnapshotCliError("template is required (positional or --template)")
    return str(value)


def snap_manifest_remote_path(template_name: str, sid: str) -> str:
    return f"{core.snapshot_dir(template_name)}/{sid}.manifest.json"


def parse_created(meta: dict[str, Any]) -> datetime | None:
    raw = str(meta.get("created_utc") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    sid = str(meta.get("id") or "")
    try:
        return datetime.strptime(sid[:15], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def human_age(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    seconds = max(0, int((now_utc() - dt).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    days = seconds // 86400
    if days < 14:
        return f"{days}d"
    if days < 70:
        return f"{days // 7}w"
    return f"{days // 30}mo"


def human_created(dt: datetime | None) -> str:
    return dt.strftime("%b %d %H:%MZ") if dt else "unknown"


def human_bytes(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return "?"


def journal(meta: dict[str, Any], template_name: str) -> dict[str, Any]:
    raw = meta.get("journal")
    current = raw if isinstance(raw, dict) else {}
    tags = current.get("tags")
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    fallback_name = ""
    outer_name = str(meta.get("name") or "").strip()
    if outer_name and outer_name != template_name:
        fallback_name = outer_name
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "name": str(current.get("name") if current.get("name") is not None else fallback_name).strip(),
        "note": str(current.get("note") or "").strip(),
        "next": str(current.get("next") or "").strip(),
        "tags": sorted(set(tags)),
        "pinned": bool(current.get("pinned", False)),
        "parent_snapshot": str(current.get("parent_snapshot") or "").strip() or None,
        "updated_utc": str(current.get("updated_utc") or "").strip() or None,
    }


def display_name(meta: dict[str, Any], template_name: str) -> str:
    name = journal(meta, template_name)["name"]
    return name or "[no description]"


def load_snapshot(template_name: str, requested: str) -> dict[str, Any]:
    sid = core.resolve_snapshot_id(template_name, requested)
    shown = core.run_hff(["snapshot", "--snapdir", core.snapshot_dir(template_name), "show", sid])
    try:
        meta = json.loads(shown)
    except json.JSONDecodeError as exc:
        raise SnapshotCliError(f"could not parse snapshot manifest for {sid}: {exc}") from exc
    if not isinstance(meta, dict) or meta.get("id") != sid:
        raise SnapshotCliError(f"invalid snapshot manifest for {sid}")
    return meta


def load_snapshots(template_name: str) -> list[dict[str, Any]]:
    output = core.run_hff(["snapshot", "--snapdir", core.snapshot_dir(template_name), "list"])
    ids = [line.strip() for line in output.splitlines() if line.strip()]
    if not ids:
        return []

    with tempfile.TemporaryDirectory(prefix=f"snapshot-list-{template_name}-") as tmp:
        core.run_hff(["get", f"{core.snapshot_dir(template_name)}/*.manifest.json", f"{tmp}/"])
        found: dict[str, dict[str, Any]] = {}
        for path in Path(tmp).rglob("*.manifest.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                warn(f"skipping unreadable snapshot manifest {path.name}: {exc}")
                continue
            if isinstance(meta, dict) and isinstance(meta.get("id"), str):
                found[meta["id"]] = meta

    result: list[dict[str, Any]] = []
    for sid in ids:
        meta = found.get(sid)
        if meta is None:
            warn(f"snapshot {sid} has no readable manifest; keeping it out of automated pruning")
            meta = {"id": sid, "name": "", "_manifest_unreadable": True}
        result.append(meta)
    return result


def write_snapshot(template_name: str, meta: dict[str, Any], message: str) -> None:
    sid = str(meta.get("id") or "").strip()
    if not sid:
        raise SnapshotCliError("snapshot manifest has no id")
    with tempfile.TemporaryDirectory(prefix=f"snapshot-meta-{sid}-") as tmp:
        local = Path(tmp) / f"{sid}.manifest.json"
        local.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        core.run_hff(["put", str(local), snap_manifest_remote_path(template_name, sid), "-m", message])


def update_journal(
    template_name: str,
    meta: dict[str, Any],
    *,
    name: str | None = None,
    note: str | None = None,
    next_action: str | None = None,
    add_tags: Iterable[str] = (),
    remove_tags: Iterable[str] = (),
    clear_tags: bool = False,
    pinned: bool | None = None,
    parent_snapshot: str | None | object = ...,
) -> dict[str, Any]:
    current = journal(meta, template_name)
    if name is not None:
        current["name"] = name.strip()
    if note is not None:
        current["note"] = note.strip()
    if next_action is not None:
        current["next"] = next_action.strip()
    tags = set() if clear_tags else set(current["tags"])
    tags.update(tag.strip() for tag in add_tags if tag.strip())
    tags.difference_update(tag.strip() for tag in remove_tags if tag.strip())
    current["tags"] = sorted(tags)
    if pinned is not None:
        current["pinned"] = pinned
    if parent_snapshot is not ...:
        current["parent_snapshot"] = str(parent_snapshot).strip() if parent_snapshot else None
    current["updated_utc"] = utc_string()
    meta = dict(meta)
    meta["journal"] = current
    return meta


def print_snapshot_detail(meta: dict[str, Any], template_name: str) -> None:
    j = journal(meta, template_name)
    dt = parse_created(meta)
    print()
    print("Snapshot")
    print(f"  ID:       {meta.get('id', '?')}")
    print(f"  Name:     {j['name'] or '[no description]'}")
    print(f"  Created:  {human_created(dt)} ({human_age(dt)} ago)")
    print(f"  Size:     {human_bytes((meta.get('tar') or {}).get('bytes'))}")
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
    print(f"Snapshots for {template_name}\n")
    print(" #  CREATED          AGE      NAME                              TAGS")
    print("--  ---------------  -------  --------------------------------  ------------------------")
    for idx, meta in enumerate(snapshots, 1):
        dt = parse_created(meta)
        j = journal(meta, template_name)
        star = "★" if j["pinned"] else " "
        name = display_name(meta, template_name)
        if len(name) > 32:
            name = name[:29] + "..."
        tags = ",".join(j["tags"])
        if len(tags) > 24:
            tags = tags[:21] + "..."
        print(f"{idx:2d}{star} {human_created(dt):15}  {human_age(dt):7}  {name:32}  {tags or '-'}")
        if j["next"]:
            nxt = j["next"]
            if len(nxt) > 100:
                nxt = nxt[:97] + "..."
            print(f"     Next: {nxt}")
    print()


def choose_snapshot(snapshots: list[dict[str, Any]], template_name: str) -> dict[str, Any]:
    if not snapshots:
        raise SnapshotCliError(f"no snapshots found for template {template_name}")
    if not sys.stdin.isatty():
        raise SnapshotCliError("interactive snapshot selection requires a TTY; specify --snapshot latest or --snapshot ID")
    print_snapshot_list(snapshots, template_name)
    while True:
        raw = input("Select snapshot [1]: ").strip()
        if not raw:
            return snapshots[0]
        try:
            idx = int(raw)
        except ValueError:
            print("Enter a snapshot number.")
            continue
        if 1 <= idx <= len(snapshots):
            return snapshots[idx - 1]
        print(f"Enter a number from 1 to {len(snapshots)}.")


def confirm(prompt: str, default: bool = False) -> bool:
    if not sys.stdin.isatty():
        return False
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input(prompt + suffix).strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def parent_snapshot_path(template_name: str) -> Path:
    """Local lineage marker for the snapshot this workspace currently descends from."""
    return Path("/workspace/.pod-state") / template_name / "snapshot_parent"


def get_parent_snapshot(template_name: str) -> str | None:
    path = parent_snapshot_path(template_name)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def set_parent_snapshot(template_name: str, sid: str | None) -> None:
    path = parent_snapshot_path(template_name)
    if sid:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sid + "\n", encoding="utf-8")
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def retention_policy(template: dict[str, Any]) -> dict[str, Any] | None:
    raw = template.get("snapshot", {}).get("retention")
    if not isinstance(raw, dict):
        return None

    def integer(key: str, default: int) -> int:
        value = raw.get(key, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise SnapshotCliError(f"snapshot.retention.{key} must be an integer") from exc
        if parsed < 0:
            raise SnapshotCliError(f"snapshot.retention.{key} must be >= 0")
        return parsed

    return {
        "recent": integer("recent", 5),
        "daily": integer("daily", 7),
        "weekly": integer("weekly", 4),
        "grace_hours": integer("grace_hours", 48),
        "auto_prune_after_snapshot": bool(raw.get("auto_prune_after_snapshot", False)),
    }


def retention_plan(
    snapshots: list[dict[str, Any]],
    template_name: str,
    policy: dict[str, Any],
    extra_keep: set[str] | None = None,
) -> tuple[dict[str, set[str]], list[dict[str, Any]]]:
    keep: dict[str, set[str]] = {}
    extra_keep = extra_keep or set()

    def protect(meta: dict[str, Any], reason: str) -> None:
        sid = str(meta.get("id") or "")
        if sid:
            keep.setdefault(sid, set()).add(reason)

    ordered = sorted(
        snapshots,
        key=lambda m: parse_created(m) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    for meta in ordered:
        sid = str(meta.get("id") or "")
        if meta.get("_manifest_unreadable") or parse_created(meta) is None:
            protect(meta, "unreadable/unknown-date")
        if sid in extra_keep:
            protect(meta, "active")
        if journal(meta, template_name)["pinned"]:
            protect(meta, "pinned")

    recent = int(policy["recent"])
    for meta in ordered[:recent]:
        protect(meta, "recent")

    grace_hours = int(policy["grace_hours"])
    if grace_hours:
        cutoff_seconds = grace_hours * 3600
        for meta in ordered:
            dt = parse_created(meta)
            if dt is not None and (now_utc() - dt).total_seconds() <= cutoff_seconds:
                protect(meta, "grace")

    generational_ids = {
        sid for sid, reasons in keep.items() if reasons & {"recent", "grace", "active"}
    }

    seen_days: set[tuple[int, int, int]] = set()
    for meta in ordered:
        sid = str(meta.get("id") or "")
        if sid not in generational_ids:
            continue
        dt = parse_created(meta)
        if dt:
            seen_days.add((dt.year, dt.month, dt.day))
    for meta in ordered:
        if len(seen_days) >= int(policy["daily"]):
            break
        dt = parse_created(meta)
        if dt is None:
            continue
        key = (dt.year, dt.month, dt.day)
        if key not in seen_days:
            protect(meta, "daily")
            generational_ids.add(str(meta.get("id") or ""))
            seen_days.add(key)

    seen_weeks: set[tuple[int, int]] = set()
    for meta in ordered:
        sid = str(meta.get("id") or "")
        if sid not in generational_ids:
            continue
        dt = parse_created(meta)
        if dt:
            iso = dt.isocalendar()
            seen_weeks.add((iso.year, iso.week))
    for meta in ordered:
        if len(seen_weeks) >= int(policy["weekly"]):
            break
        dt = parse_created(meta)
        if dt is None:
            continue
        iso = dt.isocalendar()
        key = (iso.year, iso.week)
        if key not in seen_weeks:
            protect(meta, "weekly")
            generational_ids.add(str(meta.get("id") or ""))
            seen_weeks.add(key)

    eligible = [meta for meta in reversed(ordered) if str(meta.get("id") or "") not in keep]
    return keep, eligible


def show_prune_plan(eligible: list[dict[str, Any]], template_name: str) -> None:
    if not eligible:
        print("Retention: no snapshots are eligible for pruning.")
        return
    total = sum(int((meta.get("tar") or {}).get("bytes") or 0) for meta in eligible)
    print(f"Retention: {len(eligible)} snapshot(s) eligible for pruning ({human_bytes(total)}).")
    for meta in eligible:
        print(f"  - {meta.get('id')}  {display_name(meta, template_name)}  {human_bytes((meta.get('tar') or {}).get('bytes'))}")


def prune(
    template: dict[str, Any],
    *,
    dry_run: bool,
    assume_yes: bool,
    extra_keep: set[str] | None = None,
) -> int:
    policy = retention_policy(template)
    if policy is None:
        raise SnapshotCliError(f"template {template['name']} has no snapshot.retention policy")
    snapshots = load_snapshots(template["name"])
    _, eligible = retention_plan(snapshots, template["name"], policy, extra_keep=extra_keep)
    show_prune_plan(eligible, template["name"])
    if not eligible or dry_run:
        return 0
    if not assume_yes and not confirm(f"Prune these {len(eligible)} snapshot(s)?"):
        info("prune cancelled")
        return 0
    for meta in eligible:
        sid = str(meta["id"])
        info(f"pruning {sid}")
        core.run_hff(["snapshot", "--snapdir", core.snapshot_dir(template["name"]), "destroy", sid, "-y"])
    info(f"pruned {len(eligible)} snapshot(s)")
    return len(eligible)


class Tee(io.TextIOBase):
    def __init__(self, target: Any) -> None:
        self.target = target
        self.buffer = io.StringIO()

    def write(self, s: str) -> int:
        self.target.write(s)
        self.target.flush()
        self.buffer.write(s)
        return len(s)

    def flush(self) -> None:
        self.target.flush()

    def value(self) -> str:
        return self.buffer.getvalue()


def run_core_snapshot(args: argparse.Namespace) -> str | None:
    ns = argparse.Namespace(template=args.template, name=args.name, force=args.force, dry_run=args.dry_run)
    tee = Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        core.cmd_snapshot(ns)
    if args.dry_run:
        return None
    matches = re.findall(r"^\[pod-state\] snapshot: (\S+)\s*$", tee.value(), flags=re.MULTILINE)
    if not matches:
        raise SnapshotCliError("snapshot was created but its id could not be determined")
    return matches[-1]


def snapshot_create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="snapshot-pod",
        description="Capture a pod snapshot and optionally attach journal metadata.",
        epilog=(
            "Management: snapshot-pod list TEMPLATE | show TEMPLATE [ID] | "
            "prune TEMPLATE | delete TEMPLATE ID"
        ),
    )
    p.add_argument("template", nargs="?", help="template name or YAML path")
    p.add_argument("--template", dest="template_opt", default="", help="template name or YAML path")
    p.add_argument("--name", default="", help="short human-readable snapshot name")
    p.add_argument("--note", "--why", "--description", dest="note", default="", help="why this snapshot was taken")
    p.add_argument("--next", dest="next_action", default="", help="suggested next action")
    p.add_argument("--tag", action="append", default=[], help="tag (repeatable)")
    p.add_argument("--pin", action="store_true", help="exempt snapshot from automatic pruning")
    p.add_argument("--force", action="store_true", help="allow dirty/unpushed source state")
    p.add_argument("--dry-run", action="store_true")
    pruning = p.add_mutually_exclusive_group()
    pruning.add_argument("--prune", action="store_true", help="run retention after successful snapshot even if template auto-prune is off")
    pruning.add_argument("--no-prune", action="store_true", help="skip retention for this snapshot")
    return p


def cmd_snapshot_create(argv: list[str]) -> int:
    args = snapshot_create_parser().parse_args(argv)
    args.template = resolve_template_arg(args)
    template = core.load_template(args.template)
    sid = run_core_snapshot(args)
    if sid is None:
        return 0

    meta = load_snapshot(template["name"], sid)
    parent = get_parent_snapshot(template["name"])
    meta = update_journal(
        template["name"], meta,
        name=args.name,
        note=args.note,
        next_action=args.next_action,
        add_tags=args.tag,
        pinned=args.pin,
        parent_snapshot=parent,
    )
    write_snapshot(template["name"], meta, f"snapshot journal: {sid}")
    set_parent_snapshot(template["name"], sid)
    info("snapshot journal metadata recorded")
    if not any((args.name, args.note, args.next_action, args.tag, args.pin)):
        print(f"Add notes later with: configure-snapshot {template['name']} {sid}")

    policy = retention_policy(template)
    should_prune = False
    if not args.no_prune:
        should_prune = args.prune or bool(policy and policy["auto_prune_after_snapshot"])
    if should_prune:
        prune(template, dry_run=False, assume_yes=True, extra_keep={sid})
    return 0


def snapshot_management_parser(action: str) -> argparse.ArgumentParser:
    if action == "list":
        p = argparse.ArgumentParser(prog="snapshot-pod list")
        p.add_argument("template")
        p.add_argument("--tag", default="", help="show only snapshots with this tag")
        p.add_argument("--json", action="store_true")
        return p
    if action == "show":
        p = argparse.ArgumentParser(prog="snapshot-pod show")
        p.add_argument("template")
        p.add_argument("snapshot", nargs="?", default="latest")
        return p
    if action == "prune":
        p = argparse.ArgumentParser(prog="snapshot-pod prune")
        p.add_argument("template")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("-y", "--yes", action="store_true")
        return p
    if action == "delete":
        p = argparse.ArgumentParser(prog="snapshot-pod delete")
        p.add_argument("template")
        p.add_argument("snapshot")
        p.add_argument("--force", action="store_true", help="allow deletion of a pinned snapshot")
        p.add_argument("-y", "--yes", action="store_true")
        return p
    raise SnapshotCliError(f"unknown snapshot action: {action}")


def cmd_snapshot_management(action: str, argv: list[str]) -> int:
    args = snapshot_management_parser(action).parse_args(argv)
    template = core.load_template(args.template)
    name = template["name"]
    if action == "list":
        snapshots = load_snapshots(name)
        if args.tag:
            snapshots = [m for m in snapshots if args.tag in journal(m, name)["tags"]]
        if args.json:
            print(json.dumps(snapshots, indent=2))
        else:
            print_snapshot_list(snapshots, name)
        return 0
    if action == "show":
        print_snapshot_detail(load_snapshot(name, args.snapshot), name)
        return 0
    if action == "prune":
        prune(template, dry_run=args.dry_run, assume_yes=args.yes)
        return 0
    if action == "delete":
        meta = load_snapshot(name, args.snapshot)
        sid = str(meta["id"])
        if journal(meta, name)["pinned"] and not args.force:
            raise SnapshotCliError(
                f"snapshot {sid} is pinned; unpin it with configure-snapshot or pass --force"
            )
        print_snapshot_detail(meta, name)
        if not args.yes and not confirm(f"Delete snapshot {sid}?"):
            info("delete cancelled")
            return 0
        core.run_hff(["snapshot", "--snapdir", core.snapshot_dir(name), "destroy", sid, "-y"])
        info(f"deleted {sid}")
        return 0
    return 1


def main_snapshot(argv: list[str]) -> int:
    actions = {"list", "show", "prune", "delete"}
    if argv and argv[0] in actions:
        return cmd_snapshot_management(argv[0], argv[1:])
    return cmd_snapshot_create(argv)


def configure_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="configure-pod")
    p.add_argument("template", nargs="?", help="template name or YAML path")
    p.add_argument("--template", dest="template_opt", default="", help="template name or YAML path")
    p.add_argument(
        "--snapshot",
        nargs="?",
        const=PICK_SNAPSHOT,
        default="",
        help="snapshot id, 'latest', or omit value to browse snapshots interactively",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--prune-snapshots", action="store_true", help="apply retention after successful configure")
    p.add_argument("-y", "--yes", action="store_true", help="do not prompt for post-configure pruning")
    return p


def cmd_configure(argv: list[str]) -> int:
    args = configure_parser().parse_args(argv)
    args.template = resolve_template_arg(args)
    template = core.load_template(args.template)
    requested = args.snapshot
    selected_sid: str | None = None
    interactive_choice = requested == PICK_SNAPSHOT

    if interactive_choice:
        selected = choose_snapshot(load_snapshots(template["name"]), template["name"])
        selected_sid = str(selected["id"])
        print_snapshot_detail(selected, template["name"])
        if not confirm("Restore this snapshot?", default=True):
            info("configure cancelled")
            return 0
    elif requested:
        selected = load_snapshot(template["name"], requested)
        selected_sid = str(selected["id"])
        print_snapshot_detail(selected, template["name"])

    ns = argparse.Namespace(
        template=args.template,
        snapshot=selected_sid or "",
        dry_run=args.dry_run,
    )
    result = core.cmd_configure(ns)
    if not args.dry_run:
        set_parent_snapshot(template["name"], selected_sid)
    if args.prune_snapshots and not args.dry_run:
        prune(
            template,
            dry_run=False,
            assume_yes=args.yes,
            extra_keep={selected_sid} if selected_sid else set(),
        )
    return result


def configure_snapshot_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="configure-snapshot",
        description="View or edit snapshot journal metadata without rebuilding the snapshot archive.",
    )
    p.add_argument("template", nargs="?", help="template name or YAML path")
    p.add_argument("snapshot", nargs="?", default="", help="snapshot id or 'latest'; omit to choose interactively")
    p.add_argument("--template", dest="template_opt", default="", help="template name or YAML path")
    p.add_argument("--name", default=None, help="replace human-readable name")
    p.add_argument("--note", "--why", "--description", dest="note", default=None, help="replace why/description")
    p.add_argument("--next", dest="next_action", default=None, help="replace next action")
    p.add_argument("--tag", action="append", default=[], help="add tag (repeatable)")
    p.add_argument("--remove-tag", action="append", default=[], help="remove tag (repeatable)")
    p.add_argument("--clear-tags", action="store_true")
    pins = p.add_mutually_exclusive_group()
    pins.add_argument("--pin", action="store_true")
    pins.add_argument("--unpin", action="store_true")
    p.add_argument("--show", action="store_true", help="show metadata without opening interactive editor")
    return p


def prompt_value(label: str, current: str) -> str:
    shown = current or "-"
    raw = input(f"{label} [{shown}]: ").strip()
    if not raw:
        return current
    if raw == "-":
        return ""
    return raw


def interactive_edit(meta: dict[str, Any], template_name: str) -> dict[str, Any]:
    current = journal(meta, template_name)
    print("Press Enter to keep a value; enter '-' to clear text/tags.\n")
    name = prompt_value("Name", current["name"])
    note = prompt_value("Why", current["note"])
    next_action = prompt_value("Next", current["next"])
    tags_raw = prompt_value("Tags (comma-separated)", ",".join(current["tags"]))
    while True:
        pin_default = "y" if current["pinned"] else "n"
        raw = input(f"Pinned [y/n, current {pin_default}]: ").strip().lower()
        if not raw:
            pinned = current["pinned"]
            break
        if raw in {"y", "yes"}:
            pinned = True
            break
        if raw in {"n", "no"}:
            pinned = False
            break
        print("Enter y or n.")
    return update_journal(
        template_name,
        meta,
        name=name,
        note=note,
        next_action=next_action,
        clear_tags=True,
        add_tags=[tag.strip() for tag in tags_raw.split(",") if tag.strip()],
        pinned=pinned,
    )


def cmd_configure_snapshot(argv: list[str]) -> int:
    args = configure_snapshot_parser().parse_args(argv)
    args.template = resolve_template_arg(args)
    template = core.load_template(args.template)
    template_name = template["name"]

    if args.snapshot:
        meta = load_snapshot(template_name, args.snapshot)
    else:
        meta = choose_snapshot(load_snapshots(template_name), template_name)

    has_patch = any([
        args.name is not None,
        args.note is not None,
        args.next_action is not None,
        bool(args.tag),
        bool(args.remove_tag),
        args.clear_tags,
        args.pin,
        args.unpin,
    ])

    if args.show:
        print_snapshot_detail(meta, template_name)
        return 0

    if not has_patch:
        if not sys.stdin.isatty():
            print_snapshot_detail(meta, template_name)
            return 0
        print_snapshot_detail(meta, template_name)
        updated = interactive_edit(meta, template_name)
    else:
        pinned = True if args.pin else False if args.unpin else None
        updated = update_journal(
            template_name,
            meta,
            name=args.name,
            note=args.note,
            next_action=args.next_action,
            add_tags=args.tag,
            remove_tags=args.remove_tag,
            clear_tags=args.clear_tags,
            pinned=pinned,
        )

    sid = str(updated["id"])
    write_snapshot(template_name, updated, f"configure snapshot journal: {sid}")
    info(f"updated snapshot metadata: {sid}")
    print_snapshot_detail(updated, template_name)
    return 0


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        die("internal invocation requires mode: snapshot, configure, or configure-snapshot", 2)
    mode, rest = values[0], values[1:]
    try:
        if mode == "snapshot":
            return main_snapshot(rest)
        if mode == "configure":
            return cmd_configure(rest)
        if mode == "configure-snapshot":
            return cmd_configure_snapshot(rest)
        raise SnapshotCliError(f"unknown mode: {mode}")
    except SnapshotCliError as exc:
        die(str(exc))
    except core.PodStateError as exc:
        die(str(exc))
    except subprocess.CalledProcessError as exc:
        rendered = " ".join(str(part) for part in exc.cmd)
        die(f"command failed ({exc.returncode}): {rendered}", exc.returncode or 1)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
