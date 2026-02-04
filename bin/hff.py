#!/usr/bin/env python3
import argparse
import inspect
import json
import os
import shutil
import subprocess
import sys
import time
from fnmatch import fnmatchcase
from pathlib import Path
from typing import List, Set, Optional, Dict, Iterable

from huggingface_hub import HfApi

# ---- commit ops imports (version-flexible) ----
try:
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, CommitOperationCopy  # type: ignore
except Exception:
    from huggingface_hub._commit_api import CommitOperationAdd, CommitOperationDelete, CommitOperationCopy  # type: ignore


# ---------------- utils ----------------

def die(msg: str, code: int = 2) -> None:
    print(f"[hff] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def warn(msg: str) -> None:
    print(f"[hff] WARN: {msg}", file=sys.stderr)


def need_token() -> str:
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        die("HF_TOKEN is not set")
    return tok


def normalize_path(p: str) -> str:
    p = (p or "").strip()
    p = p.lstrip("/")  # treat as repo-relative
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def parent_dir(path: str) -> str:
    p = normalize_path(path)
    if "/" not in p:
        return ""
    return p.rsplit("/", 1)[0]


def has_glob(s: str) -> bool:
    # minimal glob detection (shell-style)
    return any(ch in s for ch in ["*", "?", "["])


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


def _tar_extract(tar_path: Path, extract_dir: Path) -> None:
    """
    Extract tarball using system tar.
    - .tar.gz uses -xzf
    - everything else uses -xf
    """
    if str(tar_path).endswith(".tar.gz"):
        subprocess.run(["tar", "-xzf", str(tar_path), "-C", str(extract_dir)], check=True)
    else:
        subprocess.run(["tar", "-xf", str(tar_path), "-C", str(extract_dir)], check=True)


# ---------------- commit op constructors (signature-safe) ----------------

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

    positional = [
        p for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
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


# ---------------- API helpers ----------------

def api(token: str) -> HfApi:
    return HfApi(token=token)


def list_files(api_: HfApi, repo: str, rtype: str) -> List[str]:
    return api_.list_repo_files(repo_id=repo, repo_type=rtype)


def _hf_download(repo: str, rtype: str, filename: str, token: str, cache_dir: Optional[str] = None) -> Path:
    from huggingface_hub import hf_hub_download  # type: ignore
    p = hf_hub_download(
        repo_id=repo,
        repo_type=rtype,
        filename=filename,
        token=token,
        cache_dir=cache_dir or None,
    )
    return Path(p)


# ---------------- glob helpers ----------------

def match_glob(files: Iterable[str], pattern: str) -> List[str]:
    """
    HF-side glob match (repo-relative). Pattern is treated like shell glob.
    """
    pat = normalize_path(pattern)
    return sorted([f for f in files if fnmatchcase(f, pat)])


def list_children(files: List[str], base_path: str) -> List[str]:
    """
    Like `ls` of a directory: show immediate children under base_path.
    Returns names (with / for dirs).
    """
    path = normalize_path(base_path or "")
    if not path:
        children = set()
        for f in files:
            children.add(f.split("/", 1)[0] + "/" if "/" in f else f)
        return sorted(children)

    prefix = path.rstrip("/") + "/"
    kids = [f for f in files if f.startswith(prefix)]
    if not kids:
        return []

    children = set()
    for f in kids:
        rest = f[len(prefix):]
        if not rest:
            continue
        first = rest.split("/", 1)[0]
        children.add(first + "/" if "/" in rest else first)
    return sorted(children)


# ---------------- FS commands ----------------

def cmd_ls(args) -> None:
    tok = need_token()
    a = api(tok)
    files = list_files(a, args.repo, args.type)

    raw = (args.path or "").strip()
    p = normalize_path(raw)

    # Glob mode: show matching files (full paths)
    if p and has_glob(p):
        matches = match_glob(files, p)
        if not matches:
            print("(empty)")
            return
        for m in matches:
            print(m)
        return

    # Prefix/dir mode: show children, but print with prefix included (your request)
    children = list_children(files, p)
    if not children:
        print("(empty)")
        return

    if p:
        prefix = p.rstrip("/") + "/"
        for c in children:
            # keep directory marker as-is (c may end with "/")
            print(prefix + c)
    else:
        for c in children:
            print(c)


def cmd_mkdir(args) -> None:
    tok = need_token()
    a = api(tok)
    files = set(list_files(a, args.repo, args.type))

    d = normalize_path(args.path)
    if not d:
        die("mkdir: path is empty")

    ops = ensure_dir_ops(files, d)
    if not ops:
        print("exists")
        return

    try:
        a.create_commit(
            repo_id=args.repo,
            repo_type=args.type,
            operations=ops,
            commit_message=f"mkdir {d}",
        )
    except Exception as e:
        die(f"mkdir: failed: {e}", 1)

    print("ok")


def cmd_rm(args) -> None:
    tok = need_token()
    a = api(tok)
    raw = (args.path or "").strip()
    p = normalize_path(raw)
    if not p:
        die("rm: path is empty")

    files = list_files(a, args.repo, args.type)
    targets: List[str] = []

    # Glob mode
    if has_glob(p):
        targets = match_glob(files, p)

    # Prefix mode
    elif p.endswith("/"):
        pref = p.rstrip("/") + "/"
        targets = [f for f in files if f.startswith(pref)]

    # Single file
    else:
        if p not in files:
            die(f"rm: not found: {p}", 1)
        targets = [p]

    if not targets:
        die(f"rm: nothing matched: {raw}", 1)

    if args.dry_run:
        for t in targets:
            print(t)
        return

    ops = [_make_delete_op(t) for t in targets]
    try:
        a.create_commit(
            repo_id=args.repo,
            repo_type=args.type,
            operations=ops,
            commit_message=f"rm {raw}",
        )
    except Exception as e:
        die(f"rm: failed: {e}", 1)

    print("ok")


def _mv_single(a: HfApi, repo: str, rtype: str, files: Set[str], src: str, dst: str) -> str:
    """
    Move one file src->dst. Returns final destination path (after collision handling).
    """
    ops: List[object] = []
    ops += ensure_dir_ops(files, parent_dir(dst))

    dst2 = unique_dest(dst, files)
    ops.append(_make_copy_op(src, dst2))
    ops.append(_make_delete_op(src))

    a.create_commit(
        repo_id=repo,
        repo_type=rtype,
        operations=ops,
        commit_message=f"mv {src} -> {dst2}",
    )
    return dst2


def cmd_mv(args) -> None:
    tok = need_token()
    a = api(tok)
    files_set = set(list_files(a, args.repo, args.type))

    src_raw = (args.src or "").strip()
    dst_raw = (args.dst or "").strip()

    src = normalize_path(src_raw)
    dst = normalize_path(dst_raw)
    if not src or not dst:
        die("mv: src/dst required")

    # Directory/prefix move: src ends with /
    if src_raw.endswith("/") or src.endswith("/"):
        src_prefix = src.rstrip("/") + "/"
        dst_prefix = dst.rstrip("/") + "/"

        # move everything under src_prefix
        matches = sorted([f for f in files_set if f.startswith(src_prefix)])
        if not matches:
            die(f"mv: nothing under prefix: {src_prefix}", 1)

        # Build operations in one commit
        ops: List[object] = []
        ensured_dirs: Set[str] = set()

        def ensure_parent(d: str) -> None:
            d = normalize_path(d)
            if not d or d in ensured_dirs:
                return
            ops.extend(ensure_dir_ops(files_set, d))
            ensured_dirs.add(d)

        moved: List[str] = []
        for f in matches:
            rel = f[len(src_prefix):]  # preserve structure
            new_path = dst_prefix + rel

            # ensure parent dir exists (best-effort)
            ensure_parent(parent_dir(new_path))

            new_path2 = unique_dest(new_path, files_set)
            ops.append(_make_copy_op(f, new_path2))
            ops.append(_make_delete_op(f))
            files_set.add(new_path2)
            moved.append(new_path2)

        try:
            a.create_commit(
                repo_id=args.repo,
                repo_type=args.type,
                operations=ops,
                commit_message=f"mv {src_prefix} -> {dst_prefix} ({len(matches)} files)",
            )
        except Exception as e:
            die(f"mv: dir move failed: {e}", 1)

        # Print destination prefix (and count) in a friendly way
        print(f"{dst_prefix}  ({len(matches)} files)")
        return

    # Single-file move
    if dst.endswith("/"):
        dst = dst + Path(src).name

    if src not in files_set:
        die(f"mv: src not found: {src}", 1)

    try:
        final = _mv_single(a, args.repo, args.type, files_set, src, dst)
    except Exception as e:
        die(f"mv: failed: {e}", 1)

    print(final)


def cmd_put(args) -> None:
    tok = need_token()
    a = api(tok)
    files = set(list_files(a, args.repo, args.type))

    local = Path(args.local).expanduser()
    if not local.exists() or not local.is_file():
        die(f"put: local file not found: {local}", 1)

    dst = normalize_path(args.dst)
    if not dst:
        die("put: dst required")
    if dst.endswith("/"):
        dst = dst + local.name

    try:
        ops: List[object] = []
        ops += ensure_dir_ops(files, parent_dir(dst))
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
    except Exception as e:
        die(f"put: failed: {e}", 1)

    print("ok")


def cmd_get(args) -> None:
    tok = need_token()
    src = normalize
