"""Simulation analytics parsing, snapshots, and API payload generation."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from shared.database import (
    read_all_simulation_runs,
    read_artifact_paths,
    read_simulation_run_metadata,
)
from shared.object_storage import get_object_storage, run_object_path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARKING_CONFIG_PATH = BACKEND_ROOT / "config" / "parking" / "parking_areas.yaml"
MAX_OCCUPANCY_POINTS = 900
DETECTOR_COMPARISON_INTERVAL_SECONDS = 15 * 60
ANALYTICS_SNAPSHOT_FILENAME = "analytics.snapshot.json"
ANALYTICS_SNAPSHOT_VERSION = 6
DESTINATION_SELECTION_INTERVAL_SECONDS = 15 * 60
TRIP_SEGMENT_TYPES = (
    "to_parking",
    "inside_parking",
    "between_parkings",
    "parked",
)
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LOG_MESSAGE_PATTERN = re.compile(r"^(warning|error)\s*:\s*(.+)$", re.IGNORECASE)
PYTHON_ERROR_PATTERN = re.compile(
    r"^(?:[\w.]+\.)?([A-Za-z_][\w]*(?:Error|Exception))\s*:\s*(.+)$"
)


class AnalyticsError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _analytics_paths(model_storage_dir: Path):
    yield from model_storage_dir.glob("*/simulations/*/run.json")


def _analytics_available(run_path: Path) -> dict[str, bool]:
    output_dir = run_path.parent / "outputs"
    return {
        "occupancy": (output_dir / "parking_occupancy.csv").is_file(),
        "search_times": (output_dir / "search_times.csv").is_file(),
        "trip_segments": (output_dir / "vehicle_trip_segments.csv").is_file(),
        "detectors": any(
            (output_dir / "detectors" / filename).is_file()
            for filename in ("e1.xml", "e2_pedestrians.xml", "e3.xml")
        ),
        "debug": (run_path.parent / "simulation.log").is_file(),
    }


def _run_summary(
    record: dict[str, Any],
    run_path: Path,
    availability: dict[str, bool] | None = None,
) -> dict[str, Any]:
    availability = availability or _analytics_available(run_path)
    failure_reason = record.get("failure_reason")
    if record.get("status") == "failed" and not failure_reason:
        log_tail = str(record.get("log_tail") or "")
        matches = re.findall(
            r"(?:^|\b)(?:[\w.]+(?:Error|Exception)|Error):\s*(.+)$",
            log_tail,
            flags=re.MULTILINE,
        )
        failure_reason = matches[-1].strip() if matches else record.get("message")
    return {
        "id": record.get("id"),
        "model_id": record.get("model_id"),
        "model_name": record.get("model_name") or "Unnamed model",
        "status": record.get("status") or "unknown",
        "message": record.get("message"),
        "failure_reason": failure_reason,
        "created_at": record.get("created_at"),
        "completed_at": record.get("completed_at"),
        "mode": record.get("mode") or "sumo",
        "vehicle_count": int(record.get("vehicle_count") or 0),
        "pedestrian_count": int(record.get("pedestrian_count") or 0),
        "total_people": int(
            record.get("total_people")
            or int(record.get("vehicle_count") or 0) + int(record.get("pedestrian_count") or 0)
        ),
        "vehicle_percentage": record.get("vehicle_percentage"),
        "building_classification_id": record.get("building_classification_id"),
        "residential_pedestrian_count": int(
            record.get("residential_pedestrian_count") or 0
        ),
        "public_transport_pedestrian_count": int(
            record.get("public_transport_pedestrian_count")
            if record.get("public_transport_pedestrian_count") is not None
            else record.get("pedestrian_count") or 0
        ),
        "parked_car_pedestrian_count": int(
            record.get("parked_car_pedestrian_count")
            if record.get("parked_car_pedestrian_count") is not None
            else record.get("vehicle_count") or 0
        ),
        "pedestrian_source_counts": record.get("pedestrian_source_counts") or {
            "residential": 0,
            "public_transport": int(record.get("pedestrian_count") or 0),
            "parked_cars": int(record.get("vehicle_count") or 0),
        },
        "building_destination_count": int(record.get("building_destination_count") or 0),
        "excluded_building_destination_count": int(
            record.get("excluded_building_destination_count") or 0
        ),
        "pedestrian_accessible_parking_count": int(
            record.get("pedestrian_accessible_parking_count") or 0
        ),
        "duration_hours": int(record.get("duration_hours") or 0),
        "duration_seconds": int(record.get("duration_seconds") or 0),
        "simulation_start_at": record.get("simulation_start_at"),
        "simulation_end_at": record.get("simulation_end_at"),
        "simulation_timezone": record.get("simulation_timezone") or "Europe/Paris",
        "vehicle_traffic_model": record.get("vehicle_traffic_model") or "linear",
        "pedestrian_traffic_model": record.get("pedestrian_traffic_model") or "linear",
        "random_seed": record.get("random_seed"),
        "vehicle_fourier_parameters": record.get("vehicle_fourier_parameters") or {},
        "pedestrian_fourier_parameters": record.get("pedestrian_fourier_parameters") or {},
        "parking_area_count": int(
            record.get("parking_area_count")
            or len(record.get("parking_areas") or [])
        ),
        "parking_areas": record.get("parking_areas") or [],
        "vehicle_origin_allocations": record.get("vehicle_origin_allocations") or [],
        "detector_count": int(record.get("detector_count") or 0),
        "detectors": record.get("detectors") or [],
        "calibration": record.get("calibration"),
        "availability": availability,
    }


def _aggregate_detector_counts(
    points: list[dict[str, Any]],
    interval_seconds: int = DETECTOR_COMPARISON_INTERVAL_SECONDS,
    duration_seconds: int | None = None,
) -> list[dict[str, float]]:
    """Re-bin detector entry counts without discarding the native SUMO series."""
    buckets: dict[int, float] = defaultdict(float)
    for point in points:
        begin = max(float(point.get("begin_seconds") or 0), 0.0)
        original_end = max(float(point.get("end_seconds") or begin), begin)
        source_duration = original_end - begin
        end = original_end
        if duration_seconds is not None:
            if begin >= duration_seconds:
                continue
            end = min(end, float(duration_seconds))
        count = max(float(point.get("entry_count") or 0), 0.0)
        if source_duration <= 0 or end <= begin:
            continue
        bucket_start = int(begin // interval_seconds) * interval_seconds
        while bucket_start < end:
            bucket_end = bucket_start + interval_seconds
            overlap = max(min(end, bucket_end) - max(begin, bucket_start), 0.0)
            if overlap:
                buckets[bucket_start] += count * overlap / source_duration
            bucket_start = bucket_end
    return [
        {
            "begin_seconds": float(begin),
            "end_seconds": float(begin + interval_seconds),
            "interval_count": count,
            "flow_per_hour": count * 3600.0 / interval_seconds,
        }
        for begin, count in sorted(buckets.items())
    ]


def _detector_results(
    e1_output_path: Path,
    e3_output_path: Path,
    pedestrian_zone_output_path: Path,
    snapshot_path: Path,
    comparison_duration_seconds: int | None = None,
) -> dict[str, Any]:
    snapshot = _read_json(snapshot_path) or {}
    definitions = []
    for logical in snapshot.get("detectors") or []:
        detector_type = str(logical.get("type") or "e1")
        if detector_type == "e3":
            measurements = logical.get("measurements") or [{
                "id": str(logical.get("sumo_id") or logical.get("id")),
                "subject": "vehicles",
                "entries": (logical.get("entry") or {}).get("cross_sections") or [],
                "exits": (logical.get("exit") or {}).get("cross_sections") or [],
            }]
            for measurement in measurements:
                subject = str(measurement.get("subject") or "vehicles")
                measurement_type = str(measurement.get("detector_type") or "e3")
                logical_name = logical.get("name") or logical.get("id")
                definitions.append({
                    "id": str(measurement.get("id")),
                    "logical_id": logical.get("id"),
                    "logical_name": logical_name,
                    "label": (
                        logical_name
                        if len(measurements) == 1
                        else f"{logical_name} · {subject.capitalize()}"
                    ),
                    "type": measurement_type,
                    "subject": subject,
                    "period_seconds": logical.get("period_seconds") or 60,
                    "entries": measurement.get("entries") or [],
                    "exits": measurement.get("exits") or [],
                    "physical_detectors": measurement.get("physical_detectors") or [],
                })
            continue
        for physical in logical.get("physical_detectors") or []:
            definition = {
                **physical,
                "logical_id": logical.get("id"),
                "logical_name": logical.get("name") or logical.get("id"),
                "period_seconds": logical.get("period_seconds") or 60,
                "type": "e1",
                "label": (
                    str(logical.get("name") or logical.get("id"))
                    if len(logical.get("physical_detectors") or []) == 1
                    else f"{logical.get('name') or logical.get('id')} · lane {physical.get('lane_index')}"
                ),
            }
            definitions.append(definition)

    series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if e1_output_path.is_file():
        try:
            for _event, element in ET.iterparse(e1_output_path, events=("end",)):
                if element.tag != "interval":
                    continue
                detector_id = str(element.attrib.get("id") or "")
                if detector_id:
                    begin = float(element.attrib.get("begin") or 0)
                    end = float(element.attrib.get("end") or 0)
                    duration = max(end - begin, 1.0)
                    entry_count = int(float(element.attrib.get("nVehEntered") or 0))
                    series[detector_id].append({
                        "begin_seconds": begin,
                        "end_seconds": end,
                        "vehicle_count": int(float(element.attrib.get("nVehEntered") or element.attrib.get("nVehContrib") or 0)),
                        "flow_vehicles_per_hour": float(element.attrib.get("flow") or 0),
                        "entry_count": entry_count,
                        "entry_flow_per_hour": entry_count * 3600.0 / duration,
                        "occupancy_percent": float(element.attrib.get("occupancy") or 0),
                        "mean_speed_metres_per_second": max(0.0, float(element.attrib.get("speed") or 0)),
                        "mean_travel_time_seconds": 0.0,
                        "mean_halts_per_vehicle": 0.0,
                        "mean_time_loss_seconds": 0.0,
                        "vehicles_within": 0,
                    })
                element.clear()
        except (ET.ParseError, OSError, ValueError):
            # Failed/interrupted runs may leave a partial XML document. Keep
            # detector definitions available and return the intervals parsed so far.
            pass
    if e3_output_path.is_file():
        previous_within_by_detector: dict[str, int] = defaultdict(int)
        try:
            for _event, element in ET.iterparse(e3_output_path, events=("end",)):
                if element.tag != "interval":
                    continue
                detector_id = str(element.attrib.get("id") or "")
                if detector_id:
                    begin = float(element.attrib.get("begin") or 0)
                    end = float(element.attrib.get("end") or 0)
                    vehicle_count = int(float(element.attrib.get("vehicleSum") or 0))
                    duration = max(end - begin, 1.0)
                    vehicles_within = int(float(element.attrib.get("vehicleSumWithin") or 0))
                    entry_count = max(
                        vehicle_count
                        + vehicles_within
                        - previous_within_by_detector[detector_id],
                        0,
                    )
                    previous_within_by_detector[detector_id] = vehicles_within
                    series[detector_id].append({
                        "begin_seconds": begin,
                        "end_seconds": end,
                        "vehicle_count": vehicle_count,
                        "flow_vehicles_per_hour": vehicle_count * 3600.0 / duration,
                        "entry_count": entry_count,
                        "entry_flow_per_hour": entry_count * 3600.0 / duration,
                        "occupancy_percent": 0.0,
                        "mean_speed_metres_per_second": max(0.0, float(element.attrib.get("meanSpeed") or 0)),
                        "mean_travel_time_seconds": max(0.0, float(element.attrib.get("meanTravelTime") or 0)),
                        "mean_halts_per_vehicle": max(0.0, float(element.attrib.get("meanHaltsPerVehicle") or 0)),
                        "mean_time_loss_seconds": max(0.0, float(element.attrib.get("meanTimeLoss") or 0)),
                        "vehicles_within": vehicles_within,
                    })
                element.clear()
        except (ET.ParseError, OSError, ValueError):
            pass

    e2_measurement_by_physical_id = {
        str(physical.get("id")): str(definition["id"])
        for definition in definitions
        if definition.get("type") == "e2"
        for physical in definition.get("physical_detectors") or []
        if physical.get("id")
    }
    if pedestrian_zone_output_path.is_file():
        e2_buckets: dict[tuple[str, float, float], dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        try:
            for _event, element in ET.iterparse(
                pedestrian_zone_output_path,
                events=("end",),
            ):
                if element.tag != "interval":
                    continue
                physical_id = str(element.attrib.get("id") or "")
                measurement_id = e2_measurement_by_physical_id.get(physical_id)
                if measurement_id:
                    begin = float(element.attrib.get("begin") or 0)
                    end = float(element.attrib.get("end") or 0)
                    bucket = e2_buckets[(measurement_id, begin, end)]
                    entered = max(float(element.attrib.get("nVehEntered") or 0), 0.0)
                    seen = max(float(element.attrib.get("nVehSeen") or 0), 0.0)
                    # Empty E2 zones report meanSpeed=-1. They must not dilute
                    # the speed from zones that actually observed pedestrians.
                    weight = max(seen, entered, 0.0)
                    bucket["entry_count"] += entered
                    bucket["speed_total"] += max(
                        float(element.attrib.get("meanSpeed") or 0), 0.0
                    ) * weight
                    bucket["weight"] += weight
                    bucket["occupancy_total"] += max(
                        float(element.attrib.get("meanOccupancy") or 0), 0.0
                    )
                    bucket["zone_count"] += 1.0
                element.clear()
        except (ET.ParseError, OSError, ValueError):
            pass
        for (measurement_id, begin, end), bucket in sorted(e2_buckets.items()):
            duration = max(end - begin, 1.0)
            entry_count = int(bucket["entry_count"])
            series[measurement_id].append({
                "begin_seconds": begin,
                "end_seconds": end,
                "vehicle_count": entry_count,
                "flow_vehicles_per_hour": entry_count * 3600.0 / duration,
                "entry_count": entry_count,
                "entry_flow_per_hour": entry_count * 3600.0 / duration,
                "occupancy_percent": (
                    bucket["occupancy_total"] / max(bucket["zone_count"], 1.0)
                ),
                "mean_speed_metres_per_second": (
                    bucket["speed_total"] / max(bucket["weight"], 1.0)
                ),
                "mean_travel_time_seconds": 0.0,
                "mean_halts_per_vehicle": 0.0,
                "mean_time_loss_seconds": 0.0,
                "vehicles_within": 0,
            })
    comparison_series = {
        detector_id: _aggregate_detector_counts(
            points,
            duration_seconds=comparison_duration_seconds,
        )
        for detector_id, points in series.items()
    }
    return {
        "available": (
            e1_output_path.is_file()
            or e3_output_path.is_file()
            or pedestrian_zone_output_path.is_file()
        ),
        "definitions": definitions,
        "series": dict(series),
        "comparison_interval_seconds": DETECTOR_COMPARISON_INTERVAL_SECONDS,
        "comparison_series": comparison_series,
    }


def list_available_analytics_runs(model_storage_dir: Path) -> list[dict[str, Any]]:
    runs = []
    database_records = read_all_simulation_runs()
    if database_records is not None:
        sources = [
            (
                record,
                model_storage_dir
                / str(record.get("model_id") or "")
                / "simulations"
                / str(record.get("id") or "")
                / "run.json",
            )
            for record in database_records
        ]
    else:
        sources = [
            (record, run_path)
            for run_path in _analytics_paths(model_storage_dir)
            if (record := _read_json(run_path)) is not None
        ]

    storage = get_object_storage()
    indexed_paths = read_artifact_paths()
    for record, run_path in sources:
        availability = _analytics_available(run_path)
        run_id = str(record.get("id") or "")
        if indexed_paths is not None:
            object_paths = indexed_paths.get(run_id, set())
        elif storage is not None:
            model_id = str(record.get("model_id") or "")
            object_paths = {
                item.relative_path
                for item in storage.list_prefix(run_object_path(model_id, run_id))
            }
        else:
            object_paths = set()
        if object_paths:
            availability = {
                "occupancy": "outputs/parking_occupancy.csv" in object_paths,
                "search_times": "outputs/search_times.csv" in object_paths,
                "trip_segments": "outputs/vehicle_trip_segments.csv" in object_paths,
                "detectors": bool(
                    {
                        "outputs/detectors/e1.xml",
                        "outputs/detectors/e2_pedestrians.xml",
                        "outputs/detectors/e3.xml",
                    }
                    & object_paths
                ),
                "debug": "simulation.log" in object_paths,
            }
        if not any(availability.values()):
            continue
        runs.append(_run_summary(record, run_path, availability))
    return sorted(runs, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _find_run(model_storage_dir: Path, run_id: str) -> tuple[dict[str, Any], Path]:
    if not run_id or "/" in run_id or "\\" in run_id:
        raise AnalyticsError("Invalid simulation run id.")
    database_record = read_simulation_run_metadata(run_id)
    if database_record is not None:
        model_id = str(database_record.get("model_id") or "")
        run_path = model_storage_dir / model_id / "simulations" / run_id / "run.json"
        if not run_path.is_file():
            run_path.parent.mkdir(parents=True, exist_ok=True)
            run_path.write_text(
                json.dumps(database_record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return database_record, run_path
    for run_path in _analytics_paths(model_storage_dir):
        if run_path.parent.name != run_id:
            continue
        record = _read_json(run_path)
        if record is not None:
            return record, run_path
    raise AnalyticsError("Analytics data was not found.")


def _parking_names(snapshot_path: Path) -> dict[str, str]:
    config_path = snapshot_path if snapshot_path.is_file() else PARKING_CONFIG_PATH
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {
        str(parking.get("id")): str(parking.get("name") or parking.get("id"))
        for parking in config.get("parking_areas", [])
        if parking.get("id")
    }


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _grouped_log_entries(
    path: Path,
) -> dict[str, Any]:
    counters: dict[str, Counter[str]] = {
        "warnings": Counter(),
        "errors": Counter(),
    }
    first_lines: dict[tuple[str, str], int] = {}
    if path.is_file():
        try:
            lines = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            lines = []
        for line_number, raw_line in enumerate(lines, start=1):
            line = ANSI_ESCAPE_PATTERN.sub("", raw_line).strip()
            if not line:
                continue
            match = LOG_MESSAGE_PATTERN.match(line)
            if match:
                category = (
                    "warnings"
                    if match.group(1).lower() == "warning"
                    else "errors"
                )
                message = match.group(2).strip()
            else:
                python_match = PYTHON_ERROR_PATTERN.match(line)
                if not python_match:
                    continue
                category = "errors"
                message = f"{python_match.group(1)}: {python_match.group(2).strip()}"
            if not message:
                continue
            counters[category][message] += 1
            first_lines.setdefault((category, message), line_number)

    def section(category: str) -> dict[str, Any]:
        counter = counters[category].copy()
        display_first_lines = {
            message: first_lines[(category, message)]
            for message in counter
        }
        if category == "warnings":
            aggregate_pattern = re.compile(
                r"^(\d+) total messages of type: (.+)$"
            )
            aggregate_messages = []
            for message in list(counter):
                match = aggregate_pattern.match(message)
                if match:
                    aggregate_messages.append((
                        message,
                        int(match.group(1)),
                        match.group(2),
                    ))
            for summary_message, aggregate_count, template in aggregate_messages:
                summary_occurrences = counter.pop(summary_message, 0)
                first_line = display_first_lines.pop(
                    summary_message,
                    first_lines[(category, summary_message)],
                )
                template_pattern = re.compile(
                    "^"
                    + ".+?".join(
                        re.escape(part)
                        for part in template.split("%")
                    )
                    + "$"
                )
                for candidate in list(counter):
                    if not template_pattern.match(candidate):
                        continue
                    counter.pop(candidate, None)
                    first_line = min(
                        first_line,
                        display_first_lines.pop(candidate, first_line),
                    )
                counter[template] += aggregate_count * max(
                    summary_occurrences,
                    1,
                )
                display_first_lines[template] = min(
                    display_first_lines.get(template, first_line),
                    first_line,
                )
        entries = [
            {
                "message": message,
                "count": count,
                "first_line": display_first_lines[message],
            }
            for message, count in sorted(
                counter.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        ]
        return {
            "total": sum(counter.values()),
            "unique": len(counter),
            "entries": entries,
        }

    return {
        "log_available": path.is_file(),
        "warnings": section("warnings"),
        "errors": section("errors"),
    }


def _downsample_occupancy(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep chronological peaks and troughs while bounding week-long chart payloads."""
    if len(points) <= MAX_OCCUPANCY_POINTS:
        return points
    interior = points[1:-1]
    bucket_count = max((MAX_OCCUPANCY_POINTS - 2) // 2, 1)
    bucket_size = max(math.ceil(len(interior) / bucket_count), 1)
    sampled = [points[0]]
    for start in range(0, len(interior), bucket_size):
        bucket = interior[start:start + bucket_size]
        minimum = min(bucket, key=lambda point: point["occupied_percent"])
        maximum = max(bucket, key=lambda point: point["occupied_percent"])
        sampled.extend(sorted(
            [minimum] if minimum is maximum else [minimum, maximum],
            key=lambda point: point["time_seconds"],
        ))
    sampled.append(points[-1])
    return sampled[:MAX_OCCUPANCY_POINTS - 1] + [points[-1]] if len(sampled) > MAX_OCCUPANCY_POINTS else sampled


def _occupancy_results(
    path: Path,
    parking_config_snapshot: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if not path.is_file():
        return [], {}

    aggregates: dict[float, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"capacity": 0.0, "occupied": 0.0})
    )
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            time_seconds = _number(row.get("time"))
            capacity = _number(row.get("capacity"))
            occupied = _number(row.get("occupied"))
            parking_id = str(row.get("logical_parking_id") or "").strip()
            if time_seconds is None or capacity is None or occupied is None or not parking_id:
                continue
            aggregates[time_seconds][parking_id]["capacity"] += max(capacity, 0.0)
            aggregates[time_seconds][parking_id]["occupied"] += max(occupied, 0.0)

    parking_ids = sorted({parking_id for values in aggregates.values() for parking_id in values})
    names = _parking_names(parking_config_snapshot)
    series: dict[str, list[dict[str, Any]]] = {parking_id: [] for parking_id in parking_ids}
    series["all"] = []

    for time_seconds in sorted(aggregates):
        all_capacity = 0.0
        all_occupied = 0.0
        for parking_id in parking_ids:
            values = aggregates[time_seconds].get(parking_id)
            if not values:
                continue
            capacity = values["capacity"]
            occupied = min(values["occupied"], capacity) if capacity else 0.0
            unoccupied = max(capacity - occupied, 0.0)
            series[parking_id].append({
                "time_seconds": time_seconds,
                "capacity": round(capacity),
                "occupied": round(occupied),
                "unoccupied": round(unoccupied),
                "occupied_percent": round(occupied / capacity * 100, 3) if capacity else 0.0,
                "unoccupied_percent": round(unoccupied / capacity * 100, 3) if capacity else 0.0,
            })
            all_capacity += capacity
            all_occupied += occupied

        if all_capacity:
            all_unoccupied = max(all_capacity - all_occupied, 0.0)
            series["all"].append({
                "time_seconds": time_seconds,
                "capacity": round(all_capacity),
                "occupied": round(all_occupied),
                "unoccupied": round(all_unoccupied),
                "occupied_percent": round(all_occupied / all_capacity * 100, 3),
                "unoccupied_percent": round(all_unoccupied / all_capacity * 100, 3),
            })

    for points in series.values():
        if points and points[0]["time_seconds"] > 0:
            initial = dict(points[0])
            initial.update({
                "time_seconds": 0.0,
                "occupied": 0,
                "unoccupied": initial["capacity"],
                "occupied_percent": 0.0,
                "unoccupied_percent": 100.0,
            })
            points.insert(0, initial)

    series = {
        parking_id: _downsample_occupancy(points)
        for parking_id, points in series.items()
    }

    parkings = [{
        "id": "all",
        "name": "All parking areas",
        "capacity": series["all"][0]["capacity"] if series["all"] else 0,
    }]
    parkings.extend({
        "id": parking_id,
        "name": names.get(parking_id, parking_id),
        "capacity": series[parking_id][0]["capacity"] if series[parking_id] else 0,
    } for parking_id in parking_ids)
    return parkings, series


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(math.ceil(len(ordered) * fraction) - 1, 0), len(ordered) - 1)
    return ordered[index]


def _first_parking_attempt_times(path: Path) -> dict[str, float]:
    first_attempts: dict[str, float] = {}
    if not path.is_file():
        return first_attempts
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row.get("event") != "parking_attempt":
                continue
            vehicle_id = str(row.get("vehicle_id") or "")
            time_seconds = _number(row.get("time"))
            if vehicle_id and time_seconds is not None:
                first_attempts.setdefault(vehicle_id, time_seconds)
    return first_attempts


def _search_time_results(
    path: Path,
    duration_seconds: int,
    parking_events_path: Path | None = None,
) -> dict[str, Any]:
    measurements: list[tuple[float, float]] = []
    first_attempts = _first_parking_attempt_times(
        parking_events_path or path.with_name("parking_events.csv")
    )
    if path.is_file():
        with path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                start_time = _number(
                    row.get("first_parking_arrival_time")
                    or row.get("first_reroute_time")
                )
                if start_time is None:
                    start_time = first_attempts.get(str(row.get("vehicle_id") or ""))
                search_time = _number(row.get("search_time"))
                if start_time is None or search_time is None or search_time < 0:
                    continue
                measurements.append((start_time, search_time))

    maximum_time = max([float(duration_seconds), *(item[0] for item in measurements)], default=1.0)
    bin_count = min(60, max(12, math.ceil(maximum_time / 300)))
    bin_width = max(maximum_time / bin_count, 1.0)
    bins: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for start_time, search_time in measurements:
        bins[min(int(start_time / bin_width), bin_count - 1)].append((start_time, search_time))

    points = []
    for index in sorted(bins):
        values = bins[index]
        points.append({
            "time_seconds": round(statistics.fmean(item[0] for item in values), 3),
            "average_search_seconds": round(statistics.fmean(item[1] for item in values), 3),
            "vehicle_count": len(values),
        })

    durations = [item[1] for item in measurements]
    return {
        "points": points,
        "summary": {
            "vehicle_count": len(durations),
            "average_seconds": round(statistics.fmean(durations), 3) if durations else 0.0,
            "median_seconds": round(statistics.median(durations), 3) if durations else 0.0,
            "p95_seconds": round(_percentile(durations, 0.95), 3),
            "maximum_seconds": round(max(durations), 3) if durations else 0.0,
        },
    }


def _parking_attempt_results(path: Path) -> dict[str, Any]:
    attempts: list[int] = []
    status_counts: Counter[str] = Counter()
    available = False
    if path.is_file():
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            available = "num_parking_attempts" in (reader.fieldnames or [])
            if available:
                for row in reader:
                    value = _number(row.get("num_parking_attempts"))
                    if value is None or value < 1:
                        continue
                    attempts.append(int(value))
                    status_counts[str(row.get("status") or "unknown")] += 1

    counts = Counter(attempts)
    vehicle_count = len(attempts)
    fallback_count = sum(count for value, count in counts.items() if value > 1)
    return {
        "available": available,
        "distribution": [
            {
                "attempt_count": attempt_count,
                "vehicle_count": count,
                "percentage": round(count / vehicle_count * 100, 3) if vehicle_count else 0.0,
            }
            for attempt_count, count in sorted(counts.items())
        ],
        "summary": {
            "vehicle_count": vehicle_count,
            "average_attempts": round(statistics.fmean(attempts), 3) if attempts else 0.0,
            "maximum_attempts": max(attempts, default=0),
            "vehicles_using_fallback": fallback_count,
            "fallback_percentage": round(fallback_count / vehicle_count * 100, 3) if vehicle_count else 0.0,
            "unserved_vehicle_count": status_counts["unserved"],
        },
    }


def _semicolon_values(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _route_departure_times(path: Path | None, element_name: str) -> dict[str, float]:
    if path is None or not path.is_file():
        return {}
    departures: dict[str, float] = {}
    try:
        for _event, element in ET.iterparse(path, events=("end",)):
            if element.tag.rsplit("}", 1)[-1] != element_name:
                element.clear()
                continue
            agent_id = str(element.get("id") or "").strip()
            departure = _number(element.get("depart"))
            if agent_id and departure is not None:
                departures[agent_id] = departure
            element.clear()
    except (OSError, ET.ParseError):
        return {}
    return departures


def _parking_destination_results(
    person_plan_path: Path,
    vehicle_plan_path: Path,
    search_times_path: Path,
    parking_events_path: Path,
    parking_config_snapshot: Path,
    person_access_snapshot: Path | None = None,
    passenger_routes_path: Path | None = None,
    pedestrian_routes_path: Path | None = None,
) -> dict[str, Any]:
    """Join planned destinations to initial choices and observed parking outcomes."""
    parking_names = _parking_names(parking_config_snapshot)
    access_snapshot = _read_json(person_access_snapshot) if person_access_snapshot else None
    accessible_parking_ids = {
        str(parking_id)
        for parking_id in (access_snapshot or {}).get("accessible_logical_parking_ids", [])
    }
    maximum_access_distance = _number(
        (access_snapshot or {}).get("max_access_distance_metres")
    )
    eligible_building_counts: Counter[str] = Counter()
    building_metadata: dict[str, dict[str, Any]] = {}
    for building in (access_snapshot or {}).get("buildings", []):
        if not isinstance(building, dict):
            continue
        building_id = str(building.get("id") or "").strip()
        if building_id:
            constant = _number(building.get("capacity_constant"))
            building_metadata[building_id] = {
                "name": str(building.get("name") or building_id),
                "vehicle_weight": max(_number(building.get("vehicle_weight")) or 0.0, 0.0),
                "pedestrian_weight": max(_number(building.get("pedestrian_weight")) or 0.0, 0.0),
                "capacity_constant": max(constant if constant is not None else 1.0, 0.0),
                "destination_capacity": max(_number(building.get("destination_capacity")) or 0.0, 0.0),
                "footprint_area_square_metres": max(_number(building.get("footprint_area_square_metres")) or 0.0, 0.0),
                "building_levels": max(_number(building.get("building_levels")) or 0.0, 0.0),
                "eligible_parking_area_count": len({
                    str(candidate.get("parking_id") or "").strip()
                    for candidate in building.get("parking_candidates") or []
                    if isinstance(candidate, dict) and candidate.get("parking_id")
                }),
            }
        seen: set[str] = set()
        for candidate in building.get("parking_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            parking_id = str(candidate.get("parking_id") or "").strip()
            if parking_id and parking_id not in seen:
                eligible_building_counts[parking_id] += 1
                seen.add(parking_id)
    vehicle_plans: dict[str, dict[str, Any]] = {}
    candidate_counts: Counter[str] = Counter()
    if vehicle_plan_path.is_file():
        with vehicle_plan_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                vehicle_id = str(row.get("vehicle_id") or "").strip()
                if not vehicle_id:
                    continue
                try:
                    raw_candidates = json.loads(
                        str(row.get("parking_candidates_json") or "[]")
                    )
                except (json.JSONDecodeError, TypeError):
                    raw_candidates = []
                candidate_ids: list[str] = []
                for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
                    if not isinstance(candidate, dict):
                        continue
                    parking_id = str(candidate.get("parking_id") or "").strip()
                    if parking_id and parking_id not in candidate_ids:
                        candidate_ids.append(parking_id)
                initial_parking = str(row.get("initial_parking") or "").strip()
                if initial_parking and initial_parking not in candidate_ids:
                    candidate_ids.insert(0, initial_parking)
                vehicle_plans[vehicle_id] = {
                    "initial_parking_id": initial_parking,
                    "candidate_parking_ids": candidate_ids,
                }

    outcomes: dict[str, dict[str, Any]] = {}
    if search_times_path.is_file():
        with search_times_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                vehicle_id = str(row.get("vehicle_id") or "").strip()
                if not vehicle_id:
                    continue
                outcomes[vehicle_id] = {
                    "initial_parking_id": str(row.get("initial_parking") or "").strip(),
                    "final_physical_parking_id": str(row.get("final_parking") or "").strip(),
                    "status": str(row.get("status") or "unknown").strip() or "unknown",
                    "parking_changes": int(_number(row.get("num_parking_changes")) or 0),
                    "parking_attempts": int(_number(row.get("num_parking_attempts")) or 0),
                    "attempted_parking_ids": _semicolon_values(row.get("attempted_parking_ids")),
                    "rejected_parking_ids": _semicolon_values(row.get("rejected_parking_ids")),
                }

    final_parkings: dict[str, tuple[str, str]] = {}
    if parking_events_path.is_file():
        with parking_events_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                if row.get("event") not in {"parking_started", "parking_ended"}:
                    continue
                vehicle_id = str(row.get("vehicle_id") or "").strip()
                logical_id = str(row.get("logical_parking") or "").strip()
                physical_id = str(row.get("physical_parking") or "").strip()
                if vehicle_id and logical_id:
                    final_parkings[vehicle_id] = (logical_id, physical_id)

    vehicle_departures = _route_departure_times(passenger_routes_path, "trip")
    pedestrian_departures = _route_departure_times(pedestrian_routes_path, "person")
    destination_rows: list[dict[str, Any]] = []
    person_rows: list[dict[str, Any]] = []
    if person_plan_path.is_file():
        with person_plan_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                arrival_mode = str(row.get("arrival_mode") or "").strip()
                if arrival_mode not in {"vehicle", "pedestrian"}:
                    continue
                vehicle_id = str(row.get("vehicle_id") or "").strip()
                person_id = str(row.get("person_id") or "").strip()
                building_id = str(row.get("building_id") or "").strip()
                if not building_id:
                    continue
                departure = _number(row.get("departure_time_seconds"))
                if departure is None:
                    departure = (
                        vehicle_departures.get(vehicle_id)
                        if arrival_mode == "vehicle"
                        else pedestrian_departures.get(person_id)
                    )
                destination = {
                    "person_id": person_id or (f"person.{vehicle_id}" if vehicle_id else ""),
                    "vehicle_id": vehicle_id,
                    "arrival_mode": arrival_mode,
                    "building_id": building_id,
                    "building_name": str(row.get("building_name") or building_id),
                    "departure_time_seconds": departure,
                }
                destination_rows.append(destination)
                if arrival_mode == "vehicle" and vehicle_id:
                    person_rows.append(destination)

    destination_totals: dict[tuple[str, str], Counter[str]] = {}
    destination_buckets: dict[tuple[str, int], Counter[str]] = {}
    for destination in destination_rows:
        building_key = (destination["building_id"], destination["building_name"])
        destination_totals.setdefault(building_key, Counter())[destination["arrival_mode"]] += 1
        departure = destination.get("departure_time_seconds")
        if departure is None:
            continue
        bucket_start = (
            int(max(float(departure), 0) // DESTINATION_SELECTION_INTERVAL_SECONDS)
            * DESTINATION_SELECTION_INTERVAL_SECONDS
        )
        destination_buckets.setdefault(
            (destination["building_id"], bucket_start),
            Counter(),
        )[destination["arrival_mode"]] += 1

    parking_totals: dict[str, Counter[str]] = {
        parking_id: Counter()
        for parking_id in parking_names
    }
    people: list[dict[str, Any]] = []
    building_totals: dict[tuple[str, str], Counter[str]] = {}
    parking_building_counts: Counter[tuple[str, str, str]] = Counter()
    for person in person_rows:
        vehicle_id = person["vehicle_id"]
        plan = vehicle_plans.get(vehicle_id, {})
        outcome = outcomes.get(vehicle_id, {})
        initial_id = str(
            plan.get("initial_parking_id")
            or outcome.get("initial_parking_id")
            or ""
        )
        candidate_ids = list(plan.get("candidate_parking_ids") or [])
        if initial_id and initial_id not in candidate_ids:
            candidate_ids.insert(0, initial_id)
        for parking_id in candidate_ids:
            candidate_counts[parking_id] += 1
            parking_totals.setdefault(parking_id, Counter())
        if initial_id:
            parking_totals.setdefault(initial_id, Counter())["initial_choice_people"] += 1

        final_id, event_physical_id = final_parkings.get(vehicle_id, ("", ""))
        physical_id = event_physical_id or str(
            outcome.get("final_physical_parking_id") or ""
        )
        status = "parked" if final_id else str(outcome.get("status") or "unknown")
        if final_id:
            parking_totals.setdefault(final_id, Counter())["parked_people"] += 1
            if initial_id and initial_id != final_id:
                parking_totals[final_id]["rerouted_in_people"] += 1
                parking_totals.setdefault(initial_id, Counter())["rerouted_out_people"] += 1
        elif initial_id and status == "unserved":
            parking_totals.setdefault(initial_id, Counter())["unserved_after_initial_people"] += 1

        building_key = (person["building_id"], person["building_name"])
        building_counter = building_totals.setdefault(building_key, Counter())
        building_counter["planned_vehicle_people"] += 1
        if final_id:
            building_counter["parked_people"] += 1
            building_counter[f"parking:{final_id}"] += 1
            parking_building_counts[(final_id, person["building_id"], person["building_name"])] += 1
        elif status == "unserved":
            building_counter["unserved_people"] += 1
        else:
            building_counter["without_parking_outcome"] += 1

        people.append({
            **person,
            "initial_parking_id": initial_id,
            "initial_parking_name": parking_names.get(initial_id, initial_id),
            "final_parking_id": final_id,
            "final_parking_name": parking_names.get(final_id, final_id),
            "final_physical_parking_id": physical_id,
            "status": status,
            "parking_changes": int(outcome.get("parking_changes") or 0),
            "parking_attempts": int(outcome.get("parking_attempts") or 0),
            "candidate_parking_ids": candidate_ids,
            "attempted_parking_ids": list(outcome.get("attempted_parking_ids") or []),
            "rejected_parking_ids": list(outcome.get("rejected_parking_ids") or []),
        })

    all_parking_ids = sorted(
        set(parking_names) | set(parking_totals) | set(candidate_counts),
        key=lambda parking_id: parking_names.get(parking_id, parking_id).casefold(),
    )
    parkings = []
    for parking_id in all_parking_ids:
        totals = parking_totals.get(parking_id, Counter())
        candidate_count = candidate_counts[parking_id]
        initial_count = totals["initial_choice_people"]
        parked_count = totals["parked_people"]
        unused_reason = None
        if parked_count == 0:
            if candidate_count == 0:
                if access_snapshot is not None and parking_id not in accessible_parking_ids:
                    distance_note = (
                        f" within {maximum_access_distance:g} m"
                        if maximum_access_distance is not None
                        else ""
                    )
                    unused_reason = (
                        "No generated aisle in this logical parking area could connect "
                        f"to a pedestrian lane{distance_note}, so drivers could not walk "
                        "from it to a destination building."
                    )
                elif access_snapshot is not None and eligible_building_counts[parking_id] == 0:
                    unused_reason = (
                        "The parking area had pedestrian access, but SUMO found no "
                        "pedestrian-network route from it to any selected destination building."
                    )
                elif access_snapshot is not None:
                    building_count = eligible_building_counts[parking_id]
                    unused_reason = (
                        f"It was connected to {building_count} selected destination "
                        f"building{'s' if building_count != 1 else ''}, but no generated "
                        "driver retained it after destination assignment and car-route "
                        "filtering from that driver's entry point."
                    )
                else:
                    unused_reason = (
                        "No driver had this parking area in the candidate list for "
                        "their destination building and vehicle entry point."
                    )
            elif initial_count == 0:
                unused_reason = (
                    f"It was a reachable candidate for {candidate_count} drivers, but "
                    "was never their highest-ranked initial choice and nobody rerouted here."
                )
            else:
                unused_reason = (
                    f"It was selected initially by {initial_count} drivers, but none "
                    "recorded a completed parking start here. Check rerouted and unserved outcomes."
                )
        parkings.append({
            "id": parking_id,
            "name": parking_names.get(parking_id, parking_id),
            "candidate_people": candidate_count,
            "initial_choice_people": initial_count,
            "parked_people": parked_count,
            "rerouted_in_people": totals["rerouted_in_people"],
            "rerouted_out_people": totals["rerouted_out_people"],
            "unserved_after_initial_people": totals["unserved_after_initial_people"],
            "destination_building_count": len({
                person["building_id"]
                for person in people
                if person["final_parking_id"] == parking_id
            }),
            "eligible_destination_building_count": eligible_building_counts[parking_id],
            "pedestrian_access_available": (
                parking_id in accessible_parking_ids if access_snapshot is not None else None
            ),
            "unused_reason": unused_reason,
        })

    building_names = {
        building_id: metadata["name"]
        for building_id, metadata in building_metadata.items()
    }
    building_names.update({
        building_id: building_name
        for building_id, building_name in building_totals
    })
    building_names.update({
        building_id: building_name
        for building_id, building_name in destination_totals
    })
    buildings = []
    for building_id, building_name in sorted(
        building_names.items(), key=lambda item: item[1].casefold()
    ):
        totals = building_totals.get((building_id, building_name), Counter())
        destination_counts = destination_totals.get((building_id, building_name), Counter())
        metadata = building_metadata.get(building_id, {})
        planned_people = destination_counts["vehicle"]
        planned_pedestrians = destination_counts["pedestrian"]
        zero_driver_reason = None
        if planned_people == 0:
            if int(metadata.get("eligible_parking_area_count") or 0) == 0:
                zero_driver_reason = (
                    "No selected parking area had a pedestrian-network route to this building."
                )
            elif float(metadata.get("vehicle_weight") or 0) <= 0:
                zero_driver_reason = (
                    "The selected building-demand usage policy assigned this building a 0 vehicle weight."
                )
            else:
                zero_driver_reason = (
                    "The building was eligible for vehicle demand, but no generated driver was assigned "
                    "after weighted destination selection and car-route filtering."
                )
        buildings.append({
            "id": building_id,
            "name": building_name,
            "planned_vehicle_people": planned_people,
            "planned_pedestrian_people": planned_pedestrians,
            "parked_people": totals["parked_people"],
            "unserved_people": totals["unserved_people"],
            "without_parking_outcome": totals["without_parking_outcome"],
            "parking_area_count": sum(
                1 for key, count in totals.items()
                if key.startswith("parking:") and count > 0
            ),
            "vehicle_weight": float(metadata.get("vehicle_weight") or 0),
            "pedestrian_weight": float(metadata.get("pedestrian_weight") or 0),
            "capacity_constant": float(metadata.get("capacity_constant", 1)),
            "destination_capacity": float(metadata.get("destination_capacity") or 0),
            "footprint_area_square_metres": float(metadata.get("footprint_area_square_metres") or 0),
            "building_levels": float(metadata.get("building_levels") or 0),
            "destination_time_series": [
                {
                    "time_seconds": bucket_start,
                    "vehicle_count": counts["vehicle"],
                    "pedestrian_count": counts["pedestrian"],
                }
                for (series_building_id, bucket_start), counts
                in sorted(destination_buckets.items())
                if series_building_id == building_id
            ],
            "eligible_parking_area_count": int(
                metadata.get("eligible_parking_area_count") or 0
            ),
            "zero_driver_reason": zero_driver_reason,
        })

    people.sort(key=lambda person: (person["building_name"].casefold(), person["vehicle_id"]))
    parked_people = sum(1 for person in people if person["final_parking_id"])
    unserved_people = sum(1 for person in people if person["status"] == "unserved")
    return {
        "available": bool(destination_rows),
        "outcomes_available": search_times_path.is_file() or parking_events_path.is_file(),
        "destination_interval_seconds": DESTINATION_SELECTION_INTERVAL_SECONDS,
        "summary": {
            "planned_vehicle_people": len(people),
            "planned_pedestrian_people": sum(
                counts["pedestrian"] for counts in destination_totals.values()
            ),
            "parked_people": parked_people,
            "unserved_people": unserved_people,
            "without_parking_outcome": len(people) - parked_people - unserved_people,
            "unused_parking_areas": sum(1 for parking in parkings if not parking["parked_people"]),
            "destination_buildings": len(buildings),
            "buildings_receiving_drivers": sum(
                1 for building in buildings if building["planned_vehicle_people"] > 0
            ),
            "buildings_receiving_pedestrians": sum(
                1 for building in buildings if building["planned_pedestrian_people"] > 0
            ),
        },
        "parkings": parkings,
        "buildings": buildings,
        "parking_building_flows": [
            {
                "parking_id": parking_id,
                "parking_name": parking_names.get(parking_id, parking_id),
                "building_id": building_id,
                "building_name": building_name,
                "parked_people": count,
            }
            for (parking_id, building_id, building_name), count
            in sorted(
                parking_building_counts.items(),
                key=lambda item: (-item[1], item[0][2].casefold(), item[0][0]),
            )
        ],
    }


def _trip_segment_results(
    path: Path,
    duration_seconds: int,
    parking_names: dict[str, str],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    if path.is_file():
        with path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                segment_type = str(row.get("segment_type") or "")
                start_time = _number(row.get("start_time"))
                segment_duration = _number(row.get("duration_seconds"))
                if (
                    segment_type not in TRIP_SEGMENT_TYPES
                    or start_time is None
                    or segment_duration is None
                    or segment_duration < 0
                ):
                    continue
                parking_id = str(row.get("parking_id") or "")
                records.append({
                    "vehicle_id": str(row.get("vehicle_id") or ""),
                    "segment_type": segment_type,
                    "parking_id": parking_id,
                    "parking_name": str(
                        row.get("parking_name")
                        or parking_names.get(parking_id)
                        or parking_id
                    ),
                    "start_time": start_time,
                    "duration_seconds": segment_duration,
                    "outcome": str(row.get("outcome") or "completed"),
                })

    maximum_time = max(
        [float(duration_seconds), *(record["start_time"] for record in records)],
        default=1.0,
    )
    bin_count = min(60, max(12, math.ceil(maximum_time / 300)))
    bin_width = max(maximum_time / bin_count, 1.0)
    buckets: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    summary_values: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        bin_index = min(int(record["start_time"] / bin_width), bin_count - 1)
        parking_keys = ["all"]
        if record["parking_id"]:
            parking_keys.append(record["parking_id"])
        for parking_key in parking_keys:
            buckets[(record["segment_type"], parking_key, bin_index)].append(record)
            summary_values[(record["segment_type"], parking_key)].append(record)

    points = []
    for (segment_type, parking_id, _bin_index), values in sorted(buckets.items()):
        points.append({
            "time_seconds": round(statistics.fmean(item["start_time"] for item in values), 3),
            "segment_type": segment_type,
            "parking_id": parking_id,
            "average_duration_seconds": round(
                statistics.fmean(item["duration_seconds"] for item in values),
                3,
            ),
            "segment_count": len(values),
            "vehicle_count": len({item["vehicle_id"] for item in values}),
        })

    summaries = []
    for (segment_type, parking_id), values in sorted(summary_values.items()):
        durations = [item["duration_seconds"] for item in values]
        summaries.append({
            "segment_type": segment_type,
            "parking_id": parking_id,
            "segment_count": len(values),
            "vehicle_count": len({item["vehicle_id"] for item in values}),
            "average_seconds": round(statistics.fmean(durations), 3),
            "median_seconds": round(statistics.median(durations), 3),
            "p95_seconds": round(_percentile(durations, 0.95), 3),
            "maximum_seconds": round(max(durations), 3),
        })

    parking_options = [{"id": "all", "name": "All parking areas"}]
    parking_options.extend(
        {"id": parking_id, "name": parking_name}
        for parking_id, parking_name in sorted({
            record["parking_id"]: record["parking_name"]
            for record in records
            if record["parking_id"]
        }.items(), key=lambda item: item[1].casefold())
    )
    return {
        "available": path.is_file(),
        "points": points,
        "summaries": summaries,
        "parkings": parking_options,
        "segment_types": list(TRIP_SEGMENT_TYPES),
    }


def _build_analytics(record: dict[str, Any], run_path: Path) -> dict[str, Any]:
    output_dir = run_path.parent / "outputs"
    availability = _analytics_available(run_path)
    if not any(availability.values()):
        raise AnalyticsError("This simulation does not have analytics data yet.")

    parkings, occupancy = _occupancy_results(
        output_dir / "parking_occupancy.csv",
        run_path.parent / "parking_areas.yaml",
    )
    search_times = _search_time_results(
        output_dir / "search_times.csv",
        int(record.get("duration_seconds") or 0),
    )
    parking_attempts = _parking_attempt_results(output_dir / "search_times.csv")
    parking_names = _parking_names(run_path.parent / "parking_areas.yaml")
    trip_segments = _trip_segment_results(
        output_dir / "vehicle_trip_segments.csv",
        int(record.get("duration_seconds") or 0),
        parking_names,
    )
    parking_destinations = _parking_destination_results(
        run_path.parent / "inputs" / "person_plan.csv",
        run_path.parent / "inputs" / "vehicle_parking_plan.csv",
        output_dir / "search_times.csv",
        output_dir / "parking_events.csv",
        run_path.parent / "parking_areas.yaml",
        run_path.parent / "person_access.snapshot.json",
        run_path.parent / "inputs" / "passenger.rou.xml",
        run_path.parent / "inputs" / "pedestrian.rou.xml",
    )
    debug = _grouped_log_entries(run_path.parent / "simulation.log")
    detectors = _detector_results(
        output_dir / "detectors" / "e1.xml",
        output_dir / "detectors" / "e3.xml",
        output_dir / "detectors" / "e2_pedestrians.xml",
        run_path.parent / "detectors.snapshot.json",
        int(record.get("duration_seconds") or 0) or None,
    )
    return {
        "schema_version": ANALYTICS_SNAPSHOT_VERSION,
        "run": _run_summary(record, run_path),
        "parkings": parkings,
        "occupancy": occupancy,
        "search_times": search_times,
        "parking_attempts": parking_attempts,
        "trip_segments": trip_segments,
        "parking_destinations": parking_destinations,
        "detectors": detectors,
        "debug": debug,
    }


def generate_analytics_snapshot(
    model_storage_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    """Build analytics once in the analytics worker and atomically cache it."""
    record, run_path = _find_run(model_storage_dir, run_id)
    payload = _build_analytics(record, run_path)
    snapshot_path = run_path.parent / ANALYTICS_SNAPSHOT_FILENAME
    temporary_path = snapshot_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary_path.replace(snapshot_path)
    return payload


def get_analytics(model_storage_dir: Path, run_id: str) -> dict[str, Any]:
    record, run_path = _find_run(model_storage_dir, run_id)
    storage = get_object_storage()
    if storage is not None:
        model_id = str(record.get("model_id") or "")
        object_prefix = run_object_path(model_id, run_id)
        snapshot = storage.read_json(
            run_object_path(model_id, run_id, ANALYTICS_SNAPSHOT_FILENAME)
        )
        if (
            snapshot is not None
            and snapshot.get("schema_version") == ANALYTICS_SNAPSHOT_VERSION
            and "parking_destinations" in snapshot
        ):
            return snapshot
        if snapshot is not None:
            for relative_path in (
                "inputs/person_plan.csv",
                "inputs/vehicle_parking_plan.csv",
                "inputs/passenger.rou.xml",
                "inputs/pedestrian.rou.xml",
                "outputs/search_times.csv",
                "outputs/parking_events.csv",
                "parking_areas.yaml",
                "person_access.snapshot.json",
            ):
                storage.download_file(
                    run_object_path(model_id, run_id, relative_path),
                    run_path.parent / relative_path,
                )
            snapshot["schema_version"] = ANALYTICS_SNAPSHOT_VERSION
            snapshot["parking_destinations"] = _parking_destination_results(
                run_path.parent / "inputs" / "person_plan.csv",
                run_path.parent / "inputs" / "vehicle_parking_plan.csv",
                run_path.parent / "outputs" / "search_times.csv",
                run_path.parent / "outputs" / "parking_events.csv",
                run_path.parent / "parking_areas.yaml",
                run_path.parent / "person_access.snapshot.json",
                run_path.parent / "inputs" / "passenger.rou.xml",
                run_path.parent / "inputs" / "pedestrian.rou.xml",
            )
            snapshot_path = run_path.parent / ANALYTICS_SNAPSHOT_FILENAME
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            storage.write_json(
                run_object_path(model_id, run_id, ANALYTICS_SNAPSHOT_FILENAME),
                snapshot,
            )
            return snapshot
        storage.download_prefix(
            object_prefix,
            run_path.parent,
        )
    snapshot = _read_json(run_path.parent / ANALYTICS_SNAPSHOT_FILENAME)
    if (
        snapshot is not None
        and snapshot.get("schema_version") == ANALYTICS_SNAPSHOT_VERSION
        and "parking_destinations" in snapshot
    ):
        return snapshot
    # Backward compatibility for historical runs and local development without
    # an analytics worker. New queued deployments generate this asynchronously.
    payload = generate_analytics_snapshot(model_storage_dir, run_id)
    if storage is not None:
        storage.write_json(
            run_object_path(
                str(record.get("model_id") or ""),
                run_id,
                ANALYTICS_SNAPSHOT_FILENAME,
            ),
            payload,
        )
    return payload


def backfill_analytics_snapshots(model_storage_dir: Path) -> tuple[int, int]:
    """Cache historical terminal runs without modifying their source outputs."""
    generated = 0
    skipped = 0
    for run_path in _analytics_paths(model_storage_dir):
        record = _read_json(run_path)
        snapshot_path = run_path.parent / ANALYTICS_SNAPSHOT_FILENAME
        if (
            record is None
            or record.get("status") not in {"completed", "failed"}
            or snapshot_path.is_file()
            or not any(_analytics_available(run_path).values())
        ):
            skipped += 1
            continue
        try:
            generate_analytics_snapshot(model_storage_dir, run_path.parent.name)
        except AnalyticsError:
            skipped += 1
            continue
        generated += 1
    return generated, skipped


def analytics_run_directory(model_storage_dir: Path, run_id: str) -> Path:
    """Return the artifact directory for an analytics run after validating it."""
    _record, run_path = _find_run(model_storage_dir, run_id)
    return run_path.parent
