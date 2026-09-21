from __future__ import annotations

import unittest

from domain.simulations.service import _residential_origin_building_ids


class ResidentialOriginTests(unittest.TestCase):
    def test_name_matching_is_case_insensitive_and_only_selected_assignments_count(self) -> None:
        model = {
            "selectedBuildingIds": ["building-1", "building-2"],
            "buildingClassifications": [{
                "id": "classification",
                "types": [
                    {"id": "res", "name": "  RESIDENTIAL  "},
                    {"id": "teaching", "name": "Teaching"},
                ],
                "assignments": {
                    "building-1": "res",
                    "building-2": "teaching",
                    "unselected-building": "res",
                },
            }],
        }

        self.assertEqual(
            _residential_origin_building_ids(model, "classification"),
            {"building-1"},
        )

    def test_missing_residential_type_has_no_origins(self) -> None:
        model = {
            "selectedBuildingIds": ["building-1"],
            "buildingClassifications": [{
                "id": "classification",
                "types": [{"id": "home", "name": "Housing"}],
                "assignments": {"building-1": "home"},
            }],
        }

        self.assertEqual(
            _residential_origin_building_ids(model, "classification"),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
