import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "calibrate_flow.py"
SPEC = importlib.util.spec_from_file_location("calibrate_flow", SCRIPT_PATH)
calibrate_flow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = calibrate_flow
SPEC.loader.exec_module(calibrate_flow)


class FlowCalibrationTests(unittest.TestCase):
    def test_normalized_name_resolution_is_case_and_accent_insensitive(self):
        item = calibrate_flow.resolve_named(
            [{"id": "1", "name": "Cité Scientifique TEST 2"}],
            "cite scientifique test 2",
            label="model",
        )
        self.assertEqual(item["id"], "1")

    def test_request_locks_the_requested_configuration(self):
        workflow = calibrate_flow.FlowCalibration(calibrate_flow.CalibrationConfig())
        workflow.classification = {"id": "classification-id"}
        workflow.sensor = {"id": "sensor-id"}
        workflow.detector = {"id": "detector-id"}
        payload = workflow.calibration_payload()
        simulation = payload["simulation"]
        self.assertEqual(payload["iterations"], 10)
        self.assertEqual(payload["step_percentage"], 1)
        self.assertEqual(payload["subjects"], ["vehicles"])
        self.assertEqual(simulation["total_people"], 16_000)
        self.assertEqual(simulation["vehicle_count"], 3_000)
        self.assertEqual(simulation["pedestrian_count"], 13_000)
        self.assertEqual(simulation["residential_pedestrian_count"], 4_000)
        self.assertEqual(simulation["public_transport_pedestrian_count"], 9_000)
        self.assertEqual(simulation["simulation_start_at"], "2026-01-19T07:00:00")
        self.assertEqual(simulation["duration_hours"], 12)
        self.assertEqual(simulation["pedestrian_model"], "nonInteracting")
        self.assertEqual(simulation["parking_choice"]["stochastic_scale"], 0.0)
        self.assertEqual(simulation["random_seed"], 20260119)

    def test_profile_file_preserves_fourier_geometry_and_percentages(self):
        profile = {
            "peak_count": 3,
            "peak_width_hours": 0.4,
            "harmonics": 7,
            "peak_heights": [0.2, 0.5, 1.1],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            self.assertEqual(calibrate_flow.load_fourier_profile(path, {}), profile)

    def test_invalid_iteration_count_is_rejected(self):
        with self.assertRaises(calibrate_flow.CalibrationError):
            calibrate_flow.CalibrationConfig(iterations=0).validate()


if __name__ == "__main__":
    unittest.main()
