from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from domain.analytics.service import _detector_results


class PedestrianDetectorResultTests(unittest.TestCase):
    def test_physical_zone_entries_are_summed_into_logical_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            snapshot = {
                "detectors": [{
                    "id": "camera",
                    "name": "Camera",
                    "type": "e3",
                    "period_seconds": 900,
                    "measurements": [{
                        "id": "camera__pedestrians",
                        "subject": "pedestrians",
                        "detector_type": "e2",
                        "physical_detectors": [
                            {"id": "zone_1"},
                            {"id": "zone_2"},
                        ],
                    }],
                }],
            }
            (root / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
            (root / "e2.xml").write_text(
                """<?xml version="1.0"?>
<detector>
  <interval begin="0" end="900" id="zone_1" nVehEntered="2" nVehSeen="2" meanSpeed="1.2" meanOccupancy="4"/>
  <interval begin="0" end="900" id="zone_2" nVehEntered="3" nVehSeen="3" meanSpeed="1.4" meanOccupancy="6"/>
</detector>
""",
                encoding="utf-8",
            )

            result = _detector_results(
                root / "missing-e1.xml",
                root / "missing-e3.xml",
                root / "e2.xml",
                root / "snapshot.json",
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["definitions"][0]["type"], "e2")
        point = result["series"]["camera__pedestrians"][0]
        self.assertEqual(point["entry_count"], 5)
        self.assertEqual(point["vehicle_count"], 5)
        self.assertEqual(point["entry_flow_per_hour"], 20)


if __name__ == "__main__":
    unittest.main()
