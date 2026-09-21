from __future__ import annotations

import unittest

from sumo.scenario.detectors.generate import (
    _directional_vehicle_cross_sections,
    _pedestrian_zones,
)


class PedestrianZoneTests(unittest.TestCase):
    def test_reversed_markers_create_one_normalized_bidirectional_zone(self) -> None:
        zones = _pedestrian_zones(
            [{
                "lane_id": "sidewalk_0",
                "edge_id": "sidewalk",
                "lane_index": 0,
                "position_metres": 32.864,
            }],
            [{
                "lane_id": "sidewalk_0",
                "edge_id": "sidewalk",
                "lane_index": 0,
                "position_metres": 3.952,
            }],
        )

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["start_position_metres"], 3.952)
        self.assertEqual(zones[0]["end_position_metres"], 32.864)

    def test_only_lanes_selected_at_both_markers_become_zones(self) -> None:
        entries = [
            {"lane_id": "shared_0", "position_metres": 2, "lane_index": 0},
            {"lane_id": "entry_only_0", "position_metres": 2, "lane_index": 0},
        ]
        exits = [
            {"lane_id": "shared_0", "position_metres": 8, "lane_index": 0},
            {"lane_id": "exit_only_0", "position_metres": 8, "lane_index": 0},
        ]

        self.assertEqual(
            [zone["lane_id"] for zone in _pedestrian_zones(entries, exits)],
            ["shared_0"],
        )


class DirectionalVehicleCrossSectionTests(unittest.TestCase):
    def test_two_way_same_edge_boundaries_are_oriented_per_lane(self) -> None:
        first = [
            {"lane_id": "eastbound", "position_metres": 10},
            {"lane_id": "westbound", "position_metres": 40},
        ]
        second = [
            {"lane_id": "eastbound", "position_metres": 40},
            {"lane_id": "westbound", "position_metres": 10},
        ]

        entries, exits = _directional_vehicle_cross_sections(first, second)

        self.assertEqual(
            {item["lane_id"]: item["position_metres"] for item in entries},
            {"eastbound": 10, "westbound": 10},
        )
        self.assertEqual(
            {item["lane_id"]: item["position_metres"] for item in exits},
            {"eastbound": 40, "westbound": 40},
        )

    def test_distinct_entry_and_exit_lanes_keep_explicit_roles(self) -> None:
        first = [{"lane_id": "incoming", "position_metres": 20}]
        second = [{"lane_id": "outgoing", "position_metres": 5}]

        entries, exits = _directional_vehicle_cross_sections(first, second)

        self.assertEqual(entries, first)
        self.assertEqual(exits, second)


if __name__ == "__main__":
    unittest.main()
