# File Chain (see DEVELOPER.md):
# Doc Version: v1.7.1
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
from ipaddress import IPv4Interface
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position
from topogen.models import TopogenInterface, TopogenNode  # pylint: disable=wrong-import-position
from topogen.nac import (  # pylint: disable=wrong-import-position
    _select_host,
    build_canonical_nac_model,
    write_devices_yaml,
    write_nac_tree,
    write_terraform_tfvars_json,
)


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
            devices_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "devices.yaml"
            metadata_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac_metadata.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertTrue(tfvars_json.exists())
            self.assertTrue(inventory_yaml.exists())
            self.assertTrue(group_all_yaml.exists())
            self.assertTrue(host_vars_yaml.exists())
            self.assertTrue(devices_yaml.exists())
            self.assertTrue(metadata_yaml.exists())

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

            devices_doc = yaml.safe_load(devices_yaml.read_text(encoding="utf-8"))
            self.assertIn("devices", devices_doc)
            self.assertEqual(len(devices_doc["devices"]), 1)
            dev = devices_doc["devices"][0]
            for key in ("name", "hostname", "platform", "role", "mgmt_ip"):
                self.assertIn(key, dev)

            meta = yaml.safe_load(metadata_yaml.read_text(encoding="utf-8"))
            for key in (
                "schema",
                "schema_version",
                "canonical_root",
                "generator",
                "ticket_ref",
                "generated_artifacts",
            ):
                self.assertIn(key, meta)

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
            devices_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "devices.yaml"
            metadata_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac_metadata.yaml"
            nested_bad = Path(tmp) / "out" / "iosv-test" / "iosv-test" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertTrue(tfvars_json.exists())
            self.assertTrue(inventory_yaml.exists())
            self.assertTrue(group_all_yaml.exists())
            self.assertTrue(host_vars_yaml.exists())
            self.assertTrue(devices_yaml.exists())
            self.assertTrue(metadata_yaml.exists())
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
            devices_a = devices_yaml.read_text(encoding="utf-8")
            devices_b = devices_yaml.read_text(encoding="utf-8")
            self.assertEqual(devices_a, devices_b)
            meta_a = metadata_yaml.read_text(encoding="utf-8")
            meta_b = metadata_yaml.read_text(encoding="utf-8")
            self.assertEqual(meta_a, meta_b)

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
            nac_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac.yaml"
            nac = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            self.assertEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], nac["iosxe"]["devices"][0]["host"])
            self.assertNotEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], "10.0.0.1")

    def test_devices_yaml_mgmt_ip_uses_host_ip_for_cidr(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = {
                "iosxe": {
                    "devices": [
                        {
                            "name": "iosv-01",
                            "hostname": "iosv-01",
                            "platform": "iosxe",
                            "role": "router",
                            "mgmt": {"ipv4": "10.254.0.11/24"},
                        }
                    ]
                }
            }
            out_path = Path(tmp) / "devices.yaml"
            write_devices_yaml(model, out_path, overwrite=True)
            devices_doc = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            self.assertEqual(devices_doc["devices"][0]["mgmt_ip"], "10.254.0.11")

    def test_missing_interfaces_emits_empty_list_without_crash(self):
        node = TopogenNode(hostname="r1", loopback=None, interfaces=[])
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="x",
            mode="simple",
        )
        device = model["iosxe"]["devices"][0]
        self.assertEqual(device["interfaces"], [])

    def test_missing_loopback_uses_deterministic_empty_fallbacks(self):
        node = TopogenNode(hostname="r1", loopback=None, interfaces=[])
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="x",
            mode="simple",
        )
        device = model["iosxe"]["devices"][0]
        self.assertEqual(device["mgmt"]["ipv4"], "")
        self.assertEqual(device["loopbacks"], [])

    def test_select_host_uses_slot_zero_data_without_mgmt(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                TopogenInterface(address=IPv4Interface("172.16.0.10/30"), slot=1),
            ],
        )
        self.assertEqual(_select_host(node, SimpleNamespace(enable_mgmt=False)), "172.16.0.6")

    def test_select_host_uses_oob_mgmt_when_enabled(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                TopogenInterface(
                    address=IPv4Interface("10.254.0.1/16"),
                    vrf="Mgmt-vrf",
                    description="OOB Management",
                    slot=5,
                ),
            ],
        )
        self.assertEqual(_select_host(node, SimpleNamespace(enable_mgmt=True)), "10.254.0.1")

    def test_select_host_has_no_loopback_fallback(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[],
        )
        self.assertEqual(_select_host(node, SimpleNamespace(enable_mgmt=False)), "")

    def test_vrf_mapping_emits_forwarding_and_vrf_definition(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), vrf="tenant", slot=1),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="flat-pair",
        )
        config = model["iosxe"]["devices"][0]["configuration"]
        self.assertEqual(config["interfaces"]["ethernets"][0]["vrf_forwarding"], "tenant")
        self.assertEqual(config["vrfs"], [{"name": "tenant"}])

    def test_global_table_omits_vrf_keys(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="simple",
        )
        config = model["iosxe"]["devices"][0]["configuration"]
        self.assertNotIn("vrfs", config)
        self.assertNotIn("vrf_forwarding", config["interfaces"]["ethernets"][0])

    def test_flat_pair_cli_vrf_reaches_nac_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-pair-vrf.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--vrf",
                    "--pair-vrf",
                    "tenant",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "flat-pair-vrf" / "nac" / "nac.yaml"
            devices = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"]
            r1_config = devices[0]["configuration"]
            self.assertEqual(r1_config["vrfs"], [{"name": "tenant"}])
            self.assertTrue(
                any(
                    iface.get("vrf_forwarding") == "tenant"
                    for iface in r1_config["interfaces"]["ethernets"]
                )
            )

    def test_mgmt_cli_emits_mgmt_host_interface_and_vrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "mgmt-simple.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--mgmt",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "mgmt-simple" / "nac" / "nac.yaml"
            inventory_yaml = Path(tmp) / "out" / "mgmt-simple" / "nac" / "inventory.yaml"
            device = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertEqual(device["host"], "10.254.0.1")
            self.assertEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], "10.254.0.1")
            self.assertEqual(device["configuration"]["vrfs"], [{"name": "Mgmt-vrf"}])
            mgmt_iface = next(
                iface
                for iface in device["configuration"]["interfaces"]["ethernets"]
                if iface.get("description") == "OOB Management"
            )
            self.assertEqual(mgmt_iface["vrf_forwarding"], "Mgmt-vrf")

    def test_mgmt_global_vrf_omits_vrf_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "mgmt-global.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--mgmt",
                    "--mgmt-vrf",
                    "global",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "mgmt-global" / "nac" / "nac.yaml"
            device = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            config = device["configuration"]
            self.assertEqual(device["host"], "10.254.0.1")
            self.assertNotIn("vrfs", config)
            mgmt_iface = next(
                iface
                for iface in config["interfaces"]["ethernets"]
                if iface.get("description") == "OOB Management"
            )
            self.assertNotIn("vrf_forwarding", mgmt_iface)

    def test_name_and_hostname_sources_are_distinct(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="simple",
        )
        device = model["iosxe"]["devices"][0]
        self.assertEqual(device["name"], "iosv-01")
        self.assertEqual(device["configuration"]["system"]["hostname"], "R1")

    def test_optional_interface_keys_absent_writer_still_succeeds(self):
        class PartialIface:
            pass

        iface = PartialIface()
        node = TopogenNode(hostname="r1", loopback=None, interfaces=[iface])
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="x",
            mode="simple",
        )
        iface_entry = model["iosxe"]["devices"][0]["interfaces"][0]
        self.assertEqual(iface_entry["slot"], 0)
        self.assertEqual(iface_entry["name"], "GigabitEthernet0/0")
        self.assertNotIn("ipv4", iface_entry)
        self.assertNotIn("description", iface_entry)

    def test_missing_metadata_sections_in_model_do_not_crash_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = {
                "iosxe": {
                    "devices": [
                        {
                            "name": "iosv-01",
                            "hostname": "iosv-01",
                            "platform": "iosxe",
                            "role": "router",
                        }
                    ]
                }
            }
            out_path = Path(tmp) / "devices.yaml"
            write_devices_yaml(model, out_path, overwrite=True)
            devices_doc = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            self.assertEqual(devices_doc["devices"][0]["mgmt_ip"], "")

    def test_rerun_stability_with_fallback_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(hostname="r1", loopback=None, interfaces=[{"description": "uplink"}])
            nac_root = Path(tmp) / "nac"
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="x",
                mode="simple",
                overwrite=True,
            )
            first = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="x",
                mode="simple",
                overwrite=True,
            )
            second = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_two_router_flat_nac_outputs_include_both_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat" / "nac"
            nac_yaml = nac_root / "nac.yaml"
            devices_yaml = nac_root / "devices.yaml"
            tfvars_json = nac_root / "terraform.tfvars.json"
            inventory_yaml = nac_root / "inventory.yaml"
            group_all_yaml = nac_root / "group_vars" / "all.yaml"
            host_vars_1 = nac_root / "host_vars" / "iosv-01.yaml"
            host_vars_2 = nac_root / "host_vars" / "iosv-02.yaml"
            metadata_yaml = nac_root / "nac_metadata.yaml"
            for path in (
                nac_yaml,
                devices_yaml,
                tfvars_json,
                inventory_yaml,
                group_all_yaml,
                host_vars_1,
                host_vars_2,
                metadata_yaml,
            ):
                self.assertTrue(path.exists())

            canonical = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            self.assertEqual(len(canonical["iosxe"]["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in canonical["iosxe"]["devices"]],
                ["iosv-01", "iosv-02"],
            )

            devices_doc = yaml.safe_load(devices_yaml.read_text(encoding="utf-8"))
            self.assertEqual(len(devices_doc["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in devices_doc["devices"]],
                ["iosv-01", "iosv-02"],
            )

            tfvars = yaml.safe_load(tfvars_json.read_text(encoding="utf-8"))
            self.assertEqual(len(tfvars["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in tfvars["devices"]],
                ["iosv-01", "iosv-02"],
            )

            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertIn("iosv-01", inv["all"]["hosts"])
            self.assertIn("iosv-02", inv["all"]["hosts"])
            self.assertIn("ansible_host", inv["all"]["hosts"]["iosv-01"])
            self.assertIn("ansible_host", inv["all"]["hosts"]["iosv-02"])

            grp = yaml.safe_load(group_all_yaml.read_text(encoding="utf-8"))
            self.assertEqual(grp["nac_device_count"], 2)

            metadata = yaml.safe_load(metadata_yaml.read_text(encoding="utf-8"))
            self.assertEqual(metadata["device_count"], 2)
            self.assertIn("host_vars/iosv-01.yaml", metadata["generated_artifacts"])
            self.assertIn("host_vars/iosv-02.yaml", metadata["generated_artifacts"])

    def test_two_router_flat_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat.yaml"
            argv = [
                "2",
                "--mode",
                "flat",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat" / "nac"
            nested_bad = Path(tmp) / "out" / "two-router-flat" / "two-router-flat" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())

            files = [
                nac_root / "nac.yaml",
                nac_root / "devices.yaml",
                nac_root / "terraform.tfvars.json",
                nac_root / "inventory.yaml",
                nac_root / "group_vars" / "all.yaml",
                nac_root / "host_vars" / "iosv-01.yaml",
                nac_root / "host_vars" / "iosv-02.yaml",
                nac_root / "nac_metadata.yaml",
            ]
            for path in files:
                self.assertTrue(path.exists())
                a = path.read_text(encoding="utf-8")
                b = path.read_text(encoding="utf-8")
                self.assertEqual(a, b)

    def test_two_router_simple_nac_outputs_include_both_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-simple.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_root = Path(tmp) / "out" / "two-router-simple" / "nac"
            host_vars_1 = nac_root / "host_vars" / "iosv-01.yaml"
            host_vars_2 = nac_root / "host_vars" / "iosv-02.yaml"
            self.assertTrue((nac_root / "nac.yaml").exists())
            self.assertTrue((nac_root / "devices.yaml").exists())
            self.assertTrue((nac_root / "inventory.yaml").exists())
            self.assertTrue(host_vars_1.exists())
            self.assertTrue(host_vars_2.exists())

            canonical = yaml.safe_load((nac_root / "nac.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(canonical["iosxe"]["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in canonical["iosxe"]["devices"]],
                ["iosv-01", "iosv-02"],
            )

            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual(metadata["device_count"], 2)

    def test_two_router_simple_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-simple.yaml"
            argv = [
                "2",
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
            nac_root = Path(tmp) / "out" / "two-router-simple" / "nac"
            nested_bad = Path(tmp) / "out" / "two-router-simple" / "two-router-simple" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())
            data_a = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            data_b = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            self.assertEqual(data_a, data_b)

    def test_two_router_flat_pair_nac_outputs_include_both_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat-pair.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat-pair" / "nac"
            self.assertTrue((nac_root / "nac.yaml").exists())
            self.assertTrue((nac_root / "devices.yaml").exists())
            self.assertTrue((nac_root / "inventory.yaml").exists())
            self.assertTrue((nac_root / "host_vars" / "iosv-01.yaml").exists())
            self.assertTrue((nac_root / "host_vars" / "iosv-02.yaml").exists())

            canonical = yaml.safe_load((nac_root / "nac.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(canonical["iosxe"]["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in canonical["iosxe"]["devices"]],
                ["iosv-01", "iosv-02"],
            )

            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual(metadata["device_count"], 2)

    def test_two_router_flat_pair_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat-pair.yaml"
            argv = [
                "2",
                "--mode",
                "flat-pair",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat-pair" / "nac"
            nested_bad = Path(tmp) / "out" / "two-router-flat-pair" / "two-router-flat-pair" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())
            data_a = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            data_b = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            self.assertEqual(data_a, data_b)


if __name__ == "__main__":
    unittest.main()
