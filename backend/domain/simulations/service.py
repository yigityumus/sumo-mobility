"""Simulation run creation, execution, cancellation, and state transitions."""

from __future__ import annotations

import csv
import json
import os
import re
import secrets
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from shared.database import (
    persist_object_artifacts,
    persist_run_artifacts,
    persist_simulation_run,
    read_all_simulation_runs,
    read_simulation_run_metadata,
    read_simulation_runs,
    remove_simulation_run,
    request_simulation_cancel,
    simulation_cancel_requested,
)
from domain.models.store import ModelStoreError, _model_dir, read_model
from shared.object_storage import get_object_storage, run_object_path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASE_SCENARIO_PATH = (
    BACKEND_ROOT / "sumo" / "scenario" / "configuration" / "model_run_template.yaml"
)
RUN_LOCK = threading.Lock()
PROCESS_LOCK = threading.Lock()
# The boolean marks preparation commands that own a separate process group.
# They can be terminated together with any netconvert/polyconvert children.
ACTIVE_SIMULATION_PROCESSES: dict[str, tuple[subprocess.Popen, bool]] = {}
STOP_REQUESTS: set[str] = set()
SIMULATION_PROGRESS_START = 15.0
SIMULATION_PROGRESS_END = 98.0


class SimulationRunNotFoundError(ValueError):
    pass


class SimulationRunActiveError(ValueError):
    pass


class SimulationRunStopError(ValueError):
    pass


class SimulationInterrupted(RuntimeError):
    pass


def _simulation_calendar_window(
    start_at: datetime | None,
    timezone_name: str,
    duration_seconds: int,
) -> tuple[datetime, datetime]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ModelStoreError(f"Unknown simulation timezone: {timezone_name}") from exc

    if start_at is None:
        local_start = datetime.now(zone).replace(second=0, microsecond=0)
    elif start_at.tzinfo is None:
        local_start = start_at.replace(tzinfo=zone)
        # ZoneInfo accepts wall-clock values in the daylight-saving gap. A
        # UTC round trip exposes those nonexistent local times.
        round_trip = local_start.astimezone(timezone.utc).astimezone(zone)
        if round_trip.replace(tzinfo=None) != start_at:
            raise ModelStoreError(
                f"The selected local simulation start does not exist in {timezone_name} "
                "because of a daylight-saving clock change."
            )
    else:
        local_start = start_at.astimezone(zone)

    local_end = (
        local_start.astimezone(timezone.utc) + timedelta(seconds=duration_seconds)
    ).astimezone(zone)
    return local_start, local_end


def _failure_reason(log_path: Path, fallback: str) -> str:
    """Extract the most useful final exception from a failed command log."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fallback

    exception_pattern = re.compile(
        r"(?:^|\b)(?:[\w.]+(?:Error|Exception)|Error):\s*(.+)$"
    )
    for line in reversed(lines):
        match = exception_pattern.search(line.strip())
        if match and match.group(1).strip():
            return match.group(1).strip()
    return fallback


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runs_dir(model_storage_dir: Path, model_id: str) -> Path:
    path = _model_dir(model_storage_dir, model_id) / "simulations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_dir(model_storage_dir: Path, model_id: str, run_id: str) -> Path:
    return _runs_dir(model_storage_dir, model_id) / run_id


def _record_path(model_storage_dir: Path, model_id: str, run_id: str) -> Path:
    return _run_dir(model_storage_dir, model_id, run_id) / "run.json"


def _stop_marker_path(model_storage_dir: Path, model_id: str, run_id: str) -> Path:
    return _run_dir(model_storage_dir, model_id, run_id) / "stop.requested"


def _write_record(model_storage_dir: Path, record: dict[str, Any]) -> None:
    path = _record_path(model_storage_dir, record["model_id"], record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    persist_simulation_run(record, model_storage_dir)
    storage = get_object_storage()
    if storage is not None and record.get("status") != "running":
        storage.write_json(
            run_object_path(record["model_id"], record["id"], "run.json"),
            record,
        )


def read_simulation_run(
    model_storage_dir: Path,
    model_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Read one run record without exposing its filesystem layout to workers."""
    database_record = read_simulation_run_metadata(run_id, model_id)
    if database_record is not None:
        return database_record
    local_record = _read_record(_record_path(model_storage_dir, model_id, run_id))
    if local_record is not None:
        return local_record
    storage = get_object_storage()
    if storage is None:
        return None
    return storage.read_json(run_object_path(model_id, run_id, "run.json"))


def claim_simulation_run(
    model_storage_dir: Path,
    model_id: str,
    run_id: str,
    worker_id: str,
) -> dict[str, Any] | None:
    """Record which worker accepted a delivery and skip terminal redeliveries."""
    with RUN_LOCK:
        record = read_simulation_run(model_storage_dir, model_id, run_id)
        if record is None or str(record.get("model_id")) != str(model_id):
            raise SimulationRunNotFoundError("Simulation run not found.")
        if record.get("status") in {"completed", "failed"}:
            return None
        record["worker_id"] = worker_id
        record["attempt_count"] = max(int(record.get("attempt_count") or 0), 0) + 1
        record["last_attempt_started_at"] = _now_iso()
        record["message"] = "Simulation worker accepted the run."
        _write_record(model_storage_dir, record)
        return record


def mark_simulation_queue_failure(
    model_storage_dir: Path,
    model_id: str,
    run_id: str,
    reason: str,
) -> dict[str, Any] | None:
    """Make a failed enqueue visible instead of leaving a run queued forever."""
    with RUN_LOCK:
        record = read_simulation_run(model_storage_dir, model_id, run_id)
        if record is None or record.get("status") not in {"queued", "running"}:
            return record
        record["status"] = "failed"
        record["message"] = reason
        record["failure_reason"] = reason
        record["progress_phase"] = "queue_failed"
        record["estimated_remaining_seconds"] = None
        record["completed_at"] = _now_iso()
        _write_record(model_storage_dir, record)
        return record


def _positive_capacity(value: Any) -> int | None:
    try:
        capacity = int(float(value))
    except (TypeError, ValueError):
        return None
    return capacity if capacity > 0 else None


def _selected_parking_config(
    model: dict[str, Any],
    run_dir: Path,
    *,
    required: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected_ids = [str(value) for value in model.get("selectedParkingIds") or []]
    if not selected_ids:
        if not required:
            return {"parking_areas": []}, []
        raise ModelStoreError(
            "This model has no selected parking areas. Select and save at least one parking area first."
        )

    features = {
        str(feature.get("id") or ""): feature
        for feature in (model.get("parkingAreas") or {}).get("features", [])
        if isinstance(feature, dict)
    }
    specs = model.get("parkingSpecs") or {}
    parking_directory = run_dir / "inputs" / "parking"
    parking_directory.mkdir(parents=True, exist_ok=True)
    parking_config: list[dict[str, Any]] = []
    snapshot: list[dict[str, Any]] = []

    for selected_id in selected_ids:
        match = re.fullmatch(r"way/(\d+)", selected_id)
        if not match:
            raise ModelStoreError(
                f"Selected parking '{selected_id}' is not an OSM way. "
                "Parking relations are not supported by lane discovery yet."
            )
        osm_way_id = int(match.group(1))
        logical_id = f"parking_osm_{osm_way_id}"
        spec = specs.get(selected_id) if isinstance(specs, dict) else None
        spec = spec if isinstance(spec, dict) else {}
        feature = features.get(selected_id) or {}
        tags = (feature.get("properties") or {}).get("tags") or {}
        name = str(
            spec.get("name")
            or tags.get("name")
            or f"Parking {osm_way_id}"
        )
        configured_capacity = _positive_capacity(spec.get("capacity"))
        original_capacity = _positive_capacity(spec.get("originalCapacity"))
        safe_stem = f"parking_{osm_way_id}"
        additional_path = parking_directory / f"{safe_stem}.add.xml"
        report_path = parking_directory / f"{safe_stem}_report.csv"
        capacity_config: dict[str, Any] = {
            "value": configured_capacity,
            "source": str(spec.get("capacitySource") or "model"),
            "original_capacity": original_capacity,
            "original_capacity_source": str(
                spec.get("originalCapacitySource") or "model"
            ),
            "space_length": 2.3,
        }
        parking_config.append({
            "id": logical_id,
            "model_parking_id": selected_id,
            "name": name,
            "enabled": True,
            "osm_way_id": osm_way_id,
            "parking_id_prefix": logical_id,
            "additional_path": str(additional_path.resolve()),
            "report_path": str(report_path.resolve()),
            "lane_discovery": {
                "minimum_way_inside_ratio": 0.5,
                "minimum_lane_inside_ratio": 0.5,
                "parking_buffer_metres": 3.0,
                "minimum_lane_length": 3.0,
                "nearest_access_lane_metres": 150.0,
            },
            "capacity": capacity_config,
        })
        snapshot.append({
            "id": logical_id,
            "model_parking_id": selected_id,
            "osm_way_id": osm_way_id,
            "name": name,
            "configured_capacity": configured_capacity or original_capacity,
            "capacity_source": str(
                spec.get("capacitySource")
                or spec.get("originalCapacitySource")
                or "calculated_during_run"
            ),
            "generated_capacity": None,
            "report_path": str(report_path.resolve()),
        })

    return {"parking_areas": parking_config}, snapshot


def _snapshot_model_inputs(
    model_storage_dir: Path,
    model: dict[str, Any],
    run_dir: Path,
    *,
    require_parking: bool = True,
    source_osm_path: Path | None = None,
) -> list[dict[str, Any]]:
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_osm_path or (
        _model_dir(model_storage_dir, str(model["id"])) / "source.osm.xml"
    )
    if not source_path.is_file():
        raise ModelStoreError(
            "This model has no cached source OSM file. Re-save the model or fetch its map data first."
        )
    shutil.copy2(source_path, inputs_dir / "source.osm.xml")
    (run_dir / "model.snapshot.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    parking_config, snapshot = _selected_parking_config(
        model,
        run_dir,
        required=require_parking,
    )
    (run_dir / "parking_areas.yaml").write_text(
        yaml.safe_dump(parking_config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (run_dir / "parking_areas.snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _annotate_queue_positions(
    records: list[dict[str, Any]],
    all_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Add global FIFO positions without persisting derived queue metadata."""
    queue_records = all_records if all_records is not None else records
    waiting = sorted(
        (
            record
            for record in queue_records
            if record.get("status") == "queued"
            and not record.get("stop_requested_at")
        ),
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("id") or ""),
        ),
    )
    positions = {
        str(record.get("id") or ""): index
        for index, record in enumerate(waiting, start=1)
    }
    annotated: list[dict[str, Any]] = []
    for source in records:
        record = dict(source)
        queue_position = positions.get(str(record.get("id") or ""))
        record["queue_position"] = queue_position
        record["queued_ahead"] = queue_position - 1 if queue_position is not None else None
        annotated.append(record)
    return annotated


def list_simulation_runs(model_storage_dir: Path, model_id: str) -> list[dict[str, Any]]:
    database_records = read_simulation_runs(model_id)
    records: list[dict[str, Any]] = []
    if database_records is not None:
        record_sources = [
            (record, _record_path(model_storage_dir, model_id, str(record.get("id") or "")))
            for record in database_records
        ]
    else:
        record_sources = []
        for path in _runs_dir(model_storage_dir, model_id).glob("*/run.json"):
            record = _read_record(path)
            if record is not None:
                record_sources.append((record, path))

    for record, path in record_sources:
        if record.get("status") == "failed" and not record.get("failure_reason"):
            fallback = str(record.get("message") or "Simulation failed.")
            record["failure_reason"] = _failure_reason(
                path.parent / "simulation.log",
                fallback,
            )
        records.append(record)
    all_database_records = read_all_simulation_runs()
    annotated = _annotate_queue_positions(records, all_database_records)
    return sorted(
        annotated,
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )


def delete_simulation_run(model_storage_dir: Path, model_id: str, run_id: str) -> None:
    try:
        safe_run_id = str(uuid.UUID(str(run_id)))
    except (ValueError, AttributeError) as exc:
        raise SimulationRunNotFoundError("Simulation run not found.") from exc

    run_directory = _model_dir(model_storage_dir, model_id) / "simulations" / safe_run_id
    record = read_simulation_run(model_storage_dir, model_id, safe_run_id)
    if record is None or str(record.get("model_id")) != str(model_id):
        raise SimulationRunNotFoundError("Simulation run not found.")

    if record.get("status") in {"queued", "running"}:
        raise SimulationRunActiveError("A queued or running simulation cannot be deleted.")

    storage = get_object_storage()
    if storage is not None:
        storage.delete_prefix(run_object_path(model_id, safe_run_id))
    if run_directory.is_dir():
        shutil.rmtree(run_directory)
    remove_simulation_run(safe_run_id)


def request_simulation_stop(
    model_storage_dir: Path,
    model_id: str,
    run_id: str,
) -> dict[str, Any]:
    try:
        safe_run_id = str(uuid.UUID(str(run_id)))
    except (ValueError, AttributeError) as exc:
        raise SimulationRunNotFoundError("Simulation run not found.") from exc

    record = read_simulation_run(model_storage_dir, model_id, safe_run_id)
    if record is None or str(record.get("model_id")) != str(model_id):
        raise SimulationRunNotFoundError("Simulation run not found.")
    if record.get("status") == "running" and record.get("mode") != "sumo":
        raise SimulationRunStopError("Only background SUMO simulations can be stopped from the website.")
    if record.get("status") not in {"queued", "running"}:
        raise SimulationRunStopError("This simulation is no longer running.")
    if record.get("stop_requested_at"):
        return record

    queued = record.get("status") == "queued"

    with PROCESS_LOCK:
        STOP_REQUESTS.add(safe_run_id)
        active_process = ACTIVE_SIMULATION_PROCESSES.get(safe_run_id)

    database_record = request_simulation_cancel(safe_run_id, model_id)
    if database_record is not None:
        record = database_record
    else:
        record["message"] = "Stopping simulation."
        record["stop_requested_at"] = _now_iso()
        _write_record(model_storage_dir, record)

    if queued and active_process is None:
        # The durable RabbitMQ delivery cannot be deleted selectively. Marking
        # the record terminal removes it from the visible queue immediately;
        # when the worker later receives the delivery, it recognizes the
        # terminal record and acknowledges it without starting SUMO.
        record["status"] = "failed"
        record["message"] = "Removed from the simulation queue by the user."
        record["failure_reason"] = "Removed from queue"
        record["progress_phase"] = "interrupted"
        record["estimated_remaining_seconds"] = None
        record["completed_at"] = _now_iso()
        _write_record(model_storage_dir, record)
    marker_path = _stop_marker_path(
        model_storage_dir,
        model_id,
        safe_run_id,
    )
    marker_path.write_text(record["stop_requested_at"], encoding="utf-8")

    if active_process is not None:
        process, terminate_process_group = active_process
    else:
        process, terminate_process_group = None, False
    if process is not None and process.poll() is None:
        try:
            if terminate_process_group and hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGTERM)
            elif terminate_process_group:
                process.terminate()
            else:
                # Let the controller's finally block close TraCI and flush
                # all partial simulation outputs before it exits.
                process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass
    return record


def _stop_requested(run_id: str, marker_path: Path | None = None) -> bool:
    with PROCESS_LOCK:
        requested_in_process = run_id in STOP_REQUESTS
    return (
        requested_in_process
        or bool(marker_path and marker_path.is_file())
        or simulation_cancel_requested(run_id)
    )


def _raise_if_stop_requested(run_id: str, marker_path: Path | None = None) -> None:
    if _stop_requested(run_id, marker_path):
        raise SimulationInterrupted("User Interruption")


def _residential_origin_building_ids(
    model: dict[str, Any],
    classification_id: str | None,
) -> set[str]:
    """Return selected buildings assigned to a type named Residential."""
    if not classification_id:
        return set()
    classification = next(
        (
            item
            for item in model.get("buildingClassifications") or []
            if str(item.get("id")) == str(classification_id)
        ),
        None,
    )
    if not classification:
        return set()
    residential_type_ids = {
        str(item.get("id"))
        for item in classification.get("types") or []
        if " ".join(str(item.get("name") or "").split()).casefold()
        == "residential"
    }
    if not residential_type_ids:
        return set()
    selected_ids = {str(value) for value in model.get("selectedBuildingIds") or []}
    assignments = classification.get("assignments") or {}
    return {
        building_id
        for building_id in selected_ids
        if str(assignments.get(building_id) or "") in residential_type_ids
    }


def _vehicle_origin_allocation_snapshot(
    model: dict[str, Any],
    vehicle_count: int,
    requested: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    points = [
        point for point in (model.get("vehicleGenerationPoints") or [])
        if isinstance(point, dict) and str(point.get("id") or "").strip()
    ]
    if not points:
        if requested:
            raise ModelStoreError(
                "Vehicle origin allocations were supplied, but the model has no saved vehicle generation points."
            )
        return []

    point_ids = [str(point["id"]) for point in points]
    if len(point_ids) != len(set(point_ids)):
        raise ModelStoreError("Saved vehicle generation point IDs must be unique.")

    if requested is None:
        base, remainder = divmod(vehicle_count, len(points))
        count_by_id = {
            point_id: base + (1 if index < remainder else 0)
            for index, point_id in enumerate(point_ids)
        }
    else:
        count_by_id = {
            str(item.get("origin_id") or ""): int(item.get("vehicle_count") or 0)
            for item in requested
            if isinstance(item, dict)
        }
        if set(count_by_id) != set(point_ids):
            missing = sorted(set(point_ids) - set(count_by_id))
            unknown = sorted(set(count_by_id) - set(point_ids))
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise ModelStoreError(
                "Vehicle origin allocations must match the model's saved generation points"
                + (f" ({'; '.join(details)})" if details else ".")
            )
        if any(count < 0 for count in count_by_id.values()):
            raise ModelStoreError("Vehicle origin allocation counts cannot be negative.")
        allocated = sum(count_by_id.values())
        if allocated != vehicle_count:
            raise ModelStoreError(
                "Vehicle origin allocation counts must add up to the vehicle total "
                f"({allocated} != {vehicle_count})."
            )

    return [{
        "origin_id": str(point["id"]),
        "origin_name": str(point.get("name") or f"Vehicle origin {index + 1}"),
        "vehicle_count": count_by_id[str(point["id"])],
        "percentage": (
            round(count_by_id[str(point["id"])] * 100 / vehicle_count, 6)
            if vehicle_count > 0
            else 0.0
        ),
    } for index, point in enumerate(points)]


def create_simulation_run(
    model_storage_dir: Path,
    model: dict[str, Any],
    *,
    vehicle_count: int,
    pedestrian_count: int,
    duration_hours: int,
    mode: str,
    vehicle_traffic_model: str = "normal",
    pedestrian_traffic_model: str = "linear",
    vehicle_fourier_parameters: dict[str, Any] | None = None,
    pedestrian_fourier_parameters: dict[str, Any] | None = None,
    parking_choice: dict[str, Any] | None = None,
    total_people: int | None = None,
    vehicle_percentage: int | None = None,
    building_classification_id: str | None = None,
    residential_pedestrian_count: int = 0,
    public_transport_pedestrian_count: int = 0,
    simulation_start_at: datetime | None = None,
    simulation_timezone: str = "Europe/Paris",
    pedestrian_model: str = "striping",
    diagnostic_tracing: bool = False,
    random_seed: int | None = None,
    vehicle_origin_allocations: list[dict[str, Any]] | None = None,
    calibration: dict[str, Any] | None = None,
    source_osm_path: Path | None = None,
) -> dict[str, Any]:
    model_id = str(model.get("id") or "").strip()
    if not model_id:
        raise ModelStoreError("Model id is required.")
    residential_pedestrian_count = int(residential_pedestrian_count)
    public_transport_pedestrian_count = int(public_transport_pedestrian_count)
    if residential_pedestrian_count + public_transport_pedestrian_count != pedestrian_count:
        raise ModelStoreError(
            "Residential and public-transport pedestrian counts must add up to "
            "the independently generated pedestrian count."
        )
    if public_transport_pedestrian_count > 0 and not (
        model.get("publicTransportOrigins") or []
    ):
        raise ModelStoreError(
            "Public-transport pedestrian demand requires at least one saved "
            "Public Transportation Origin."
        )
    residential_building_ids = _residential_origin_building_ids(
        model,
        building_classification_id,
    )
    if residential_pedestrian_count > 0 and not residential_building_ids:
        raise ModelStoreError(
            "Residential pedestrian demand requires the selected classification to "
            "contain a type named 'Residential' with at least one selected building "
            "assigned to it."
        )

    vehicle_origin_allocation_snapshot = _vehicle_origin_allocation_snapshot(
        model,
        vehicle_count,
        vehicle_origin_allocations,
    )

    duration_seconds = duration_hours * 3600
    calendar_start, calendar_end = _simulation_calendar_window(
        simulation_start_at,
        simulation_timezone,
        duration_seconds,
    )
    run_id = str(uuid.uuid4())
    run_random_seed = int(
        random_seed
        if random_seed is not None
        else secrets.randbelow(2_147_483_646) + 1
    )
    run_dir = _run_dir(model_storage_dir, model_id, run_id)
    parking_snapshot = _snapshot_model_inputs(
        model_storage_dir,
        model,
        run_dir,
        require_parking=vehicle_count > 0,
        source_osm_path=source_osm_path,
    )
    record = {
        "id": run_id,
        "model_id": model_id,
        "model_name": model.get("name") or "Unnamed model",
        "status": "queued",
        "vehicle_count": vehicle_count,
        "pedestrian_count": pedestrian_count,
        "total_people": total_people if total_people is not None else vehicle_count + pedestrian_count,
        "vehicle_percentage": vehicle_percentage,
        "building_classification_id": building_classification_id,
        "residential_pedestrian_count": residential_pedestrian_count,
        "public_transport_pedestrian_count": public_transport_pedestrian_count,
        "parked_car_pedestrian_count": vehicle_count,
        "pedestrian_source_counts": {
            "residential": residential_pedestrian_count,
            "public_transport": public_transport_pedestrian_count,
            "parked_cars": vehicle_count,
        },
        "residential_origin_building_count": len(residential_building_ids),
        "person_based_demand": True,
        "duration_hours": duration_hours,
        "duration_seconds": duration_seconds,
        "simulation_start_at": calendar_start.isoformat(timespec="minutes"),
        "simulation_end_at": calendar_end.isoformat(timespec="minutes"),
        "simulation_timezone": simulation_timezone,
        "mode": mode,
        "pedestrian_model": pedestrian_model,
        "diagnostic_tracing": bool(diagnostic_tracing),
        "random_seed": run_random_seed,
        "calibration": calibration,
        "vehicle_traffic_model": vehicle_traffic_model,
        "pedestrian_traffic_model": pedestrian_traffic_model,
        "vehicle_fourier_parameters": vehicle_fourier_parameters or {},
        "pedestrian_fourier_parameters": pedestrian_fourier_parameters or {},
        "parking_choice": parking_choice or {},
        "progress_percent": 0.0,
        "progress_phase": "queued",
        "simulated_seconds": 0.0,
        "estimated_remaining_seconds": None,
        "planned_agents": vehicle_count + pedestrian_count,
        "completed_agents": 0,
        "remaining_agents": vehicle_count + pedestrian_count,
        "active_agents": 0,
        "created_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
        "message": "Waiting for an available simulation worker. Runs execute one at a time.",
        "failure_reason": None,
        "output_directory": None,
        "log_file": None,
        "parking_areas": parking_snapshot,
        "parking_area_count": len(parking_snapshot),
        "detectors": model.get("detectors") or [],
        "detector_count": len(model.get("detectors") or []),
        "public_transport_origin_count": len(model.get("publicTransportOrigins") or []),
        "vehicle_generation_points": model.get("vehicleGenerationPoints") or [],
        "vehicle_generation_point_count": len(model.get("vehicleGenerationPoints") or []),
        "vehicle_origin_allocations": vehicle_origin_allocation_snapshot,
    }
    _write_record(model_storage_dir, record)
    storage = get_object_storage()
    if storage is not None:
        uploaded = storage.upload_tree(run_dir, run_object_path(model_id, run_id))
        persist_object_artifacts(run_id, [item.__dict__ for item in uploaded])
    return record


def update_simulation_calibration(
    model_storage_dir: Path,
    model_id: str,
    run_id: str,
    calibration: dict[str, Any],
) -> dict[str, Any]:
    """Attach an iteration result to a terminal run and persist the snapshot."""
    with RUN_LOCK:
        record = read_simulation_run(model_storage_dir, model_id, run_id)
        if record is None:
            raise SimulationRunNotFoundError("Simulation run not found.")
        record["calibration"] = calibration
        _write_record(model_storage_dir, record)
        return record


def _scenario_for_run(record: dict[str, Any], run_dir: Path) -> Path:
    scenario = yaml.safe_load(BASE_SCENARIO_PATH.read_text(encoding="utf-8")) or {}
    simulation = scenario.setdefault("simulation", {})
    simulation["begin"] = 0
    simulation["end"] = record["duration_seconds"]
    simulation["sumo_binary"] = record["mode"]
    simulation["calendar_start_at"] = record.get("simulation_start_at")
    simulation["calendar_end_at"] = record.get("simulation_end_at")
    simulation["timezone"] = record.get("simulation_timezone") or "Europe/Paris"
    simulation["pedestrian_model"] = record.get("pedestrian_model") or "striping"
    scenario["demand_totals"] = {
        "vehicles": record["vehicle_count"],
        "pedestrians": record["pedestrian_count"],
    }
    scenario["person_based_demand"] = bool(record.get("person_based_demand"))
    controller = scenario.setdefault("controller", {})
    controller["diagnostic_tracing"] = bool(record.get("diagnostic_tracing", False))
    controller["random_seed"] = int(record.get("random_seed") or 42)
    controller["parking_choice"] = {
        **(controller.get("parking_choice") or {}),
        **(record.get("parking_choice") or {}),
        "weights": {
            **((controller.get("parking_choice") or {}).get("weights") or {}),
            **((record.get("parking_choice") or {}).get("weights") or {}),
        },
    }
    scenario["building_classification_id"] = record.get("building_classification_id")
    scenario["pedestrian_source_counts"] = {
        "residential": int(record.get("residential_pedestrian_count") or 0),
        "public_transport": int(
            record.get("public_transport_pedestrian_count")
            if record.get("public_transport_pedestrian_count") is not None
            else record.get("pedestrian_count") or 0
        ),
        "parked_cars": int(record.get("vehicle_count") or 0),
    }
    scenario["traffic_models"] = {
        "vehicles": record.get("vehicle_traffic_model", "linear"),
        "pedestrians": record.get("pedestrian_traffic_model", "linear"),
    }
    scenario["traffic_model_parameters"] = {
        "vehicles": record.get("vehicle_fourier_parameters") or {},
        "pedestrians": record.get("pedestrian_fourier_parameters") or {},
    }
    scenario["vehicle_generation_points"] = record.get("vehicle_generation_points") or []
    scenario["vehicle_origin_allocations"] = record.get("vehicle_origin_allocations") or []

    path = run_dir / "inputs" / "scenario.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    return path


def _refresh_generated_capacities(record: dict[str, Any], run_dir: Path) -> None:
    snapshots = record.get("parking_areas") or []
    for parking in snapshots:
        report_path = Path(str(parking.get("report_path") or ""))
        if not report_path.is_file():
            continue
        total = 0
        with report_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                total += int(float(row.get("capacity") or 0))
        parking["generated_capacity"] = total
    (run_dir / "parking_areas.snapshot.json").write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _command_environment() -> dict[str, str]:
    environment = os.environ.copy()
    python_paths = [str(BACKEND_ROOT)]
    sumo_tools = Path(os.environ.get("SUMO_HOME", "/usr/share/sumo")) / "tools"
    if sumo_tools.is_dir():
        python_paths.append(str(sumo_tools))
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return environment


def _run_command(
    command: list[str],
    log_file,
    run_id: str,
    stop_marker_path: Path,
) -> None:
    log_file.write(f"\n$ {' '.join(command)}\n")
    log_file.flush()
    process = subprocess.Popen(
        command,
        cwd=BACKEND_ROOT,
        env=_command_environment(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    active_process = (process, True)
    with PROCESS_LOCK:
        ACTIVE_SIMULATION_PROCESSES[run_id] = active_process
    try:
        termination_sent = False
        while process.poll() is None:
            if _stop_requested(run_id, stop_marker_path) and not termination_sent:
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
                termination_sent = True
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
    finally:
        with PROCESS_LOCK:
            if ACTIVE_SIMULATION_PROCESSES.get(run_id) == active_process:
                ACTIVE_SIMULATION_PROCESSES.pop(run_id, None)

    if _stop_requested(run_id, stop_marker_path):
        raise SimulationInterrupted("User Interruption")
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def _read_progress(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _update_run_progress(
    model_storage_dir: Path,
    record: dict[str, Any],
    progress_path: Path,
    simulation_started: float,
) -> None:
    progress = _read_progress(progress_path)
    if progress is None:
        return

    stop_requested = _stop_requested(
        str(record.get("id") or ""),
        _stop_marker_path(
            model_storage_dir,
            str(record.get("model_id") or ""),
            str(record.get("id") or ""),
        ),
    )

    simulated_seconds = max(
        float(progress.get("simulated_seconds") or 0),
        0.0,
    )
    simulation_progress_percent = min(
        max(float(progress.get("progress_percent") or 0), 0.0),
        100.0,
    )
    progress_phase = str(progress.get("phase") or "demand")
    planned_agents = max(int(progress.get("planned_agents") or 0), 0)
    completed_agents = min(
        max(int(progress.get("completed_agents") or 0), 0),
        planned_agents,
    )
    remaining_agents = max(
        int(progress.get("remaining_agents") or 0),
        0,
    )
    active_agents = max(int(progress.get("active_agents") or 0), 0)
    elapsed_seconds = max(time.monotonic() - simulation_started, 0.0)
    estimated_remaining = None
    if 0 < simulation_progress_percent < 100:
        estimated_remaining = (
            elapsed_seconds
            * (100 - simulation_progress_percent)
            / simulation_progress_percent
        )
    elif simulation_progress_percent >= 100:
        estimated_remaining = 0.0

    overall_progress_percent = SIMULATION_PROGRESS_START + (
        simulation_progress_percent
        / 100.0
        * (SIMULATION_PROGRESS_END - SIMULATION_PROGRESS_START)
    )
    next_percent = round(overall_progress_percent, 1)
    next_simulated = round(simulated_seconds, 1)
    next_remaining = round(estimated_remaining) if estimated_remaining is not None else None
    if (
        record.get("progress_percent") == next_percent
        and record.get("simulated_seconds") == next_simulated
        and record.get("estimated_remaining_seconds") == next_remaining
        and record.get("progress_phase") == progress_phase
        and record.get("completed_agents") == completed_agents
        and record.get("remaining_agents") == remaining_agents
        and record.get("active_agents") == active_agents
        and (not stop_requested or record.get("stop_requested_at"))
    ):
        return

    record["progress_percent"] = next_percent
    record["simulated_seconds"] = next_simulated
    record["estimated_remaining_seconds"] = next_remaining
    record["progress_phase"] = progress_phase
    record["planned_agents"] = planned_agents
    record["completed_agents"] = completed_agents
    record["remaining_agents"] = remaining_agents
    record["active_agents"] = active_agents
    record["worker_heartbeat_at"] = _now_iso()
    if stop_requested:
        # Keep the stop state visible while the controller is shutting down;
        # otherwise a concurrent progress write could overwrite the API update.
        record["stop_requested_at"] = record.get("stop_requested_at") or _now_iso()
        record["message"] = "Stopping simulation."
    elif progress_phase == "finishing":
        record["message"] = (
            f"Demand window complete; finishing {remaining_agents} remaining agent"
            f"{'s' if remaining_agents != 1 else ''}."
        )
    elif progress_phase == "demand":
        record["message"] = "Running simulation."
    _write_record(model_storage_dir, record)


def _run_simulation_command(
    command: list[str],
    log_file,
    model_storage_dir: Path,
    record: dict[str, Any],
    progress_path: Path,
    run_id: str,
    stop_marker_path: Path,
) -> None:
    log_file.write(f"\n$ {' '.join(command)}\n")
    log_file.flush()
    process = subprocess.Popen(
        command,
        cwd=BACKEND_ROOT,
        env=_command_environment(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    active_process = (process, False)
    with PROCESS_LOCK:
        ACTIVE_SIMULATION_PROCESSES[run_id] = active_process
    simulation_started = time.monotonic()
    interruption_sent = False
    try:
        while process.poll() is None:
            if _stop_requested(run_id, stop_marker_path) and not interruption_sent:
                try:
                    process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                interruption_sent = True
            _update_run_progress(
                model_storage_dir,
                record,
                progress_path,
                simulation_started,
            )
            time.sleep(0.5)
    finally:
        with PROCESS_LOCK:
            if ACTIVE_SIMULATION_PROCESSES.get(run_id) == active_process:
                ACTIVE_SIMULATION_PROCESSES.pop(run_id, None)

    _update_run_progress(
        model_storage_dir,
        record,
        progress_path,
        simulation_started,
    )
    if _stop_requested(run_id, stop_marker_path):
        raise SimulationInterrupted("User Interruption")
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def execute_simulation_run(model_storage_dir: Path, model_id: str, run_id: str) -> None:
    record_path = _record_path(model_storage_dir, model_id, run_id)
    record = _read_record(record_path)
    if record is None:
        return
    if record.get("status") in {"completed", "failed"}:
        return

    run_dir = record_path.parent
    log_path = run_dir / "simulation.log"
    progress_path = run_dir / "progress.json"
    output_dir = run_dir / "outputs"
    stop_marker_path = _stop_marker_path(model_storage_dir, model_id, run_id)
    record["log_file"] = str(log_path)
    record["output_directory"] = str(output_dir)

    with RUN_LOCK:
        record["status"] = "running"
        record["started_at"] = record.get("started_at") or _now_iso()
        record["last_attempt_started_at"] = _now_iso()
        record["worker_heartbeat_at"] = _now_iso()
        record["progress_percent"] = 1.0
        record["progress_phase"] = "preparing_snapshot"
        record["message"] = "Preparing the saved model snapshot."
        _write_record(model_storage_dir, record)

        try:
            _raise_if_stop_requested(run_id, stop_marker_path)
            if not (run_dir / "model.snapshot.json").is_file():
                model = read_model(model_storage_dir, model_id)
                if model is None:
                    raise ModelStoreError("Model not found while preparing simulation.")
                record["parking_areas"] = _snapshot_model_inputs(
                    model_storage_dir,
                    model,
                    run_dir,
                    require_parking=int(record.get("vehicle_count") or 0) > 0,
                )
                record["parking_area_count"] = len(record["parking_areas"])
            scenario_path = _scenario_for_run(record, run_dir)
            inputs_dir = run_dir / "inputs"
            source_osm_path = inputs_dir / "source.osm.xml"
            compressed_osm_path = inputs_dir / "source.osm.xml.gz"
            network_path = inputs_dir / "model.net.xml.gz"
            polygons_path = inputs_dir / "model.poly.xml.gz"
            parking_config_path = run_dir / "parking_areas.yaml"
            passenger_routes_path = inputs_dir / "passenger.rou.xml"
            pedestrian_routes_path = inputs_dir / "pedestrian.rou.xml"
            vehicle_plan_path = inputs_dir / "vehicle_parking_plan.csv"
            person_plan_path = inputs_dir / "person_plan.csv"
            person_access_path = run_dir / "person_access.snapshot.json"
            sumocfg_path = inputs_dir / "simulation.sumocfg"
            detector_additional_path = inputs_dir / "detectors.add.xml"
            detector_snapshot_path = run_dir / "detectors.snapshot.json"
            detector_output_path = output_dir / "detectors" / "e1.xml"
            e3_detector_output_path = output_dir / "detectors" / "e3.xml"
            pedestrian_zone_output_path = (
                output_dir / "detectors" / "e2_pedestrians.xml"
            )
            build_network_command = [
                sys.executable,
                "-m",
                "sumo.scenario.network.build",
                str(source_osm_path),
                "--force",
                "--allow-passenger-on-delivery",
                "--osm-output",
                str(compressed_osm_path),
                "--network-output",
                str(network_path),
                "--polygon-output",
                str(polygons_path),
            ]
            # Polygon conversion only supplies visual map shapes to SUMO GUI. It
            # is unnecessary for headless simulation and can be expensive on a
            # large OSM extract.
            if record.get("mode") == "sumo-gui":
                build_network_command.insert(6, "--with-polygons")

            commands = [
                build_network_command,
                [
                    sys.executable,
                    "-m",
                    "sumo.scenario.parking.generate",
                    "--parking-config",
                    str(parking_config_path),
                    "--network",
                    str(network_path),
                    "--osm",
                    str(source_osm_path),
                ],
                [
                    sys.executable,
                    "-m",
                    "sumo.scenario.configuration.configure",
                    "--config",
                    str(scenario_path),
                    "--parking-config",
                    str(parking_config_path),
                    "--network",
                    str(network_path),
                ],
                [
                    sys.executable,
                    "-m",
                    "sumo.scenario.detectors.generate",
                    "--model-snapshot",
                    str(run_dir / "model.snapshot.json"),
                    "--network",
                    str(network_path),
                    "--output",
                    str(detector_additional_path),
                    "--detector-output",
                    str(detector_output_path),
                    "--e3-detector-output",
                    str(e3_detector_output_path),
                    "--pedestrian-zone-output",
                    str(pedestrian_zone_output_path),
                    "--snapshot-output",
                    str(detector_snapshot_path),
                ],
                [
                    sys.executable,
                    "-m",
                    "sumo.scenario.demand.person_access",
                    "--model-snapshot",
                    str(run_dir / "model.snapshot.json"),
                    "--network",
                    str(network_path),
                    "--scenario",
                    str(scenario_path),
                    "--parking-config",
                    str(parking_config_path),
                    "--output",
                    str(person_access_path),
                ],
                [
                    sys.executable,
                    "-m",
                    "sumo.scenario.demand.generate",
                    "--config",
                    str(scenario_path),
                    "--parking-config",
                    str(parking_config_path),
                    "--network",
                    str(network_path),
                    "--person-access-config",
                    str(person_access_path),
                    "--passenger-output",
                    str(passenger_routes_path),
                    "--pedestrian-output",
                    str(pedestrian_routes_path),
                    "--plan-output",
                    str(vehicle_plan_path),
                    "--person-plan-output",
                    str(person_plan_path),
                ],
                [
                    sys.executable,
                    "-m",
                    "sumo.scenario.configuration.generate_sumocfg",
                    "--config",
                    str(scenario_path),
                    "--output",
                    str(sumocfg_path),
                    "--network",
                    str(network_path),
                    "--polygons",
                    str(polygons_path),
                    "--passenger-routes",
                    str(passenger_routes_path),
                    "--pedestrian-routes",
                    str(pedestrian_routes_path),
                    "--parking-config",
                    str(parking_config_path),
                    "--detectors",
                    str(detector_additional_path),
                ],
                [
                    sys.executable,
                    "-m",
                    "sumo.controller.main",
                    "--config",
                    str(scenario_path),
                    "--output-dir",
                    str(output_dir),
                    "--progress-file",
                    str(progress_path),
                    "--sumocfg",
                    str(sumocfg_path),
                    "--parking-config",
                    str(parking_config_path),
                    "--vehicle-plan",
                    str(vehicle_plan_path),
                    "--person-access-config",
                    str(person_access_path),
                    "--person-plan",
                    str(person_plan_path),
                    "--detector-snapshot",
                    str(detector_snapshot_path),
                ],
            ]
            command_progress = [
                ("building_network", 3.0, "Building the SUMO road and walking network."),
                ("configuring_parking", 6.0, "Generating the selected parking areas."),
                ("configuring_scenario", 8.0, "Configuring routes and simulation settings."),
                ("configuring_detectors", 10.0, "Adding vehicle detectors and pedestrian zones to the network."),
                ("resolving_access", 12.0, "Checking reachable pedestrian entrances and routes."),
                ("generating_demand", 14.0, "Generating vehicles, pedestrians, and departure times."),
                ("writing_configuration", 14.5, "Writing the final SUMO configuration."),
                ("starting_sumo", SIMULATION_PROGRESS_START, "Starting SUMO."),
            ]

            with log_path.open("a", encoding="utf-8") as log_file:
                for index, command in enumerate(commands):
                    _raise_if_stop_requested(run_id, stop_marker_path)
                    progress_phase, progress_percent, progress_message = command_progress[index]
                    record["progress_phase"] = progress_phase
                    record["progress_percent"] = progress_percent
                    record["estimated_remaining_seconds"] = None
                    record["worker_heartbeat_at"] = _now_iso()
                    record["message"] = progress_message
                    _write_record(model_storage_dir, record)
                    if index == len(commands) - 1:
                        _run_simulation_command(
                            command,
                            log_file,
                            model_storage_dir,
                            record,
                            progress_path,
                            run_id,
                            stop_marker_path,
                        )
                    else:
                        _run_command(
                            command,
                            log_file,
                            run_id,
                            stop_marker_path,
                        )
                        _raise_if_stop_requested(run_id, stop_marker_path)
                        if index == 1:
                            _refresh_generated_capacities(record, run_dir)
                            _write_record(model_storage_dir, record)
                        if command[2:4] == ["sumo.scenario.detectors.generate", "--model-snapshot"]:
                            detector_snapshot = _read_record(detector_snapshot_path) or {}
                            record["detectors"] = detector_snapshot.get("detectors") or []
                            record["detector_count"] = int(detector_snapshot.get("logical_count") or 0)
                            record["physical_detector_count"] = int(detector_snapshot.get("physical_count") or 0)
                            _write_record(model_storage_dir, record)
                        if command[2:4] == ["sumo.scenario.demand.person_access", "--model-snapshot"]:
                            access_snapshot = _read_record(person_access_path) or {}
                            record["building_destination_count"] = int(
                                access_snapshot.get("building_count") or 0
                            )
                            origin_counts_by_mode = (
                                access_snapshot.get("origin_counts_by_mode") or {}
                            )
                            record["public_transport_origin_count"] = int(
                                origin_counts_by_mode.get("public_transport") or 0
                            )
                            record["residential_origin_building_count"] = int(
                                origin_counts_by_mode.get("residential") or 0
                            )
                            record["excluded_building_destination_count"] = len(
                                access_snapshot.get("excluded_buildings") or []
                            )
                            record["pedestrian_accessible_parking_count"] = int(
                                access_snapshot.get("parking_access_count") or 0
                            )
                            _write_record(model_storage_dir, record)

            record["progress_phase"] = "finalizing"
            record["progress_percent"] = 99.0
            record["estimated_remaining_seconds"] = None
            record["message"] = "Finalizing analytics and output files."
            record["worker_heartbeat_at"] = _now_iso()
            _write_record(model_storage_dir, record)

            record["status"] = "completed"
            record["message"] = "Simulation completed successfully."
            record["failure_reason"] = None
            record["progress_percent"] = 100.0
            final_progress = _read_progress(progress_path) or {}
            record["simulated_seconds"] = max(
                float(final_progress.get("simulated_seconds") or 0),
                float(record["duration_seconds"]),
            )
            record["estimated_remaining_seconds"] = 0
            record["progress_phase"] = "completed"
            record["planned_agents"] = (
                record["vehicle_count"] + record["pedestrian_count"]
            )
            record["completed_agents"] = record["planned_agents"]
            record["remaining_agents"] = 0
            record["active_agents"] = 0
        except SimulationInterrupted:
            record["status"] = "failed"
            record["estimated_remaining_seconds"] = None
            record["failure_reason"] = "User Interruption"
            record["message"] = "User Interruption"
            record["progress_phase"] = "interrupted"
        except subprocess.CalledProcessError as exc:
            reason = _failure_reason(
                log_path,
                f"Simulation command exited with code {exc.returncode}.",
            )
            record["status"] = "failed"
            record["estimated_remaining_seconds"] = None
            record["failure_reason"] = reason
            record["message"] = reason
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            record["status"] = "failed"
            record["estimated_remaining_seconds"] = None
            record["failure_reason"] = reason
            record["message"] = reason
        finally:
            try:
                _refresh_generated_capacities(record, run_dir)
            except (OSError, TypeError, ValueError):
                # A failed preparation may leave only some parking reports.
                # Preserve the run status even if one partial report is bad.
                pass
            record["completed_at"] = _now_iso()
            if log_path.exists():
                record["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            _write_record(model_storage_dir, record)
            persist_run_artifacts(run_id, run_dir)
            with PROCESS_LOCK:
                ACTIVE_SIMULATION_PROCESSES.pop(run_id, None)
                STOP_REQUESTS.discard(run_id)
