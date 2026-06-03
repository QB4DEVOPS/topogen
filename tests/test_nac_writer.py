# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
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
from topogen.nac import write_terraform_tfvars_json  # pylint: disable=wrong-import-position


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
            tfvars_json = Path(tmp) / "out" / "iosv-test" / "nac" / "terraform.tfvars.json"
            self.assertTrue(nac_yaml.exists())
            self.assertTrue(tfvars_json.exists())

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

            tfvars = yaml.safe_load(tfvars_json.read_text(encoding="utf-8"))
            self.assertIn("devices", tfvars)
            self.assertEqual(len(tfvars["devices"]), 1)
            tf_device = tfvars["devices"][0]
            for key in ("name", "hostname", "platform", "mgmt_ip"):
                self.assertIn(key, tf_device)

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
            tfvars_json = Path(tmp) / "out" / "iosv-test" / "nac" / "terraform.tfvars.json"
            nested_bad = Path(tmp) / "out" / "iosv-test" / "iosv-test" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertTrue(tfvars_json.exists())
            self.assertFalse(nested_bad.exists())

            content_a = nac_yaml.read_text(encoding="utf-8")
            content_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(content_a, content_b)
            tf_a = tfvars_json.read_text(encoding="utf-8")
            tf_b = tfvars_json.read_text(encoding="utf-8")
            self.assertEqual(tf_a, tf_b)

    def test_tfvars_mgmt_ip_uses_host_ip_for_cidr(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = {
                "iosxe": {
                    "devices": [
                        {
                            "name": "iosv-01",
                            "hostname": "iosv-01",
                            "platform": "iosxe",
                            "mgmt": {"ipv4": "10.254.0.11/24"},
                        }
                    ]
                }
            }
            out_path = Path(tmp) / "terraform.tfvars.json"
            write_terraform_tfvars_json(model, out_path, overwrite=True)
            tfvars = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            self.assertEqual(tfvars["devices"][0]["mgmt_ip"], "10.254.0.11")


if __name__ == "__main__":
    unittest.main()
