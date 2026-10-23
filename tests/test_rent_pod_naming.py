import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
import sys

if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import rent_pod_naming as naming
import rent_pod_templates as templates


class RentPodNamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        naming.register_template_option(templates)

    def _context(self, root: Path, template_text: str, defaults: str = ""):
        cfg = root / "templates.toml"
        cfg.write_text(
            'version = 2\ntemplate_dir = "templates"\n' + defaults,
            encoding="utf-8",
        )
        template_dir = root / "templates"
        template_dir.mkdir()
        (template_dir / "qwen3-captioning.toml").write_text(
            'image = "ubuntu:latest"\n' + template_text,
            encoding="utf-8",
        )
        _argv, context = templates.apply_template_profile(
            ["l40s", "--template", "qwen3-captioning"],
            {"RENT_POD_TEMPLATES_FILE": str(cfg)},
        )
        return context

    def _reservation_env(self, root: Path) -> dict[str, str]:
        return {"RENT_POD_NAME_RESERVATIONS": str(root / "reservations.json")}

    def test_registers_naming_metadata(self):
        self.assertIn("naming", templates.LOCAL_KEYS)

    def test_directory_template_supplies_incrementing_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = self._context(
                root,
                '[naming]\npattern = "q3c"\ncollision = "increment"\n',
            )
            with mock.patch.object(
                naming,
                "existing_pod_names",
                return_value={"q3c", "q3c-1", "other"},
            ):
                argv, pod_name, source = naming.apply_template_naming(
                    ["l40s", "--template", "qwen3-captioning"],
                    context,
                    "token",
                    resolve_collisions=True,
                    environ=self._reservation_env(root),
                )
        self.assertEqual(pod_name, "q3c-2")
        self.assertEqual(source, "template")
        self.assertEqual(argv[-2:], ["--name", "q3c-2"])

    def test_first_template_name_uses_bare_pattern(self):
        self.assertEqual(naming.increment_name("q3c", {"other"}), "q3c")

    def test_explicit_name_is_a_numbered_stem(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = mock.Mock()
            with mock.patch.object(
                naming,
                "existing_pod_names",
                return_value={"manual-1", "other"},
            ) as existing:
                argv, pod_name, source = naming.apply_template_naming(
                    ["l40s", "--name", "manual"],
                    context,
                    "token",
                    resolve_collisions=True,
                    environ=self._reservation_env(root),
                )
        existing.assert_called_once_with("token")
        self.assertEqual(argv, ["l40s", "--name", "manual-2"])
        self.assertEqual((pod_name, source), ("manual-2", "CLI"))

    def test_explicit_equals_name_is_rewritten_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(naming, "existing_pod_names", return_value=set()):
                argv, pod_name, source = naming.apply_template_naming(
                    ["l40s", "--name=rp-krea2"],
                    mock.Mock(),
                    "token",
                    resolve_collisions=True,
                    environ=self._reservation_env(root),
                )
        self.assertEqual(argv, ["l40s", "--name", "rp-krea2-1"])
        self.assertEqual((pod_name, source), ("rp-krea2-1", "CLI"))

    def test_local_reservations_close_parallel_inventory_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = self._reservation_env(root)
            context = mock.Mock()
            with mock.patch.object(naming, "existing_pod_names", return_value=set()):
                _argv1, first, _source1 = naming.apply_template_naming(
                    ["l40s", "--name", "rp-krea2"],
                    context,
                    "token",
                    resolve_collisions=True,
                    environ=env,
                )
                _argv2, second, _source2 = naming.apply_template_naming(
                    ["l40s", "--name", "rp-krea2"],
                    context,
                    "token",
                    resolve_collisions=True,
                    environ=env,
                )
        self.assertEqual(first, "rp-krea2-1")
        self.assertEqual(second, "rp-krea2-2")

    def test_reservation_lock_is_safe_across_processes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reservation = root / "reservations.json"
            env = os.environ.copy()
            env["RENT_POD_NAME_RESERVATIONS"] = str(reservation)
            env["PYTHONPATH"] = str(BIN) + os.pathsep + env.get("PYTHONPATH", "")
            code = (
                "from rent_pod_naming import reserve_incremented_name; "
                "print(reserve_incremented_name('rp-krea2', set(), always_suffix=True))"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", code],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
                for _ in range(4)
            ]
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                results.append(stdout.strip())

        self.assertEqual(
            set(results),
            {"rp-krea2-1", "rp-krea2-2", "rp-krea2-3", "rp-krea2-4"},
        )

    def test_explicit_dry_run_previews_first_suffix_without_query_or_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = self._reservation_env(root)
            with mock.patch.object(naming, "existing_pod_names") as existing:
                argv, pod_name, source = naming.apply_template_naming(
                    ["l40s", "--name", "rp-krea2", "--dry-run"],
                    mock.Mock(),
                    "",
                    resolve_collisions=False,
                    environ=env,
                )
        existing.assert_not_called()
        self.assertEqual(argv[-2:], ["--name", "rp-krea2-1"])
        self.assertEqual((pod_name, source), ("rp-krea2-1", "CLI"))
        self.assertFalse(Path(env["RENT_POD_NAME_RESERVATIONS"]).exists())

    def test_dry_run_renders_template_base_without_querying_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = self._context(root, '[naming]\npattern = "q3c"\n')
            with mock.patch.object(naming, "existing_pod_names") as existing:
                argv, pod_name, source = naming.apply_template_naming(
                    ["l40s", "--dry-run"],
                    context,
                    "",
                    resolve_collisions=False,
                    environ=self._reservation_env(root),
                )
        existing.assert_not_called()
        self.assertEqual(argv[-2:], ["--name", "q3c"])
        self.assertEqual((pod_name, source), ("q3c", "template"))

    def test_directory_template_inherits_default_naming(self):
        with tempfile.TemporaryDirectory() as td:
            context = self._context(
                Path(td),
                "",
                '[defaults.naming]\npattern = "{template}"\n',
            )
            config = naming.template_naming_config(context)
        self.assertIsNotNone(config)
        self.assertEqual(config.pattern, "{template}")

    def test_supported_placeholders_render(self):
        context = mock.Mock(profile_name="qwen3-captioning", requested="qwen3-captioning")
        rendered = naming.render_pattern(
            "{template}-{date}-{uid}",
            context,
            now=datetime(2026, 9, 17),
            uid="abc123",
        )
        self.assertEqual(rendered, "qwen3-captioning-20260917-abc123")

    def test_unknown_placeholder_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown naming placeholder"):
            naming._normalize_naming({"pattern": "q3c-{pod-id}"}, "naming")

    def test_inline_remote_template_supports_naming(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "templates.toml"
            cfg.write_text(
                '''
version = 2
[templates.remote]
id = "tmpl123"
[templates.remote.naming]
pattern = "remote"
''',
                encoding="utf-8",
            )
            _argv, context = templates.apply_template_profile(
                ["l40s", "--template", "remote"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            config = naming.template_naming_config(context)
        self.assertIsNotNone(config)
        self.assertEqual(config.pattern, "remote")


if __name__ == "__main__":
    unittest.main()
