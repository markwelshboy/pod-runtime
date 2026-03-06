#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path
from datetime import datetime

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
HEADER_RE = re.compile(r"^\[(.+?)\]\s*$")  # [filename.png]

def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)

def normalize_caption_block(lines):
    # Strip leading/trailing blank lines; keep internal newlines
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    while lines and lines[-1].strip() == "":
        lines = lines[:-1]
    return "\n".join(l.rstrip("\r") for l in lines).strip()

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def write_text(p: Path, s: str):
    p.write_text(s, encoding="utf-8")

def backup_file(p: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    b = p.with_suffix(p.suffix + f".bak.{ts}")
    b.write_bytes(p.read_bytes())
    return b

def iter_images(input_dir: Path):
    for p in sorted(input_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            yield p

def find_caption_for_image(img_path: Path) -> Path:
    return img_path.with_suffix(".txt")

def ensure_trigger_prefix(caption: str, trigger: str) -> str:
    """
    Ensure caption starts with 'trigger, ' (idempotent-ish).
    """
    trig = trigger.strip()
    if not trig:
        return caption

    cap_l = caption.lstrip()
    if cap_l.startswith(trig):
        rest = cap_l[len(trig):]
        if rest == "" or rest.startswith(",") or rest.startswith(" "):
            return caption

    if caption.strip() == "":
        return trig
    return f"{trig}, {cap_l}"

def ensure_trigger_suffix(caption: str, trigger: str) -> str:
    """
    Ensure caption ends with ', trigger' (idempotent-ish).
    """
    trig = trigger.strip()
    if not trig:
        return caption

    cap = caption.strip()
    if cap == "":
        return trig

    # crude but effective: if trigger already appears as last token, don't re-add
    # allow trailing punctuation/space
    tail = cap.rstrip(" ,")
    if tail.endswith(trig):
        return caption

    # Add with comma separation
    return f"{cap}, {trig}"

def parse_block_file(p: Path):
    """
    Parses:
      [filename.png]
      caption...
      [next.png]
      ...

    Returns list of (filename, caption_str).
    """
    text = read_text(p).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    entries = []
    cur_fn = None
    cur_lines = []

    def flush():
        nonlocal cur_fn, cur_lines
        if cur_fn is None:
            return
        cap = normalize_caption_block(cur_lines)
        entries.append((cur_fn, cap))
        cur_fn = None
        cur_lines = []

    for i, line in enumerate(lines, start=1):
        m = HEADER_RE.match(line.strip())
        if m:
            flush()
            fn = m.group(1).strip()
            if not fn:
                raise SystemExit(f"Invalid empty header at line {i}")
            cur_fn = Path(fn).name  # sanitize to filename only
            cur_lines = []
        else:
            if cur_fn is None:
                # allow comments/blanks before first header
                if line.strip() == "" or line.lstrip().startswith("#"):
                    continue
                raise SystemExit(f"Content before first [header] at line {i}: {line!r}")
            cur_lines.append(line)

    flush()
    return entries

def render_block_file(entries):
    """
    Render entries back into block file text.
    """
    out_lines = []
    out_lines.append("# captionator block file")
    out_lines.append("# format:")
    out_lines.append("#   [filename.png]")
    out_lines.append("#   caption text (can be multiple lines)")
    out_lines.append("")

    for fn, cap in entries:
        out_lines.append(f"[{Path(fn).name}]")
        if cap:
            out_lines.extend(cap.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
        out_lines.append("")

    return "\n".join(out_lines).rstrip() + "\n"

def cmd_merge(args):
    input_dir = Path(args.input_dir).resolve()
    out_file = Path(args.file).resolve()

    if not input_dir.exists():
        raise SystemExit(f"Input dir does not exist: {input_dir}")

    blocks = []
    total = 0
    missing = 0

    for img in iter_images(input_dir):
        total += 1
        cap_file = find_caption_for_image(img)
        if cap_file.exists():
            cap = read_text(cap_file).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        else:
            missing += 1
            if not args.include_missing:
                continue
            cap = ""

        if args.trigger:
            cap = ensure_trigger_prefix(cap, args.trigger)

        blocks.append((img.name, cap))

    content = render_block_file(blocks)

    if out_file.exists() and not args.no_backup:
        b = backup_file(out_file)
        eprint(f"Backed up existing file -> {b}")

    if args.dry_run:
        eprint(f"[dry-run] Would write {len(blocks)} blocks to {out_file}")
    else:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        write_text(out_file, content)
        eprint(f"Wrote {len(blocks)} blocks to {out_file}")

    eprint(f"Scanned images: {total}, included: {len(blocks)}, missing captions: {missing}")

def cmd_split(args):
    caps_file = Path(args.file).resolve()
    out_dir = Path(args.output_dir).resolve()

    if not caps_file.exists():
        raise SystemExit(f"Captions file does not exist: {caps_file}")

    entries = parse_block_file(caps_file)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    for fn, cap in entries:
        img_name = Path(fn).name
        txt_name = str(Path(img_name).with_suffix(".txt"))
        out_path = out_dir / txt_name

        if args.require_image:
            img_path = out_dir / img_name
            if not img_path.exists():
                skipped += 1
                continue

        if out_path.exists() and not args.no_backup:
            b = backup_file(out_path)
            eprint(f"Backed up {out_path.name} -> {b.name}")

        if args.dry_run:
            eprint(f"[dry-run] Would write {out_path}")
        else:
            write_text(out_path, (cap.rstrip("\n") + "\n") if cap else "\n")

        written += 1

    eprint(f"Entries: {len(entries)}, written: {written}, skipped: {skipped}")
    if skipped:
        eprint("Note: skipped entries due to --require-image")

def cmd_trigger(args):
    caps_file = Path(args.file).resolve()
    if not caps_file.exists():
        raise SystemExit(f"Captions file does not exist: {caps_file}")

    entries = parse_block_file(caps_file)

    trigger = args.trigger.strip()
    if not trigger:
        raise SystemExit("Trigger must be non-empty")

    changed = 0
    out_entries = []

    for fn, cap in entries:
        new_cap = cap
        if args.mode == "prefix":
            new_cap = ensure_trigger_prefix(cap, trigger)
        elif args.mode == "suffix":
            new_cap = ensure_trigger_suffix(cap, trigger)
        else:
            raise SystemExit(f"Unknown mode: {args.mode}")

        if new_cap != cap:
            changed += 1
        out_entries.append((fn, new_cap))

    content = render_block_file(out_entries)

    if args.dry_run:
        eprint(f"[dry-run] Would update {changed}/{len(entries)} blocks in {caps_file} (mode={args.mode})")
        return

    if caps_file.exists() and not args.no_backup:
        b = backup_file(caps_file)
        eprint(f"Backed up -> {b}")

    write_text(caps_file, content)
    eprint(f"Updated {changed}/{len(entries)} blocks in {caps_file} (mode={args.mode})")

def build_parser():
    p = argparse.ArgumentParser(
        prog="captionator",
        description="Merge per-image caption .txt files into a single block file, split back, and apply triggers."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("merge", help="Merge per-image .txt captions into a single block file")
    pm.add_argument("--input-dir", "-i", default=".", help="Directory containing images + .txt captions")
    pm.add_argument("--file", "-f", required=True, help="Output captions file (e.g. captions.txt)")
    pm.add_argument("--trigger", default="", help='Prepend trigger to every caption during merge (e.g. "ohwx dog")')
    pm.add_argument("--include-missing", action="store_true", help="Include images even if caption .txt is missing (empty caption)")
    pm.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    pm.add_argument("--no-backup", action="store_true", help="Do not create .bak.* backups when overwriting captions file")
    pm.set_defaults(func=cmd_merge)

    ps = sub.add_parser("split", help="Split a block captions file back into individual .txt caption files")
    ps.add_argument("--file", "-f", required=True, help="Input captions file (e.g. captions.txt)")
    ps.add_argument("--output-dir", "-o", default=".", help="Where to write individual .txt files")
    ps.add_argument("--require-image", action="store_true", help="Only write captions where the referenced image exists in output-dir")
    ps.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    ps.add_argument("--no-backup", action="store_true", help="Do not create .bak.* backups when overwriting caption .txt files")
    ps.set_defaults(func=cmd_split)

    pt = sub.add_parser("trigger", help="Apply a trigger to captions.txt in-place (backup by default)")
    pt.add_argument("--file", "-f", required=True, help="Captions file to edit in-place (block format)")
    pt.add_argument("--trigger", required=True, help='Trigger text (e.g. "ohwx dog")')
    pt.add_argument("--mode", choices=["prefix", "suffix"], default="prefix",
                    help="Where to apply trigger: prefix (default) or suffix")
    pt.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    pt.add_argument("--no-backup", action="store_true", help="Do not create .bak.* backups when editing captions file")
    pt.set_defaults(func=cmd_trigger)

    return p

def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

