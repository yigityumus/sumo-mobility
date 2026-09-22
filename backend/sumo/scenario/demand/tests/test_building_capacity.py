import unittest
import random

from sumo.scenario.demand.generate import _choose_destination_building
from sumo.scenario.demand.person_access import (
    _building_footprint_area_square_metres,
    _building_levels,
    _capacity_constant,
    _destination_capacity_profile,
)


def _building(coordinates, *, levels=None, geometry_type="Polygon"):
    tags = {"building": "yes"}
    if levels is not None:
        tags["building:levels"] = levels
    return {
        "type": "Feature",
        "id": "way/1",
        "properties": {"tags": tags},
        "geometry": {"type": geometry_type, "coordinates": coordinates},
    }


class BuildingCapacityTests(unittest.TestCase):
    def test_polygon_area_is_measured_in_square_metres(self) -> None:
        # Near the equator, 0.0001 degrees is approximately 11.12 metres.
        feature = _building([[[
            0.0, 0.0,
        ], [
            0.0001, 0.0,
        ], [
            0.0001, 0.0001,
        ], [
            0.0, 0.0001,
        ], [
            0.0, 0.0,
        ]]])

        self.assertAlmostEqual(
            _building_footprint_area_square_metres(feature),
            123.64,
            delta=0.5,
        )

    def test_capacity_and_mode_weights_follow_requested_formula(self) -> None:
        feature = _building([[[
            0.0, 0.0,
        ], [
            0.0001, 0.0,
        ], [
            0.0001, 0.0001,
        ], [
            0.0, 0.0001,
        ], [
            0.0, 0.0,
        ]]], levels="3")

        profile = _destination_capacity_profile(feature, {
            "pedestrian": 25,
            "vehicle": 75,
            "capacityConstant": 2,
        })

        expected_capacity = profile["footprint_area_square_metres"] * 3 * 2
        self.assertAlmostEqual(profile["destination_capacity"], expected_capacity, delta=0.01)
        self.assertAlmostEqual(profile["pedestrian_weight"], expected_capacity * 0.25, delta=0.01)
        self.assertAlmostEqual(profile["vehicle_weight"], expected_capacity * 0.75, delta=0.01)

    def test_zero_constant_produces_zero_capacity(self) -> None:
        feature = _building([[[0, 0], [0.0001, 0], [0, 0.0001], [0, 0]]], levels="2")
        profile = _destination_capacity_profile(feature, {
            "pedestrian": 50,
            "vehicle": 50,
            "capacityConstant": 0,
        })

        self.assertEqual(profile["destination_capacity"], 0)
        self.assertEqual(profile["pedestrian_weight"], 0)
        self.assertEqual(profile["vehicle_weight"], 0)

    def test_legacy_defaults_are_one_level_and_constant_one(self) -> None:
        feature = _building([[[0, 0], [0.0001, 0], [0, 0.0001], [0, 0]]])

        self.assertEqual(_building_levels(feature), 1)
        self.assertEqual(_capacity_constant({}), 1)
        self.assertEqual(_capacity_constant({"capacityConstant": -4}), 0)

    def test_zero_capacity_buildings_are_never_selected(self) -> None:
        candidates = [
            {"id": "zero", "pedestrian_weight": 0},
            {"id": "positive", "pedestrian_weight": 10},
        ]

        choices = {
            _choose_destination_building(random.Random(seed), "pedestrian", candidates)["id"]
            for seed in range(20)
        }

        self.assertEqual(choices, {"positive"})

    def test_all_zero_capacity_weights_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive vehicle capacity weight"):
            _choose_destination_building(
                random.Random(42),
                "vehicle",
                [{"id": "zero", "vehicle_weight": 0}],
            )


if __name__ == "__main__":
    unittest.main()
