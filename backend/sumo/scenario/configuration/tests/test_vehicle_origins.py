from __future__ import annotations

import unittest

from sumo.scenario.configuration.configure import _configured_vehicle_origins


class _Edge:
    def __init__(self, edge_id: str) -> None:
        self._edge_id = edge_id

    def getID(self) -> str:
        return self._edge_id


class _Lane:
    def __init__(self, lane_id: str, edge_id: str, index: int, length: float = 100) -> None:
        self._lane_id = lane_id
        self._edge = _Edge(edge_id)
        self._index = index
        self._length = length

    def allows(self, vehicle_class: str) -> bool:
        return vehicle_class == "passenger"

    def getEdge(self) -> _Edge:
        return self._edge

    def getIndex(self) -> int:
        return self._index

    def getLength(self) -> float:
        return self._length


class _Network:
    def __init__(self) -> None:
        self._lanes = {
            "inbound_1": _Lane("inbound_1", "inbound", 1),
            "other_0": _Lane("other_0", "other", 0, 50),
        }

    def getLane(self, lane_id: str) -> _Lane:
        return self._lanes[lane_id]


class ConfiguredVehicleOriginTests(unittest.TestCase):
    def test_saved_points_resolve_to_exact_edge_lane_and_position(self) -> None:
        points = _configured_vehicle_origins(_Network(), [{
            "id": "saved-1",
            "name": "North gate",
            "positionMetres": 43.2,
            "laneSelection": {"mode": "lane", "laneId": "inbound_1"},
        }])

        self.assertEqual(points, [{
            "id": "vehicle_origin_1",
            "configured_id": "saved-1",
            "name": "North gate",
            "from_edge": "inbound",
            "depart_lane": 1,
            "depart_position": 43.2,
        }])

    def test_duplicate_directed_edges_are_rejected(self) -> None:
        configured = [
            {"name": "First", "laneSelection": {"laneId": "inbound_1"}},
            {"name": "Second", "laneSelection": {"laneId": "inbound_1"}},
        ]

        with self.assertRaisesRegex(ValueError, "distinct directed edges"):
            _configured_vehicle_origins(_Network(), configured)


if __name__ == "__main__":
    unittest.main()
