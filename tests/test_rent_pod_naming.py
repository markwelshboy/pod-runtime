import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import rent_pod_naming as naming
import rent_pod_templates as templates

naming.register_template_option(templates)


class RentPodNamingTests(unittest.TestCase):
    def write_config(self, root: str, text: str) -> Path:
        path = Path(root) / "templates.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def write_template(self, root: str, name: str, text: str) -> Path:
        directory = Path(root) / "templates"
        directory.mkdir(exist_ok=True)
        path = directory / f"{name}.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def context_for_directory_template(
        self,
        td: str,
        *,
        config_text: str,
        template_text: str,
        name: str = "qwen3-captioning",
    ):
        cfg = self.write_config(td, config_text)
        self.write_template(td, name, template_text)
        _argv, context = templates.apply_template_profile(
            ["l40s", "--template", name],
            {"RENT_POD_TEMPLATES_FILE": str(cfg)},
        )
        return cfg, context

    def test_registers_naming_as_template_metadata(self):
        self.assertIn("naming", templates.LOCAL_KEYS)

    def test_directory_template_inherits_collision_default(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text='''
version = 2
[defaults.naming]
collision = "increment"
''',
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
''',
            )
            got = naming.template_naming(context)

        self.assertEqual(got, {"pattern": "q3c", "collision": "increment"})

    def test_directory_template_can_inherit_full_naming_default(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text='''
version = 2
[defaults.naming]
pattern = "{template}"
collision = "increment"
''',
                template_text='image = "ubuntu:latest"\n',
            )
            got = naming.template_naming(context)

        self.assertEqual(got, {"pattern": "{template}", "collision": "increment"})

    def test_inline_remote_profile_supports_naming(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(
                td,
                '''
version = 2

[templates.remote]
id = "tmpl123"

[templates.remote.naming]
pattern = "remote-{date}"
collision = "allow"
''',
            )
            _argv, context = templates.apply_template_profile(
                ["l40s", "--template", "remote"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            got = naming.template_naming(context)

        self.assertEqual(got, {"pattern": "remote-{date}", "collision": "allow"})

    def test_increment_collision_chooses_first_free_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
collision = "increment"
''',
            )
            pods = [
                {"id": "a", "name": "q3c"},
                {"id": "b", "name": "q3c-1"},
                {"id": "c", "name": "q3c-3"},
                {"id": "d", "name": "other"},
            ]
            with mock.patch.object(naming.core, "api_request", return_value=pods) as request:
                argv, selection = naming.apply_template_naming(
                    ["l40s", "--template", "qwen3-captioning"],
                    context,
                    {"RUNPOD_API_KEY": "token"},
                )

        self.assertEqual(argv[-2:], ["--name", "q3c-2"])
        self.assertEqual(selection["name"], "q3c-2")
        self.assertEqual(selection["base"], "q3c")
        request.assert_called_once_with("token", "GET", "/pods")

    def test_free_base_name_is_used_without_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
''',
            )
            with mock.patch.object(
                naming.core,
                "api_request",
                return_value=[{"id": "x", "name": "other"}],
            ):
                argv, selection = naming.apply_template_naming(
                    ["l40s", "--template", "qwen3-captioning"],
                    context,
                    {"RUNPOD_API_KEY": "token"},
                )

        self.assertEqual(argv[-2:], ["--name", "q3c"])
        self.assertEqual(selection["name"], "q3c")

    def test_explicit_cli_name_wins_and_does_not_query_pods(self):
        context = mock.Mock()
        with mock.patch.object(naming.core, "api_request") as request:
            argv, selection = naming.apply_template_naming(
                ["l40s", "--name", "manual-name"],
                context,
                {"RUNPOD_API_KEY": "token"},
            )

        self.assertEqual(argv, ["l40s", "--name", "manual-name"])
        self.assertEqual(selection["source"], "CLI")
        self.assertEqual(selection["name"], "manual-name")
        request.assert_not_called()

    def test_dry_run_injects_preview_without_querying_account(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
collision = "increment"
''',
            )
            with mock.patch.object(naming.core, "api_request") as request:
                argv, selection = naming.apply_template_naming(
                    ["l40s", "--template", "qwen3-captioning", "--dry-run"],
                    context,
                    {},
                    resolve_collision=False,
                )

        self.assertEqual(argv[-2:], ["--name", "q3c"])
        self.assertEqual(selection["deferred"], "true")
        request.assert_not_called()

    def test_pattern_tokens_render_locally(self):
        context = mock.Mock(profile_name="qwen3-captioning", requested="qwen3-captioning")
        rendered = naming.render_pattern(
            "{template}-{date}-{uid}",
            context,
            uid="a83f2c",
            now=datetime(2026, 9, 17, 12, 0, 0),
        )
        self.assertEqual(rendered, "qwen3-captioning-20260917-a83f2c")

    def test_pod_id_token_is_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c-{pod-id}"
''',
            )
            with self.assertRaisesRegex(ValueError, "does not exist until after creation"):
                naming.template_naming(context)

    def test_error_collision_policy_rejects_existing_name(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
collision = "error"
''',
            )
            with mock.patch.object(
                naming.core,
                "api_request",
                return_value=[{"id": "a", "name": "q3c"}],
            ):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    naming.apply_template_naming(
                        ["l40s", "--template", "qwen3-captioning"],
                        context,
                        {"RUNPOD_API_KEY": "token"},
                    )

    def test_allow_collision_policy_does_not_query_pods(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
collision = "allow"
''',
            )
            with mock.patch.object(naming.core, "api_request") as request:
                argv, selection = naming.apply_template_naming(
                    ["l40s", "--template", "qwen3-captioning"],
                    context,
                    {},
                )

        self.assertEqual(argv[-2:], ["--name", "q3c"])
        self.assertEqual(selection["collision"], "allow")
        request.assert_not_called()

    def test_missing_api_key_only_matters_when_collision_resolution_is_needed(self):
        with tempfile.TemporaryDirectory() as td:
            _cfg, context = self.context_for_directory_template(
                td,
                config_text="version = 2\n",
                template_text='''
image = "ubuntu:latest"

[naming]
pattern = "q3c"
collision = "increment"
''',
            )
            with self.assertRaisesRegex(ValueError, "RUNPOD_API_KEY"):
                naming.apply_template_naming(
                    ["l40s", "--template", "qwen3-captioning"],
                    context,
                    {},
                )


if __name__ == "__main__":
    unittest.main()
