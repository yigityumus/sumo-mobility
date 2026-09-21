from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from domain.analytics.service import _parking_destination_results


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ParkingDestinationResultTests(unittest.TestCase):
    def test_joins_buildings_choices_candidates_and_actual_parking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            person_plan = root / "inputs" / "person_plan.csv"
            vehicle_plan = root / "inputs" / "vehicle_parking_plan.csv"
            search_times = root / "outputs" / "search_times.csv"
            parking_events = root / "outputs" / "parking_events.csv"
            parking_config = root / "parking_areas.yaml"
            person_access = root / "person_access.snapshot.json"
            parking_config.write_text(
                "parking_areas:\n"
                "  - id: p1\n    name: North\n"
                "  - id: p2\n    name: South\n"
                "  - id: p3\n    name: Never eligible\n"
                "  - id: p4\n    name: Never preferred\n",
                encoding="utf-8",
            )
            person_access.write_text(json.dumps({
                "max_access_distance_metres": 100,
                "accessible_logical_parking_ids": ["p1", "p2", "p4"],
                "buildings": [
                    {"id": "b1", "name": "Library", "vehicle_weight": 50, "parking_candidates": [{"parking_id": "p1"}, {"parking_id": "p2"}]},
                    {"id": "b2", "name": "Laboratory", "vehicle_weight": 50, "parking_candidates": [{"parking_id": "p2"}, {"parking_id": "p4"}]},
                    {"id": "b3", "name": "Pedestrian hall", "vehicle_weight": 0, "parking_candidates": [{"parking_id": "p1"}]},
                ],
            }), encoding="utf-8")
            _write_csv(person_plan, [
                "person_id", "vehicle_id", "arrival_mode", "building_id", "building_name",
            ], [
                {"person_id": "person.v1", "vehicle_id": "v1", "arrival_mode": "vehicle", "building_id": "b1", "building_name": "Library"},
                {"person_id": "person.v2", "vehicle_id": "v2", "arrival_mode": "vehicle", "building_id": "b1", "building_name": "Library"},
                {"person_id": "person.v3", "vehicle_id": "v3", "arrival_mode": "vehicle", "building_id": "b2", "building_name": "Laboratory"},
                {"person_id": "walker", "vehicle_id": "", "arrival_mode": "pedestrian", "building_id": "b2", "building_name": "Laboratory"},
            ])
            _write_csv(vehicle_plan, [
                "vehicle_id", "initial_parking", "parking_candidates_json",
            ], [
                {"vehicle_id": "v1", "initial_parking": "p1", "parking_candidates_json": json.dumps([{"parking_id": "p1"}, {"parking_id": "p2"}])},
                {"vehicle_id": "v2", "initial_parking": "p1", "parking_candidates_json": json.dumps([{"parking_id": "p1"}])},
                {"vehicle_id": "v3", "initial_parking": "p2", "parking_candidates_json": json.dumps([{"parking_id": "p2"}, {"parking_id": "p4"}])},
            ])
            _write_csv(search_times, [
                "vehicle_id", "initial_parking", "final_parking", "num_parking_changes",
                "num_parking_attempts", "attempted_parking_ids", "rejected_parking_ids", "status",
            ], [
                {"vehicle_id": "v1", "initial_parking": "p1", "final_parking": "physical.p2", "num_parking_changes": 1, "num_parking_attempts": 2, "attempted_parking_ids": "p1;p2", "rejected_parking_ids": "", "status": "parked"},
                {"vehicle_id": "v2", "initial_parking": "p1", "final_parking": "physical.p1", "num_parking_changes": 0, "num_parking_attempts": 1, "attempted_parking_ids": "p1", "rejected_parking_ids": "", "status": "completed"},
                {"vehicle_id": "v3", "initial_parking": "p2", "final_parking": "", "num_parking_changes": 0, "num_parking_attempts": 1, "attempted_parking_ids": "p2", "rejected_parking_ids": "p4", "status": "unserved"},
            ])
            _write_csv(parking_events, [
                "vehicle_id", "event", "logical_parking", "physical_parking",
            ], [
                {"vehicle_id": "v1", "event": "parking_started", "logical_parking": "p2", "physical_parking": "physical.p2"},
                {"vehicle_id": "v2", "event": "parking_ended", "logical_parking": "p1", "physical_parking": "physical.p1"},
            ])

            result = _parking_destination_results(
                person_plan, vehicle_plan, search_times, parking_events, parking_config,
                person_access,
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["summary"], {
            "planned_vehicle_people": 3,
            "parked_people": 2,
            "unserved_people": 1,
            "without_parking_outcome": 0,
            "unused_parking_areas": 2,
            "destination_buildings": 3,
            "buildings_receiving_drivers": 2,
        })
        parkings = {parking["id"]: parking for parking in result["parkings"]}
        self.assertEqual(parkings["p1"]["initial_choice_people"], 2)
        self.assertEqual(parkings["p1"]["parked_people"], 1)
        self.assertEqual(parkings["p1"]["rerouted_out_people"], 1)
        self.assertEqual(parkings["p2"]["candidate_people"], 2)
        self.assertEqual(parkings["p2"]["rerouted_in_people"], 1)
        self.assertIn("could connect to a pedestrian lane", parkings["p3"]["unused_reason"])
        self.assertIn("never their highest-ranked", parkings["p4"]["unused_reason"])
        buildings = {building["id"]: building for building in result["buildings"]}
        self.assertEqual(buildings["b1"]["parked_people"], 2)
        self.assertEqual(buildings["b1"]["parking_area_count"], 2)
        self.assertEqual(buildings["b3"]["planned_vehicle_people"], 0)
        self.assertIn("0 vehicle weight", buildings["b3"]["zero_driver_reason"])
        flows = {
            (flow["parking_id"], flow["building_id"]): flow["parked_people"]
            for flow in result["parking_building_flows"]
        }
        self.assertEqual(flows[("p1", "b1")], 1)
        self.assertEqual(flows[("p2", "b1")], 1)

    def test_is_unavailable_without_a_vehicle_person_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = _parking_destination_results(
                root / "missing-person.csv",
                root / "missing-vehicle.csv",
                root / "missing-search.csv",
                root / "missing-events.csv",
                root / "missing-parkings.yaml",
            )

        self.assertFalse(result["available"])
        self.assertEqual(result["parking_building_flows"], [])


if __name__ == "__main__":
    unittest.main()
