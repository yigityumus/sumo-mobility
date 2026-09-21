from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from domain.analytics.service import _search_time_results


class SearchTimeResultTests(unittest.TestCase):
    def test_full_first_parking_attempt_is_included_as_zero_search_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "search_times.csv").open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "vehicle_id",
                    "first_parking_arrival_time",
                    "first_reroute_time",
                    "search_time",
                ])
                writer.writeheader()
                writer.writerows([
                    {
                        "vehicle_id": "parked",
                        "first_parking_arrival_time": 10,
                        "first_reroute_time": "",
                        "search_time": 20,
                    },
                    {
                        "vehicle_id": "full-on-arrival",
                        "first_parking_arrival_time": "",
                        "first_reroute_time": "",
                        "search_time": 0,
                    },
                ])
            with (root / "parking_events.csv").open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=["time", "vehicle_id", "event"])
                writer.writeheader()
                writer.writerow({
                    "time": 30,
                    "vehicle_id": "full-on-arrival",
                    "event": "parking_attempt",
                })

            result = _search_time_results(root / "search_times.csv", 60)

        self.assertEqual(result["summary"]["vehicle_count"], 2)
        self.assertEqual(result["summary"]["average_seconds"], 10)
        self.assertEqual(sum(point["vehicle_count"] for point in result["points"]), 2)


if __name__ == "__main__":
    unittest.main()
