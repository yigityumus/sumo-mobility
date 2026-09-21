from __future__ import annotations

import unittest
from types import SimpleNamespace

from vehicle_calibration.calibrate import (
    GaussianProcess,
    canonical_parameters,
    current_batch_candidates,
    peak_timing_error,
    project_sum_with_bounds,
    select_batch,
    simplex_from_unit,
)


class CalibrationMathTests(unittest.TestCase):
    def test_bounded_peak_projection_preserves_requested_sum(self) -> None:
        projected = project_sum_with_bounds(
            [0, 10, 50, 100, 200, 250, 300, 300],
            800,
            0,
            300,
            5,
        )
        self.assertEqual(sum(projected), 800)
        self.assertTrue(all(0 <= value <= 300 for value in projected))
        self.assertTrue(all(value % 5 == 0 for value in projected))

    def test_dynamic_simplex_always_totals_one_hundred(self) -> None:
        for values in ([0.2, 0.4], [0.1, 0.3, 0.7, 0.9], [0.2] * 6):
            shares = simplex_from_unit(values)
            self.assertEqual(len(shares), len(values))
            self.assertAlmostEqual(sum(shares), 100.0)
            self.assertTrue(all(value >= 0 for value in shares))

    def test_peak_timing_error_is_zero_for_identical_profiles(self) -> None:
        profile = [0, 1, 4, 1, 0, 0] * 8
        self.assertEqual(peak_timing_error(profile, profile, 8), 0.0)

    def test_gaussian_process_prefers_observed_low_region(self) -> None:
        model = GaussianProcess([[0.0], [0.5], [1.0]], [1.0, 0.0, 1.0])
        center, _ = model.predict([0.5])
        edge, _ = model.predict([0.0])
        self.assertLess(center, edge)

    def test_scheduler_selects_earliest_unfinished_validation_batch(self) -> None:
        state = {
            "phases": {"validation": {
                "candidate_ids": ["a", "b", "c", "d"],
                "batches_created": 2,
            }},
            "candidates": {
                "a": {"batch": 1, "status": "valid"},
                "b": {"batch": 1, "status": "valid"},
                "c": {"batch": 2, "status": "planned"},
                "d": {"batch": 2, "status": "planned"},
            },
        }
        selected = current_batch_candidates(state, "validation")
        self.assertEqual(selected, [state["candidates"]["c"], state["candidates"]["d"]])

    def test_candidate_supports_dynamic_origin_count(self) -> None:
        context = SimpleNamespace(
            config={
                "search": {
                    "vehicle_count": {"minimum": 3000, "maximum": 7000, "step": 100},
                    "fourier_peak_percent": {
                        "minimum": 0,
                        "maximum": 300,
                        "step": 5,
                        "normalized_mean_percent": 100,
                    },
                },
                "baseline": {"random_seed": 1},
            },
            baseline_payload={
                "vehicle_count": 3000,
                "vehicle_origin_allocations": [
                    {"origin_id": f"origin-{index}", "vehicle_count": 500}
                    for index in range(6)
                ],
                "vehicle_fourier_parameters": {
                    "peak_count": 8,
                    "peak_heights": [1.0] * 8,
                },
                "random_seed": 1,
            },
            origin_ids=[f"origin-{index}" for index in range(6)],
        )
        result = canonical_parameters(context, {
            "vehicle_count": 5123,
            "origin_percentages": [1, 2, 3, 4, 5, 6],
            "peak_heights_percent": [0, 50, 75, 100, 125, 150, 200, 300],
            "random_seed": 7,
        })
        self.assertEqual(result["vehicle_count"], 5100)
        self.assertAlmostEqual(sum(result["origin_percentages"]), 100.0)
        self.assertEqual(len(result["origin_percentages"]), 6)
        self.assertEqual(sum(result["peak_heights_percent"]), 800)

    def test_initial_batch_contains_four_unique_valid_candidates(self) -> None:
        search = {
            "vehicle_count": {"minimum": 3000, "maximum": 7000, "step": 100},
            "fourier_peak_percent": {
                "minimum": 0,
                "maximum": 300,
                "step": 5,
                "normalized_mean_percent": 100,
            },
            "candidate_pool_size": 64,
            "phases": {
                "volume_routing": {"runs": 24, "initial_design_runs": 12},
            },
        }
        context = SimpleNamespace(
            config={"search": search, "baseline": {"random_seed": 1}},
            baseline_payload={
                "vehicle_count": 3000,
                "vehicle_origin_allocations": [
                    {"origin_id": item, "vehicle_count": 750}
                    for item in ["a", "b", "c", "d"]
                ],
                "vehicle_fourier_parameters": {
                    "peak_count": 8,
                    "peak_heights": [1.0] * 8,
                },
                "random_seed": 1,
            },
            origin_ids=["a", "b", "c", "d"],
        )
        base = {
            "vehicle_count": 3000,
            "origin_percentages": [25, 25, 25, 25],
            "peak_heights_percent": [100] * 8,
            "random_seed": 1,
        }
        state = {
            "phases": {"volume_routing": {
                "base_parameters": base,
                "candidate_ids": [],
                "batches_created": 0,
            }},
            "candidates": {},
        }
        selected = select_batch(context, state, [], "volume_routing", 4)
        self.assertEqual(len(selected), 4)
        self.assertEqual(len({str(item) for item in selected}), 4)
        for item in selected:
            self.assertAlmostEqual(sum(item["origin_percentages"]), 100.0)
            self.assertEqual(sum(item["peak_heights_percent"]), 800)


if __name__ == "__main__":
    unittest.main()
