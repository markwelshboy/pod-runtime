#!/usr/bin/env python3
"""Pod-local, standalone VLM batch worker (no ComfyUI/Python web framework).

Only bind loopback. Image Playground stages downsized JPEGs by HTTP or vcp's
HF relay; numerical results return over the SSH tunnel (tiny JSON).
Suggested tags remain proposals: the worker never writes ComfyUI sidecars.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

JOB_RE = re.compile(r"^[a-f0-9]{32}$")
ITEM_RE = re.compile(r"^i[0-9]{6}\.jpg$")
MAX_ZIP = 512 * 1024 * 1024
MAX_FILES = 10000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 768 * 1024 * 1024
DEFAULT_ROOT = Path(os.getenv("VLM_WORKER_ROOT", "/workspace/vlm-worker"))


def valid_job(value):
    if not isinstance(value, str) or not JOB_RE.fullmatch(value):
        raise ValueError("Invalid job identifier.")
    return value


def safe_zip(path, dest):
    """Reject traversal, links, zip bombs and mismatched contents before extraction."""
    with zipfile.ZipFile(path) as archive:
        files = archive.infolist()
        if len(files) > MAX_FILES + 1:
            raise ValueError("Too many ZIP members.")
        names, image_files, total = set(), set(), 0
        for entry in files:
            name = entry.filename
            if name in names or not name or name.startswith("/") or "\\" in name:
                raise ValueError("Duplicate/unsafe archive member.")
            names.add(name)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if mode not in (0, stat.S_IFREG):
                raise ValueError("ZIP links/directories are not allowed.")
            if name == "manifest.json":
                cap = 2 * 1024 * 1024
            elif name.startswith("images/") and ITEM_RE.fullmatch(name[7:]):
                cap = MAX_IMAGE_BYTES
                image_files.add(name[7:])
            else:
                raise ValueError("Unexpected input member: " + name)
            if entry.file_size > cap:
                raise ValueError("Oversized ZIP member: " + name)
            total += entry.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Uncompressed input exceeds worker limits.")
        if "manifest.json" not in names:
            raise ValueError("Missing manifest.json.")
        with archive.open("manifest.json") as stream:
            manifest = json.loads(stream.read(2 * 1024 * 1024 + 1))
        items = manifest.get("images", [])
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_FILES:
            raise ValueError("Manifest must describe 1–10000 images.")
        ids = [x.get("id") for x in items if isinstance(x, dict)]
        if len(ids) != len(items) or len(set(ids)) != len(ids) or set(ids) != image_files:
            raise ValueError("Manifest image IDs do not match ZIP members.")
        if any(not ITEM_RE.fullmatch(v) for v in ids):
            raise ValueError("Invalid manifest image ID.")
        if any(not isinstance(x.get("sha256"), str) or
               not re.fullmatch(r"[a-f0-9]{64}", x["sha256"]) for x in items):
            raise ValueError("Missing image digests.")
        dest.mkdir(parents=True, exist_ok=True)
        import hashlib
        for entry in files:
            if entry.filename == "manifest.json":
                continue
            target = dest / entry.filename
            target.parent.mkdir(exist_ok=True)
            with archive.open(entry) as src, target.open("xb") as out:
                digest = hashlib.sha256()
                while block := src.read(65536):
                    digest.update(block)
                    out.write(block)
            matching = next(x for x in items if x["id"] == target.name)
            if digest.hexdigest() != matching["sha256"]:
                raise ValueError("Image checksum mismatch: " + target.name)
        (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return len(items)


class Worker:
    def __init__(self, root=DEFAULT_ROOT, *, skill_root="/workspace/vlm-skills"):
        self.root = Path(root).expanduser().resolve()
        self.uploads = self.root / "uploads"
        self.jobs_root = self.root / "jobs"
        self.skills = Path(skill_root)
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.current = None
        self.thread = None
        self.proc = None
        self.cancelled = threading.Event()
        # Reboot-safe recovery: completed per-image JSON is retained. Interrupted
        # jobs are shown as such and can be rerun with --skip-existing.
        for folder in self.jobs_root.iterdir():
            if folder.is_dir() and JOB_RE.fullmatch(folder.name):
                path = folder / "state.json"
                if path.is_file():
                    try:
                        state = json.loads(path.read_text())
                        if state.get("status") in {"running", "queued"}:
                            state["status"] = "interrupted"
                            path.write_text(json.dumps(state))
                    except (OSError, ValueError):
                        continue

    def folder(self, job_id):
        return self.jobs_root / valid_job(job_id)

    def state(self, job_id):
        path = self.folder(job_id) / "state.json"
        if not path.is_file():
            raise FileNotFoundError("Unknown VLM job.")
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, job_id, **fields):
        with self.lock:
            state = self.state(job_id)
            state.update(fields, updated=time.time())
            file = self.folder(job_id) / "state.json"
            tmp = file.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, file)
            return state

    def upload(self, job_id, source, length):
        valid_job(job_id)
        if not 0 < length <= MAX_ZIP:
            raise ValueError("Invalid upload size.")
        target = self.uploads / (job_id + ".zip")
        if target.exists():
            raise FileExistsError("Upload already exists; create a new job ID.")
        tmp = target.with_suffix(".part")
        try:
            with tmp.open("xb") as stream:
                remaining = length
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Truncated ZIP upload.")
                    stream.write(chunk)
                    remaining -= len(chunk)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    def start(self, job_id, *, model="qwen3-vl:8b-instruct",
              geometry=True):
        valid_job(job_id)
        if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9._:/-]{1,96}", model):
            raise ValueError("Invalid Ollama model.")
        if type(geometry) is not bool:
            raise ValueError("geometry must be boolean.")
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError("A VLM batch is already running.")
            root = self.folder(job_id)
            archive = self.uploads / (job_id + ".zip")
            if not archive.is_file() or archive.stat().st_size > MAX_ZIP:
                raise ValueError("No uploaded ZIP for job, or ZIP too large.")
            if not (root / "manifest.json").is_file():
                temp = self.jobs_root / (".stage-" + job_id)
                if temp.exists():
                    shutil.rmtree(temp)
                try:
                    count = safe_zip(archive, temp)
                    os.replace(temp, root)
                except BaseException:
                    shutil.rmtree(temp, ignore_errors=True)
                    raise
                state = {"job_id": job_id, "status": "queued", "stage": "queued",
                         "total": count, "completed": 0, "failures": 0, "message": "",
                         "model": model, "geometry": geometry, "created": time.time()}
                (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            else:
                state = self.state(job_id)
                if state["status"] == "completed":
                    return state
                model = state["model"]
                geometry = state["geometry"]
            self.cancelled.clear()
            self.current = job_id
            self.thread = threading.Thread(target=self._run,
                        args=(job_id, model, geometry), daemon=True)
            self.thread.start()
            return self.state(job_id)

    def cancel(self, job_id):
        with self.lock:
            if self.current != job_id or self.thread is None or not self.thread.is_alive():
                return self.state(job_id)
            self.cancelled.set()
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
            return self.save(job_id, message="Cancellation requested.")

    def _stage(self, job_id, name, command, *, progress=False):
        self.save(job_id, stage=name)
        log = self.folder(job_id) / "worker.log"
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\n=== " + name + " ===\n")
            stream.flush()
            with self.lock:
                self.proc = subprocess.Popen(command, cwd=str(self.folder(job_id)),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, start_new_session=True)
            try:
                for line in self.proc.stdout:
                    stream.write(line)
                    stream.flush()
                    if progress and (" done " in line or " skip " in line):
                        value = self.state(job_id)["completed"] + 1
                        self.save(job_id, completed=value)
                    if self.cancelled.is_set():
                        self.proc.terminate()
                        break
                code = self.proc.wait()
            finally:
                with self.lock:
                    self.proc = None
            if self.cancelled.is_set():
                raise InterruptedError("Batch cancelled.")
            if code:
                raise RuntimeError(f"{name} exited with status {code}; see worker.log")

    def _run(self, job_id, model, geometry):
        root = self.folder(job_id)
        results = root / "qwen"
        try:
            self.save(job_id, status="running", stage="qwen", message="")
            script = Path(os.getenv("VLM_RUNNER", "/usr/local/bin/vlm-skill"))
            self._stage(job_id, "qwen",
                [sys.executable, str(script), "--images", str(root/"images"),
                 "--skill", str(self.skills/"image-detailer-analysis"),
                 "--output-dir", str(results), "--model", model, "--json",
                 "--num-ctx", "8192", "--max-image-edge", "768",
                 "--skip-existing"], progress=True)
            self.save(job_id, stage="qwen-complete")
            if geometry:
                geometry_python = os.getenv("VLM_GEOMETRY_PYTHON", "/opt/venv/bin/python")
                if not Path(geometry_python).is_file():
                    geometry_python = sys.executable
                bench = self.skills/"vlm-face-benchmark"
                head_model = Path(os.getenv("VLM_HEAD_MODEL",
                    "/workspace/models/mediapipe/face_landmarker.task"))
                gaze_model = Path(os.getenv("VLM_GAZE_MODEL",
                    "/workspace/models/gaze/l2cs_gaze360_resnet50.safetensors"))
                reasons = []
                if head_model.is_file():
                    try:
                        self._stage(job_id, "head-pose",
                            [geometry_python, str(bench/"benchmark_head_pose.py"),
                             "--images", str(root/"images"), "--model", str(head_model),
                             "--orientation-results", str(results), "--limit", "0",
                             "--output-dir", str(root/"head")])
                    except RuntimeError as exc:
                        reasons.append(str(exc))
                else:
                    reasons.append("MediaPipe .task model is not installed.")
                if gaze_model.is_file():
                    try:
                        self._stage(job_id, "l2cs",
                            [geometry_python, str(bench/"benchmark_gaze_l2cs.py"),
                             "--images", str(root/"images"), "--weights", str(gaze_model),
                             "--device", os.getenv("VLM_GAZE_DEVICE", "cuda"),
                             "--limit", "0", "--output-dir", str(root/"gaze")])
                    except RuntimeError as exc:
                        reasons.append(str(exc))
                else:
                    reasons.append("L2CS checkpoint is not installed.")
                if (root/"head/head-pose.json").is_file() and (root/"gaze/gaze-benchmark.json").is_file():
                    try:
                        self._stage(job_id, "fusion",
                            [sys.executable, str(bench/"fuse_gaze_reviews.py"),
                             "--vlm-results", str(results),
                             "--head-report", str(root/"head/head-pose.json"),
                             "--gaze-report", str(root/"gaze/gaze-benchmark.json"),
                             "--output-dir", str(root/"fused")])
                    except RuntimeError as exc:
                        reasons.append(str(exc))
                if reasons:
                    self.save(job_id, message="Geometry unavailable/incomplete: " +
                              "; ".join(reasons)[:1000])
            completed = len(list(results.glob("*.vlm.json")))
            failures = max(0, self.state(job_id)["total"]-completed)
            self.save(job_id, status="completed", stage="finished",
                      completed=completed, failures=failures)
        except InterruptedError as exc:
            self.save(job_id, status="cancelled", stage="cancelled", message=str(exc))
        except Exception as exc:
            self.save(job_id, status="failed", stage="failed", message=str(exc)[:1000])
        finally:
            with self.lock:
                self.current = None

    def results(self, job_id):
        root = self.folder(job_id)
        state = self.state(job_id)
        if state["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
            return {"job": state, "results": {}}
        records = {}
        # Prefer fused evidence for each image, fall back to Qwen-only if
        # geometry was unavailable or a fusion stage partially failed.
        for folder in (root/"qwen", root/"fused"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.vlm.json"))[:MAX_FILES]:
                name = path.name[:-len(".vlm.json")]
                if ITEM_RE.fullmatch(name) and path.stat().st_size < 256*1024:
                    try:
                        records[name] = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
        return {"job": state, "results": records}


class Handler(BaseHTTPRequestHandler):
    worker: Worker

    def json_response(self, body, code=200):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            path = urlsplit(self.path).path.strip("/").split("/")
            if path == ["health"]:
                self.json_response({"service": "image-playground-vlm-worker",
                    "version": 1, "active": self.worker.current,
                    "pod_id": os.getenv("RUNPOD_POD_ID", ""),
                    "ollama": "127.0.0.1:11434",
                    "skill_ready": (self.worker.skills /
                                    "image-detailer-analysis/SKILL.md").is_file()})
            elif len(path) >= 2 and path[0] == "jobs":
                job_id = valid_job(path[1])
                if len(path) == 2:
                    self.json_response(self.worker.state(job_id))
                elif len(path) == 3 and path[2] == "results":
                    self.json_response(self.worker.results(job_id))
                else:
                    self.json_response({"error": "Unknown endpoint"}, 404)
            else:
                self.json_response({"error": "Unknown endpoint"}, 404)
        except (ValueError, FileNotFoundError) as exc:
            self.json_response({"error": str(exc)}, 404)

    def do_POST(self):
        try:
            path = urlsplit(self.path).path.strip("/").split("/")
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 < length <= MAX_ZIP:
                raise ValueError("Request body missing or exceeds worker limit.")
            if len(path) == 2 and path[0] == "uploads":
                job_id = valid_job(path[1])
                if self.headers.get("Content-Type") != "application/zip":
                    raise ValueError("Expected application/zip.")
                # Direct mode has a bounded, single ZIP request. Bulk mode
                # uses vcp/HF and never sends image bytes via this endpoint.
                self.worker.upload(job_id, self.rfile, length)
                self.json_response({"uploaded": True, "job_id": job_id}, 201)
                return
            raw = json.loads(self.rfile.read(length))
            if len(path) == 3 and path[0] == "jobs":
                job_id = valid_job(path[1])
                if path[2] == "start":
                    self.json_response(self.worker.start(
                        job_id, model=raw.get("model", "qwen3-vl:8b-instruct"),
                        geometry=raw.get("geometry", True)), 202)
                elif path[2] == "cancel":
                    self.json_response(self.worker.cancel(job_id))
                else:
                    self.json_response({"error": "Unknown endpoint"}, 404)
            else:
                self.json_response({"error": "Unknown endpoint"}, 404)
        except (ValueError, FileExistsError, RuntimeError,
                json.JSONDecodeError, zipfile.BadZipFile) as exc:
            self.json_response({"error": str(exc)}, 400)
        except OSError as exc:
            self.json_response({"error": str(exc)}, 500)


def make_server(root=DEFAULT_ROOT, port=8765, host="127.0.0.1"):
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("VLM worker must bind to loopback only.")
    worker = Worker(root)
    class WorkerHandler(Handler):
        pass
    WorkerHandler.worker = worker
    server = ThreadingHTTPServer((host, port), WorkerHandler)
    server.daemon_threads = True
    return server


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    server = make_server(args.root, args.port)
    print(f"[vlm-worker] http://127.0.0.1:{args.port} (SSH forwarding only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
