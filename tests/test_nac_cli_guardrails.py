# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py parser and validation helpers
# - Writes to: None (test-only)
# - Calls into: topogen.main (create_argparser, validate_nodes_for_mode, validate_nac_mvp_guardrails)
#
# Purpose: Validate TG-119 NaC CLI guardrails and preserve non-NaC node behavior.
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import (  # pylint: disable=wrong-import-position
    create_argparser,
    validate_nac_mvp_guardrails,
    validate_nodes_for_mode,
)


class TestNacCliGuardrails(unittest.TestCase):
    def setUp(self):
        self.parser = create_argparser()

    def _parse_and_validate(self, argv):
        args = self.parser.parse_args(argv)
        validate_nodes_for_mode(args, self.parser)
        validate_nac_mvp_guardrails(args, self.parser)
        return args

    def test_valid_nac_mvp_command_shape(self):
        args = self._parse_and_validate(
            ["1", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 1)
        self.assertEqual(args.mode, "simple")
        self.assertEqual(args.offline_yaml, "out/iosv-test.yaml")

    def test_valid_nac_two_router_flat_command_shape(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat", "--offline-yaml", "out/two-router-flat.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 2)
        self.assertEqual(args.mode, "flat")
        self.assertEqual(args.offline_yaml, "out/two-router-flat.yaml")

    def test_nac_requires_offline_yaml(self):
        with self.assertRaises(SystemExit):
            self._parse_and_validate(["1", "--mode", "simple", "--nac"])

    def test_nac_rejects_unsupported_mode_or_path(self):
        with self.assertRaises(SystemExit):
            self._parse_and_validate(
                ["1", "--mode", "flat", "--offline-yaml", "out/iosv-test.yaml", "--nac"]
            )
        with self.assertRaises(SystemExit):
            self._parse_and_validate(
                ["2", "--mode", "simple", "--offline-yaml", "out/two-router-simple.yaml", "--nac"]
            )

    def test_nac_rejects_unsupported_platform_family(self):
        with self.assertRaises(SystemExit):
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

    def test_non_nac_still_rejects_one_node(self):
        with self.assertRaises(SystemExit):
            self._parse_and_validate(["1", "--mode", "simple", "--offline-yaml", "out/non-nac.yaml"])


if __name__ == "__main__":
    unittest.main()
