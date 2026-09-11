import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rpods.py"
spec = importlib.util.spec_from_file_location("rpods", MODULE)
rpods = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = rpods
spec.loader.exec_module(rpods)


class RPodsTests(unittest.TestCase):
    def choice(self, **overrides):
        data = dict(
            pod_id="p1",
            name="qwen3",
            stage="NETWORK",
            gpu="NVIDIA L40S",
            machine="machine-1",
            datacenter="US-CA-1",
            public_ip="1.2.3.4",
            ssh_port=22022,
            uptime_seconds=3723,
            created_at=None,
        )
        data.update(overrides)
        return rpods.PodChoice(**data)

    def test_format_age(self):
        self.assertEqual(rpods.format_age(None), "?")
        self.assertEqual(rpods.format_age(45), "0m")
        self.assertEqual(rpods.format_age(3723), "1h 2m")
        self.assertEqual(rpods.format_age(90061), "1d 1h")

    def test_choice_from_pod_prefers_live_graphql_endpoint(self):
        rest = {
            "id": "p1",
            "name": "qwen3-captioning",
            "createdAt": "2026-09-11T20:00:00Z",
            "desiredStatus": "RUNNING",
            "gpuTypeId": "NVIDIA L40S",
            "publicIp": "9.9.9.9",
            "portMappings": {"22": 11111},
            "machineId": "machine-1",
            "machine": {"dataCenterId": "US-CA-1"},
        }
        gql = {
            "id": "p1",
            "desiredStatus": "RUNNING",
            "runtime": {
                "uptimeInSeconds": 1234,
                "ports": [
                    {
                        "ip": "1.2.3.4",
                        "isIpPublic": True,
                        "privatePort": 22,
                        "publicPort": 22022,
                        "type": "tcp",
                    }
                ],
            },
        }
        choice = rpods.choice_from_pod(rest, gql)
        self.assertTrue(choice.connectable)
        self.assertEqual(choice.public_ip, "1.2.3.4")
        self.assertEqual(choice.ssh_port, 22022)
        self.assertEqual(choice.uptime_seconds, 1234)
        self.assertEqual(choice.machine, "machine-1")
        self.assertEqual(choice.stage, "NETWORK")

    def test_print_choices_numbers_only_connectable_pods(self):
        ready = self.choice()
        starting = self.choice(
            pod_id="p2",
            name="starting",
            stage="STARTING",
            public_ip=None,
            ssh_port=None,
        )
        stream = io.StringIO()
        with redirect_stdout(stream):
            numbered = rpods.print_choices([ready, starting], show_all=True)
        self.assertEqual(numbered, [ready])
        text = stream.getvalue()
        self.assertIn("1) qwen3", text)
        self.assertIn("--) starting", text)
        self.assertIn("SSH mapping pending", text)

    def test_select_choice_accepts_number_id_or_name(self):
        one = self.choice(pod_id="p1", name="qwen")
        two = self.choice(pod_id="p2", name="seedvr2")
        all_choices = [one, two]
        self.assertIs(rpods.select_choice("1", all_choices, all_choices), one)
        self.assertIs(rpods.select_choice("p2", all_choices, all_choices), two)
        self.assertIs(rpods.select_choice("seedvr2", all_choices, all_choices), two)

    def test_select_choice_rejects_ambiguous_name(self):
        one = self.choice(pod_id="p1", name="same")
        two = self.choice(pod_id="p2", name="same")
        with self.assertRaises(ValueError) as ctx:
            rpods.select_choice("same", [one, two], [one, two])
        self.assertIn("ambiguous", str(ctx.exception))

    def test_ssh_argv_uses_rent_pod_ssh_builder(self):
        choice = self.choice()
        argv = rpods.ssh_argv(choice, "/tmp/key")
        self.assertEqual(argv[0], "ssh")
        self.assertIn("/tmp/key", argv)
        self.assertIn("22022", argv)
        self.assertIn("root@1.2.3.4", argv)

    def test_ssh_argv_rejects_unmapped_pod(self):
        choice = self.choice(public_ip=None, ssh_port=None, stage="STARTING")
        with self.assertRaises(ValueError):
            rpods.ssh_argv(choice, "/tmp/key")


if __name__ == "__main__":
    unittest.main()
