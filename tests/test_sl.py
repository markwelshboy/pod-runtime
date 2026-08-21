import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

from sl_lib import cli, commands, common, memory  # noqa: E402


class SlTests(unittest.TestCase):
    def test_parse_command_typed_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.cmd"
            path.write_text(
                "# sl:name demo\n# sl:input 1\n# sl:output 2\n# sl:setup-version 3\n# sl:memcheck\nsl_run() { :; }\n"
            )
            spec = commands._parse_command(path)
        self.assertEqual(spec.name, "demo")
        self.assertEqual(spec.inputs, [1])
        self.assertEqual(spec.outputs, [2])
        self.assertEqual(spec.setup_version, "3")
        self.assertTrue(spec.memcheck)
        self.assertIsNone(spec.memcheck_default)

    def test_memcheck_can_have_command_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.cmd"
            path.write_text("# sl:name demo\n# sl:memcheck 18G\nsl_run() { :; }\n")
            spec = commands._parse_command(path)
        self.assertTrue(spec.memcheck)
        self.assertEqual(spec.memcheck_default, "18G")

    def test_memory_parser_requires_units(self):
        self.assertEqual(memory.parse_memory_mib("18G"), 18 * 1024)
        self.assertEqual(memory.parse_memory_mib("18.5GB"), 18944)
        self.assertEqual(memory.parse_memory_mib("18000M"), 18000)
        with self.assertRaises(common.SlError):
            memory.parse_memory_mib("18")

    def test_output_path_rejects_escape(self):
        for value in ("../oops", "/tmp/oops", "foo/../bar", ""):
            with self.subTest(value=value):
                with self.assertRaises(common.SlError):
                    commands._validate_output_arg(value)
        self.assertEqual(commands._validate_output_arg("results/run1/"), "results/run1")

    def test_build_arg_values_stages_input_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "images"
            source.mkdir()
            cmd = Path(tmp) / "demo.cmd"
            cmd.write_text("# sl:name demo\n# sl:input 1\n# sl:output 2\nsl_run() { :; }\n")
            spec = commands._parse_command(cmd)
            values = commands._build_arg_values(spec, [str(source), "out/results"], "/workspace/.sl", "20260820_120000_deadbeef")
        self.assertTrue(values[1].endswith("/input/arg1/images"))
        self.assertTrue(values[2].endswith("/output/out/results"))

    def test_runner_loads_pod_runtime_before_command_and_gates_memory_before_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "demo.cmd"
            cmd.write_text("# sl:name demo\n# sl:memcheck\nsl_run() { :; }\n")
            spec = commands._parse_command(cmd)
            script = commands._build_run_script(
                job_id="20260820_120000_deadbeef",
                spec=spec,
                arg_values={},
                extra_args=["--thing", "value with spaces"],
                remote_root="/workspace/.sl",
                runtime_repo="https://example.invalid/pod-runtime.git",
                runtime_ref="main",
                memory_mib=18 * 1024,
            )
        self.assertLess(script.index('source "$SL_RUNTIME_DIR/helpers.sh"'), script.index('source "$SL_COMMAND_FILE"'))
        self.assertIn("SL_EXTRA_ARGS=(--thing 'value with spaces')", script)
        self.assertIn("export SL_MEMORY_REQUIRED_MIB=18432", script)
        self.assertIn("WAITING_FOR_MEMORY", script)
        self.assertLess(script.index("\n_sl_wait_for_memory\nrc=$?\n"), script.index("\n_sl_status RUNNING\n"))
        self.assertNotIn("eval ", script)

    def test_run_parser_preserves_extra_argv_and_mem(self):
        ns = cli._parse_run(["--mem", "18G", "seedvr2", "in", "out", "--", "--config", "a b.json", "--seed", "43"])
        self.assertEqual(ns.command, "seedvr2")
        self.assertEqual(ns.operands, ["in", "out"])
        self.assertEqual(ns.mem, "18G")
        self.assertEqual(ns.extra, ["--config", "a b.json", "--seed", "43"])

    def test_alias_parser(self):
        ns = cli._parse_run(["--mem", "18000M", "in", "out", "--", "--scale", "2"], command_alias="seedvr2.cmd")
        self.assertEqual(ns.command, "seedvr2.cmd")
        self.assertEqual(ns.operands, ["in", "out"])
        self.assertEqual(ns.mem, "18000M")
        self.assertEqual(ns.extra, ["--scale", "2"])

    def test_vcp_ssh_config_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vcp.json"
            path.write_text('{"ssh":["-p","1234","root@host"]}')
            with mock.patch.object(common, "VCP_CONFIG_PATH", path):
                self.assertEqual(common._ssh_argv(), ["-p", "1234", "root@host"])


if __name__ == "__main__":
    unittest.main()
