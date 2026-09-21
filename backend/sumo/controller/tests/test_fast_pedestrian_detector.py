from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from sumo.controller.fast_pedestrian_detector import (
    FastPedestrianDetector,
    PersonPosition,
)


class FastPedestrianDetectorTests(unittest.TestCase):
    def _detector(self, directory: Path) -> FastPedestrianDetector:
        snapshot = directory / "detectors.snapshot.json"
        snapshot.write_text(json.dumps({
            "detectors": [{
                "type": "e3",
                "period_seconds": 900,
                "measurements": [{
                    "subject": "pedestrians",
                    "detector_type": "e2",
                    "physical_detectors": [{
                        "id": "sup__pedestrians",
                        "edge_id": "walk-edge",
                        "lane_id": "walk-edge_0",
                        "start_position_metres": 20,
                        "end_position_metres": 30,
                    }],
                }],
            }],
        }), encoding="utf-8")
        return FastPedestrianDetector.from_snapshot(snapshot)

    def test_counts_forward_reverse_and_whole_zone_crossings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            detector = self._detector(Path(directory))
            detector.observe(0, {
                "forward": PersonPosition("walk-edge", 10, 2, "walk-edge_0"),
                "reverse": PersonPosition("walk-edge", 40, 2, "walk-edge_0"),
                "jump": PersonPosition("walk-edge", 5, 20, "walk-edge_0"),
            })
            detector.observe(1, {
                "forward": PersonPosition("walk-edge", 21, 2, "walk-edge_0"),
                "reverse": PersonPosition("walk-edge", 29, 2, "walk-edge_0"),
                "jump": PersonPosition("walk-edge", 45, 20, "walk-edge_0"),
            })
            detector.observe(2, {
                "forward": PersonPosition("walk-edge", 25, 2, "walk-edge_0"),
                "reverse": PersonPosition("walk-edge", 25, 2, "walk-edge_0"),
                "jump": PersonPosition("walk-edge", 50, 20, "walk-edge_0"),
            })

            self.assertEqual(detector.total_entries, 3)

    def test_reentry_is_counted_but_remaining_inside_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            detector = self._detector(Path(directory))
            detector.observe(0, {"person": PersonPosition("walk-edge", 10, 0, "walk-edge_0")})
            detector.observe(1, {"person": PersonPosition("walk-edge", 21, 0, "walk-edge_0")})
            detector.observe(2, {"person": PersonPosition("walk-edge", 25, 0, "walk-edge_0")})
            detector.observe(3, {"person": PersonPosition("walk-edge", 35, 0, "walk-edge_0")})
            detector.observe(4, {"person": PersonPosition("walk-edge", 29, 0, "walk-edge_0")})

            self.assertEqual(detector.total_entries, 2)

    def test_person_in_driving_stage_is_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            detector = self._detector(Path(directory))
            detector.observe(0, {
                "occupant": PersonPosition("walk-edge", 10, 10, "", 3),
            })
            detector.observe(1, {
                "occupant": PersonPosition("walk-edge", 25, 10, "", 3),
            })

            self.assertEqual(detector.total_entries, 0)

    def test_snapshot_restore_and_e2_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detector = self._detector(root)
            detector.observe(899, {"person": PersonPosition("walk-edge", 10, 2, "walk-edge_0")})
            detector.observe(900, {"person": PersonPosition("walk-edge", 21, 2, "walk-edge_0")})

            restored = self._detector(root)
            restored.restore(detector.snapshot())
            output = root / "e2_pedestrians.xml"
            restored.write_e2_xml(
                output,
                simulation_begin=0,
                simulation_end=1800,
            )

            intervals = ET.parse(output).getroot().findall("interval")
            self.assertEqual(len(intervals), 2)
            self.assertEqual(intervals[0].attrib["nVehEntered"], "0")
            self.assertEqual(intervals[1].attrib["nVehEntered"], "1")


if __name__ == "__main__":
    unittest.main()
