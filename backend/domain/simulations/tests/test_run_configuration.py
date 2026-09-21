from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from domain.simulations.service import (
    _scenario_for_run,
    _vehicle_origin_allocation_snapshot,
    create_simulation_run,
)


class RunRandomnessTests(unittest.TestCase):
    @patch("domain.simulations.service.get_object_storage", return_value=None)
    @patch("domain.simulations.service._write_record")
    @patch("domain.simulations.service._snapshot_model_inputs", return_value=[])
    @patch("domain.simulations.service.secrets.randbelow", side_effect=[100, 200])
    def test_each_new_run_receives_a_fresh_saved_seed(
        self,
        _randbelow,
        _snapshot,
        _write,
        _storage,
    ) -> None:
        model = {
            "id": "model-1",
            "name": "Model",
            "publicTransportOrigins": [{"id": "origin"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            first = create_simulation_run(
                Path(directory),
                model,
                vehicle_count=0,
                pedestrian_count=1,
                duration_hours=1,
                mode="sumo",
                public_transport_pedestrian_count=1,
            )
            second = create_simulation_run(
                Path(directory),
                model,
                vehicle_count=0,
                pedestrian_count=1,
                duration_hours=1,
                mode="sumo",
                public_transport_pedestrian_count=1,
            )

        self.assertEqual(first["random_seed"], 101)
        self.assertEqual(second["random_seed"], 201)


class RunScenarioTests(unittest.TestCase):
    def test_seed_and_parking_choice_are_snapshotted_into_scenario(self) -> None:
        record = {
            "duration_seconds": 3600,
            "mode": "sumo",
            "vehicle_count": 1,
            "pedestrian_count": 0,
            "person_based_demand": True,
            "random_seed": 12345,
            "parking_choice": {
                "knowledge_probability": 0.9,
                "weights": {"capacity": 2.5},
            },
            "vehicle_generation_points": [{
                "id": "north-gate",
                "positionMetres": 12.5,
                "laneSelection": {"mode": "lane", "laneId": "edge_0"},
            }],
            "vehicle_origin_allocations": [{
                "origin_id": "north-gate",
                "origin_name": "North gate",
                "vehicle_count": 1,
                "percentage": 100.0,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = _scenario_for_run(record, Path(directory))
            scenario = yaml.safe_load(path.read_text(encoding="utf-8"))

        controller = scenario["controller"]
        self.assertEqual(controller["random_seed"], 12345)
        self.assertEqual(controller["parking_choice"]["knowledge_probability"], 0.9)
        self.assertEqual(controller["parking_choice"]["weights"]["capacity"], 2.5)
        self.assertIn("drive_time", controller["parking_choice"]["weights"])
        self.assertEqual(
            scenario["vehicle_generation_points"],
            record["vehicle_generation_points"],
        )
        self.assertEqual(
            scenario["vehicle_origin_allocations"],
            record["vehicle_origin_allocations"],
        )

    def test_vehicle_origin_allocation_defaults_to_dynamic_equal_counts(self) -> None:
        model = {
            "vehicleGenerationPoints": [
                {"id": "north", "name": "North"},
                {"id": "south", "name": "South"},
                {"id": "east", "name": "East"},
            ],
        }

        allocation = _vehicle_origin_allocation_snapshot(model, 10, None)

        self.assertEqual(
            [item["vehicle_count"] for item in allocation],
            [4, 3, 3],
        )

    def test_vehicle_origin_allocation_requires_current_model_points(self) -> None:
        model = {
            "vehicleGenerationPoints": [
                {"id": "north", "name": "North"},
                {"id": "south", "name": "South"},
            ],
        }

        with self.assertRaisesRegex(ValueError, "must match"):
            _vehicle_origin_allocation_snapshot(
                model,
                5,
                [{"origin_id": "north", "vehicle_count": 5}],
            )


if __name__ == "__main__":
    unittest.main()
