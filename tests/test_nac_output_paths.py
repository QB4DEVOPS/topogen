# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/render.py path resolver
# - Writes to: None (test-only)
# - Calls into: topogen.render.resolve_offline_output_paths
#
# Purpose: Verify deterministic NaC offline output path/layout resolution (TG-137).
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.render import resolve_offline_output_paths  # pylint: disable=wrong-import-position


class TestNacOutputPaths(unittest.TestCase):
    def test_non_nac_path_unchanged(self):
        yaml_target, nac_root = resolve_offline_output_paths(
            "out/iosv-test.yaml", nac_enabled=False
        )
        self.assertEqual(yaml_target.as_posix(), "out/iosv-test.yaml")
        self.assertIsNone(nac_root)

    def test_nac_path_transforms_to_layout(self):
        yaml_target, nac_root = resolve_offline_output_paths(
            "out/iosv-test.yaml", nac_enabled=True
        )
        self.assertEqual(yaml_target.as_posix(), "out/iosv-test/iosv-test.yaml")
        self.assertIsNotNone(nac_root)
        self.assertEqual(nac_root.as_posix(), "out/iosv-test/nac")

    def test_nac_root_is_ansible_artifact_home(self):
        yaml_target, nac_root = resolve_offline_output_paths(
            "out/iosv-test.yaml", nac_enabled=True
        )
        self.assertEqual(yaml_target.as_posix(), "out/iosv-test/iosv-test.yaml")
        self.assertIsNotNone(nac_root)
        ansible_artifacts = (
            "inventory.yaml",
            "ansible.cfg",
            "group_vars/all.yaml",
            "host_vars/iosv-01.yaml",
            "verify_reachability.yaml",
        )
        for artifact in ansible_artifacts:
            self.assertEqual((nac_root / artifact).as_posix(), f"out/iosv-test/nac/{artifact}")

    def test_nac_rerun_does_not_double_nest(self):
        yaml_target, nac_root = resolve_offline_output_paths(
            "out/iosv-test/iosv-test.yaml", nac_enabled=True
        )
        self.assertEqual(yaml_target.as_posix(), "out/iosv-test/iosv-test.yaml")
        self.assertIsNotNone(nac_root)
        self.assertEqual(nac_root.as_posix(), "out/iosv-test/nac")


if __name__ == "__main__":
    unittest.main()
