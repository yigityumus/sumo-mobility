from __future__ import annotations

from collections import Counter
import random
import unittest

from sumo.scenario.demand.generate import (
    _pedestrian_origin_sequence,
    _vehicle_origin_sequence,
)


class PedestrianOriginSequenceTests(unittest.TestCase):
    def test_exact_source_counts_are_preserved(self) -> None:
        origins = [
            {"id": "home-1", "mode": "residential"},
            {"id": "home-2", "mode": "residential"},
            {"id": "station", "mode": "public_transport"},
        ]

        sequence = _pedestrian_origin_sequence(
            10,
            origins,
            {"residential": 4, "public_transport": 6, "parked_cars": 3},
            random.Random(42),
        )

        self.assertEqual(Counter(item["mode"] for item in sequence), {
            "residential": 4,
            "public_transport": 6,
        })

    def test_requested_source_requires_a_resolved_origin(self) -> None:
        with self.assertRaisesRegex(ValueError, "no resolved"):
            _pedestrian_origin_sequence(
                2,
                [{"id": "station", "mode": "public_transport"}],
                {"residential": 1, "public_transport": 1},
                random.Random(42),
            )


class VehicleOriginSequenceTests(unittest.TestCase):
    def test_exact_origin_counts_are_preserved_and_spread_across_departures(self) -> None:
        origins = [
            {"id": "north", "vehicle_count": 6},
            {"id": "south", "vehicle_count": 2},
        ]

        sequence = _vehicle_origin_sequence(8, origins)

        self.assertEqual(Counter(item["id"] for item in sequence), {
            "north": 6,
            "south": 2,
        })
        self.assertEqual([item["id"] for item in sequence], [
            "north", "north", "south", "north", "north", "north", "south", "north",
        ])

    def test_origin_counts_must_match_vehicle_demand(self) -> None:
        with self.assertRaisesRegex(ValueError, "must add up"):
            _vehicle_origin_sequence(3, [
                {"id": "north", "vehicle_count": 1},
                {"id": "south", "vehicle_count": 1},
            ])


if __name__ == "__main__":
    unittest.main()
