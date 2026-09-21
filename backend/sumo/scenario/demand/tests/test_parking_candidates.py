from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from sumo.scenario.demand.person_access import (
    _attach_building_parking_candidates,
    _parking_capacity_band,
    _physical_parking_areas,
)


class _Edge:
    def __init__(self, edge_id: str):
        self.edge_id = edge_id

    def __hash__(self) -> int:
        return hash(self.edge_id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Edge) and other.edge_id == self.edge_id


class _Network:
    def __init__(self) -> None:
        self.edges = {edge_id: _Edge(edge_id) for edge_id in ("building", "a", "b", "c")}

    def getEdge(self, edge_id: str) -> _Edge:
        return self.edges[edge_id]

    def getShortestPath(self, source: _Edge, _destination: _Edge, **_kwargs):
        distances = {"building": 0, "a": 20, "b": 50}
        if source.edge_id not in distances:
            return None, None
        return (source, self.edges["building"]), distances[source.edge_id]


class ParkingCandidateTests(unittest.TestCase):
    def test_capacity_band_boundaries_do_not_overlap(self) -> None:
        self.assertEqual(_parking_capacity_band(16), ("small", 2))
        self.assertEqual(_parking_capacity_band(17), ("medium", 1))
        self.assertEqual(_parking_capacity_band(80), ("medium", 1))
        self.assertEqual(_parking_capacity_band(81), ("large", 0))

    def test_logical_capacity_sums_every_physical_area(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "parking.add.xml").write_text(
                """<additional>
                <parkingArea id="a" lane="edge_0" startPos="0" endPos="10" roadsideCapacity="45"/>
                <parkingArea id="b" lane="edge_1" startPos="0" endPos="10" roadsideCapacity="40"/>
                </additional>""",
                encoding="utf-8",
            )
            (root / "parking.yaml").write_text(
                """parking_areas:
  - id: parking-large
    enabled: true
    additional_path: parking.add.xml
""",
                encoding="utf-8",
            )

            areas = _physical_parking_areas(root / "parking.yaml")

        self.assertEqual([area["capacity"] for area in areas], [45, 40])
        self.assertEqual(
            {area["logical_total_capacity"] for area in areas},
            {85},
        )

    def test_candidates_are_routable_unique_and_nearest_first(self) -> None:
        buildings = [{
            "pedestrian_edge_id": "building",
            "pedestrian_x": 0,
            "pedestrian_y": 0,
        }]
        accesses = {
            "a-entrance": {
                "logical_parking_id": "parking-a",
                "pedestrian_edge_id": "a",
                "pedestrian_x": 20,
                "pedestrian_y": 0,
                "logical_total_capacity": 20,
            },
            "a-far-entrance": {
                "logical_parking_id": "parking-a",
                "pedestrian_edge_id": "a",
                "pedestrian_x": 40,
                "pedestrian_y": 0,
                "logical_total_capacity": 20,
            },
            "b-entrance": {
                "logical_parking_id": "parking-b",
                "pedestrian_edge_id": "b",
                "pedestrian_x": 50,
                "pedestrian_y": 0,
                "logical_total_capacity": 300,
            },
            "unreachable": {
                "logical_parking_id": "parking-c",
                "pedestrian_edge_id": "c",
                "pedestrian_x": 10,
                "pedestrian_y": 0,
                "logical_total_capacity": 10,
            },
        }

        _attach_building_parking_candidates(_Network(), buildings, accesses)

        self.assertEqual(buildings[0]["parking_candidates"], [
            {
                "parking_id": "parking-b",
                "distance_metres": 50.0,
                "total_capacity": 300,
                "capacity_band": "large",
                "band_priority": 0,
            },
            {
                "parking_id": "parking-a",
                "distance_metres": 20.0,
                "total_capacity": 20,
                "capacity_band": "medium",
                "band_priority": 1,
            },
        ])


if __name__ == "__main__":
    unittest.main()
