from __future__ import annotations

import unittest

from sumo.parking_choice import rank_parking_candidates


NO_RANDOMNESS = {
    "stochastic_scale": 0,
    "knowledge_probability": 1,
}


class ParkingChoiceTests(unittest.TestCase):
    def test_large_lot_can_outweigh_a_small_walking_distance_penalty(self) -> None:
        ranked = rank_parking_candidates(
            "vehicle.1",
            [
                {
                    "parking_id": "small-near",
                    "distance_metres": 20,
                    "driving_distance_metres": 100,
                    "total_capacity": 16,
                },
                {
                    "parking_id": "large-slightly-farther",
                    "distance_metres": 60,
                    "driving_distance_metres": 120,
                    "total_capacity": 300,
                },
            ],
            config={
                **NO_RANDOMNESS,
                "weights": {
                    "drive_time": 0.2,
                    "walk_time": 0.2,
                    "capacity": 1.0,
                    "absolute_free_space": 1.0,
                    "relative_free_space": 0.0,
                },
            },
        )

        self.assertEqual(ranked[0]["parking_id"], "large-slightly-farther")

    def test_a_known_full_lot_is_not_selected(self) -> None:
        ranked = rank_parking_candidates(
            "vehicle.2",
            [
                {
                    "parking_id": "full",
                    "distance_metres": 10,
                    "drive_time_seconds": 10,
                    "total_capacity": 300,
                    "free_spaces": 0,
                    "occupancy_visible": True,
                },
                {
                    "parking_id": "available",
                    "distance_metres": 50,
                    "drive_time_seconds": 60,
                    "total_capacity": 40,
                    "free_spaces": 5,
                    "occupancy_visible": True,
                },
            ],
            config=NO_RANDOMNESS,
        )

        self.assertEqual([item["parking_id"] for item in ranked], ["available"])

    def test_unknown_full_lot_can_still_be_considered(self) -> None:
        ranked = rank_parking_candidates(
            "vehicle.3",
            [
                {
                    "parking_id": "unknown-full",
                    "distance_metres": 10,
                    "drive_time_seconds": 10,
                    "total_capacity": 100,
                    "free_spaces": 0,
                },
                {
                    "parking_id": "other",
                    "distance_metres": 50,
                    "drive_time_seconds": 60,
                    "total_capacity": 40,
                    "free_spaces": 5,
                },
            ],
            config={**NO_RANDOMNESS, "knowledge_probability": 0},
        )

        self.assertEqual(len(ranked), 2)
        unknown = next(
            item for item in ranked if item["parking_id"] == "unknown-full"
        )
        self.assertFalse(unknown["occupancy_known"])
        self.assertGreater(unknown["perceived_free_spaces"], 0)

    def test_random_utility_is_reproducible_for_a_run_seed(self) -> None:
        candidates = [
            {
                "parking_id": parking_id,
                "distance_metres": 50,
                "driving_distance_metres": 100,
                "total_capacity": 50,
            }
            for parking_id in ("a", "b", "c")
        ]

        first = rank_parking_candidates("vehicle.4", candidates, seed=71)
        second = rank_parking_candidates("vehicle.4", candidates, seed=71)

        self.assertEqual(
            [(item["parking_id"], item["choice_utility"]) for item in first],
            [(item["parking_id"], item["choice_utility"]) for item in second],
        )


if __name__ == "__main__":
    unittest.main()
