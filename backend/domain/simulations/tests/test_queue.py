from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domain.simulations.service import (
    STOP_REQUESTS,
    _annotate_queue_positions,
    request_simulation_stop,
)


class QueuePositionTests(unittest.TestCase):
    def test_positions_are_global_fifo_and_only_added_to_waiting_runs(self) -> None:
        all_records = [
            {"id": "running", "status": "running", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "first", "status": "queued", "created_at": "2026-01-01T00:01:00Z"},
            {"id": "second", "status": "queued", "created_at": "2026-01-01T00:02:00Z"},
            {"id": "done", "status": "completed", "created_at": "2026-01-01T00:03:00Z"},
        ]

        annotated = _annotate_queue_positions(
            [all_records[0], all_records[2], all_records[3]],
            all_records,
        )

        self.assertIsNone(annotated[0]["queue_position"])
        self.assertEqual(annotated[1]["queue_position"], 2)
        self.assertEqual(annotated[1]["queued_ahead"], 1)
        self.assertIsNone(annotated[2]["queue_position"])

    def test_cancel_requested_waiting_runs_are_not_counted(self) -> None:
        records = [
            {
                "id": "cancelled",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00Z",
                "stop_requested_at": "2026-01-01T00:00:01Z",
            },
            {"id": "next", "status": "queued", "created_at": "2026-01-01T00:01:00Z"},
        ]

        annotated = _annotate_queue_positions(records)

        self.assertIsNone(annotated[0]["queue_position"])
        self.assertEqual(annotated[1]["queue_position"], 1)


class QueueCancellationTests(unittest.TestCase):
    @patch("domain.simulations.service.get_object_storage", return_value=None)
    @patch("domain.simulations.service.persist_simulation_run")
    @patch("domain.simulations.service.request_simulation_cancel", return_value=None)
    def test_waiting_gui_run_can_be_removed_without_starting_sumo(
        self,
        _cancel,
        _persist,
        _storage,
    ) -> None:
        run_id = "109d9504-3934-48d2-985f-04eaf14767ba"
        record = {
            "id": run_id,
            "model_id": "model",
            "mode": "sumo-gui",
            "status": "queued",
            "created_at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "domain.simulations.service.read_simulation_run",
                return_value=dict(record),
            ):
                result = request_simulation_stop(
                    Path(temporary_directory),
                    "model",
                    run_id,
                )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "Removed from queue")
        self.assertEqual(result["progress_phase"], "interrupted")
        STOP_REQUESTS.discard(run_id)


if __name__ == "__main__":
    unittest.main()
