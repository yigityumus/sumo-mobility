from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from domain.analytics.service import _parking_attempt_results


class ParkingAttemptResultTests(unittest.TestCase):
    def test_builds_attempt_distribution_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "search_times.csv"
            with path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "vehicle_id", "num_parking_attempts", "status",
                ])
                writer.writeheader()
                writer.writerows([
                    {"vehicle_id": "a", "num_parking_attempts": 1, "status": "parked"},
                    {"vehicle_id": "b", "num_parking_attempts": 2, "status": "parked"},
                    {"vehicle_id": "c", "num_parking_attempts": 2, "status": "unserved"},
                    {"vehicle_id": "not-inserted", "num_parking_attempts": 0, "status": "not_inserted"},
                ])

            result = _parking_attempt_results(path)

        self.assertTrue(result["available"])
        self.assertEqual(result["distribution"], [
            {"attempt_count": 1, "vehicle_count": 1, "percentage": 33.333},
            {"attempt_count": 2, "vehicle_count": 2, "percentage": 66.667},
        ])
        self.assertEqual(result["summary"]["vehicles_using_fallback"], 2)
        self.assertEqual(result["summary"]["unserved_vehicle_count"], 1)
        self.assertEqual(result["summary"]["maximum_attempts"], 2)

    def test_old_search_output_is_reported_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "search_times.csv"
            path.write_text("vehicle_id,search_time\na,10\n", encoding="utf-8")
            result = _parking_attempt_results(path)

        self.assertFalse(result["available"])
        self.assertEqual(result["distribution"], [])


if __name__ == "__main__":
    unittest.main()
