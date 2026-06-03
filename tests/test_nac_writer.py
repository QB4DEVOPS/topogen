# File Chain (see DEVELOPER.md):
# Doc Version: v1.2.0
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
            inventory_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "inventory.yaml"
            group_all_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "group_vars" / "all.yaml"
            host_vars_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "host_vars" / "iosv-01.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertTrue(tfvars_json.exists())
            self.assertTrue(inventory_yaml.exists())
            self.assertTrue(group_all_yaml.exists())
            self.assertTrue(host_vars_yaml.exists())

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

            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertIn("all", inv)
            self.assertIn("hosts", inv["all"])
            self.assertIn("iosv-01", inv["all"]["hosts"])
            self.assertIn("ansible_host", inv["all"]["hosts"]["iosv-01"])
            self.assertIn("platform", inv["all"]["hosts"]["iosv-01"])

            grp = yaml.safe_load(group_all_yaml.read_text(encoding="utf-8"))
            self.assertIn("nac_platform", grp)
            self.assertIn("nac_device_count", grp)

            host_vars = yaml.safe_load(host_vars_yaml.read_text(encoding="utf-8"))
            for key in ("hostname", "role", "template", "device_template", "loopbacks", "interfaces"):
                self.assertIn(key, host_vars)

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
            inventory_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "inventory.yaml"
            group_all_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "group_vars" / "all.yaml"
            host_vars_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "host_vars" / "iosv-01.yaml"
            nested_bad = Path(tmp) / "out" / "iosv-test" / "iosv-test" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertTrue(tfvars_json.exists())
            self.assertTrue(inventory_yaml.exists())
            self.assertTrue(group_all_yaml.exists())
            self.assertTrue(host_vars_yaml.exists())
            self.assertFalse(nested_bad.exists())

            content_a = nac_yaml.read_text(encoding="utf-8")
            content_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(content_a, content_b)
            tf_a = tfvars_json.read_text(encoding="utf-8")
            tf_b = tfvars_json.read_text(encoding="utf-8")
            self.assertEqual(tf_a, tf_b)
            inv_a = inventory_yaml.read_text(encoding="utf-8")
            inv_b = inventory_yaml.read_text(encoding="utf-8")
            self.assertEqual(inv_a, inv_b)
            grp_a = group_all_yaml.read_text(encoding="utf-8")
            grp_b = group_all_yaml.read_text(encoding="utf-8")
            self.assertEqual(grp_a, grp_b)
            hv_a = host_vars_yaml.read_text(encoding="utf-8")
            hv_b = host_vars_yaml.read_text(encoding="utf-8")
            self.assertEqual(hv_a, hv_b)

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

    def test_inventory_ansible_host_uses_host_ip_for_cidr(self):
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
            inventory_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "inventory.yaml"
            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
