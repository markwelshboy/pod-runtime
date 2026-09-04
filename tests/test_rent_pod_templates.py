import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_templates.py"
spec = importlib.util.spec_from_file_location("rent_pod_templates", MODULE)
templates = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = templates
spec.loader.exec_module(templates)


class RentPodTemplateTests(unittest.TestCase):
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

    def test_builtin_default_exists_without_file(self):
        with tempfile.TemporaryDirectory() as td:
            registry = templates.load_registry(
                {"RENT_POD_TEMPLATES_FILE": str(Path(td) / "missing.toml")}
            )
        self.assertFalse(registry.file_exists)
        self.assertEqual(registry.profiles["default"].template_id, "86n5dpgf7h")
        self.assertEqual(registry.profiles["default"].kind, "remote")

    def test_loads_named_profile_description_and_env(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
version = 1
default = "comfyui-inference-lite"

[templates.comfyui-inference-lite]
id = "abc123def4"
description = "Lean ComfyUI inference pod"

[templates.comfyui-inference-lite.env]
ENABLE_SAGE_UPLOAD = true
MINMAX = false
WORKERS = 2
''',
            )
            registry = templates.load_registry({"RENT_POD_TEMPLATES_FILE": str(path)})
        profile = registry.profiles["comfyui-inference-lite"]
        self.assertEqual(registry.default_name, "comfyui-inference-lite")
        self.assertEqual(profile.description, "Lean ComfyUI inference pod")
        self.assertEqual(profile.kind, "remote")
        self.assertEqual(
            profile.env,
            {"ENABLE_SAGE_UPLOAD": "true", "MINMAX": "false", "WORKERS": "2"},
        )

    def test_directory_local_template_uses_filename_as_profile_name(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
version = 2
default = "qwen3-captioning"

[defaults]
container_disk_gb = 40
volume_gb = 100
volume_mount_path = "/workspace"
ports = ["22/tcp"]

[defaults.env]
COMMON = "yes"

[defaults.secrets]
HF_TOKEN = "huggingface_token"
''',
            )
            source = self.write_template(
                td,
                "qwen3-captioning",
                '''
description = "Qwen captioning pod"
image = "runpod/pytorch:qwen"
docker_args = "sleep infinity"
ports = ["22/tcp", "8000/http"]

[env]
PROJECT = "qwen3"

[secrets]
OPENAI_API_KEY = "openai_key"
''',
            )
            registry = templates.load_registry({"RENT_POD_TEMPLATES_FILE": str(path)})

        profile = registry.profiles["qwen3-captioning"]
        self.assertEqual(profile.kind, "local")
        self.assertEqual(profile.source, source)
        self.assertEqual(profile.pod["imageName"], "runpod/pytorch:qwen")
        self.assertEqual(profile.pod["containerDiskInGb"], 40)
        self.assertEqual(profile.pod["volumeInGb"], 100)
        self.assertEqual(profile.pod["ports"], ["22/tcp", "8000/http"])
        self.assertEqual(profile.pod["dockerArgs"], "sleep infinity")
        self.assertEqual(profile.env, {"COMMON": "yes", "PROJECT": "qwen3"})
        self.assertEqual(
            profile.secret_env,
            {"HF_TOKEN": "huggingface_token", "OPENAI_API_KEY": "openai_key"},
        )

    def test_config_default_is_injected_when_template_not_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
default = "lite"
[templates.lite]
id = "tmpl123456"
description = "Lite"
''',
            )
            argv, context = templates.apply_template_profile(
                ["4090"], {"RENT_POD_TEMPLATES_FILE": str(path)}
            )
        self.assertEqual(argv, ["4090", "--template", "lite"])
        self.assertEqual(context.profile_name, "lite")
        self.assertEqual(context.template_id, "tmpl123456")

    def test_cli_env_overrides_profile_env_and_secret(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
[templates.lite]
id = "tmpl123456"
[templates.lite.env]
ENABLE_SAGE_UPLOAD = true
MINMAX = true
[templates.lite.secrets]
HF_TOKEN = "huggingface_token"
''',
            )
            argv, context = templates.apply_template_profile(
                [
                    "4090",
                    "--template",
                    "lite",
                    "--env",
                    "ENABLE_SAGE_UPLOAD=false;HF_TOKEN=temporary;EXTRA=yes",
                ],
                {"RENT_POD_TEMPLATES_FILE": str(path)},
            )
        self.assertEqual(argv, ["4090", "--template", "lite"])
        self.assertEqual(
            context.env,
            {
                "ENABLE_SAGE_UPLOAD": "false",
                "MINMAX": "true",
                "HF_TOKEN": "temporary",
                "EXTRA": "yes",
            },
        )

    def test_runpod_secret_reference_format(self):
        self.assertEqual(
            templates.runpod_secret_ref("huggingface_token"),
            "{{ RUNPOD_SECRET_huggingface_token }}",
        )

    def test_raw_template_id_still_passes_through(self):
        with tempfile.TemporaryDirectory() as td:
            argv, context = templates.apply_template_profile(
                ["4090", "--template", "raw9876543"],
                {"RENT_POD_TEMPLATES_FILE": str(Path(td) / "none.toml")},
            )
        self.assertEqual(argv, ["4090", "--template", "raw9876543"])
        self.assertIsNone(context.profile_name)
        self.assertEqual(context.template_id, "raw9876543")

    def test_api_hook_resolves_remote_alias_and_adds_env(self):
        context = templates.TemplateContext(
            requested="lite",
            template_id="tmpl123456",
            profile_name="lite",
            description="Lite",
            env={"A": "profile", "B": "run"},
            config_path=Path("/tmp/templates.toml"),
        )
        calls = []

        def fake_request(api_key, method, path, payload=None):
            calls.append((api_key, method, path, payload))
            return {"id": "pod1"}

        with mock.patch.object(templates.core, "api_request", fake_request):
            templates.install_core_api_hook(context)
            result = templates.core.api_request(
                "token",
                "POST",
                "/pods",
                {"templateId": "lite", "env": {"A": "existing", "C": "keep"}},
            )

        self.assertEqual(result, {"id": "pod1"})
        payload = calls[0][3]
        self.assertEqual(payload["templateId"], "tmpl123456")
        self.assertEqual(payload["env"], {"A": "profile", "C": "keep", "B": "run"})

    def test_local_template_removes_template_id_and_injects_pod_fields(self):
        context = templates.TemplateContext(
            requested="qwen3-captioning",
            template_id=None,
            profile_name="qwen3-captioning",
            description="Qwen",
            env={"HF_TOKEN": "{{ RUNPOD_SECRET_huggingface_token }}"},
            pod={
                "imageName": "runpod/pytorch:qwen",
                "containerDiskInGb": 40,
                "ports": ["22/tcp", "8000/http"],
            },
            config_path=Path("/tmp/templates.toml"),
        )
        payload = templates.apply_context_to_payload(
            {
                "templateId": "qwen3-captioning",
                "gpuTypeIds": ["NVIDIA L40S"],
                "gpuCount": 1,
            },
            context,
        )
        self.assertNotIn("templateId", payload)
        self.assertEqual(payload["imageName"], "runpod/pytorch:qwen")
        self.assertEqual(payload["containerDiskInGb"], 40)
        self.assertEqual(payload["ports"], ["22/tcp", "8000/http"])
        self.assertEqual(
            payload["env"]["HF_TOKEN"],
            "{{ RUNPOD_SECRET_huggingface_token }}",
        )

    def test_profile_cannot_define_remote_id_and_local_image(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(td, "version = 2\n")
            self.write_template(
                td,
                "bad",
                'id = "remote123"\nimage = "ubuntu:latest"\n',
            )
            with self.assertRaises(ValueError):
                templates.load_registry({"RENT_POD_TEMPLATES_FILE": str(path)})

    def test_parse_env_supports_repeated_and_semicolon_specs(self):
        got = templates.parse_env_specs(["A=1;B=two", "A=final", "EMPTY="])
        self.assertEqual(got, {"A": "final", "B": "two", "EMPTY": ""})

    def test_invalid_env_key_rejected(self):
        with self.assertRaises(ValueError):
            templates.parse_env_specs(["BAD-NAME=x"])

    def test_list_templates_is_local_only_action(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"RENT_POD_TEMPLATES_FILE": str(Path(td) / "missing.toml")}
            self.assertEqual(templates.handle_template_meta_command(["--list-templates"], env), 0)
            with self.assertRaises(ValueError):
                templates.handle_template_meta_command(["--list-templates", "4090"], env)


if __name__ == "__main__":
    unittest.main()
