import math
import unittest

from domain.calibration.service import FlowCalibrationError, compare_and_update_profile


class PeakUpdateTests(unittest.TestCase):
    def test_only_peak_heights_change_by_real_to_simulation_ratio(self):
        profile = {
            "peak_count": 2,
            "peak_width_hours": 0.4,
            "harmonics": 7,
            "peak_heights": [0.5, 0.8],
        }
        real = [
            {"time_seconds": 0, "flow_per_hour": 120},
            {"time_seconds": 900, "flow_per_hour": 120},
            {"time_seconds": 1800, "flow_per_hour": 50},
            {"time_seconds": 2700, "flow_per_hour": 50},
        ]
        simulated = [
            {"begin_seconds": 0, "flow_per_hour": 100},
            {"begin_seconds": 900, "flow_per_hour": 100},
            {"begin_seconds": 1800, "flow_per_hour": 100},
            {"begin_seconds": 2700, "flow_per_hour": 100},
        ]

        updated, result = compare_and_update_profile(profile, real, simulated, 3600)

        self.assertEqual(updated["peak_count"], 2)
        self.assertEqual(updated["peak_width_hours"], 0.4)
        self.assertEqual(updated["harmonics"], 7)
        self.assertTrue(math.isclose(updated["peak_heights"][0], 0.6))
        self.assertTrue(math.isclose(updated["peak_heights"][1], 0.4))
        self.assertTrue(math.isclose(result["peaks"][0]["raw_ratio"], 1.2))

    def test_sixteen_peaks_over_twelve_hours_have_45_minute_cells(self):
        profile = {
            "peak_count": 16,
            "peak_width_hours": 0.3,
            "harmonics": 10,
            "peak_heights": [1.0] * 16,
        }
        real = [
            {"time_seconds": index * 2700, "flow_per_hour": 100}
            for index in range(16)
        ]
        simulated = [
            {"begin_seconds": index * 2700, "flow_per_hour": 100}
            for index in range(16)
        ]

        _, result = compare_and_update_profile(profile, real, simulated, 12 * 3600)

        self.assertEqual(result["metrics"]["peak_spacing_seconds"], 2700)
        self.assertEqual(result["peaks"][0]["window_end_seconds"], 2700)
        self.assertEqual(result["peaks"][0]["center_seconds"], 1350)
        self.assertEqual(result["peaks"][15]["center_seconds"], 41850)

    def test_zero_simulation_flow_is_reported_as_an_undefined_ratio(self):
        profile = {
            "peak_count": 1,
            "peak_width_hours": 1,
            "harmonics": 1,
            "peak_heights": [0.5],
        }
        updated, result = compare_and_update_profile(
            profile,
            [{"time_seconds": 0, "flow_per_hour": 100}],
            [{"begin_seconds": 0, "flow_per_hour": 0}],
            3600,
        )
        self.assertIsNone(result["peaks"][0]["raw_ratio"])
        self.assertIsNone(result["peaks"][0]["applied_ratio"])
        self.assertEqual(updated["peak_heights"], [0.5])

    def test_peak_height_count_must_stay_locked(self):
        with self.assertRaises(FlowCalibrationError):
            compare_and_update_profile(
                {
                    "peak_count": 2,
                    "peak_width_hours": 1,
                    "harmonics": 2,
                    "peak_heights": [1.0],
                },
                [],
                [],
                3600,
            )

    def test_percentage_changes_are_quantized_to_the_configured_step(self):
        profile = {
            "peak_count": 1,
            "peak_width_hours": 1,
            "harmonics": 1,
            "peak_heights": [0.50],
        }
        updated, result = compare_and_update_profile(
            profile,
            [{"time_seconds": 0, "flow_per_hour": 106}],
            [{"begin_seconds": 0, "flow_per_hour": 100}],
            3600,
            step_percentage=5,
        )
        self.assertEqual(updated["peak_heights"], [0.55])
        self.assertEqual(result["peaks"][0]["new_percentage"], 55)

    def test_hill_response_is_used_after_three_distinct_inputs(self):
        profile = {
            "peak_count": 1,
            "peak_width_hours": 1,
            "harmonics": 1,
            "peak_heights": [1.5],
        }
        history = [
            {"peaks": [{"old_percentage": 50, "simulation_flow_per_hour": 40}]},
            {"peaks": [{"old_percentage": 100, "simulation_flow_per_hour": 66.7}]},
        ]
        _, result = compare_and_update_profile(
            profile,
            [{"time_seconds": 0, "flow_per_hour": 85}],
            [{"begin_seconds": 0, "flow_per_hour": 80}],
            3600,
            history=history,
        )
        peak = result["peaks"][0]
        self.assertEqual(peak["update_method"], "hill")
        self.assertIsNotNone(peak["hill_model"])
        self.assertGreaterEqual(peak["new_percentage"], peak["old_percentage"])


if __name__ == "__main__":
    unittest.main()
