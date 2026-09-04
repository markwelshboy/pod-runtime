import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

MODULE = BIN / "rent_pod_gpu_aliases.py"
spec = importlib.util.spec_from_file_location("rent_pod_gpu_aliases", MODULE)
gpus = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = gpus
spec.loader.exec_module(gpus)


class RentPodGpuAliasTests(unittest.TestCase):
    def write_config(self, root: str, text: str) -> Path:
        path = Path(root) / "gpu-aliases.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_default_config_path(self):
        self.assertEqual(
            gpus.config_path({"HOME": "/tmp/home"}),
            Path("/tmp/home/.config/rentpod/gpu-aliases.toml"),
        )

    def test_xdg_config_path(self):
        self.assertEqual(
            gpus.config_path({"XDG_CONFIG_HOME": "/tmp/xdg"}),
            Path("/tmp/xdg/rentpod/gpu-aliases.toml"),
        )

    def test_legacy_config_root_is_used_when_it_already_exists(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            legacy = home / ".config" / "rent-pod"
            legacy.mkdir(parents=True)
            self.assertEqual(
                gpus.config_path({"HOME": str(home)}),
                legacy / "gpu-aliases.toml",
            )

    def test_loads_aliases_case_insensitively(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
[aliases]
pro6000 = "RTX PRO 6000"
A100 = "A100 PCIe"
''',
            )
            config = gpus.load_aliases({"RENT_POD_GPU_ALIASES_FILE": str(path)})
        self.assertTrue(config.file_exists)
        self.assertEqual(config.aliases["pro6000"], "RTX PRO 6000")
        self.assertEqual(config.aliases["a100"], "A100 PCIe")

    def test_invalid_alias_name_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
[aliases]
"bad alias" = "RTX PRO 6000"
''',
            )
            with self.assertRaises(ValueError):
                gpus.load_aliases({"RENT_POD_GPU_ALIASES_FILE": str(path)})

    def test_user_alias_resolves_live_display_name(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write_config(
                td,
                '''
[aliases]
pro6000 = "RTX PRO 6000"
''',
            )
            env = {"RENT_POD_GPU_ALIASES_FILE": str(path)}
            original = gpus.core.resolve_gpu
            try:
                with mock.patch.object(
                    gpus,
                    "graphql_gpu_types",
                    return_value=[
                        {
                            "id": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
                            "displayName": "RTX PRO 6000",
                        }
                    ],
                ) as lookup:
                    gpus.install_core_gpu_resolver("token", env)
                    self.assertEqual(
                        gpus.core.resolve_gpu("pro6000"),
                        "NVIDIA RTX PRO 6000 Blackwell Server Edition",
                    )
                    # The same live table is cached for subsequent resolutions.
                    self.assertEqual(
                        gpus.core.resolve_gpu("RTX PRO 6000"),
                        "NVIDIA RTX PRO 6000 Blackwell Server Edition",
                    )
                    lookup.assert_called_once_with("token")
            finally:
                gpus.core.resolve_gpu = original

    def test_exact_display_name_is_case_insensitive(self):
        original = gpus.core.resolve_gpu
        try:
            with mock.patch.object(
                gpus,
                "graphql_gpu_types",
                return_value=[{"id": "NVIDIA A100 80GB PCIe", "displayName": "A100 PCIe"}],
            ):
                gpus.install_core_gpu_resolver("token", {"RENT_POD_GPU_ALIASES_FILE": "/missing"})
                self.assertEqual(gpus.core.resolve_gpu("a100 pcie"), "NVIDIA A100 80GB PCIe")
        finally:
            gpus.core.resolve_gpu = original

    def test_builtin_alias_does_not_need_live_lookup(self):
        original = gpus.core.resolve_gpu
        try:
            with mock.patch.object(gpus, "graphql_gpu_types") as lookup:
                gpus.install_core_gpu_resolver("token", {"RENT_POD_GPU_ALIASES_FILE": "/missing"})
                self.assertEqual(gpus.core.resolve_gpu("4090"), "NVIDIA GeForce RTX 4090")
                lookup.assert_not_called()
        finally:
            gpus.core.resolve_gpu = original

    def test_unknown_value_preserves_raw_id_compatibility(self):
        original = gpus.core.resolve_gpu
        try:
            with mock.patch.object(gpus, "graphql_gpu_types", return_value=[]):
                gpus.install_core_gpu_resolver("token", {"RENT_POD_GPU_ALIASES_FILE": "/missing"})
                self.assertEqual(gpus.core.resolve_gpu("NVIDIA Future GPU"), "NVIDIA Future GPU")
        finally:
            gpus.core.resolve_gpu = original


if __name__ == "__main__":
    unittest.main()
