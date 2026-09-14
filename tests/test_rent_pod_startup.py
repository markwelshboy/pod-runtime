import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
import sys

if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import rent_pod_startup as startup
import rent_pod_templates as templates


class RentPodStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        startup.register_template_option(templates)

    def test_consumes_cli_startup_without_confusing_startup_timeout(self):
        forwarded, command = startup.consume_startup_args(
            [
                "--template",
                "qwen3-captioning",
                "--startup",
                "configure-pod --snapshot latest",
                "--startup-timeout",
                "900",
                "l40s",
            ]
        )
        self.assertEqual(command, "configure-pod --snapshot latest")
        self.assertEqual(
            forwarded,
            [
                "--template",
                "qwen3-captioning",
                "--startup-timeout",
                "900",
                "l40s",
            ],
        )

    def test_cli_startup_overrides_template_startup(self):
        context = mock.Mock()
        command, source = startup.resolve_startup_command("echo cli", context)
        self.assertEqual((command, source), ("echo cli", "CLI"))

    def test_directory_template_supplies_startup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "templates.toml"
            cfg.write_text(
                'version = 2\ntemplate_dir = "templates"\n',
                encoding="utf-8",
            )
            template_dir = root / "templates"
            template_dir.mkdir()
            template_file = template_dir / "qwen3-captioning.toml"
            template_file.write_text(
                '''
description = "Qwen captioning"
image = "runpod/pytorch:qwen"
startup = "configure-pod --template qwen3-captioning --snapshot latest"
''',
                encoding="utf-8",
            )
            env = {"RENT_POD_TEMPLATES_FILE": str(cfg)}
            _argv, context = templates.apply_template_profile(
                ["l40s", "--template", "qwen3-captioning"], env
            )
            command, source = startup.resolve_startup_command(None, context)
        self.assertEqual(
            command,
            "configure-pod --template qwen3-captioning --snapshot latest",
        )
        self.assertEqual(source, "template")

    def test_directory_template_inherits_default_startup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "templates.toml"
            cfg.write_text(
                '''
version = 2
template_dir = "templates"
[defaults]
startup = "echo default-startup"
''',
                encoding="utf-8",
            )
            template_dir = root / "templates"
            template_dir.mkdir()
            (template_dir / "worker.toml").write_text(
                'image = "ubuntu:latest"\n', encoding="utf-8"
            )
            env = {"RENT_POD_TEMPLATES_FILE": str(cfg)}
            _argv, context = templates.apply_template_profile(
                ["l40s", "--template", "worker"], env
            )
            command, source = startup.resolve_startup_command(None, context)
        self.assertEqual((command, source), ("echo default-startup", "template"))

    def test_inline_remote_template_supplies_startup(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "templates.toml"
            cfg.write_text(
                '''
version = 2
[templates.remote]
id = "tmpl123"
startup = "echo remote-ready"
''',
                encoding="utf-8",
            )
            env = {"RENT_POD_TEMPLATES_FILE": str(cfg)}
            _argv, context = templates.apply_template_profile(
                ["l40s", "--template", "remote"], env
            )
            command, source = startup.resolve_startup_command(None, context)
        self.assertEqual((command, source), ("echo remote-ready", "template"))

    def test_remote_bootstrap_loads_runtime_environment(self):
        remote = startup.build_remote_startup(
            "configure-pod --snapshot latest", "/workspace/custom-runtime"
        )
        self.assertIn("/workspace/custom-runtime", remote)
        self.assertIn("BASH_ENV", remote)
        self.assertIn("env.provisioned", remote)
        self.assertIn("env.current", remote)
        self.assertIn("configure-pod --snapshot latest", remote)

    def test_hook_runs_startup_only_after_successful_provision(self):
        events = []

        def provision(_identity, _key):
            events.append("provision")
            return 0

        def run_startup(_identity, _key, command, **_kwargs):
            events.append(f"startup:{command}")
            return 0

        with mock.patch.object(startup.core, "run_provision", provision):
            with mock.patch.object(startup, "run_startup_command", run_startup):
                startup.install_core_hook("echo ready")
                rc = startup.core.run_provision(
                    {"public_ip": "203.0.113.1", "ssh_port": 1234}, "key"
                )
        self.assertEqual(rc, 0)
        self.assertEqual(events, ["provision", "startup:echo ready"])

    def test_hook_does_not_run_startup_when_provision_fails(self):
        with mock.patch.object(startup.core, "run_provision", return_value=78):
            with mock.patch.object(startup, "run_startup_command") as run_startup:
                startup.install_core_hook("echo ready")
                rc = startup.core.run_provision({}, "key")
        self.assertEqual(rc, 78)
        run_startup.assert_not_called()

    def test_startup_failure_78_exits_without_returning_network_rejection_code(self):
        identity = {"public_ip": "203.0.113.1", "ssh_port": 1234}
        with mock.patch.object(startup.core, "run_provision", return_value=0):
            with mock.patch.object(startup, "run_startup_command", return_value=78):
                startup.install_core_hook("false")
                with self.assertRaises(SystemExit) as raised:
                    startup.core.run_provision(identity, "key")
        self.assertEqual(raised.exception.code, 78)

    def test_help_mentions_startup_and_template_form(self):
        import io
        import rent_pod_cli

        stream = io.StringIO()
        rent_pod_cli.print_help(stream)
        text = stream.getvalue()
        self.assertIn("--startup COMMAND", text)
        self.assertIn('startup = "configure-pod', text)
        self.assertIn("after successful provisioning", text)


if __name__ == "__main__":
    unittest.main()
