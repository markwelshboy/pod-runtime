"""Offline VLM worker ZIP validation, state recovery and HTTP integration."""
from __future__ import annotations
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from urllib import request, error
from unittest import mock

BIN = Path(__file__).resolve().parents[1]/"bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))
import vlm_worker as w
import rpods
import rpods_vlm
import rpods_pixlstash


def bundle(names=("i000000.jpg",), contents=b"\xff\xd8test\xff\xd9"):
    dest=io.BytesIO()
    items=[{"id": name, "sha256": hashlib.sha256(contents).hexdigest()}
           for name in names]
    with zipfile.ZipFile(dest,"w",zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", json.dumps({"images": items}))
        for name in names:
            z.writestr("images/"+name, contents)
    return dest.getvalue()


class WorkerTests(unittest.TestCase):
    def test_zip_members_are_checked_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/"valid.zip";path.write_bytes(bundle())
            self.assertEqual(w.safe_zip(path,root/"unpack"),1)
            self.assertEqual((root/"unpack/images/i000000.jpg").read_bytes(),
                             b"\xff\xd8test\xff\xd9")
            with zipfile.ZipFile(path,"w") as z:
                z.writestr("manifest.json", json.dumps({"images":[{
                    "id":"i000000.jpg","sha256":"0"*64}]}))
                z.writestr("images/i000000.jpg", b"mismatch")
            with self.assertRaisesRegex(ValueError,"checksum mismatch"):
                w.safe_zip(path,root/"invalid")
            with zipfile.ZipFile(path,"w") as z:
                z.writestr("../unsafe", b"data")
            with self.assertRaisesRegex(ValueError,"Unexpected input"):
                w.safe_zip(path,root/"unsafe")

    def test_job_id_rejects_path_injection(self):
        for bad in ("../../../etc/passwd", "b"*33, "hello", "ABC", ""):
            with self.assertRaises(ValueError):
                w.valid_job(bad)
        self.assertEqual(w.valid_job("a"*32),"a"*32)

    def test_server_only_binds_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"loopback"):
                w.make_server(tmp, 0, host="0.0.0.0")

    def test_persisted_completed_results_and_interruption_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker=w.Worker(tmp)
            job="a"*32
            root=worker.folder(job)
            root.mkdir()
            (root/"state.json").write_text(json.dumps(
                {"job_id":job,"status":"running","completed":2}))
            new_worker=w.Worker(tmp)
            self.assertEqual(new_worker.state(job)["status"],"interrupted")
            (root/"qwen").mkdir()
            item={"image":"/pod/i000000.jpg","data":{"tags":["eyes-closed"],
                                                    "tasks":[]}}
            (root/"qwen/i000000.jpg.vlm.json").write_text(json.dumps(item))
            new_worker.save(job,status="completed")
            self.assertEqual(new_worker.results(job)["results"]["i000000.jpg"],item)

    def test_http_upload_start_status_results_without_real_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(w.Worker, "_run", autospec=True) as fake_run:
                def finish(worker, job_id, model, geometry):
                    root=worker.folder(job_id)
                    (root/"qwen").mkdir()
                    (root/"qwen/i000000.jpg.vlm.json").write_text(json.dumps({
                        "image":"i000000.jpg","data":{"tags":["eyes-open"],"tasks":[]}
                    }))
                    worker.save(job_id, status="completed",stage="finished",
                                completed=1)
                fake_run.side_effect=finish
                server=w.make_server(tmp,0)
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                host="http://127.0.0.1:%d"%server.server_port
                ident="b"*32
                try:
                    health=json.load(request.urlopen(host+"/health",timeout=3))
                    self.assertEqual(health["service"],"image-playground-vlm-worker")
                    payload=bundle()
                    req=request.Request(host+"/uploads/"+ident,data=payload,
                           headers={"Content-Type":"application/zip"},method="POST")
                    result=json.load(request.urlopen(req,timeout=3))
                    self.assertTrue(result["uploaded"])
                    req=request.Request(host+"/jobs/"+ident+"/start",
                           data=b'{"geometry":false}',method="POST",
                           headers={"Content-Type":"application/json"})
                    json.load(request.urlopen(req,timeout=3))
                    server.RequestHandlerClass.worker.thread.join(timeout=3)
                    state=json.load(request.urlopen(host+"/jobs/"+ident,timeout=3))
                    self.assertEqual(state["status"],"completed")
                    results=json.load(request.urlopen(host+"/jobs/"+ident+"/results",timeout=3))
                    self.assertIn("i000000.jpg",results["results"])
                    self.assertTrue((Path(tmp)/"uploads"/(ident+".zip")).is_file())
                finally:
                    server.shutdown();server.server_close();thread.join(timeout=3)

    def test_rpods_exposes_worker_on_third_loopback_forward(self):
        ssh=["ssh","-i","/tmp/key","-p","53292","root@195.26.232.177"]
        a=rpods_vlm.tunnel_argv(ssh)
        self.assertEqual(a.count("-L"),2)
        self.assertIn("127.0.0.1:47962:127.0.0.1:8765",a)
        b=rpods_pixlstash.tunnel_argv(ssh,local_comfy_port=47960,
            remote_comfy_port=8288,local_pixlstash_port=64404,
            remote_pixlstash_port=64404,local_ollama_port=47961,
            local_worker_port=47962)
        self.assertEqual(b.count("-L"),3)
        self.assertEqual(b.count("-R"),1)
        args=rpods.build_parser().parse_args(["--tunnel","pixlstash","vlm"])
        self.assertEqual(args.worker_local_port,47962)
        with self.assertRaises(ValueError):
            rpods_vlm.tunnel_argv(ssh,local_ollama_port=47962)


if __name__=="__main__":
    unittest.main()
