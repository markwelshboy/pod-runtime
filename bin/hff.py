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

    # -------- local glob expansion --------
    raw = args.local
    paths: List[Path] = []

    if has_glob(raw):
        # Expand locally (shell-like, but inside Python)
        base = Path(".")
        matches = list(base.glob(raw))
        paths = [p for p in matches if p.is_file()]
        if not paths:
            die(f"put: no files matched: {raw}", 1)
    else:
        p = Path(raw).expanduser()
        if not p.exists() or not p.is_file():
            die(f"put: local file not found: {p}", 1)
        paths = [p]

    # -------- destination handling --------
    dst_raw = normalize_path(args.dst)
    if not dst_raw:
        die("put: dst required")

    multi = len(paths) > 1

    # If multiple files, dst must be a directory
    if multi and not dst_raw.endswith("/"):
        die("put: destination must be a directory when uploading multiple files", 1)

    # Ensure directory once
    target_dir = dst_raw.rstrip("/") if dst_raw.endswith("/") else parent_dir(dst_raw)

    if target_dir:
        ops = ensure_dir_ops(files, target_dir)
        if ops:
            a.create_commit(
                repo_id=args.repo,
                repo_type=args.type,
                operations=ops,
                commit_message=f"mkdir {target_dir}",
            )

    # -------- upload loop --------
    uploaded = []

    for local in paths:
        if dst_raw.endswith("/"):
            dst = dst_raw.rstrip("/") + "/" + local.name
        else:
            # single-file mode
            dst = dst_raw

        try:
            a.upload_file(
                path_or_fileobj=str(local),
                path_in_repo=dst,
                repo_id=args.repo,
                repo_type=args.type,
                commit_message=args.message or f"put {dst}",
            )
        except Exception as e:
            die(f"put: failed for {local}: {e}", 1)

        uploaded.append(dst)

    # -------- output --------
    if multi:
        print(f"ok ({len(uploaded)} files)")
    else:
        print("ok")

def cmd_get(args) -> None:
    tok = need_token()
    src = normalize_path(args.src)
    if not src:
        die("get: src required")

    out = Path(args.out or Path(src).name).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        cached_p = _hf_download(args.repo, args.type, src, tok, cache_dir=args.cache_dir or None)
    except Exception as e:
        die(f"get: download failed: {e}", 1)

    try:
        if args.move:
            try:
                os.replace(str(cached_p), str(out))
            except OSError:
                shutil.copy2(str(cached_p), str(out))
                try:
                    cached_p.unlink()
                except OSError:
                    pass
        else:
            shutil.copy2(str(cached_p), str(out))
    except Exception as e:
        die(f"get: failed to write {out}: {e}", 1)

    print(str(out))


# ---------------- Snapshot commands (pure hub API, no CLI) ----------------

def snap_id_from_name(name: str) -> str:
    slug = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name).strip("._-")
    slug = "_".join(slug.split())
    slug = slug[:120] if slug else "snapshot"
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{ts}__{slug}"


def cmd_snapshot_create(args) -> None:
    tok = need_token()

    if os.environ.get("HF_HUB_ENABLE_HF_TRANSFER") is None:
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    if not args.name:
        die("snapshot create: --name is required")
    if not args.items:
        die("snapshot create: provide files/dirs to archive")

    sid = snap_id_from_name(args.name)
    tmp = Path(args.tmp_dir or ".").expanduser() / f"{sid}.tar"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    tar_path = tmp
    try:
        if args.compress == "gz":
            tar_path = tmp.with_suffix(".tar.gz")
            subprocess.run(["tar", "-czf", str(tar_path), *args.items], check=True)
        else:
            subprocess.run(["tar", "-cf", str(tar_path), *args.items], check=True)
    except subprocess.CalledProcessError as e:
        die(f"snapshot create: tar failed: {e}", 1)

    manifest = tmp.with_suffix(".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "id": sid,
                "name": args.name,
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "items": args.items,
                "tar": {"basename": tar_path.name, "bytes": tar_path.stat().st_size, "compress": args.compress},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    snapdir = normalize_path(args.snapdir).rstrip("/")
    tar_in_repo = f"{snapdir}/{tar_path.name}"
    mf_in_repo = f"{snapdir}/{manifest.name}"

    a = api(tok)
    try:
        a.upload_file(
            path_or_fileobj=str(tar_path),
            path_in_repo=tar_in_repo,
            repo_id=args.repo,
            repo_type=args.type,
            commit_message=f"snapshot: {sid} - {args.name}",
        )
        a.upload_file(
            path_or_fileobj=str(manifest),
            path_in_repo=mf_in_repo,
            repo_id=args.repo,
            repo_type=args.type,
            commit_message=f"snapshot manifest: {sid}",
        )
    except Exception as e:
        die(f"snapshot create: upload failed: {e}", 1)

    print(sid)


def cmd_snapshot_list(args) -> None:
    tok = need_token()
    a = api(tok)
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
    a = api(tok)
    files = list_files(a, args.repo, args.type)

    pref = normalize_path(args.snapdir).rstrip("/") + "/"
    sid = args.id
    mf = f"{pref}{sid}.manifest.json"
    if mf not in files:
        die(f"snapshot show: manifest not found: {mf}", 1)

    try:
        cached = _hf_download(args.repo, args.type, mf, tok, cache_dir=None)
        print(cached.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"snapshot show: failed: {e}", 1)


def cmd_snapshot_get(args) -> None:
    tok = need_token()
    if os.environ.get("HF_HUB_ENABLE_HF_TRANSFER") is None:
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    if not args.id:
        die("snapshot get: id required")

    pref = normalize_path(args.snapdir).rstrip("/")
    extract_dir = Path(args.extract_dir or ".").expanduser()
    extract_dir.mkdir(parents=True, exist_ok=True)

    mf = f"{pref}/{args.id}.manifest.json"
    try:
        mf_cached = _hf_download(args.repo, args.type, mf, tok, cache_dir=args.cache_dir or None)
    except Exception as e:
        die(f"snapshot get: could not download manifest {mf}: {e}", 1)

    try:
        meta = json.loads(mf_cached.read_text(encoding="utf-8"))
        tar_base = meta.get("tar", {}).get("basename")
        if not tar_base:
            die("snapshot get: manifest missing tar.basename", 1)
    except Exception as e:
        die(f"snapshot get: failed to parse manifest: {e}", 1)

    tar_in_repo = f"{pref}/{tar_base}"
    try:
        tar_cached = _hf_download(args.repo, args.type, tar_in_repo, tok, cache_dir=args.cache_dir or None)
    except Exception as e:
        die(f"snapshot get: could not download tar {tar_in_repo}: {e}", 1)

    try:
        _tar_extract(tar_cached, extract_dir)
    except subprocess.CalledProcessError as e:
        die(f"snapshot get: tar extract failed: {e}", 1)

    print("ok")


def cmd_snapshot_destroy(args) -> None:
    tok = need_token()
    a = api(tok)
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
    try:
        a.create_commit(
            repo_id=args.repo,
            repo_type=args.type,
            operations=ops,
            commit_message=f"destroy snapshot {args.id}",
        )
    except Exception as e:
        die(f"snapshot destroy: failed: {e}", 1)
    print("ok")


# ---------------- Doctor ----------------

def _cli_candidates() -> List[str]:
    venv = os.environ.get("HFF_VENV", "/opt/hf-tools-venv")
    cands = [
        os.path.join(venv, "bin", "huggingface-cli"),
        os.path.join(venv, "bin", "hf"),
        "huggingface-cli",
        "hf",
    ]
    return cands


def cmd_doctor(args) -> None:
    tok = os.environ.get("HF_TOKEN", "")
    venv = os.environ.get("HFF_VENV", "/opt/hf-tools-venv")

    report = {
        "python": sys.executable,
        "hff_venv_env": venv,
        "hf_token_set": bool(tok),
        "env": {
            "HF_HUB_ENABLE_HF_TRANSFER": os.environ.get("HF_HUB_ENABLE_HF_TRANSFER"),
            "HUGGINGFACE_HUB_TOKEN_set": bool(os.environ.get("HUGGINGFACE_HUB_TOKEN")),
            "HF_HOME": os.environ.get("HF_HOME"),
            "HF_HUB_CACHE": os.environ.get("HF_HUB_CACHE"),
        },
        "packages": {},
        "hub_smoke": {},
        "cli": {},
    }

    try:
        import huggingface_hub
        report["packages"]["huggingface_hub"] = getattr(huggingface_hub, "__version__", "?")
    except Exception as e:
        report["packages"]["huggingface_hub"] = f"ERROR: {e}"

    try:
        import hf_transfer
        report["packages"]["hf_transfer"] = getattr(hf_transfer, "__version__", "OK")
    except Exception as e:
        report["packages"]["hf_transfer"] = f"missing/ERROR: {e}"

    cli_info = {}
    for cand in _cli_candidates():
        exists = os.path.exists(cand) if ("/" in cand) else True
        cli_info[cand] = {"exists_or_on_path": exists}
    report["cli"]["candidates"] = cli_info

    if tok:
        try:
            a = HfApi(token=tok)
            report["hub_smoke"]["whoami"] = a.whoami().get("name", "?")
            try:
                a.repo_info(repo_id=args.repo, repo_type=args.type)
                report["hub_smoke"]["repo_access"] = f"OK: {args.repo} ({args.type})"
            except Exception as e:
                report["hub_smoke"]["repo_access"] = f"ERROR: {e}"
        except Exception as e:
            report["hub_smoke"]["whoami"] = f"ERROR: {e}"
    else:
        report["hub_smoke"]["whoami"] = "SKIPPED (HF_TOKEN not set)"

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("=== hff doctor ===")
    print("python:", report["python"])
    print("HFF_VENV:", report["hff_venv_env"])
    print("HF_TOKEN set:", report["hf_token_set"])
    print("huggingface_hub:", report["packages"].get("huggingface_hub"))
    print("hf_transfer:", report["packages"].get("hf_transfer"))
    print("HF_HUB_ENABLE_HF_TRANSFER:", report["env"].get("HF_HUB_ENABLE_HF_TRANSFER"))
    print("HUGGINGFACE_HUB_TOKEN set:", report["env"].get("HUGGINGFACE_HUB_TOKEN_set"))
    print("whoami:", report["hub_smoke"].get("whoami"))
    print("repo access:", report["hub_smoke"].get("repo_access"))
    print("CLI candidates (not required):")
    for cand, info in report["cli"]["candidates"].items():
        print(f"  - {cand}: {info['exists_or_on_path']}")
    print("==================")


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
    sp.add_argument("--dry-run", action="store_true", help="print matched targets, do not delete")
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
    s4.add_argument("--cache-dir", default="")
    s4.set_defaults(fn=cmd_snapshot_get)

    s5 = ssub.add_parser("destroy")
    s5.add_argument("id")
    s5.add_argument("-y", "--yes", action="store_true")
    s5.set_defaults(fn=cmd_snapshot_destroy)

    sp = sub.add_parser("doctor")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_doctor)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    # Make it less brittle in interactive shells: clean error output,
    # no massive tracebacks unless you opt-in.
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        die("interrupted", 130)
    except Exception as e:
        die(str(e), 1)
