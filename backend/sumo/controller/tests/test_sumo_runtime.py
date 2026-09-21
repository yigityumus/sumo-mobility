from __future__ import annotations

import unittest
from pathlib import Path

from sumo.controller.sumo_runtime import make_sumo_cmd


class SumoCommandTests(unittest.TestCase):
    def test_selected_pedestrian_model_is_forwarded_to_sumo(self) -> None:
        command = make_sumo_cmd(
            {
                "simulation": {
                    "sumo_binary": "sumo",
                    "begin": 0,
                    "step_length": 1,
                    "pedestrian_model": "nonInteracting",
                },
                "controller": {"random_seed": 9876},
            },
            Path("outputs"),
            Path("simulation.sumocfg"),
        )

        model_option = command.index("--pedestrian.model")
        self.assertEqual(command[model_option + 1], "nonInteracting")
        seed_option = command.index("--seed")
        self.assertEqual(command[seed_option + 1], "9876")
        self.assertNotIn("--window-pos", command)

    def test_gui_command_opens_at_a_visible_default_position(self) -> None:
        command = make_sumo_cmd(
            {
                "simulation": {
                    "sumo_binary": "sumo-gui",
                    "begin": 0,
                    "step_length": 1,
                },
                "controller": {"random_seed": 42},
            },
            Path("outputs"),
            Path("simulation.sumocfg"),
        )

        position_option = command.index("--window-pos")
        size_option = command.index("--window-size")
        self.assertEqual(command[position_option + 1], "80,80")
        self.assertEqual(command[size_option + 1], "1100,750")


if __name__ == "__main__":
    unittest.main()
