#!/usr/bin/env python3
import argparse
import fnmatch
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Set, Tuple

from huggingface_hub import HfApi

# ---- commit ops imports (version-flexible) ----
try:
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, CommitOperationCopy  # type: ignore
except Exception:
    from huggingface_hub._commit_api import CommitOperationAdd, CommitOperationDelete, CommitOperationCopy  # type: ignore


def die(msg: str, code: int = 2) -> None:
    print(f"[hff] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def need_token() -> str:
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        die("HF_TOKEN is not set")
    return tok


def normalize_path(p: str) -> str:
    p = p.strip()
    p = p.lstrip("/")  # treat as repo-relative
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def is_root(path: str) -> bool:
    return "/" not in normalize_path(path)


def parent_dir(path: str) -> str:
    p = normalize_path(path)
    if "/" not in p:
        return ""
    return p.rsplit("/", 1)[0]


def ensure_dir_ops(existing: Set[str], dir_path: str) -> List[object]:
    """Ensure a 'directory' exists by adding <dir>/.gitkeep if missing."""
    ops: List[object] = []
    d = normalize_path(dir_path)
    if not d:
        return ops
    keep = f"{d}/.gitkeep"
    if keep not in existing:
        ops.append(_make_add_op(keep, b""))
        existing.add(keep)
    return ops


def unique_dest(dest: str, existing: Set[str]) -> str:
    if dest not in existing:
        return dest
    i = 1
    while True:
        cand = f"{dest}__dup{i}"
        if cand not in existing:
            return cand
        i += 1


def _make_copy_op(src: str, dst: str):
    sig = inspect.signature(CommitOperationCopy.__init__)
    params = set(sig.parameters.keys())
    params.discard("self")

    if {"path_in_repo", "path_in_repo_dest"} <= params:
        return CommitOperationCopy(path_in_repo=src, path_in_repo_dest=dst)
    if {"path_in_repo", "dest_path_in_repo"} <= params:
        return CommitOperationCopy(path_in_repo=src, dest_path_in_repo=dst)
    if {"src_path_in_repo", "path_in_repo"} <= params:
        return CommitOperationCopy(src_path_in_repo=src, path_in_repo=dst)
    if {"from_path", "to_path"} <= params:
        return CommitOperationCopy(from_path=src, to_path=dst)

    positional = [p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) >= 3:
        return CommitOperationCopy(src, dst)

    raise TypeError(f"Unknown CommitOperationCopy signature: {sig}")


def _make_delete_op(path: str):
    sig = inspect.signature(CommitOperationDelete.__init__)
    params = set(sig.parameters.keys())
    params.discard("self")
    if "path_in_repo" in params:
        return CommitOperationDelete(path_in_repo=path)
    if "path" in params:
        return CommitOperationDelete(path=path)
    return CommitOperationDelete(path)


def _make_add_op(path: str, content: bytes = b""):
    sig = inspect.signature(CommitOperationAdd.__init__)
    params = set(sig.parameters.keys())
    params.discard("self")
    if {"path_in_repo", "path_or_fileobj"} <= params:
        return CommitOperationAdd(path_in_repo=path, path_or_fileobj=content)
    if {"path_in_repo", "fileobj"} <= params:
        return CommitOperationAdd(path_in_repo=path, fileobj=content)
    return CommitOperationAdd(path, content)


def api(repo: str, token: str) -> HfApi:
    return HfApi(token=token)


def list_files(api_: HfApi, repo: str, rtype: str) -> List[str]:
    return api_.list_repo_files(repo_id=repo, repo_type=rtype)


# ---------------- FS commands ----------------

def cmd_ls(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = list_files(a, args.repo, args.type)

    path = normalize_path(args.path or "")
    if path:
        prefix = path.rstrip("/") + "/"
        # show immediate children under prefix
        kids_files = [f for f in files if f.startswith(prefix)]
        if not kids_files:
            print("(empty)")
            return
        children = set()
        for f in kids_files:
            rest = f[len(prefix):]
            if rest == "":
                continue
            first = rest.split("/", 1)[0]
            # directory?
            if "/" in rest:
                children.add(first + "/")
            else:
                children.add(first)
        for c in sorted(children):
            print(c)
    else:
        # root: show top-level dirs + root files
        children = set()
        for f in files:
            if "/" in f:
                children.add(f.split("/", 1)[0] + "/")
            else:
                children.add(f)
        for c in sorted(children):
            print(c)


def cmd_mkdir(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = set(list_files(a, args.repo, args.type))

    d = normalize_path(args.path)
    if not d:
        die("mkdir: path is empty")

    ops = ensure_dir_ops(files, d)

    if not ops:
        print("exists")
        return

    a.create_commit(
        repo_id=args.repo,
        repo_type=args.type,
        operations=ops,
        commit_message=f"mkdir {d}",
    )
    print("ok")


def cmd_rm(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    p = normalize_path(args.path)
    if not p:
        die("rm: path is empty")

    # Support prefix delete if user passes something ending with /
    files = list_files(a, args.repo, args.type)
    targets: List[str] = []
    if p.endswith("/"):
        pref = p
        targets = [f for f in files if f.startswith(pref)]
        if not targets:
            die(f"rm: nothing under prefix {pref}", 1)
    else:
        if p not in files:
            die(f"rm: not found: {p}", 1)
        targets = [p]

    ops = [_make_delete_op(t) for t in targets]
    a.create_commit(
        repo_id=args.repo,
        repo_type=args.type,
        operations=ops,
        commit_message=f"rm {p}",
    )
    print("ok")


def cmd_mv(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = set(list_files(a, args.repo, args.type))

    src = normalize_path(args.src)
    dst = normalize_path(args.dst)
    if not src or not dst:
        die("mv: src/dst required")

    # Allow "mv file dir/" semantics
    if dst.endswith("/"):
        dst = dst + Path(src).name

    if src not in files:
        die(f"mv: src not found: {src}", 1)

    # Ensure destination dir exists
    ops: List[object] = []
    ops += ensure_dir_ops(files, parent_dir(dst))

    dst2 = unique_dest(dst, files)
    ops.append(_make_copy_op(src, dst2))
    ops.append(_make_delete_op(src))

    a.create_commit(
        repo_id=args.repo,
        repo_type=args.type,
        operations=ops,
        commit_message=f"mv {src} -> {dst2}",
    )
    print(dst2)


def cmd_put(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = set(list_files(a, args.repo, args.type))

    local = Path(args.local).expanduser()
    if not local.exists() or not local.is_file():
        die(f"put: local file not found: {local}", 1)

    dst = normalize_path(args.dst)
    if not dst:
        die("put: dst required")

    # If dst ends with / treat as directory
    if dst.endswith("/"):
        dst = dst + local.name

    # Ensure destination dir exists
    ops: List[object] = []
    ops += ensure_dir_ops(files, parent_dir(dst))

    # upload_file is simplest & fastest; commit message included
    # Note: upload_file creates its own commit, so we do mkdir via commit first if needed.
    if ops:
        a.create_commit(
            repo_id=args.repo,
            repo_type=args.type,
            operations=ops,
            commit_message=f"mkdir {parent_dir(dst)}",
        )

    a.upload_file(
        path_or_fileobj=str(local),
        path_in_repo=dst,
        repo_id=args.repo,
        repo_type=args.type,
        commit_message=args.message or f"put {dst}",
    )
    print("ok")


def cmd_get(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)

    src = normalize_path(args.src)
    if not src:
        die("get: src required")

    out = Path(args.out or Path(src).name).expanduser()
    out_parent = out.parent
    out_parent.mkdir(parents=True, exist_ok=True)

    # download_file
    # We use hf_hub_download via HfApi as a stable path: download to cache then copy to out.
    from huggingface_hub import hf_hub_download  # type: ignore

    cached = hf_hub_download(
        repo_id=args.repo,
        repo_type=args.type,
        filename=src,
        token=tok,
        cache_dir=args.cache_dir or None,
    )
    Path(cached).replace(out) if args.move else Path(cached).read_bytes() and out.write_bytes(Path(cached).read_bytes())
    # Above line keeps compatibility if cached is on different FS; simpler explicit:
    # out.write_bytes(Path(cached).read_bytes())
    print(str(out))


# ---------------- Snapshot commands ----------------

def _run_hf_cli(cmd: List[str]) -> None:
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        die("huggingface-cli not found (install huggingface-hub to get it)")
    except subprocess.CalledProcessError as e:
        raise SystemExit(e.returncode)


def snap_id_from_name(name: str) -> str:
    slug = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name).strip("._-")
    slug = "_".join(slug.split())
    slug = slug[:120] if slug else "snapshot"
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{ts}__{slug}"


def cmd_snapshot_create(args) -> None:
    tok = need_token()
    # enable hf_transfer if user wants it
    if os.environ.get("HF_HUB_ENABLE_HF_TRANSFER") is None:
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    if not args.name:
        die("snapshot create: --name is required")
    if not args.items:
        die("snapshot create: provide files/dirs to archive")

    sid = snap_id_from_name(args.name)
    tmp = Path(args.tmp_dir or ".").expanduser() / f"{sid}.tar"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    # Tar (simple, gzip optional)
    tar_path = tmp
    if args.compress == "gz":
        tar_path = tmp.with_suffix(".tar.gz")
        subprocess.run(["tar", "-czf", str(tar_path), *args.items], check=True)
    else:
        subprocess.run(["tar", "-cf", str(tar_path), *args.items], check=True)

    manifest = tmp.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({
        "id": sid,
        "name": args.name,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items": args.items,
        "tar": {"basename": tar_path.name, "bytes": tar_path.stat().st_size, "compress": args.compress},
    }, indent=2), encoding="utf-8")

    # Upload both under snapshot dir
    path_in_repo = normalize_path(args.snapdir)
    _run_hf_cli([
        "huggingface-cli", "upload", args.repo,
        str(tar_path), str(manifest),
        "--repo-type", args.type,
        "--path-in-repo", path_in_repo,
        "--commit-message", f"snapshot: {sid} - {args.name}",
    ])
    print(sid)


def cmd_snapshot_list(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = list_files(a, args.repo, args.type)
    pref = normalize_path(args.snapdir).rstrip("/") + "/"
    ids = sorted(
        {Path(f).name[:-len(".manifest.json")] for f in files if f.startswith(pref) and f.endswith(".manifest.json")},
        reverse=True,
    )
    for i in ids:
        print(i)


def cmd_snapshot_show(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = list_files(a, args.repo, args.type)

    pref = normalize_path(args.snapdir).rstrip("/") + "/"
    sid = args.id
    if not sid:
        die("snapshot show: id required (wire in fzf/select later if you want)")

    mf = f"{pref}{sid}.manifest.json"
    if mf not in files:
        die(f"snapshot show: manifest not found: {mf}", 1)

    from huggingface_hub import hf_hub_download  # type: ignore
    cached = hf_hub_download(repo_id=args.repo, repo_type=args.type, filename=mf, token=tok)
    print(Path(cached).read_text(encoding="utf-8"))


def cmd_snapshot_get(args) -> None:
    need_token()
    if os.environ.get("HF_HUB_ENABLE_HF_TRANSFER") is None:
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    if not args.id:
        die("snapshot get: id required")

    pref = normalize_path(args.snapdir).rstrip("/")
    extract_dir = Path(args.extract_dir or ".").expanduser()
    extract_dir.mkdir(parents=True, exist_ok=True)

    # Try common tar extensions
    for ext in ("tar.zst", "tar.gz", "tar"):
        inc = f"{pref}/{args.id}.{ext}"
        cmd = [
            "huggingface-cli", "download", args.repo,
            "--repo-type", args.type,
            "--include", inc,
            "--local-dir", str(args.local_dir or "."),
            "--local-dir-use-symlinks", "False",
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # find downloaded file under local-dir
            local_root = Path(args.local_dir or ".")
            tar_path = local_root / pref / f"{args.id}.{ext}"
            if tar_path.exists():
                # Extract
                if ext.endswith(".tar.gz"):
                    subprocess.run(["tar", "-xzf", str(tar_path), "-C", str(extract_dir)], check=True)
                else:
                    subprocess.run(["tar", "-xf", str(tar_path), "-C", str(extract_dir)], check=True)
                print("ok")
                return
        except subprocess.CalledProcessError:
            continue

    die("snapshot get: could not find tar for that id (tried .tar.zst/.tar.gz/.tar)", 1)


def cmd_snapshot_destroy(args) -> None:
    tok = need_token()
    a = api(args.repo, tok)
    files = list_files(a, args.repo, args.type)

    if not args.id:
        die("snapshot destroy: id required")

    pref = normalize_path(args.snapdir).rstrip("/") + "/"
    targets = [f for f in files if f.startswith(pref + args.id + ".")]
    if not targets:
        die("snapshot destroy: nothing matched", 1)

    if not args.yes:
        print("About to DELETE:")
        for t in targets:
            print("  -", t)
        confirm = input("Type DELETE to confirm: ").strip()
        if confirm != "DELETE":
            die("aborted", 1)

    ops = [_make_delete_op(t) for t in targets]
    a.create_commit(
        repo_id=args.repo,
        repo_type=args.type,
        operations=ops,
        commit_message=f"destroy snapshot {args.id}",
    )
    print("ok")


# ---------------- CLI ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hff.py")
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--type", default="model", choices=["model", "dataset"], help="repo type")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ls")
    sp.add_argument("path", nargs="?", default="")
    sp.set_defaults(fn=cmd_ls)

    sp = sub.add_parser("mkdir")
    sp.add_argument("path")
    sp.set_defaults(fn=cmd_mkdir)

    sp = sub.add_parser("mv")
    sp.add_argument("src")
    sp.add_argument("dst")
    sp.set_defaults(fn=cmd_mv)

    sp = sub.add_parser("rm")
    sp.add_argument("path")
    sp.set_defaults(fn=cmd_rm)

    sp = sub.add_parser("put")
    sp.add_argument("local")
    sp.add_argument("dst")
    sp.add_argument("-m", "--message", default="")
    sp.set_defaults(fn=cmd_put)

    sp = sub.add_parser("get")
    sp.add_argument("src")
    sp.add_argument("out", nargs="?", default="")
    sp.add_argument("--cache-dir", default="")
    sp.add_argument("--move", action="store_true", help="move cached file into place (best-effort)")
    sp.set_defaults(fn=cmd_get)

    # snapshots grouped
    sp = sub.add_parser("snapshot")
    sp.add_argument("--snapdir", default="snapshot", help="remote snapshot dir")
    ssub = sp.add_subparsers(dest="scmd", required=True)

    s1 = ssub.add_parser("create")
    s1.add_argument("--name", required=True)
    s1.add_argument("--compress", default="gz", choices=["gz", "none"])
    s1.add_argument("--tmp-dir", default="")
    s1.add_argument("items", nargs="+")
    s1.set_defaults(fn=cmd_snapshot_create)

    s2 = ssub.add_parser("list")
    s2.set_defaults(fn=cmd_snapshot_list)

    s3 = ssub.add_parser("show")
    s3.add_argument("id")
    s3.set_defaults(fn=cmd_snapshot_show)

    s4 = ssub.add_parser("get")
    s4.add_argument("id")
    s4.add_argument("--extract-dir", default=".")
    s4.add_argument("--local-dir", default=".")
    s4.set_defaults(fn=cmd_snapshot_get)

    s5 = ssub.add_parser("destroy")
    s5.add_argument("id")
    s5.add_argument("-y", "--yes", action="store_true")
    s5.set_defaults(fn=cmd_snapshot_destroy)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
