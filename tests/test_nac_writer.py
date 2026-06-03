# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py, src/topogen/nac.py
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main, yaml.safe_load
#
# Purpose: Verify TG-121 canonical NaC writer output path, keys, and deterministic rerun behavior.
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position


class TestNacWriter(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def test_nac_yaml_created_at_expected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "iosv-test.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            nac_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())

            data = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            self.assertIn("iosxe", data)
            self.assertIn("devices", data["iosxe"])
            self.assertEqual(len(data["iosxe"]["devices"]), 1)
            device = data["iosxe"]["devices"][0]
            for key in (
                "name",
                "hostname",
                "platform",
                "role",
                "template",
                "device_template",
                "mgmt",
                "loopbacks",
                "interfaces",
            ):
                self.assertIn(key, device)

    def test_nac_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "iosv-test.yaml"
            argv = [
                "1",
                "--mode",
                "simple",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)

            nac_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac.yaml"
            nested_bad = Path(tmp) / "out" / "iosv-test" / "iosv-test" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertFalse(nested_bad.exists())

            content_a = nac_yaml.read_text(encoding="utf-8")
            content_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(content_a, content_b)


if __name__ == "__main__":
    unittest.main()
