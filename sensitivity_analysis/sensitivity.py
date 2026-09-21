#!/usr/bin/env python3
"""Plan, run, resume, and analyze a SUMO one-factor-at-a-time study.

The program intentionally uses only Python's standard library.  It talks to the
same HTTP API as the web UI and keeps an atomic local checkpoint so closing the
terminal never loses which server run belongs to which design point.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence


VERSION = 1
TERMINAL_STATUSES = {"completed", "failed"}
ACTIVE_STATUSES = {"queued", "running"}
PARKING_PATHS = {
    "weights.drive_time",
    "weights.walk_time",
    "weights.capacity",
    "weights.absolute_free_space",
    "weights.relative_free_space",
    "knowledge_probability",
    "uninformed_occupancy_mean",
    "uninformed_occupancy_stddev",
    "frustration_step",
    "stochastic_scale",
}


class StudyError(RuntimeError):
    """An actionable error which should be shown without a traceback."""


class ApiError(StudyError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                detail = str(parsed.get("detail") or detail)
            except json.JSONDecodeError:
                pass
            raise ApiError(f"{method} {path} returned {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f"Could not reach {self.base_url}: {exc}") from exc
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ApiError(f"{method} {path} returned invalid JSON") from exc


def normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def resolve_named(
    items: Iterable[dict[str, Any]],
    query: str,
    *,
    label: str,
    fields: tuple[str, ...] = ("name",),
) -> dict[str, Any]:
    candidates = list(items)
    needle = normalized_text(query)
    exact = [
        item for item in candidates
        if any(normalized_text(item.get(field)) == needle for field in fields)
    ]
    matches = exact or [
        item for item in candidates
        if any(needle in normalized_text(item.get(field)) for field in fields)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        available = ", ".join(str(item.get("name") or item.get("id")) for item in candidates)
        raise StudyError(f"No {label} matched '{query}'. Available: {available or 'none'}")
    names = ", ".join(str(item.get("name") or item.get("id")) for item in matches)
    raise StudyError(f"'{query}' matched multiple {label}s: {names}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed_seconds(start: Any, end: Any) -> float | None:
    left, right = parse_time(start), parse_time(end)
    if left is None or right is None:
        return None
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return max((right - left).total_seconds(), 0.0)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def numeric_values(spec: dict[str, Any], *, percent: bool = False) -> list[float]:
    explicit_key = "values_percent" if percent else "values"
    if explicit_key in spec:
        values = [float(item) for item in spec[explicit_key]]
    else:
        prefix = "_percent" if percent else ""
        minimum = Decimal(str(spec[f"minimum{prefix}"]))
        maximum = Decimal(str(spec[f"maximum{prefix}"]))
        step = Decimal(str(spec[f"step{prefix}"]))
        if step <= 0 or maximum < minimum:
            raise StudyError(f"Invalid range: minimum={minimum}, maximum={maximum}, step={step}")
        values = []
        current = minimum
        while current <= maximum:
            values.append(float(current))
            current += step
        if not math.isclose(values[-1], float(maximum), rel_tol=0, abs_tol=1e-10):
            values.append(float(maximum))
    if not values or any(not math.isfinite(item) for item in values):
        raise StudyError("Experiment values must contain finite numbers.")
    return sorted(set(values))


def include_value(values: Sequence[float], required: float) -> list[float]:
    return sorted(set([*map(float, values), float(required)]))


def set_nested(target: dict[str, Any], dotted_path: str, value: float) -> None:
    parts = dotted_path.split(".")
    current = target
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def get_nested(target: dict[str, Any], dotted_path: str) -> float:
    current: Any = target
    for part in dotted_path.split("."):
        current = current[part]
    return float(current)


def allocate_counts(ids: Sequence[str], percentages: Sequence[float], count: int) -> list[dict[str, Any]]:
    if len(ids) != len(percentages):
        raise StudyError("Origin IDs and percentages have different lengths.")
    if not ids:
        if count:
            raise StudyError("The model has no vehicle generation points.")
        return []
    if count == 0:
        return [{"origin_id": item, "vehicle_count": 0} for item in ids]
    total = sum(percentages)
    if total <= 0:
        raise StudyError("Vehicle-origin percentages add up to zero.")
    exact = [count * max(float(value), 0.0) / total for value in percentages]
    result = [math.floor(value) for value in exact]
    remainder = count - sum(result)
    order = sorted(range(len(ids)), key=lambda index: (-(exact[index] - result[index]), ids[index]))
    for index in order[:remainder]:
        result[index] += 1
    return [
        {"origin_id": origin_id, "vehicle_count": result[index]}
        for index, origin_id in enumerate(ids)
    ]


def mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


@dataclass
class PreparedStudy:
    config: dict[str, Any]
    config_path: Path
    output_dir: Path
    api: ApiClient
    model: dict[str, Any]
    classification: dict[str, Any]
    origins: list[dict[str, Any]]
    detector: dict[str, Any] | None
    sensor: dict[str, Any] | None
    model_signature: str
    plan: dict[str, Any]

    @property
    def state_path(self) -> Path:
        return self.output_dir / "state.json"


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StudyError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StudyError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StudyError("The configuration root must be a JSON object.")
    return value


def validate_fourier(profile: dict[str, Any], label: str) -> None:
    count = int(profile.get("peak_count") or 0)
    heights = profile.get("peak_heights_percent") or []
    if not 1 <= count <= 16 or len(heights) != count:
        raise StudyError(f"{label} needs 1–16 peaks and one percentage per peak.")
    if any(not 0 <= float(item) <= 300 for item in heights):
        raise StudyError(f"{label} percentages must be between 0 and 300.")
    if not 0.01 <= float(profile.get("peak_width_hours") or 0) <= 168:
        raise StudyError(f"{label} peak_width_hours is outside the API range.")
    if not 1 <= int(profile.get("harmonics") or 0) <= 16:
        raise StudyError(f"{label} harmonics is outside the API range.")


def baseline_payload(
    config: dict[str, Any],
    classification_id: str,
    origin_ids: Sequence[str],
    replicate: int,
) -> dict[str, Any]:
    base = config["baseline"]
    pedestrians = int(base["pedestrian_count"])
    vehicles = int(base["vehicle_count"])
    residential = int(base["residential_pedestrian_count"])
    if not 0 <= residential <= pedestrians:
        raise StudyError("Baseline residential pedestrians must fit within pedestrian_count.")
    validate_fourier(base["vehicle_fourier"], "vehicle_fourier")
    validate_fourier(base["pedestrian_fourier"], "pedestrian_fourier")
    for path in PARKING_PATHS:
        get_nested(base["parking_choice"], path)
    total = pedestrians + vehicles
    equal = [100.0 / len(origin_ids)] * len(origin_ids) if origin_ids else []

    def fourier(name: str) -> dict[str, Any]:
        profile = base[name]
        return {
            "peak_count": int(profile["peak_count"]),
            "peak_width_hours": float(profile["peak_width_hours"]),
            "harmonics": int(profile["harmonics"]),
            "peak_heights": [float(value) / 100.0 for value in profile["peak_heights_percent"]],
        }

    return {
        "vehicle_count": vehicles,
        "pedestrian_count": pedestrians,
        "total_people": total,
        "vehicle_percentage": round(vehicles / total * 100),
        "building_classification_id": classification_id,
        "residential_pedestrian_count": residential,
        "public_transport_pedestrian_count": pedestrians - residential,
        "duration_hours": int(base["duration_hours"]),
        "simulation_start_at": str(base["simulation_start_at"]),
        "simulation_timezone": str(base.get("simulation_timezone") or "Europe/Paris"),
        "mode": str(base.get("mode") or "sumo"),
        "pedestrian_model": str(base.get("pedestrian_model") or "nonInteracting"),
        "diagnostic_tracing": False,
        "random_seed": int(base.get("random_seed") or 20260119) + replicate,
        "vehicle_traffic_model": "fourier",
        "pedestrian_traffic_model": "fourier",
        "vehicle_fourier_parameters": fourier("vehicle_fourier"),
        "pedestrian_fourier_parameters": fourier("pedestrian_fourier"),
        "parking_choice": copy.deepcopy(base["parking_choice"]),
        "vehicle_origin_allocations": allocate_counts(origin_ids, equal, vehicles),
    }


def update_vehicle_count(payload: dict[str, Any], count: int, origin_ids: Sequence[str]) -> None:
    pedestrians = int(payload["pedestrian_count"])
    total = pedestrians + count
    payload["vehicle_count"] = count
    payload["total_people"] = total
    payload["vehicle_percentage"] = round(count / total * 100)
    equal = [100.0 / len(origin_ids)] * len(origin_ids) if origin_ids else []
    payload["vehicle_origin_allocations"] = allocate_counts(origin_ids, equal, count)


def build_plan(
    config: dict[str, Any],
    classification_id: str,
    origins: Sequence[dict[str, Any]],
    model_signature: str,
) -> dict[str, Any]:
    experiments = config.get("experiments") or {}
    origin_ids = [str(item["id"]) for item in origins]
    origin_names = {str(item["id"]): str(item.get("name") or item["id"]) for item in origins}
    replicates = int(config.get("replicates") or 1)
    if not 1 <= replicates <= 100:
        raise StudyError("replicates must be between 1 and 100.")
    runs: dict[str, dict[str, Any]] = {}
    points: list[dict[str, Any]] = []

    def add_point(
        parameter_id: str,
        parameter_label: str,
        value: float,
        unit: str,
        baseline_value: float,
        payload: dict[str, Any],
        replicate: int,
    ) -> None:
        payload_hash = digest(payload)
        point_id = digest({
            "parameter_id": parameter_id,
            "value": value,
            "replicate": replicate,
            "payload_hash": payload_hash,
        })[:20]
        membership = {
            "point_id": point_id,
            "parameter_id": parameter_id,
            "parameter_label": parameter_label,
            "value": float(value),
            "unit": unit,
            "baseline_value": float(baseline_value),
            "replicate": replicate + 1,
            "payload_hash": payload_hash,
        }
        points.append(membership)
        if payload_hash not in runs:
            runs[payload_hash] = {
                "payload_hash": payload_hash,
                "payload": payload,
                "memberships": [],
            }
        runs[payload_hash]["memberships"].append(point_id)

    for replicate in range(replicates):
        payload = baseline_payload(config, classification_id, origin_ids, replicate)
        add_point("baseline", "Global baseline", 0, "baseline", 0, payload, replicate)

    for subject, key in (("vehicle", "vehicle_fourier_peaks"), ("pedestrian", "pedestrian_fourier_peaks")):
        spec = experiments.get(key) or {}
        if not spec.get("enabled", False):
            continue
        values = numeric_values(spec, percent=True)
        profile_key = f"{subject}_fourier_parameters"
        count = int(config["baseline"][f"{subject}_fourier"]["peak_count"])
        other = float(spec.get("other_peaks_percent", 100))
        if any(not 0 <= item <= 300 for item in [*values, other]):
            raise StudyError(f"{key} percentages must be between 0 and 300.")
        for peak_index in range(count):
            baseline_height = float(
                config["baseline"][f"{subject}_fourier"]["peak_heights_percent"][peak_index]
            )
            peak_values = include_value(values, baseline_height)
            for value in peak_values:
                for replicate in range(replicates):
                    payload = baseline_payload(config, classification_id, origin_ids, replicate)
                    heights = [other / 100.0] * count
                    heights[peak_index] = value / 100.0
                    payload[profile_key]["peak_heights"] = heights
                    add_point(
                        f"{subject}_fourier_peak_{peak_index + 1}",
                        f"{subject.title()} Fourier peak {peak_index + 1}",
                        value,
                        "%",
                        baseline_height,
                        payload,
                        replicate,
                    )

    residential = experiments.get("residential_pedestrians") or {}
    if residential.get("enabled", False):
        values = include_value(
            numeric_values(residential),
            float(config["baseline"]["residential_pedestrian_count"]),
        )
        pedestrians = int(config["baseline"]["pedestrian_count"])
        if any(value < 0 or value > pedestrians or not value.is_integer() for value in values):
            raise StudyError("Residential pedestrian values must be whole numbers within pedestrian_count.")
        for value in values:
            for replicate in range(replicates):
                payload = baseline_payload(config, classification_id, origin_ids, replicate)
                payload["residential_pedestrian_count"] = int(value)
                payload["public_transport_pedestrian_count"] = pedestrians - int(value)
                add_point(
                    "residential_pedestrians",
                    "Residential pedestrians",
                    value,
                    "people",
                    float(config["baseline"]["residential_pedestrian_count"]),
                    payload,
                    replicate,
                )

    vehicle_count = experiments.get("vehicle_count") or {}
    if vehicle_count.get("enabled", False):
        if not vehicle_count.get("keep_pedestrian_count_fixed", True):
            raise StudyError("Only keep_pedestrian_count_fixed=true is currently supported.")
        values = include_value(numeric_values(vehicle_count), float(config["baseline"]["vehicle_count"]))
        if any(value < 0 or not value.is_integer() for value in values):
            raise StudyError("Vehicle counts must be non-negative whole numbers.")
        for value in values:
            for replicate in range(replicates):
                payload = baseline_payload(config, classification_id, origin_ids, replicate)
                update_vehicle_count(payload, int(value), origin_ids)
                add_point(
                    "vehicle_count",
                    "Vehicle count (pedestrians fixed)",
                    value,
                    "vehicles",
                    float(config["baseline"]["vehicle_count"]),
                    payload,
                    replicate,
                )

    entries = experiments.get("vehicle_entry_allocations") or {}
    if entries.get("enabled", False):
        if len(origin_ids) < 2:
            raise StudyError("Entry-allocation sensitivity needs at least two vehicle origins.")
        values = numeric_values(entries, percent=True)
        if any(not 0 <= value <= 100 for value in values):
            raise StudyError("Vehicle entry allocation percentages must be between 0 and 100.")
        baseline_share = 100.0 / len(origin_ids)
        values = include_value(values, baseline_share)
        for tested_index, origin_id in enumerate(origin_ids):
            for value in values:
                remainder_share = (100.0 - value) / (len(origin_ids) - 1)
                percentages = [remainder_share] * len(origin_ids)
                percentages[tested_index] = value
                for replicate in range(replicates):
                    payload = baseline_payload(config, classification_id, origin_ids, replicate)
                    payload["vehicle_origin_allocations"] = allocate_counts(
                        origin_ids, percentages, int(payload["vehicle_count"])
                    )
                    add_point(
                        f"vehicle_entry_{origin_id}",
                        f"Vehicle entry: {origin_names[origin_id]}",
                        value,
                        "% of vehicles",
                        baseline_share,
                        payload,
                        replicate,
                    )

    parking_specs = experiments.get("parking_choice") or {}
    unknown_paths = set(parking_specs) - PARKING_PATHS
    if unknown_paths:
        raise StudyError("Unknown parking-choice paths: " + ", ".join(sorted(unknown_paths)))
    for path, spec in parking_specs.items():
        if not spec.get("enabled", False):
            continue
        baseline_value = get_nested(config["baseline"]["parking_choice"], path)
        values = include_value(numeric_values(spec), baseline_value)
        for value in values:
            for replicate in range(replicates):
                payload = baseline_payload(config, classification_id, origin_ids, replicate)
                set_nested(payload["parking_choice"], path, value)
                add_point(
                    f"parking_choice.{path}",
                    f"Parking choice: {path}",
                    value,
                    "coefficient",
                    baseline_value,
                    payload,
                    replicate,
                )

    plan_identity = {
        "version": VERSION,
        "model_signature": model_signature,
        "points": points,
        "payload_hashes": sorted(runs),
    }
    return {
        "version": VERSION,
        "study_name": str(config.get("study_name") or "sensitivity_study"),
        "created_at": utc_now(),
        "model_signature": model_signature,
        "plan_signature": digest(plan_identity),
        "points": points,
        "runs": runs,
    }


def prepare_study(config_path: Path) -> PreparedStudy:
    config_path = config_path.resolve()
    config = load_config(config_path)
    required = {"baseline", "experiments", "output_directory"}
    missing = required - set(config)
    if missing:
        raise StudyError("Missing config keys: " + ", ".join(sorted(missing)))
    api = ApiClient(str(config.get("api_url") or "http://localhost:8000"))
    health = api.request("/api/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise StudyError(f"Application API is not healthy: {health}")
    model_summary = resolve_named(
        api.request("/api/models"), str(config["baseline"]["model_name"]), label="model"
    )
    model = api.request(f"/api/models/{model_summary['id']}")
    classification = resolve_named(
        model.get("buildingClassifications") or [],
        str(config["baseline"]["classification_name"]),
        label="building classification",
    )
    origins = list(model.get("vehicleGenerationPoints") or [])
    if int(config["baseline"]["vehicle_count"]) > 0 and not origins:
        raise StudyError("The selected model has no vehicle generation points.")

    comparison = config.get("real_world_comparison") or {}
    detector = sensor = None
    if comparison.get("enabled", False):
        sensor = resolve_named(
            api.request("/api/analytics/real-world/sources"),
            str(comparison["sensor_name"]),
            label="real-world sensor",
            fields=("name", "street", "segment_id"),
        )
        compatible = [item for item in model.get("detectors") or [] if item.get("type") == "e3"]
        detector = resolve_named(
            compatible,
            str(comparison["detector_name"]),
            label="E3 detector",
            fields=("name", "id"),
        )
        subjects = set(comparison.get("subjects") or ["vehicles"])
        invalid = subjects - {"vehicles", "pedestrians"}
        unavailable = subjects - set(detector.get("detects") or ["vehicles"])
        if invalid:
            raise StudyError("Invalid comparison subjects: " + ", ".join(sorted(invalid)))
        if unavailable:
            raise StudyError(
                f"Detector {detector.get('name') or detector.get('id')} does not measure: "
                + ", ".join(sorted(unavailable))
            )

    model_signature = digest({
        "id": model.get("id"),
        "updatedAt": model.get("updatedAt"),
        "selectedBuildingIds": model.get("selectedBuildingIds") or [],
        "selectedParkingIds": model.get("selectedParkingIds") or [],
        "buildingClassifications": model.get("buildingClassifications") or [],
        "parkingSpecs": model.get("parkingSpecs") or {},
        "origins": origins,
        "detectors": model.get("detectors") or [],
    })
    plan = build_plan(config, str(classification["id"]), origins, model_signature)
    output = Path(str(config["output_directory"]))
    output_dir = output if output.is_absolute() else config_path.parent / output
    prepared = PreparedStudy(
        config=config,
        config_path=config_path,
        output_dir=output_dir.resolve(),
        api=api,
        model=model,
        classification=classification,
        origins=origins,
        detector=detector,
        sensor=sensor,
        model_signature=model_signature,
        plan=plan,
    )
    write_plan_csv(prepared)
    return prepared


def plan_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    run_numbers = {key: index + 1 for index, key in enumerate(sorted(plan["runs"]))}
    return [
        {
            **point,
            "run_number": run_numbers[point["payload_hash"]],
            "is_parameter_baseline": math.isclose(
                float(point["value"]), float(point["baseline_value"]), rel_tol=0, abs_tol=1e-9
            ),
        }
        for point in plan["points"]
    ]


def write_plan_csv(study: PreparedStudy) -> None:
    rows = plan_rows(study.plan)
    write_csv(
        study.output_dir / "plan.csv",
        rows,
        [
            "run_number", "point_id", "parameter_id", "parameter_label", "value", "unit",
            "baseline_value", "is_parameter_baseline", "replicate", "payload_hash",
        ],
    )


def describe_spacing(values: Sequence[float]) -> str:
    ordered = sorted(set(values))
    if len(ordered) < 2:
        return "n/a"
    steps = [round(ordered[index + 1] - ordered[index], 12) for index in range(len(ordered) - 1)]
    if all(math.isclose(item, steps[0], rel_tol=0, abs_tol=1e-9) for item in steps):
        return f"{steps[0]:g}"
    return "explicit/non-uniform"


def print_plan(study: PreparedStudy) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in study.plan["points"]:
        grouped[point["parameter_id"]].append(point)
    print(f"\nSensitivity study: {study.plan['study_name']}")
    print(f"Model: {study.model.get('name')} ({study.model.get('id')})")
    print(f"Classification: {study.classification.get('name')}")
    print(f"Vehicle origins discovered: {len(study.origins)}")
    for item in study.origins:
        print(f"  - {item.get('name') or item.get('id')} [{item.get('id')}]")
    print("\nPlanned design points (baseline values are included automatically):")
    print(f"{'Parameter':54} {'Tests':>7} {'Min':>10} {'Max':>10} {'Step':>18}")
    for parameter_id, points in grouped.items():
        values = [float(item["value"]) for item in points if int(item["replicate"]) == 1]
        label = str(points[0]["parameter_label"])
        print(
            f"{label[:54]:54} {len(points):7d} {min(values):10g} {max(values):10g} "
            f"{describe_spacing(values):>18}"
        )
    print(f"\nRequested design points: {len(study.plan['points'])}")
    print(f"Actual simulations after identical-payload deduplication: {len(study.plan['runs'])}")
    print(f"Maximum submitted at once: {int(study.config.get('max_in_flight') or 4)}")
    print(f"Checkpoint: {study.state_path}")
    print(f"Plan CSV: {study.output_dir / 'plan.csv'}\n")


def initial_state(study: PreparedStudy) -> dict[str, Any]:
    atomic_write_json(study.output_dir / "config.snapshot.json", study.config)
    atomic_write_json(study.output_dir / "model_context.json", {
        "model_id": study.model.get("id"),
        "model_name": study.model.get("name"),
        "model_signature": study.model_signature,
        "classification": {
            "id": study.classification.get("id"),
            "name": study.classification.get("name"),
        },
        "vehicle_origins": [
            {"id": item.get("id"), "name": item.get("name")} for item in study.origins
        ],
        "comparison_detector": (
            {"id": study.detector.get("id"), "name": study.detector.get("name")}
            if study.detector else None
        ),
        "real_world_sensor": (
            {"id": study.sensor.get("id"), "name": study.sensor.get("name"), "street": study.sensor.get("street")}
            if study.sensor else None
        ),
    })
    runs = {}
    for payload_hash, planned in study.plan["runs"].items():
        runs[payload_hash] = {
            **copy.deepcopy(planned),
            "status": "planned",
            "run_id": None,
            "attempt": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "queue_seconds": None,
            "execution_seconds": None,
            "failure_reason": None,
            "analytics_status": "pending",
            "analytics_attempts": 0,
            "result_file": None,
        }
    return {
        "version": VERSION,
        "study_name": study.plan["study_name"],
        "plan_signature": study.plan["plan_signature"],
        "model_signature": study.model_signature,
        "model_id": study.model["id"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "runs": runs,
    }


def load_state(study: PreparedStudy, *, required: bool) -> dict[str, Any] | None:
    if not study.state_path.is_file():
        if required:
            raise StudyError(f"No checkpoint exists at {study.state_path}. Use the run command first.")
        return None
    state = load_config(study.state_path)
    if state.get("plan_signature") != study.plan["plan_signature"]:
        raise StudyError(
            "The configuration or saved model changed after this study started. "
            "Use a new study_name/output_directory so incompatible results are not mixed."
        )
    return state


def save_state(study: PreparedStudy, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(study.state_path, state)


def series_metrics(real_points: Sequence[dict[str, Any]], simulated_points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    real_by_time = {
        round(float(point.get("time_seconds") or 0)): float(point.get("flow_per_hour") or 0)
        for point in real_points
    }
    simulated_by_time = {
        round(float(point.get("begin_seconds") or 0)): float(point.get("flow_per_hour") or 0)
        for point in simulated_points
    }
    shared = sorted(set(real_by_time) & set(simulated_by_time))
    if not shared:
        return {"point_count": 0}
    real = [real_by_time[item] for item in shared]
    simulated = [simulated_by_time[item] for item in shared]
    differences = [simulated[index] - real[index] for index in range(len(shared))]
    mae = statistics.fmean(abs(item) for item in differences)
    rmse = math.sqrt(statistics.fmean(item * item for item in differences))
    real_mean = statistics.fmean(real)
    sim_mean = statistics.fmean(simulated)
    real_range = max(real) - min(real)
    smape_parts = [
        2 * abs(simulated[index] - real[index]) / (abs(simulated[index]) + abs(real[index]))
        for index in range(len(shared))
        if abs(simulated[index]) + abs(real[index]) > 0
    ]
    correlation = pearson(real, simulated)
    real_scale = real_mean if abs(real_mean) > 1e-12 else 1.0
    sim_scale = sim_mean if abs(sim_mean) > 1e-12 else 1.0
    shape_rmse = math.sqrt(statistics.fmean(
        ((simulated[index] / sim_scale) - (real[index] / real_scale)) ** 2
        for index in range(len(shared))
    ))
    return {
        "point_count": len(shared),
        "mae_flow_per_hour": mae,
        "rmse_flow_per_hour": rmse,
        "nrmse_by_real_mean": rmse / real_mean if real_mean else None,
        "nrmse_by_real_range": rmse / real_range if real_range else None,
        "smape_percent": statistics.fmean(smape_parts) * 100 if smape_parts else 0.0,
        "pearson_correlation": correlation,
        "shape_rmse": shape_rmse,
        "real_mean_flow_per_hour": real_mean,
        "simulation_mean_flow_per_hour": sim_mean,
        "mean_flow_bias_per_hour": sim_mean - real_mean,
    }


def pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator > 0 else None


def rank_values(values: Sequence[float]) -> list[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][0] == ordered[cursor][0]:
            end += 1
        rank = (cursor + end - 1) / 2 + 1
        for _, original_index in ordered[cursor:end]:
            ranks[original_index] = rank
        cursor = end
    return ranks


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    return pearson(rank_values(left), rank_values(right))


def reference_series(study: PreparedStudy) -> dict[str, dict[str, Any]]:
    comparison = study.config.get("real_world_comparison") or {}
    if not comparison.get("enabled", False) or study.sensor is None:
        return {}
    hour, minute = [int(item) for item in str(comparison.get("start_time") or "07:00").split(":", 1)]
    duration_seconds = int(study.config["baseline"]["duration_hours"]) * 3600
    result = {}
    for subject in comparison.get("subjects") or ["vehicles"]:
        result[subject] = study.api.request(
            "/api/analytics/real-world/series",
            query={
                "source_id": study.sensor["id"],
                "mode": comparison.get("mode") or "weekly_average",
                "subject": subject,
                "duration_seconds": duration_seconds,
                "start_weekday": int(comparison.get("start_weekday", 0)),
                "start_time_seconds": hour * 3600 + minute * 60,
            },
        )
    return result


def extract_result(
    study: PreparedStudy,
    tracked: dict[str, Any],
    analytics: dict[str, Any],
    references: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    detectors = analytics.get("detectors") or {}
    definitions = detectors.get("definitions") or []
    comparison_series = detectors.get("comparison_series") or {}
    detector_metrics: list[dict[str, Any]] = []
    detector_timeseries: list[dict[str, Any]] = []
    comparison_metrics: list[dict[str, Any]] = []
    for definition in definitions:
        definition_id = str(definition.get("id") or "")
        points = comparison_series.get(definition_id) or []
        flows = [float(point.get("flow_per_hour") or 0) for point in points]
        counts = [float(point.get("interval_count") or 0) for point in points]
        peak_index = max(range(len(flows)), key=flows.__getitem__) if flows else None
        detector_metrics.append({
            "detector_id": definition_id,
            "logical_id": definition.get("logical_id"),
            "logical_name": definition.get("logical_name") or definition.get("label"),
            "subject": definition.get("subject") or "vehicles",
            "total_entries": sum(counts),
            "mean_flow_per_hour": mean(flows),
            "peak_flow_per_hour": max(flows) if flows else None,
            "peak_time_seconds": (
                float(points[peak_index].get("begin_seconds") or 0) if peak_index is not None else None
            ),
            "nonzero_intervals": sum(value > 0 for value in counts),
        })
        for point in points:
            detector_timeseries.append({
                "detector_id": definition_id,
                "logical_id": definition.get("logical_id"),
                "logical_name": definition.get("logical_name") or definition.get("label"),
                "subject": definition.get("subject") or "vehicles",
                "begin_seconds": float(point.get("begin_seconds") or 0),
                "end_seconds": float(point.get("end_seconds") or 0),
                "interval_count": float(point.get("interval_count") or 0),
                "flow_per_hour": float(point.get("flow_per_hour") or 0),
            })
        if (
            study.detector is not None
            and str(definition.get("logical_id")) == str(study.detector.get("id"))
            and str(definition.get("subject") or "vehicles") in references
        ):
            subject = str(definition.get("subject") or "vehicles")
            comparison_metrics.append({
                "detector_id": definition_id,
                "logical_id": definition.get("logical_id"),
                "logical_name": definition.get("logical_name") or definition.get("label"),
                "subject": subject,
                **series_metrics(references[subject].get("points") or [], points),
            })

    parking_destinations = analytics.get("parking_destinations") or {}
    search = analytics.get("search_times") or {}
    attempts = analytics.get("parking_attempts") or {}
    return {
        "schema_version": 1,
        "run_id": tracked.get("run_id"),
        "payload_hash": tracked["payload_hash"],
        "payload": tracked["payload"],
        "detector_metrics": detector_metrics,
        "detector_timeseries": detector_timeseries,
        "real_world_comparison": comparison_metrics,
        "parking_destination_summary": parking_destinations.get("summary") or {},
        "parking_areas": parking_destinations.get("parkings") or [],
        "destination_buildings": parking_destinations.get("buildings") or [],
        "search_time_summary": search.get("summary") or {},
        "parking_attempt_summary": attempts.get("summary") or {},
    }


def reconcile_runs(study: PreparedStudy, state: dict[str, Any]) -> None:
    remote = {
        str(item.get("id")): item
        for item in study.api.request(f"/api/models/{study.model['id']}/simulations")
    }
    for tracked in state["runs"].values():
        run_id = tracked.get("run_id")
        if not run_id or run_id not in remote:
            continue
        record = remote[run_id]
        tracked["status"] = record.get("status") or tracked["status"]
        for key in ("created_at", "started_at", "completed_at", "failure_reason", "queue_position"):
            tracked[key] = record.get(key)
        tracked["queue_seconds"] = elapsed_seconds(record.get("created_at"), record.get("started_at"))
        tracked["execution_seconds"] = elapsed_seconds(record.get("started_at"), record.get("completed_at"))


def collect_completed(
    study: PreparedStudy,
    state: dict[str, Any],
    references: dict[str, dict[str, Any]],
) -> None:
    results_dir = study.output_dir / "results"
    for tracked in state["runs"].values():
        if tracked.get("status") != "completed" or tracked.get("analytics_status") == "collected":
            continue
        try:
            analytics = study.api.request(f"/api/analytics/{tracked['run_id']}")
            result = extract_result(study, tracked, analytics, references)
            result_path = results_dir / f"{tracked['payload_hash']}.json"
            atomic_write_json(result_path, result)
            tracked["analytics_status"] = "collected"
            tracked["result_file"] = str(result_path.relative_to(study.output_dir))
            tracked["analytics_error"] = None
        except ApiError as exc:
            tracked["analytics_attempts"] = int(tracked.get("analytics_attempts") or 0) + 1
            tracked["analytics_error"] = str(exc)
            if tracked["analytics_attempts"] >= 12:
                tracked["analytics_status"] = "failed"


def submit_planned(study: PreparedStudy, state: dict[str, Any]) -> None:
    maximum = int(study.config.get("max_in_flight") or 4)
    if maximum < 1:
        raise StudyError("max_in_flight must be at least 1.")
    active = sum(item.get("status") in ACTIVE_STATUSES for item in state["runs"].values())
    slots = max(maximum - active, 0)
    planned = [item for item in state["runs"].values() if item.get("status") == "planned"]
    for tracked in planned[:slots]:
        created = study.api.request(
            f"/api/models/{study.model['id']}/simulations",
            method="POST",
            payload=tracked["payload"],
        )
        tracked["run_id"] = str(created["id"])
        tracked["status"] = str(created.get("status") or "queued")
        tracked["attempt"] = int(tracked.get("attempt") or 0) + 1
        tracked["created_at"] = created.get("created_at") or utc_now()
        tracked["started_at"] = created.get("started_at")
        tracked["completed_at"] = created.get("completed_at")
        tracked["failure_reason"] = None
        tracked["analytics_status"] = "pending"
        tracked["analytics_attempts"] = 0
        save_state(study, state)


def progress_counts(state: dict[str, Any]) -> dict[str, int]:
    counts = defaultdict(int)
    for item in state["runs"].values():
        counts[str(item.get("status") or "planned")] += 1
    return counts


def format_duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "unknown"
    seconds = max(int(round(seconds)), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def progress_line(study: PreparedStudy, state: dict[str, Any]) -> str:
    counts = progress_counts(state)
    total = len(state["runs"])
    terminal = counts["completed"] + counts["failed"]
    width = 24
    filled = round(width * terminal / total) if total else width
    durations = [
        float(item["execution_seconds"])
        for item in state["runs"].values()
        if item.get("execution_seconds") is not None and item.get("status") == "completed"
    ]
    remaining = counts["planned"] + counts["queued"] + counts["running"]
    workers = max(int(study.config.get("max_in_flight") or 4), 1)
    eta = statistics.fmean(durations) * remaining / workers if durations else None
    created_at = parse_time(state.get("created_at"))
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    study_elapsed = (
        max((datetime.now(timezone.utc) - created_at).total_seconds(), 0.0)
        if created_at is not None else None
    )
    local_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return (
        f"[{local_time} | elapsed {format_duration(study_elapsed)}] "
        f"[{'#' * filled}{'-' * (width - filled)}] {terminal}/{total} | "
        f"running {counts['running']} | queued {counts['queued']} | "
        f"planned {counts['planned']} | failed {counts['failed']} | ETA {format_duration(eta)}"
    )


def progress_signature(state: dict[str, Any]) -> tuple[int, ...]:
    """Return only values whose change merits a new progress-log line."""
    counts = progress_counts(state)
    return tuple(counts[name] for name in ("completed", "failed", "running", "queued", "planned"))


def retry_failed(state: dict[str, Any]) -> int:
    changed = 0
    for tracked in state["runs"].values():
        if tracked.get("status") != "failed":
            continue
        history = tracked.setdefault("previous_attempts", [])
        history.append({
            "run_id": tracked.get("run_id"),
            "failure_reason": tracked.get("failure_reason"),
            "created_at": tracked.get("created_at"),
            "started_at": tracked.get("started_at"),
            "completed_at": tracked.get("completed_at"),
        })
        tracked.update({
            "status": "planned",
            "run_id": None,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "queue_seconds": None,
            "execution_seconds": None,
            "failure_reason": None,
            "analytics_status": "pending",
            "analytics_attempts": 0,
            "result_file": None,
        })
        changed += 1
    return changed


def execute_study(study: PreparedStudy, *, resume: bool, retry: bool) -> None:
    state = load_state(study, required=resume)
    if state is None:
        state = initial_state(study)
        save_state(study, state)
    elif not resume:
        raise StudyError(f"A checkpoint already exists. Use resume: {study.state_path}")
    reconcile_runs(study, state)
    if retry:
        count = retry_failed(state)
        print(f"Reset {count} failed run(s) to planned.")
    save_state(study, state)
    references = reference_series(study)
    poll_seconds = max(float(study.config.get("poll_seconds") or 10), 1.0)
    print("Starting/resuming the study. Ctrl+C is safe; submitted server runs continue.")
    last_progress_signature: tuple[int, ...] | None = None
    last_progress_printed_at = 0.0
    try:
        while True:
            reconcile_runs(study, state)
            collect_completed(study, state, references)
            submit_planned(study, state)
            save_state(study, state)
            now = time.monotonic()
            signature = progress_signature(state)
            # Some terminals and log collectors preserve carriage returns instead
            # of replacing the current line.  Print only meaningful transitions,
            # plus an occasional heartbeat while a long simulation is unchanged.
            if signature != last_progress_signature or now - last_progress_printed_at >= 300:
                print(progress_line(study, state), flush=True)
                last_progress_signature = signature
                last_progress_printed_at = now
            counts = progress_counts(state)
            no_work = counts["planned"] + counts["queued"] + counts["running"] == 0
            analytics_pending = any(
                item.get("status") == "completed" and item.get("analytics_status") == "pending"
                for item in state["runs"].values()
            )
            if no_work and not analytics_pending:
                break
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        save_state(study, state)
        print(f"\nInterrupted safely. Resume with:\n  python3 {Path(__file__)} resume --config {study.config_path}")
        return
    analyze_study(study, state)
    failed = progress_counts(state)["failed"]
    print(f"Study processing finished with {failed} failed simulation(s).")
    print(f"Report: {study.output_dir / 'report.md'}")


def result_metric_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def append(scope: str, entity: str, name: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        number = float(value)
        if math.isfinite(number):
            rows.append({
                "metric_scope": scope,
                "metric_entity": entity,
                "metric_name": name,
                "metric_value": number,
            })

    for item in result.get("detector_metrics") or []:
        entity = f"{item.get('logical_name')} [{item.get('subject')}]"
        for key in ("total_entries", "mean_flow_per_hour", "peak_flow_per_hour", "peak_time_seconds", "nonzero_intervals"):
            append("detector", entity, key, item.get(key))
    for item in result.get("detector_timeseries") or []:
        entity = f"{item.get('logical_name')} [{item.get('subject')}]"
        begin = int(float(item.get("begin_seconds") or 0))
        append("detector_interval", entity, f"flow_per_hour_at_{begin}s", item.get("flow_per_hour"))
    for item in result.get("real_world_comparison") or []:
        entity = f"{item.get('logical_name')} vs real [{item.get('subject')}]"
        for key, value in item.items():
            if key not in {"detector_id", "logical_id", "logical_name", "subject"}:
                append("real_world_comparison", entity, key, value)
    for key, value in (result.get("parking_destination_summary") or {}).items():
        append("parking_summary", "all parkings", key, value)
    for key, value in (result.get("search_time_summary") or {}).items():
        append("search_time", "all vehicles", key, value)
    for key, value in (result.get("parking_attempt_summary") or {}).items():
        append("parking_attempts", "all vehicles", key, value)
    for item in result.get("parking_areas") or []:
        entity = str(item.get("name") or item.get("id"))
        for key, value in item.items():
            if key not in {"id", "name", "unused_reason"}:
                append("parking_area", entity, key, value)
    for item in result.get("destination_buildings") or []:
        entity = str(item.get("name") or item.get("id"))
        for key, value in item.items():
            if key not in {"id", "name", "zero_driver_reason"}:
                append("destination_building", entity, key, value)
    return rows


def load_results(study: PreparedStudy, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = {}
    for payload_hash, tracked in state["runs"].items():
        relative = tracked.get("result_file")
        if not relative:
            continue
        path = study.output_dir / str(relative)
        if not path.is_file():
            continue
        results[payload_hash] = load_config(path)
    return results


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def regression(features: Sequence[Sequence[float]], values: Sequence[float]) -> list[float] | None:
    if not features or len(features) != len(values):
        return None
    columns = len(features[0])
    matrix = [
        [sum(row[left] * row[right] for row in features) for right in range(columns)]
        for left in range(columns)
    ]
    vector = [sum(row[column] * value for row, value in zip(features, values)) for column in range(columns)]
    return solve_linear_system(matrix, vector)


def fit_statistics(observed: Sequence[float], predicted: Sequence[float], parameter_count: int) -> dict[str, float]:
    residuals = [observed[index] - predicted[index] for index in range(len(observed))]
    sse = sum(item * item for item in residuals)
    average = statistics.fmean(observed)
    total = sum((item - average) ** 2 for item in observed)
    r_squared = 1 - sse / total if total > 0 else (1.0 if sse < 1e-12 else 0.0)
    sample_count = len(observed)
    safe_sse = max(sse, 1e-24)
    aic = sample_count * math.log(safe_sse / sample_count) + 2 * parameter_count
    aicc = (
        aic + 2 * parameter_count * (parameter_count + 1) / (sample_count - parameter_count - 1)
        if sample_count > parameter_count + 1 else math.inf
    )
    return {"sse": sse, "r_squared": r_squared, "aicc": aicc}


def fit_models(x: Sequence[float], y: Sequence[float]) -> list[dict[str, Any]]:
    if len(x) != len(y) or len(x) < 2 or len(set(x)) < 2:
        return []
    rows: list[dict[str, Any]] = []
    center = statistics.fmean(x)
    scale = max(max(abs(value - center) for value in x), 1.0)
    z = [(value - center) / scale for value in x]

    linear = regression([[1.0, value] for value in z], y)
    if linear:
        intercept = linear[0] - linear[1] * center / scale
        slope = linear[1] / scale
        predicted = [intercept + slope * value for value in x]
        rows.append({
            "model": "linear",
            "equation": f"y = {intercept:.10g} + ({slope:.10g})*x",
            "coefficients": {"a": intercept, "b": slope},
            **fit_statistics(y, predicted, 2),
        })

    if len(set(x)) >= 3 and len(x) >= 3:
        quadratic = regression([[1.0, value, value * value] for value in z], y)
        if quadratic:
            a, b, c = quadratic
            actual_c = c / (scale * scale)
            actual_b = b / scale - 2 * c * center / (scale * scale)
            actual_a = a - b * center / scale + c * center * center / (scale * scale)
            predicted = [actual_a + actual_b * value + actual_c * value * value for value in x]
            rows.append({
                "model": "quadratic",
                "equation": f"y = {actual_a:.10g} + ({actual_b:.10g})*x + ({actual_c:.10g})*x^2",
                "coefficients": {"a": actual_a, "b": actual_b, "c": actual_c},
                **fit_statistics(y, predicted, 3),
            })

    positive = [value for value in x if value > 0]
    if len(set(x)) >= 4 and len(x) >= 4 and min(x) >= 0 and positive:
        low = min(positive) / 10
        high = max(positive) * 10
        if low > 0 and high > low:
            best: dict[str, Any] | None = None
            log_low, log_high = math.log(low), math.log(high)
            for exponent_index in range(1, 25):
                exponent = exponent_index * 0.25
                for half_index in range(81):
                    half = math.exp(log_low + (log_high - log_low) * half_index / 80)
                    basis = []
                    for value in x:
                        if value <= 0:
                            basis.append(0.0)
                        else:
                            ratio = (value / half) ** exponent
                            basis.append(ratio / (1 + ratio))
                    coefficients = regression([[1.0, value] for value in basis], y)
                    if not coefficients:
                        continue
                    predicted = [coefficients[0] + coefficients[1] * value for value in basis]
                    stats = fit_statistics(y, predicted, 4)
                    candidate = {
                        "model": "hill",
                        "equation": (
                            f"y = {coefficients[0]:.10g} + ({coefficients[1]:.10g})*"
                            f"x^{exponent:.4g}/({half:.10g}^{exponent:.4g} + x^{exponent:.4g})"
                        ),
                        "coefficients": {
                            "y0": coefficients[0], "vmax": coefficients[1],
                            "k_half": half, "n": exponent,
                        },
                        **stats,
                    }
                    if best is None or candidate["sse"] < best["sse"]:
                        best = candidate
            if best:
                rows.append(best)
    finite = [item for item in rows if math.isfinite(float(item["aicc"]))]
    best = min(finite or rows, key=lambda item: (item["aicc"], item["sse"])) if rows else None
    for item in rows:
        item["is_best"] = item is best
    return rows


def nearest_baseline_slope(points: Sequence[tuple[float, float]], baseline: float) -> float | None:
    grouped: dict[float, list[float]] = defaultdict(list)
    for x, y in points:
        grouped[x].append(y)
    averaged = sorted((x, statistics.fmean(values)) for x, values in grouped.items())
    below = [item for item in averaged if item[0] < baseline]
    above = [item for item in averaged if item[0] > baseline]
    if below and above:
        left, right = below[-1], above[0]
    else:
        candidates = sorted(averaged, key=lambda item: abs(item[0] - baseline))[:2]
        if len(candidates) < 2:
            return None
        left, right = sorted(candidates)
    return (right[1] - left[1]) / (right[0] - left[0]) if right[0] != left[0] else None


def analyze_study(study: PreparedStudy, state: dict[str, Any]) -> None:
    results = load_results(study, state)
    points_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in study.plan["points"]:
        points_by_hash[point["payload_hash"]].append(point)

    run_rows = []
    detector_series_rows = []
    metric_rows = []
    parking_rows = []
    building_rows = []
    for payload_hash, tracked in state["runs"].items():
        run_rows.append({
            "payload_hash": payload_hash,
            "run_id": tracked.get("run_id"),
            "status": tracked.get("status"),
            "attempt": tracked.get("attempt"),
            "created_at": tracked.get("created_at"),
            "started_at": tracked.get("started_at"),
            "completed_at": tracked.get("completed_at"),
            "queue_seconds": tracked.get("queue_seconds"),
            "execution_seconds": tracked.get("execution_seconds"),
            "analytics_status": tracked.get("analytics_status"),
            "failure_reason": tracked.get("failure_reason"),
            "parameters": "; ".join(
                sorted({point["parameter_id"] for point in points_by_hash[payload_hash]})
            ),
        })
        result = results.get(payload_hash)
        if not result:
            continue
        for row in result.get("detector_timeseries") or []:
            detector_series_rows.append({"payload_hash": payload_hash, "run_id": tracked.get("run_id"), **row})
        normalized = result_metric_rows(result)
        for row in normalized:
            metric_rows.append({"payload_hash": payload_hash, "run_id": tracked.get("run_id"), **row})
        for row in result.get("parking_areas") or []:
            parking_rows.append({"payload_hash": payload_hash, "run_id": tracked.get("run_id"), **row})
        for row in result.get("destination_buildings") or []:
            building_rows.append({"payload_hash": payload_hash, "run_id": tracked.get("run_id"), **row})

    write_csv(
        study.output_dir / "runs.csv", run_rows,
        ["payload_hash", "run_id", "status", "attempt", "created_at", "started_at", "completed_at",
         "queue_seconds", "execution_seconds", "analytics_status", "failure_reason", "parameters"],
    )
    write_csv(
        study.output_dir / "detector_timeseries.csv", detector_series_rows,
        ["payload_hash", "run_id", "detector_id", "logical_id", "logical_name", "subject",
         "begin_seconds", "end_seconds", "interval_count", "flow_per_hour"],
    )
    write_csv(
        study.output_dir / "metrics.csv", metric_rows,
        ["payload_hash", "run_id", "metric_scope", "metric_entity", "metric_name", "metric_value"],
    )
    parking_fields = sorted({key for row in parking_rows for key in row})
    building_fields = sorted({key for row in building_rows for key in row})
    write_csv(study.output_dir / "parking_outcomes.csv", parking_rows, parking_fields or ["payload_hash"])
    write_csv(study.output_dir / "building_outcomes.csv", building_rows, building_fields or ["payload_hash"])

    metrics_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in metric_rows:
        metrics_by_hash[row["payload_hash"]].append(row)
    observations: dict[tuple[str, str, str, str], list[tuple[float, float, float]]] = defaultdict(list)
    for point in study.plan["points"]:
        if point["parameter_id"] == "baseline":
            continue
        for metric in metrics_by_hash.get(point["payload_hash"], []):
            key = (
                point["parameter_id"], metric["metric_scope"],
                metric["metric_entity"], metric["metric_name"],
            )
            observations[key].append((
                float(point["value"]), float(metric["metric_value"]), float(point["baseline_value"])
            ))

    effect_rows = []
    model_rows = []
    for (parameter, scope, entity, metric_name), triples in observations.items():
        by_x: dict[float, list[float]] = defaultdict(list)
        for x, y, _baseline in triples:
            by_x[x].append(y)
        averaged = sorted((x, statistics.fmean(values)) for x, values in by_x.items())
        if len(averaged) < 2:
            continue
        x = [item[0] for item in averaged]
        y = [item[1] for item in averaged]
        baseline = triples[0][2]
        baseline_values = by_x.get(baseline) or []
        baseline_output = statistics.fmean(baseline_values) if baseline_values else None
        slope = nearest_baseline_slope([(item[0], item[1]) for item in averaged], baseline)
        elasticity = (
            slope * baseline / baseline_output
            if slope is not None and baseline_output not in (None, 0) else None
        )
        output_range = max(y) - min(y)
        effect_rows.append({
            "parameter_id": parameter,
            "metric_scope": scope,
            "metric_entity": entity,
            "metric_name": metric_name,
            "input_min": min(x),
            "input_max": max(x),
            "distinct_input_values": len(x),
            "baseline_input": baseline,
            "baseline_output": baseline_output,
            "output_min": min(y),
            "output_max": max(y),
            "output_range": output_range,
            "output_range_percent_of_baseline": (
                output_range / abs(baseline_output) * 100 if baseline_output not in (None, 0) else None
            ),
            "local_slope_at_baseline": slope,
            "normalized_elasticity": elasticity,
            "spearman_monotonicity": spearman(x, y),
        })
        for fitted in fit_models(x, y):
            model_rows.append({
                "parameter_id": parameter,
                "metric_scope": scope,
                "metric_entity": entity,
                "metric_name": metric_name,
                "model": fitted["model"],
                "equation": fitted["equation"],
                "coefficients_json": canonical_json(fitted["coefficients"]),
                "r_squared": fitted["r_squared"],
                "sse": fitted["sse"],
                "aicc": fitted["aicc"],
                "is_best": fitted["is_best"],
            })
    write_csv(
        study.output_dir / "effects.csv", effect_rows,
        ["parameter_id", "metric_scope", "metric_entity", "metric_name", "input_min", "input_max",
         "distinct_input_values", "baseline_input", "baseline_output", "output_min", "output_max",
         "output_range", "output_range_percent_of_baseline", "local_slope_at_baseline",
         "normalized_elasticity", "spearman_monotonicity"],
    )
    write_csv(
        study.output_dir / "response_models.csv", model_rows,
        ["parameter_id", "metric_scope", "metric_entity", "metric_name", "model", "equation",
         "coefficients_json", "r_squared", "sse", "aicc", "is_best"],
    )
    write_report(study, state, effect_rows, model_rows)


def write_report(
    study: PreparedStudy,
    state: dict[str, Any],
    effects: Sequence[dict[str, Any]],
    models: Sequence[dict[str, Any]],
) -> None:
    counts = progress_counts(state)
    durations = [
        float(item["execution_seconds"])
        for item in state["runs"].values()
        if item.get("execution_seconds") is not None and item.get("status") == "completed"
    ]
    ranked = sorted(
        (
            item for item in effects
            if item.get("output_range_percent_of_baseline") is not None
            and item["metric_scope"] in {"detector", "real_world_comparison", "parking_summary", "search_time"}
        ),
        key=lambda item: abs(float(item["output_range_percent_of_baseline"])),
        reverse=True,
    )[:30]
    best_models = [item for item in models if item.get("is_best")]
    lines = [
        f"# {study.plan['study_name']}",
        "",
        f"- Model: {study.model.get('name')} (`{study.model.get('id')}`)",
        f"- Unique simulations: {len(state['runs'])}",
        f"- Completed: {counts['completed']}",
        f"- Failed: {counts['failed']}",
        f"- Mean execution time: {format_duration(statistics.fmean(durations) if durations else None)}",
        f"- Generated: {utc_now()}",
        "",
        "## Strongest observed ranges",
        "",
        "These are descriptive OFAT effects. They do not include interactions between parameters.",
        "",
        "| Parameter | Output | Range vs baseline | Local slope | Monotonicity |",
        "|---|---|---:|---:|---:|",
    ]
    for item in ranked:
        output = f"{item['metric_scope']} / {item['metric_entity']} / {item['metric_name']}"
        slope = item.get("local_slope_at_baseline")
        monotonicity = item.get("spearman_monotonicity")
        lines.append(
            f"| {item['parameter_id']} | {output} | {float(item['output_range_percent_of_baseline']):.2f}% | "
            f"{float(slope):.6g} | {float(monotonicity):.3f} |"
            if slope is not None and monotonicity is not None else
            f"| {item['parameter_id']} | {output} | {float(item['output_range_percent_of_baseline']):.2f}% | n/a | n/a |"
        )
    lines += [
        "",
        "## Response equations",
        "",
        f"`response_models.csv` contains {len(models)} candidate fits and {len(best_models)} selected fits. "
        "Selection uses the lowest finite AICc; inspect R² and residual shape before using an equation for calibration.",
        "",
        "## Important interpretation limits",
        "",
        "- OFAT estimates effects around one baseline; it cannot measure interactions such as vehicle count × entry allocation.",
        "- Detector flow can be discontinuous when route choice switches, so a smooth Hill curve may be inappropriate.",
        "- A parameter can strongly affect campus parking while barely affecting the Avenue Paul Langevin detector, or vice versa.",
        "- For non-zero choice randomness, use multiple replicates and compare the mean plus variation.",
        "",
    ]
    (study.output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def analyze_command(study: PreparedStudy) -> None:
    state = load_state(study, required=True)
    assert state is not None
    reconcile_runs(study, state)
    references = reference_series(study)
    collect_completed(study, state, references)
    save_state(study, state)
    analyze_study(study, state)
    print(f"Analysis files rebuilt in {study.output_dir}")


def confirmation(assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input("Type RUN to submit/resume simulations, or press Enter to cancel: ").strip() == "RUN"
    except EOFError:
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable SUMO one-factor-at-a-time sensitivity study.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "resume", "analyze"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", type=Path, required=True)
        if name in {"run", "resume"}:
            sub.add_argument("--yes", action="store_true", help="Skip the RUN confirmation prompt.")
        if name == "resume":
            sub.add_argument("--retry-failed", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        study = prepare_study(args.config)
        if args.command == "plan":
            print_plan(study)
            return 0
        if args.command == "analyze":
            analyze_command(study)
            return 0
        print_plan(study)
        if not confirmation(args.yes):
            print("Cancelled; no simulations were submitted.")
            return 0
        execute_study(
            study,
            resume=args.command == "resume",
            retry=bool(getattr(args, "retry_failed", False)),
        )
        return 0
    except StudyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
