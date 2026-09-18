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

    def test_registers_naming_metadata(self):
        self.assertIn("naming", templates.LOCAL_KEYS)

    def test_directory_template_supplies_incrementing_name(self):
        with tempfile.TemporaryDirectory() as td:
            context = self._context(
                Path(td),
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
                )
        self.assertEqual(pod_name, "q3c-2")
        self.assertEqual(source, "template")
        self.assertEqual(argv[-2:], ["--name", "q3c-2"])

    def test_first_name_uses_bare_pattern(self):
        self.assertEqual(naming.increment_name("q3c", {"other"}), "q3c")

    def test_cli_name_wins_without_inventory_lookup(self):
        context = mock.Mock()
        with mock.patch.object(naming, "template_naming_config") as profile:
            argv, pod_name, source = naming.apply_template_naming(
                ["l40s", "--name", "manual"],
                context,
                "token",
                resolve_collisions=True,
            )
        profile.assert_not_called()
        self.assertEqual(argv, ["l40s", "--name", "manual"])
        self.assertEqual((pod_name, source), ("manual", "CLI"))

    def test_dry_run_renders_base_without_querying_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            context = self._context(Path(td), '[naming]\npattern = "q3c"\n')
            with mock.patch.object(naming, "existing_pod_names") as existing:
                argv, pod_name, source = naming.apply_template_naming(
                    ["l40s", "--dry-run"],
                    context,
                    "",
                    resolve_collisions=False,
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
