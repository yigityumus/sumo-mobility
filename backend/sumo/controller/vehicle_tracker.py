from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


SEARCH_SEGMENT_TYPES = {"inside_parking", "between_parkings"}


class VehicleTracker:
    """Track vehicle outcomes and an event-driven journey-segment timeline."""

    def __init__(self, vehicle_plan_csv: Path):
        self.data: dict[str, dict[str, Any]] = {}
        self.parking_candidates: dict[str, list[str]] = {}
        self.parking_candidate_distances: dict[str, dict[str, float | None]] = {}
        self.parking_candidate_capacities: dict[str, dict[str, int | None]] = {}
        self.parking_candidate_bands: dict[str, dict[str, str]] = {}
        self.parking_candidate_details: dict[str, dict[str, dict[str, Any]]] = {}
        self.segments: list[dict[str, Any]] = []
        self._open_segments: dict[str, dict[str, Any]] = {}
        self._next_segment_index: dict[str, int] = {}
        if vehicle_plan_csv.exists():
            with vehicle_plan_csv.open(encoding="utf-8") as source:
                for row in csv.DictReader(source):
                    vehicle_id = row["vehicle_id"]
                    initial_parking = str(row.get("initial_parking") or "")
                    try:
                        raw_candidates = json.loads(
                            str(row.get("parking_candidates_json") or "[]")
                        )
                    except (json.JSONDecodeError, TypeError):
                        raw_candidates = []
                    candidates: list[str] = []
                    distances: dict[str, float | None] = {}
                    capacities: dict[str, int | None] = {}
                    bands: dict[str, str] = {}
                    details: dict[str, dict[str, Any]] = {}
                    for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
                        if not isinstance(candidate, dict):
                            continue
                        parking_id = str(candidate.get("parking_id") or "")
                        if not parking_id or parking_id in candidates:
                            continue
                        candidates.append(parking_id)
                        try:
                            distances[parking_id] = float(candidate["distance_metres"])
                        except (KeyError, TypeError, ValueError):
                            distances[parking_id] = None
                        try:
                            capacities[parking_id] = int(candidate["total_capacity"])
                        except (KeyError, TypeError, ValueError):
                            capacities[parking_id] = None
                        bands[parking_id] = str(candidate.get("capacity_band") or "")
                        details[parking_id] = dict(candidate)
                    if initial_parking and initial_parking not in candidates:
                        candidates.insert(0, initial_parking)
                        distances[initial_parking] = None
                        capacities[initial_parking] = None
                        bands[initial_parking] = ""
                        details[initial_parking] = {"parking_id": initial_parking}
                    self.parking_candidates[vehicle_id] = candidates
                    self.parking_candidate_distances[vehicle_id] = distances
                    self.parking_candidate_capacities[vehicle_id] = capacities
                    self.parking_candidate_bands[vehicle_id] = bands
                    self.parking_candidate_details[vehicle_id] = details
                    self.data[vehicle_id] = self._initial_record(
                        vehicle_id,
                        initial_parking,
                    )

    @staticmethod
    def _initial_record(vehicle_id: str, initial_parking: str = "") -> dict[str, Any]:
        return {
            "vehicle_id": vehicle_id,
            "initial_parking": initial_parking,
            "current_parking": initial_parking,
            "final_parking": "",
            "first_parking_arrival_time": "",
            "first_reroute_time": "",
            "parked_time": "",
            "search_time": "",
            "num_parking_changes": 0,
            "num_parking_attempts": 0,
            "attempted_parking_ids": [],
            "rejected_parking_ids": [],
            "parking_decision_count": 0,
            "status": "not_inserted",
        }

    def ensure(self, vehicle_id: str) -> None:
        if vehicle_id not in self.data:
            self.data[vehicle_id] = self._initial_record(vehicle_id)

    def target(self, vehicle_id: str) -> str:
        self.ensure(vehicle_id)
        return str(self.data[vehicle_id]["current_parking"])

    def mark_parking_attempt(
        self,
        vehicle_id: str,
        parking_id: str,
        time: float | None = None,
    ) -> int:
        self.ensure(vehicle_id)
        if (
            time is not None
            and self.data[vehicle_id]["first_parking_arrival_time"] == ""
        ):
            # The access-edge decision is the first parking arrival even when
            # the lot is already full and the vehicle never enters its aisle.
            self.data[vehicle_id]["first_parking_arrival_time"] = float(time)
        attempted = self.data[vehicle_id]["attempted_parking_ids"]
        if parking_id and parking_id not in attempted:
            attempted.append(parking_id)
            self.data[vehicle_id]["num_parking_attempts"] = len(attempted)
        return len(attempted)

    def next_parking_candidate(self, vehicle_id: str) -> str | None:
        self.ensure(vehicle_id)
        excluded = set(self.data[vehicle_id]["attempted_parking_ids"])
        excluded.update(self.data[vehicle_id]["rejected_parking_ids"])
        return next(
            (
                parking_id
                for parking_id in self.parking_candidates.get(vehicle_id, [])
                if parking_id not in excluded
            ),
            None,
        )

    def unattempted_parking_candidates(self, vehicle_id: str) -> list[str]:
        self.ensure(vehicle_id)
        excluded = set(self.data[vehicle_id]["attempted_parking_ids"])
        excluded.update(self.data[vehicle_id]["rejected_parking_ids"])
        return [
            parking_id
            for parking_id in self.parking_candidates.get(vehicle_id, [])
            if parking_id not in excluded
        ]

    def mark_candidate_rejected(self, vehicle_id: str, parking_id: str) -> None:
        """Remember a remotely known-full or unreachable lot without counting a visit."""
        self.ensure(vehicle_id)
        rejected = self.data[vehicle_id]["rejected_parking_ids"]
        if parking_id and parking_id not in rejected:
            rejected.append(parking_id)

    def next_parking_decision_index(self, vehicle_id: str) -> int:
        self.ensure(vehicle_id)
        self.data[vehicle_id]["parking_decision_count"] += 1
        return int(self.data[vehicle_id]["parking_decision_count"])

    def parking_candidate_detail(
        self,
        vehicle_id: str,
        parking_id: str,
    ) -> dict[str, Any]:
        return dict(
            self.parking_candidate_details.get(vehicle_id, {}).get(parking_id) or {}
        )

    def parking_candidate_distance(
        self,
        vehicle_id: str,
        parking_id: str,
    ) -> float | None:
        return self.parking_candidate_distances.get(vehicle_id, {}).get(parking_id)

    def parking_candidate_capacity(
        self,
        vehicle_id: str,
        parking_id: str,
    ) -> int | None:
        return self.parking_candidate_capacities.get(vehicle_id, {}).get(parking_id)

    def parking_candidate_band(self, vehicle_id: str, parking_id: str) -> str:
        return self.parking_candidate_bands.get(vehicle_id, {}).get(parking_id, "")

    def current_segment_type(self, vehicle_id: str) -> str | None:
        segment = self._open_segments.get(vehicle_id)
        return str(segment["segment_type"]) if segment else None

    def _close_segment(
        self,
        vehicle_id: str,
        time: float,
        outcome: str = "completed",
    ) -> None:
        segment = self._open_segments.pop(vehicle_id, None)
        if segment is None:
            return
        end_time = max(float(time), float(segment["start_time"]))
        segment["end_time"] = end_time
        segment["duration_seconds"] = end_time - float(segment["start_time"])
        segment["outcome"] = outcome
        self.segments.append(segment)

    def _transition(
        self,
        vehicle_id: str,
        time: float,
        segment_type: str,
        *,
        parking_id: str = "",
        parking_name: str = "",
        physical_parking_id: str = "",
        from_parking_id: str = "",
        to_parking_id: str = "",
    ) -> None:
        self.ensure(vehicle_id)
        current = self._open_segments.get(vehicle_id)
        identity = (
            segment_type,
            parking_id,
            physical_parking_id,
            from_parking_id,
            to_parking_id,
        )
        if current is not None:
            current_identity = tuple(
                str(current.get(key) or "")
                for key in (
                    "segment_type",
                    "parking_id",
                    "physical_parking_id",
                    "from_parking_id",
                    "to_parking_id",
                )
            )
            if current_identity == identity:
                return
            self._close_segment(vehicle_id, time)

        segment_index = self._next_segment_index.get(vehicle_id, 0)
        self._next_segment_index[vehicle_id] = segment_index + 1
        self._open_segments[vehicle_id] = {
            "vehicle_id": vehicle_id,
            "segment_index": segment_index,
            "segment_type": segment_type,
            "parking_id": parking_id,
            "parking_name": parking_name,
            "physical_parking_id": physical_parking_id,
            "from_parking_id": from_parking_id,
            "to_parking_id": to_parking_id,
            "start_time": float(time),
            "end_time": "",
            "duration_seconds": "",
            "outcome": "open",
        }

    def mark_active(
        self,
        vehicle_id: str,
        time: float | None = None,
        parking_name: str = "",
    ) -> None:
        self.ensure(vehicle_id)
        if self.data[vehicle_id]["status"] == "not_inserted":
            self.data[vehicle_id]["status"] = "active"
        target = self.target(vehicle_id)
        active_statuses = {
            "active",
            "assigned_physical_space",
            "searching_inside_parking",
            "between_parkings",
        }
        if (
            time is not None
            and target
            and vehicle_id not in self._open_segments
            and self.data[vehicle_id]["status"] in active_statuses
        ):
            self._transition(
                vehicle_id,
                time,
                "to_parking",
                parking_id=target,
                parking_name=parking_name,
                to_parking_id=target,
            )

    def mark_inside_parking(
        self,
        vehicle_id: str,
        time: float,
        parking_id: str,
        parking_name: str,
    ) -> None:
        self.ensure(vehicle_id)
        if self.data[vehicle_id]["first_parking_arrival_time"] == "":
            self.data[vehicle_id]["first_parking_arrival_time"] = float(time)
        self.data[vehicle_id]["status"] = "searching_inside_parking"
        self._transition(
            vehicle_id,
            time,
            "inside_parking",
            parking_id=parking_id,
            parking_name=parking_name,
        )

    def mark_target_changed(
        self,
        vehicle_id: str,
        time: float,
        new_parking_id: str,
        new_parking_name: str,
    ) -> None:
        """Begin a between-lots segment; safe to call repeatedly in a search loop."""
        self.ensure(vehicle_id)
        old_parking_id = self.target(vehicle_id)
        if old_parking_id == new_parking_id:
            return
        if self.data[vehicle_id]["first_reroute_time"] == "":
            self.data[vehicle_id]["first_reroute_time"] = float(time)
        self.data[vehicle_id]["current_parking"] = new_parking_id
        self.data[vehicle_id]["num_parking_changes"] += 1
        self.data[vehicle_id]["status"] = "between_parkings"
        self._transition(
            vehicle_id,
            time,
            "between_parkings",
            parking_id=new_parking_id,
            parking_name=new_parking_name,
            from_parking_id=old_parking_id,
            to_parking_id=new_parking_id,
        )

    def mark_reroute(self, vehicle_id: str, time: float, new_parking: str) -> None:
        """Record physical-space assignment without misclassifying it as lot search."""
        self.ensure(vehicle_id)
        self.data[vehicle_id]["final_parking"] = new_parking
        self.data[vehicle_id]["status"] = "assigned_physical_space"

    def _search_duration(self, vehicle_id: str) -> float:
        return sum(
            float(segment.get("duration_seconds") or 0)
            for segment in self.segments
            if segment["vehicle_id"] == vehicle_id
            and segment["segment_type"] in SEARCH_SEGMENT_TYPES
        )

    def mark_parked(
        self,
        vehicle_id: str,
        time: float,
        physical_parking_id: str,
        logical_parking_id: str = "",
        parking_name: str = "",
    ) -> None:
        self.ensure(vehicle_id)
        logical_id = logical_parking_id or self.target(vehicle_id)
        self.data[vehicle_id]["parked_time"] = float(time)
        self.data[vehicle_id]["final_parking"] = physical_parking_id
        self.data[vehicle_id]["status"] = "parked"
        self._transition(
            vehicle_id,
            time,
            "parked",
            parking_id=logical_id,
            parking_name=parking_name,
            physical_parking_id=physical_parking_id,
        )
        self.data[vehicle_id]["search_time"] = self._search_duration(vehicle_id)

    def mark_parking_ended(self, vehicle_id: str, time: float) -> None:
        self.ensure(vehicle_id)
        self._close_segment(vehicle_id, time)
        self.data[vehicle_id]["status"] = "completed"

    def mark_unserved(self, vehicle_id: str, time: float | None = None) -> None:
        self.ensure(vehicle_id)
        if time is not None:
            self._close_segment(vehicle_id, time, outcome="unserved")
        self.data[vehicle_id]["search_time"] = self._search_duration(vehicle_id)
        self.data[vehicle_id]["status"] = "unserved"

    def finalize(self, time: float) -> None:
        for vehicle_id in list(self._open_segments):
            self._close_segment(vehicle_id, time, outcome="simulation_ended")
            if self.data[vehicle_id]["search_time"] == "":
                self.data[vehicle_id]["search_time"] = self._search_duration(vehicle_id)

    def write_search_times(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "vehicle_id",
            "initial_parking",
            "final_parking",
            "first_parking_arrival_time",
            "first_reroute_time",
            "parked_time",
            "search_time",
            "num_parking_changes",
            "num_parking_attempts",
            "attempted_parking_ids",
            "rejected_parking_ids",
            "status",
        ]
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for row in self.data.values():
                output_row = {key: row.get(key, "") for key in fields}
                output_row["attempted_parking_ids"] = ";".join(
                    str(value)
                    for value in row.get("attempted_parking_ids") or []
                )
                output_row["rejected_parking_ids"] = ";".join(
                    str(value)
                    for value in row.get("rejected_parking_ids") or []
                )
                writer.writerow(output_row)

    def write_trip_segments(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "vehicle_id",
            "segment_index",
            "segment_type",
            "parking_id",
            "parking_name",
            "physical_parking_id",
            "from_parking_id",
            "to_parking_id",
            "start_time",
            "end_time",
            "duration_seconds",
            "outcome",
        ]
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for row in sorted(
                self.segments,
                key=lambda item: (str(item["vehicle_id"]), int(item["segment_index"])),
            ):
                writer.writerow({key: row.get(key, "") for key in fields})
