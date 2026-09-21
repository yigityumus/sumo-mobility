from __future__ import annotations

import unittest

from pydantic import ValidationError

from services.api.schemas import FlowCalibrationRequest, SimulationRunRequest


class SimulationRunRequestTests(unittest.TestCase):
    def test_accepts_a_reproducible_random_seed(self) -> None:
        request = SimulationRunRequest(
            vehicle_count=1,
            pedestrian_count=1,
            duration_hours=1,
            random_seed=20260119,
        )
        self.assertEqual(request.random_seed, 20260119)

    def test_legacy_request_assigns_all_independent_walkers_to_transit(self) -> None:
        request = SimulationRunRequest(
            vehicle_count=2,
            pedestrian_count=3,
            duration_hours=1,
        )

        self.assertEqual(request.residential_pedestrian_count, 0)
        self.assertEqual(request.public_transport_pedestrian_count, 3)
        self.assertEqual(request.pedestrian_model, "striping")
        self.assertFalse(request.diagnostic_tracing)

    def test_explicit_source_counts_must_equal_independent_walkers(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must add up"):
            SimulationRunRequest(
                vehicle_count=2,
                pedestrian_count=3,
                residential_pedestrian_count=1,
                public_transport_pedestrian_count=1,
                duration_hours=1,
            )

    def test_fast_pedestrian_model_and_diagnostic_trace_are_explicit(self) -> None:
        request = SimulationRunRequest(
            vehicle_count=0,
            pedestrian_count=3,
            public_transport_pedestrian_count=3,
            duration_hours=1,
            pedestrian_model="nonInteracting",
            diagnostic_tracing=True,
        )

        self.assertEqual(request.pedestrian_model, "nonInteracting")
        self.assertTrue(request.diagnostic_tracing)

    def test_unknown_pedestrian_model_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SimulationRunRequest(
                vehicle_count=0,
                pedestrian_count=1,
                public_transport_pedestrian_count=1,
                duration_hours=1,
                pedestrian_model="teleporting",
            )

    def test_fourier_and_parking_choice_controls_accept_new_ranges(self) -> None:
        request = SimulationRunRequest(
            vehicle_count=1,
            pedestrian_count=0,
            duration_hours=2,
            vehicle_fourier_parameters={
                "peak_count": 16,
                "peak_width_hours": 0.01,
                "harmonics": 16,
                "peak_heights": [1.0] * 16,
            },
            parking_choice={
                "knowledge_probability": 0.8,
                "frustration_step": 0.6,
                "weights": {
                    "drive_time": 0.5,
                    "walk_time": 1.2,
                    "capacity": 1.5,
                    "absolute_free_space": 2.0,
                    "relative_free_space": 2.5,
                },
            },
        )

        self.assertEqual(request.vehicle_fourier_parameters.peak_count, 16)
        self.assertEqual(request.vehicle_fourier_parameters.peak_width_hours, 0.01)
        self.assertEqual(request.parking_choice.knowledge_probability, 0.8)
        self.assertEqual(request.parking_choice.weights.relative_free_space, 2.5)

    def test_vehicle_origin_counts_must_be_unique_and_match_vehicle_total(self) -> None:
        request = SimulationRunRequest(
            vehicle_count=10,
            pedestrian_count=0,
            duration_hours=1,
            vehicle_origin_allocations=[
                {"origin_id": "north", "vehicle_count": 7},
                {"origin_id": "south", "vehicle_count": 3},
            ],
        )
        self.assertEqual(
            [item.vehicle_count for item in request.vehicle_origin_allocations or []],
            [7, 3],
        )

        with self.assertRaisesRegex(ValidationError, "must add up"):
            SimulationRunRequest(
                vehicle_count=10,
                pedestrian_count=0,
                duration_hours=1,
                vehicle_origin_allocations=[
                    {"origin_id": "north", "vehicle_count": 6},
                    {"origin_id": "south", "vehicle_count": 3},
                ],
            )

        with self.assertRaisesRegex(ValidationError, "unique origin IDs"):
            SimulationRunRequest(
                vehicle_count=10,
                pedestrian_count=0,
                duration_hours=1,
                vehicle_origin_allocations=[
                    {"origin_id": "north", "vehicle_count": 5},
                    {"origin_id": "north", "vehicle_count": 5},
                ],
            )


class FlowCalibrationRequestTests(unittest.TestCase):
    @staticmethod
    def simulation() -> dict:
        return {
            "vehicle_count": 1,
            "pedestrian_count": 1,
            "residential_pedestrian_count": 0,
            "public_transport_pedestrian_count": 1,
            "duration_hours": 12,
            "simulation_start_at": "2026-01-19T07:00:00",
            "mode": "sumo",
            "vehicle_traffic_model": "fourier",
            "pedestrian_traffic_model": "fourier",
        }

    def test_accepts_a_fixed_fourier_calibration(self) -> None:
        request = FlowCalibrationRequest(
            real_world_source_id="sensor",
            detector_logical_id="detector",
            subjects=["vehicles", "pedestrians"],
            iterations=20,
            simulation=self.simulation(),
        )
        self.assertEqual(request.iterations, 20)
        self.assertEqual(request.step_percentage, 1)

    def test_accepts_a_five_percent_minimum_step(self) -> None:
        request = FlowCalibrationRequest(
            real_world_source_id="sensor",
            detector_logical_id="detector",
            iterations=10,
            step_percentage=5,
            simulation=self.simulation(),
        )
        self.assertEqual(request.step_percentage, 5)

    def test_rejects_gui_mode_and_missing_start_time(self) -> None:
        simulation = self.simulation()
        simulation["mode"] = "sumo-gui"
        with self.assertRaisesRegex(ValidationError, "background SUMO"):
            FlowCalibrationRequest(
                real_world_source_id="sensor",
                detector_logical_id="detector",
                simulation=simulation,
            )

        simulation = self.simulation()
        simulation["simulation_start_at"] = None
        with self.assertRaisesRegex(ValidationError, "fixed simulation start"):
            FlowCalibrationRequest(
                real_world_source_id="sensor",
                detector_logical_id="detector",
                simulation=simulation,
            )


if __name__ == "__main__":
    unittest.main()
