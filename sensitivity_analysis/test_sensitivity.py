import copy
import json
import tempfile
import unittest
from pathlib import Path

from sensitivity_analysis.sensitivity import (
    allocate_counts,
    build_plan,
    fit_models,
    numeric_values,
)


ROOT = Path(__file__).resolve().parent


class SensitivityTests(unittest.TestCase):
    def config(self):
        value = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        value["replicates"] = 1
        for key, spec in value["experiments"].items():
            if key == "parking_choice":
                for item in spec.values():
                    item["enabled"] = False
            elif isinstance(spec, dict):
                spec["enabled"] = False
        return value

    def test_allocate_counts_preserves_total(self):
        result = allocate_counts(["a", "b", "c"], [33.3, 33.3, 33.4], 3001)
        self.assertEqual(sum(item["vehicle_count"] for item in result), 3001)
        self.assertEqual([item["origin_id"] for item in result], ["a", "b", "c"])

    def test_decimal_range_includes_exact_end(self):
        self.assertEqual(
            numeric_values({"minimum": 0, "maximum": 0.3, "step": 0.1}),
            [0.0, 0.1, 0.2, 0.3],
        )

    def test_plan_discovers_origins_and_deduplicates_baseline(self):
        config = self.config()
        config["experiments"]["vehicle_entry_allocations"]["enabled"] = True
        config["experiments"]["vehicle_entry_allocations"].update({
            "minimum_percent": 0,
            "maximum_percent": 100,
            "step_percent": 50,
        })
        origins = [{"id": "north", "name": "North"}, {"id": "south", "name": "South"}]
        plan = build_plan(config, "classification", origins, "model-signature")
        entry_points = [point for point in plan["points"] if point["parameter_id"].startswith("vehicle_entry_")]
        self.assertEqual(len(entry_points), 6)
        # Global baseline and both 50/50 entry baselines all share one payload.
        baseline_hashes = {
            point["payload_hash"] for point in entry_points if point["value"] == 50
        }
        self.assertEqual(len(baseline_hashes), 1)
        self.assertLess(len(plan["runs"]), len(plan["points"]))

    def test_hill_candidate_is_available_for_saturating_data(self):
        x = [0, 1, 2, 4, 8, 16, 32]
        y = [2 + 10 * value**2 / (4**2 + value**2) for value in x]
        models = fit_models(x, y)
        hill = next(item for item in models if item["model"] == "hill")
        self.assertGreater(hill["r_squared"], 0.99)


if __name__ == "__main__":
    unittest.main()
