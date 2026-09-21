from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import traci.constants as tc

from sumo.controller.main import (
    RECOVERABLE_SUMO_SIGNALS,
    _archive_sumo_attempt,
    _start_sumo,
    _remove_vehicle_without_stale_subscription,
    _parking_decision_target,
    _subscription_results,
    _walking_completion_candidates,
)
from sumo.controller.metrics_logger import CsvLogger


class WalkingCompletionCandidateTests(unittest.TestCase):
    def test_selects_person_near_final_arrival(self) -> None:
        person = SimpleNamespace(
            getIDList=lambda: ("walk.person.9",),
            getRemainingStages=lambda _person_id: 1,
            getStage=lambda _person_id, _index: SimpleNamespace(
                type=2,
                edges=("origin", "155471161"),
                arrivalPos=33.99,
            ),
            getRoadID=lambda _person_id: "155471161",
            getLanePosition=lambda _person_id: 33.0,
            getSpeed=lambda _person_id: 1.3,
        )
        with patch("sumo.controller.main.traci.person", person):
            self.assertEqual(
                _walking_completion_candidates(
                    step_length=1.0,
                    minimum_distance=2.0,
                ),
                ["walk.person.9"],
            )

    def test_subscription_values_avoid_repeated_person_getters(self) -> None:
        get_stage = Mock(return_value=SimpleNamespace(
            type=tc.STAGE_WALKING,
            edges=("origin", "destination"),
            arrivalPos=20.0,
        ))
        person = SimpleNamespace(
            getStage=get_stage,
            getRemainingStages=Mock(side_effect=AssertionError("not batched")),
            getRoadID=Mock(side_effect=AssertionError("not batched")),
            getLanePosition=Mock(side_effect=AssertionError("not batched")),
            getSpeed=Mock(side_effect=AssertionError("not batched")),
        )
        results = {
            "walk.person.11": {
                tc.VAR_STAGES_REMAINING: 1,
                tc.VAR_ROAD_ID: "destination",
                tc.VAR_LANEPOSITION: 19.0,
                tc.VAR_SPEED: 1.0,
            },
        }
        stage_cache: dict[str, tuple[str, float]] = {}
        with patch("sumo.controller.main.traci.person", person):
            for _ in range(2):
                self.assertEqual(
                    _walking_completion_candidates(
                        step_length=1.0,
                        minimum_distance=2.0,
                        person_ids=("walk.person.11",),
                        subscription_results=results,
                        final_stage_cache=stage_cache,
                    ),
                    ["walk.person.11"],
                )

        get_stage.assert_called_once_with("walk.person.11", 0)

    def test_ignores_person_far_from_arrival(self) -> None:
        person = SimpleNamespace(
            getIDList=lambda: ("walk.person.10",),
            getRemainingStages=lambda _person_id: 1,
            getStage=lambda _person_id, _index: SimpleNamespace(
                type=2,
                edges=("origin", "destination"),
                arrivalPos=100.0,
            ),
            getRoadID=lambda _person_id: "destination",
            getLanePosition=lambda _person_id: 20.0,
            getSpeed=lambda _person_id: 1.3,
        )
        with patch("sumo.controller.main.traci.person", person):
            self.assertEqual(
                _walking_completion_candidates(
                    step_length=1.0,
                    minimum_distance=2.0,
                ),
                [],
            )


class SubscriptionTests(unittest.TestCase):
    def test_only_new_objects_are_subscribed(self) -> None:
        domain = SimpleNamespace(
            subscribe=Mock(),
            getAllSubscriptionResults=Mock(return_value={
                "vehicle.1": {tc.VAR_ROAD_ID: "edge"},
            }),
        )
        subscribed = {"vehicle.1", "departed.vehicle"}

        results = _subscription_results(
            domain,
            ("vehicle.1", "vehicle.2"),
            subscribed,
            (tc.VAR_ROAD_ID,),
        )

        domain.subscribe.assert_called_once_with("vehicle.2", (tc.VAR_ROAD_ID,))
        self.assertEqual(subscribed, {"vehicle.1", "vehicle.2"})
        self.assertEqual(results["vehicle.1"][tc.VAR_ROAD_ID], "edge")

    @patch("sumo.controller.main.traci.vehicle")
    def test_vehicle_is_unsubscribed_before_controller_removal(self, vehicle) -> None:
        subscribed = {"vehicle.1", "vehicle.2"}

        _remove_vehicle_without_stale_subscription("vehicle.1", subscribed)

        self.assertEqual(
            [call[0] for call in vehicle.method_calls],
            ["unsubscribe", "remove"],
        )
        self.assertEqual(subscribed, {"vehicle.2"})


class ParkingDecisionTargetTests(unittest.TestCase):
    def test_checks_unattempted_candidate_passed_on_route(self) -> None:
        self.assertEqual(
            _parking_decision_target(
                "parking-c",
                ["parking-c", "parking-b", "parking-a"],
                {"parking-b"},
                decision_mode="access_edge",
            ),
            ("parking-b", "pass_by"),
        )

    def test_intended_target_wins_at_its_access_edge(self) -> None:
        self.assertEqual(
            _parking_decision_target(
                "parking-c",
                ["parking-c", "parking-b"],
                {"parking-b", "parking-c"},
                decision_mode="access_edge",
            ),
            ("parking-c", "target"),
        )

    def test_waits_until_a_candidate_access_edge_is_reached(self) -> None:
        self.assertEqual(
            _parking_decision_target(
                "parking-c",
                ["parking-c", "parking-b"],
                set(),
                decision_mode="access_edge",
            ),
            (None, ""),
        )


class TracingTests(unittest.TestCase):
    @patch("sumo.controller.main.traci.getConnection")
    @patch("sumo.controller.main.traci.start")
    def test_trace_is_disabled_when_no_path_is_supplied(self, start, connection) -> None:
        connection.return_value = SimpleNamespace(_process=None)

        _start_sumo(["sumo", "-c", "run.sumocfg"], None)

        start.assert_called_once_with(["sumo", "-c", "run.sumocfg"])

    @patch("sumo.controller.main.traci.getConnection")
    @patch("sumo.controller.main.traci.start")
    def test_diagnostic_trace_includes_getters(self, start, connection) -> None:
        connection.return_value = SimpleNamespace(_process=None)

        _start_sumo(
            ["sumo", "-c", "run.sumocfg"],
            Path("trace.py"),
        )

        start.assert_called_once_with(
            ["sumo", "-c", "run.sumocfg"],
            traceFile="trace.py",
            traceGetters=True,
        )

class RecoveryArtifactTests(unittest.TestCase):
    def test_only_known_walking_completion_fault_signals_are_recoverable(self) -> None:
        self.assertEqual(RECOVERABLE_SUMO_SIGNALS, {"SIGSEGV", "SIGBUS"})
        self.assertNotIn("SIGABRT", RECOVERABLE_SUMO_SIGNALS)

    def test_csv_logger_restores_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            logger = CsvLogger(path, ["event"])
            logger.write(event="kept")
            checkpoint = logger.checkpoint()
            logger.write(event="discarded")
            logger.restore(checkpoint)
            logger.write(event="replayed")
            logger.close()

            with path.open(newline="", encoding="utf-8") as source:
                self.assertEqual(
                    [row["event"] for row in csv.DictReader(source)],
                    ["kept", "replayed"],
                )

    def test_archives_native_attempt_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "sumo.log").write_text("crash", encoding="utf-8")
            (output_dir / "traci.trace.py").write_text("trace", encoding="utf-8")

            _archive_sumo_attempt(output_dir, 2)

            self.assertFalse((output_dir / "sumo.log").exists())
            self.assertTrue((output_dir / "sumo.attempt-2.log").is_file())
            self.assertTrue((output_dir / "traci.trace.attempt-2.py").is_file())


if __name__ == "__main__":
    unittest.main()
