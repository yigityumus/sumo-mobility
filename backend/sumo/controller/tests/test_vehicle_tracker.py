from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from sumo.controller.vehicle_tracker import VehicleTracker


class VehicleTrackerParkingAttemptTests(unittest.TestCase):
    def test_tracks_distinct_attempts_and_next_destination_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "vehicle_plan.csv"
            with plan_path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "vehicle_id", "initial_parking", "parking_candidates_json",
                ])
                writer.writeheader()
                writer.writerow({
                    "vehicle_id": "vehicle.1",
                    "initial_parking": "parking-a",
                    "parking_candidates_json": json.dumps([
                        {"parking_id": "parking-a", "distance_metres": 20},
                        {"parking_id": "parking-b", "distance_metres": 50, "total_capacity": 300, "capacity_band": "large"},
                        {"parking_id": "parking-c", "distance_metres": 70, "total_capacity": 50, "capacity_band": "medium"},
                    ]),
                })

            tracker = VehicleTracker(plan_path)
            self.assertEqual(tracker.next_parking_candidate("vehicle.1"), "parking-a")
            self.assertEqual(
                tracker.unattempted_parking_candidates("vehicle.1"),
                ["parking-a", "parking-b", "parking-c"],
            )
            self.assertEqual(tracker.parking_candidate_capacity("vehicle.1", "parking-b"), 300)
            self.assertEqual(tracker.parking_candidate_band("vehicle.1", "parking-b"), "large")
            self.assertEqual(tracker.mark_parking_attempt("vehicle.1", "parking-a", 12), 1)
            self.assertEqual(tracker.mark_parking_attempt("vehicle.1", "parking-a"), 1)
            self.assertEqual(tracker.next_parking_candidate("vehicle.1"), "parking-b")
            tracker.mark_candidate_rejected("vehicle.1", "parking-b")
            self.assertEqual(tracker.next_parking_candidate("vehicle.1"), "parking-c")
            tracker.mark_target_changed("vehicle.1", 10, "parking-b", "Parking B")
            self.assertEqual(tracker.mark_parking_attempt("vehicle.1", "parking-b"), 2)
            self.assertEqual(tracker.next_parking_candidate("vehicle.1"), "parking-c")

            result_path = root / "search_times.csv"
            tracker.write_search_times(result_path)
            with result_path.open(newline="", encoding="utf-8") as source:
                row = next(csv.DictReader(source))
            self.assertEqual(row["num_parking_attempts"], "2")
            self.assertEqual(row["attempted_parking_ids"], "parking-a;parking-b")
            self.assertEqual(row["rejected_parking_ids"], "parking-b")
            self.assertEqual(row["first_parking_arrival_time"], "12.0")


if __name__ == "__main__":
    unittest.main()
