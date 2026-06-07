"""Unit tests for scaled intent annotation placement."""

from __future__ import annotations

import unittest

from topogen.render import (
    INTENT_ANNOTATION_PADDING,
    _node_coords_from_offline_lines,
    _scaled_intent_annotation_xy,
)


class IntentAnnotationScalingTests(unittest.TestCase):
    def test_scaled_xy_down_only_no_x_padding(self) -> None:
        coords = [(0, 0), (600, 200), (600, 4000)]
        x1, y1 = _scaled_intent_annotation_xy(coords, padding=1500)
        self.assertEqual(x1, 600)
        self.assertEqual(y1, 4000 + INTENT_ANNOTATION_PADDING)

    def test_scaled_xy_empty_defaults_to_down_padding(self) -> None:
        self.assertEqual(
            _scaled_intent_annotation_xy([]),
            (0, INTENT_ANNOTATION_PADDING),
        )

    def test_node_coords_from_offline_lines_ignores_links(self) -> None:
        lines = [
            "lab:",
            "  title: t",
            "nodes:",
            "  - id: n0",
            "    x: 10",
            "    y: 20",
            "  - id: n1",
            "    x: 600",
            "    y: 3800",
            "links:",
            "  - id: l0",
        ]
        self.assertEqual(
            _node_coords_from_offline_lines(lines),
            [(10, 20), (600, 3800)],
        )


if __name__ == "__main__":
    unittest.main()
