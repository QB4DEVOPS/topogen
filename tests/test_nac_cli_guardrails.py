# File Chain (see DEVELOPER.md):
# Doc Version: v1.4.0
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py parser and validation helpers
# - Writes to: Temporary test directories only
# - Calls into: topogen.main (main, create_argparser, validate_nodes_for_mode, validate_nac_mvp_guardrails)
#
# Purpose: Validate NaC CLI guardrails and preserve non-NaC node behavior.
# Blast Radius: Test-only; no runtime behavior changes.

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import (  # pylint: disable=wrong-import-position
    create_argparser,
    main,
    normalize_template_inputs,
    validate_nac_mvp_guardrails,
    validate_nodes_for_mode,
)


class TestNacCliGuardrails(unittest.TestCase):
    def setUp(self):
        self.parser = create_argparser()

    def _parse_and_validate(self, argv):
        args = self.parser.parse_args(argv)
        normalize_template_inputs(args)
        validate_nodes_for_mode(args, self.parser)
        validate_nac_mvp_guardrails(args, self.parser)
        return args

    def _run_main_exit(self, argv):
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["topogen", *argv]), redirect_stderr(stderr):
            try:
                return main(), stderr.getvalue()
            except SystemExit as exc:
                return exc.code, stderr.getvalue()

    def test_valid_nac_simple_one_router_command_shape(self):
        args = self._parse_and_validate(
            ["1", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 1)
        self.assertEqual(args.mode, "simple")
        self.assertEqual(args.offline_yaml, "out/iosv-test.yaml")

    def test_valid_nac_flat_one_router_command_shape(self):
        args = self._parse_and_validate(
            ["1", "--mode", "flat", "--offline-yaml", "out/one-router-flat.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 1)
        self.assertEqual(args.mode, "flat")
        self.assertEqual(args.offline_yaml, "out/one-router-flat.yaml")

    def test_valid_nac_three_router_nx_command_shape(self):
        args = self._parse_and_validate(
            ["3", "--mode", "nx", "--offline-yaml", "out/three-router-nx.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 3)
        self.assertEqual(args.mode, "nx")
        self.assertEqual(args.offline_yaml, "out/three-router-nx.yaml")

    def test_valid_nac_three_router_simple_command_shape(self):
        args = self._parse_and_validate(
            ["3", "--mode", "simple", "--offline-yaml", "out/three-router-simple.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 3)
        self.assertEqual(args.mode, "simple")
        self.assertEqual(args.offline_yaml, "out/three-router-simple.yaml")

    def test_valid_nac_four_router_flat_pair_command_shape(self):
        args = self._parse_and_validate(
            ["4", "--mode", "flat-pair", "--offline-yaml", "out/four-router-flat-pair.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 4)
        self.assertEqual(args.mode, "flat-pair")
        self.assertEqual(args.offline_yaml, "out/four-router-flat-pair.yaml")

    def test_valid_nac_dmvpn_command_shape(self):
        args = self._parse_and_validate(
            ["3", "--mode", "dmvpn", "--offline-yaml", "out/three-router-dmvpn.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 3)
        self.assertEqual(args.mode, "dmvpn")
        self.assertEqual(args.offline_yaml, "out/three-router-dmvpn.yaml")

    def test_nac_requires_offline_yaml(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(["1", "--mode", "simple", "--nac"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--nac requires --offline-yaml FILE", stderr.getvalue())

    def test_nac_without_offline_yaml_exits_nonzero_and_creates_no_nac(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, stderr = self._run_main_exit(["1", "--mode", "simple", "--nac"])
            self.assertNotEqual(code, 0)
            self.assertIn("--nac requires --offline-yaml FILE", stderr)
            self.assertFalse((Path(tmp) / "nac").exists())

    def test_nac_rejects_import_workflow_flags(self):
        cases = [
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--import", "--nac"],
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--import-yaml", "in.yaml", "--nac"],
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--up", "in.yaml", "--nac"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as cm:
                    with redirect_stderr(io.StringIO()) as stderr:
                        self._parse_and_validate(argv)
                self.assertNotEqual(cm.exception.code, 0)
                self.assertIn("import workflow flags are not supported", stderr.getvalue())

    def test_nac_rejects_online_yaml_export(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "simple",
                        "--yaml",
                        "online.yaml",
                        "--offline-yaml",
                        "out.yaml",
                        "--nac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("use --offline-yaml instead of --yaml online export", stderr.getvalue())

    def test_nac_rejects_unsupported_platform_family(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "1",
                        "--mode",
                        "simple",
                        "--offline-yaml",
                        "out/iosv-test.yaml",
                        "--device-template",
                        "iol",
                        "--nac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("R1", stderr.getvalue())
        self.assertIn("IOL is not in the supported IOS-XE template set", stderr.getvalue())

    def test_nac_rejects_non_iosxe_node_before_nac_tree_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "lxc-test.yaml"
            code, stderr = self._run_main_exit(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--device-template",
                    "lxc",
                    "--nac",
                ]
            )
            self.assertNotEqual(code, 0)
            self.assertIn("R1", stderr)
            self.assertIn("FRR/LXC/Linux containers are not IOS-XE devices", stderr)
            self.assertFalse((Path(tmp) / "out" / "lxc-test" / "nac").exists())

    def test_valid_all_iosxe_nac_cli_succeeds_with_composed_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-pair-csr-mgmt-vrf.yaml"
            code, stderr = self._run_main_exit(
                [
                    "2",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--device-template",
                    "csr1000v",
                    "--mgmt",
                    "--vrf",
                    "--pair-vrf",
                    "tenant-a",
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(code, 0, stderr)
            nac_yaml = Path(tmp) / "out" / "flat-pair-csr-mgmt-vrf" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())

    def test_non_nac_still_rejects_one_node(self):
        with self.assertRaises(SystemExit):
            self._parse_and_validate(["1", "--mode", "simple", "--offline-yaml", "out/non-nac.yaml"])

    def test_template_csr1000v_sets_device_template_for_nac(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat", "--template", "csr1000v", "--offline-yaml", "out/two-router-csr.yaml", "--nac"]
        )
        self.assertEqual(args.template, "csr1000v")
        self.assertEqual(args.dev_template, "csr1000v")

    def test_template_crsv_alias_normalizes_to_csr1000v(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat", "--template", "CRSv", "--offline-yaml", "out/two-router-csr.yaml", "--nac"]
        )
        self.assertEqual(args.template, "csr1000v")
        self.assertEqual(args.dev_template, "csr1000v")


if __name__ == "__main__":
    unittest.main()
