# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py offline renderer
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main
#
# Purpose: End-to-end regression for TG-142 render.py -> nac.py offline wiring.
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position


class TestNacRenderEndToEnd(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def _assert_full_nac_tree(self, nac_root: Path, host_vars: tuple[str, ...]):
        expected_artifacts = [
            "nac.yaml",
            "main.tf",
            "versions.tf",
            "terraform.tfvars.example",
            ".gitignore",
            "inventory.yaml",
            "ansible.cfg",
            "group_vars/all.yaml",
            "verify_reachability.yaml",
            "devices.yaml",
            "nac_metadata.yaml",
        ]
        expected_artifacts.extend(f"host_vars/{host_var}" for host_var in host_vars)
        for artifact in expected_artifacts:
            self.assertTrue((nac_root / artifact).exists(), artifact)

    def test_flat_and_flat_pair_nac_runs_emit_complete_tree(self):
        for mode in ("flat", "flat-pair"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / "out" / f"{mode}.yaml"
                rc = self._run_main(
                    [
                        "2",
                        "--mode",
                        mode,
                        "--offline-yaml",
                        str(out_file),
                        "--nac",
                        "--overwrite",
                    ]
                )
                self.assertEqual(rc, 0)

                lab_root = Path(tmp) / "out" / mode
                self.assertTrue((lab_root / f"{mode}.yaml").exists())
                self._assert_full_nac_tree(
                    lab_root / "nac",
                    ("iosv-01.yaml", "iosv-02.yaml"),
                )

    def test_flat_and_flat_pair_non_nac_runs_do_not_emit_nac_tree(self):
        for mode in ("flat", "flat-pair"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / "out" / f"{mode}.yaml"
                rc = self._run_main(
                    [
                        "2",
                        "--mode",
                        mode,
                        "--offline-yaml",
                        str(out_file),
                        "--overwrite",
                    ]
                )
                self.assertEqual(rc, 0)

                self.assertTrue(out_file.exists())
                self.assertFalse((Path(tmp) / "out" / mode / "nac").exists())
                self.assertFalse((Path(tmp) / "out" / "nac").exists())


if __name__ == "__main__":
    unittest.main()
