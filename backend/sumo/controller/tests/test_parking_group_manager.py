from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from sumo.controller.parking_group_manager import ParkingGroupManager
from sumo.controller.parking_models import LogicalParkingArea, PhysicalParkingArea


class ParkingGroupRoutingTests(unittest.TestCase):
    @patch("sumo.controller.parking_group_manager.traci")
    def test_fallback_routes_to_nearest_access_edge_without_reserving(self, traci) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ParkingGroupManager(Path("parking.yaml"), Path(directory))
            manager.groups["parking-c"] = LogicalParkingArea(
                logical_id="parking-c",
                name="Parking C",
                osm_way_id=None,
                parking_id_prefix="parking-c",
                physical_areas=[PhysicalParkingArea(
                    logical_id="parking-c",
                    sumo_id="physical-c",
                    lane_id="inside-c_0",
                    edge_id="inside-c",
                    capacity=300,
                )],
                access_edges={"access-c-far", "access-c-near"},
            )
            traci.vehicle.getRoadID.return_value = "current"
            traci.vehicle.getTypeID.return_value = "passenger"
            traci.simulation.findRoute.side_effect = lambda _source, destination, **_kwargs: (
                SimpleNamespace(
                    edges=("current", destination),
                    travelTime=5 if destination == "access-c-near" else 20,
                )
            )

            destination = manager.route_vehicle_to_logical_parking(
                "vehicle.1",
                "parking-c",
            )

        self.assertEqual(destination, "access-c-near")
        traci.vehicle.changeTarget.assert_called_once_with(
            "vehicle.1",
            "access-c-near",
        )
        self.assertEqual(manager.reserved, {})


if __name__ == "__main__":
    unittest.main()
