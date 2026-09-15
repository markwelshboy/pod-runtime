import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import rent_pod_templates as templates
import rent_pod_cuda_profile as cuda_profile

cuda_profile.register_template_option(templates)


class RentPodCudaProfileTests(unittest.TestCase):
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

    def test_registers_min_cuda_as_template_metadata(self):
        self.assertIn("min_cuda", templates.LOCAL_KEYS)

    def test_directory_profile_overrides_default_min_cuda(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(
                td,
                '''
version = 2
[defaults]
min_cuda = "12.8"
''',
            )
            self.write_template(
                td,
                "minimax",
                '''
image = "markwelshboy/comfyui-minimax:test"
min_cuda = "13.0"
''',
            )
            _argv, context = templates.apply_template_profile(
                ["5090", "--template", "minimax"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            self.assertEqual(cuda_profile.template_min_cuda(context), "13.0")

    def test_directory_profile_inherits_default_min_cuda(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(
                td,
                '''
version = 2
[defaults]
min_cuda = "13.0"
''',
            )
            self.write_template(
                td,
                "minimax",
                'image = "markwelshboy/comfyui-minimax:test"\n',
            )
            _argv, context = templates.apply_template_profile(
                ["5090", "--template", "minimax"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            self.assertEqual(cuda_profile.template_min_cuda(context), "13.0")

    def test_inline_remote_profile_supports_min_cuda(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(
                td,
                '''
version = 2
[templates.remote-minimax]
id = "template123"
min_cuda = "13.1"
''',
            )
            _argv, context = templates.apply_template_profile(
                ["5090", "--template", "remote-minimax"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            self.assertEqual(cuda_profile.template_min_cuda(context), "13.1")

    def test_template_cuda_overrides_environment_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(td, "version = 2\n")
            self.write_template(
                td,
                "minimax",
                '''
image = "markwelshboy/comfyui-minimax:test"
min_cuda = "13.0"
''',
            )
            _argv, context = templates.apply_template_profile(
                ["5090", "--template", "minimax"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            got = cuda_profile.apply_template_cuda(
                ["5090", "--template", "minimax"],
                ["5090", "--template", "minimax", "--cuda-min", "12.8"],
                context,
                {"RENT_POD_CUDA_MIN": "12.8"},
            )
        self.assertEqual(got[-2:], ["--cuda-min", "13.0"])
        self.assertNotIn("12.8", got)

    def test_explicit_cli_cuda_overrides_template(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(td, "version = 2\n")
            self.write_template(
                td,
                "minimax",
                '''
image = "markwelshboy/comfyui-minimax:test"
min_cuda = "13.0"
''',
            )
            _argv, context = templates.apply_template_profile(
                ["5090", "--template", "minimax", "--cuda-min", "13.2"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            effective = ["5090", "--template", "minimax", "--cuda-min", "13.2"]
            got = cuda_profile.apply_template_cuda(
                ["5090", "--template", "minimax", "--cuda-min", "13.2"],
                effective,
                context,
                {"RENT_POD_CUDA_MIN": "12.8"},
            )
        self.assertEqual(got, effective)

    def test_without_template_cuda_environment_path_is_preserved(self):
        context = templates.TemplateContext(
            requested="raw-template",
            template_id="raw-template",
            profile_name=None,
            description="",
            env={},
        )
        effective = ["4090", "--template", "raw-template", "--cuda-min", "12.8"]
        got = cuda_profile.apply_template_cuda(
            ["4090", "--template", "raw-template"],
            effective,
            context,
            {"RENT_POD_CUDA_MIN": "12.8"},
        )
        self.assertEqual(got, effective)

    def test_invalid_template_cuda_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self.write_config(td, "version = 2\n")
            self.write_template(
                td,
                "bad",
                '''
image = "ubuntu:latest"
min_cuda = "thirteen"
''',
            )
            _argv, context = templates.apply_template_profile(
                ["4090", "--template", "bad"],
                {"RENT_POD_TEMPLATES_FILE": str(cfg)},
            )
            with self.assertRaises(ValueError):
                cuda_profile.template_min_cuda(context)


if __name__ == "__main__":
    unittest.main()
