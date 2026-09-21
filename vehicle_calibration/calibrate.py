#!/usr/bin/env python3
"""Calibrate simulated vehicle flow to a real weekly-average sensor profile.

The runner keeps up to four independent simulations active. Initial designs
and validation seeds refill free workers immediately. Adaptive candidates are
selected in four-run batches only after the preceding observations are ready.
State and results are written atomically so an interrupted terminal can safely
resume without resubmitting completed work.

Only Python's standard library is required. A compact Gaussian-process
surrogate with expected improvement selects adaptive candidates after an
initial low-discrepancy design.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sensitivity_analysis.sensitivity import (  # noqa: E402
    ACTIVE_STATUSES,
    ApiClient,
    ApiError,
    PreparedStudy,
    StudyError,
    allocate_counts,
    atomic_write_json,
    baseline_payload,
    canonical_json,
    digest,
    elapsed_seconds,
    extract_result,
    format_duration,
    load_config,
    parse_time,
    reference_series,
    resolve_named,
    series_metrics,
    utc_now,
    write_csv,
)


VERSION = 1
CALIBRATION_PHASES = ("volume_routing", "shape", "joint")
TERMINAL_CANDIDATE_STATUSES = {"valid", "invalid", "failed"}
PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59)


@dataclass
class CalibrationContext:
    config: dict[str, Any]
    config_path: Path
    output_dir: Path
    study: PreparedStudy
    baseline_payload: dict[str, Any]
    origin_ids: list[str]
    origin_names: dict[str, str]
    config_signature: str

    @property
    def state_path(self) -> Path:
        return self.output_dir / "state.json"


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def model_signature(model: Mapping[str, Any]) -> str:
    return digest({
        "id": model.get("id"),
        "updatedAt": model.get("updatedAt"),
        "selectedBuildingIds": model.get("selectedBuildingIds") or [],
        "selectedParkingIds": model.get("selectedParkingIds") or [],
        "buildingClassifications": model.get("buildingClassifications") or [],
        "parkingSpecs": model.get("parkingSpecs") or {},
        "origins": model.get("vehicleGenerationPoints") or [],
        "detectors": model.get("detectors") or [],
    })


def validate_config(config: dict[str, Any]) -> None:
    required = {"study_name", "output_directory", "baseline", "search", "real_world_comparison"}
    missing = required - set(config)
    if missing:
        raise StudyError("Missing calibration config keys: " + ", ".join(sorted(missing)))
    maximum = int(config.get("max_in_flight") or 4)
    if maximum != 4:
        raise StudyError("This calibration is designed for max_in_flight=4.")
    search = config["search"]
    count = search.get("vehicle_count") or {}
    if int(count.get("minimum") or 0) <= 0:
        raise StudyError("search.vehicle_count.minimum must be positive.")
    if int(count.get("maximum") or 0) < int(count.get("minimum") or 0):
        raise StudyError("Vehicle-count maximum must be at least the minimum.")
    peak = search.get("fourier_peak_percent") or {}
    if float(peak.get("maximum", 300)) < float(peak.get("minimum", 0)):
        raise StudyError("Fourier peak maximum must be at least the minimum.")
    phases = search.get("phases") or {}
    for phase_name in CALIBRATION_PHASES:
        spec = phases.get(phase_name) or {}
        runs = int(spec.get("runs") or 0)
        if runs < 4 or runs % 4:
            raise StudyError(f"Phase {phase_name} runs must be a positive multiple of four.")
        initial = int(spec.get("initial_design_runs") or 0)
        if initial < 4 or initial > runs or initial % 4:
            raise StudyError(
                f"Phase {phase_name} initial_design_runs must be a multiple of four within its budget."
            )
    weights = config.get("objective") or {}
    names = ("shape", "point_rmse", "volume", "peak_timing")
    values = [float(weights.get(name) or 0) for name in names]
    if any(value < 0 for value in values) or sum(values) <= 0:
        raise StudyError("Objective weights must be non-negative and add to more than zero.")
    comparison = config["real_world_comparison"]
    if not comparison.get("enabled", True):
        raise StudyError("Vehicle calibration requires real_world_comparison.enabled=true.")
    if set(comparison.get("subjects") or ["vehicles"]) != {"vehicles"}:
        raise StudyError("Vehicle calibration must use subjects=[\"vehicles\"].")
    validation = config.get("validation") or {}
    if int(validation.get("candidate_count") or 0) < 1:
        raise StudyError("validation.candidate_count must be at least one.")
    if not validation.get("seeds"):
        raise StudyError("validation.seeds must contain at least one seed.")


def prepare_context(config_path: Path) -> CalibrationContext:
    config_path = config_path.resolve()
    config = load_config(config_path)
    validate_config(config)
    api = ApiClient(str(config.get("api_url") or "http://localhost:8000"))
    health = api.request("/api/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise StudyError(f"Application API is not healthy: {health}")
    model_summary = resolve_named(
        api.request("/api/models"),
        str(config["baseline"]["model_name"]),
        label="model",
    )
    model = api.request(f"/api/models/{model_summary['id']}")
    classification = resolve_named(
        model.get("buildingClassifications") or [],
        str(config["baseline"]["classification_name"]),
        label="building classification",
    )
    origins = list(model.get("vehicleGenerationPoints") or [])
    if len(origins) < 2:
        raise StudyError("Vehicle calibration requires at least two vehicle generation points.")
    compatible = [item for item in model.get("detectors") or [] if item.get("type") == "e3"]
    detector = resolve_named(
        compatible,
        str(config["real_world_comparison"]["detector_name"]),
        label="E3 detector",
        fields=("name", "id"),
    )
    if "vehicles" not in set(detector.get("detects") or ["vehicles"]):
        raise StudyError(f"Detector {detector.get('name')} does not measure vehicles.")
    sensor = resolve_named(
        api.request("/api/analytics/real-world/sources"),
        str(config["real_world_comparison"]["sensor_name"]),
        label="real-world sensor",
        fields=("name", "street", "segment_id"),
    )
    signature = model_signature(model)
    output = Path(str(config["output_directory"]))
    output_dir = output if output.is_absolute() else config_path.parent / output
    origin_ids = [str(item["id"]) for item in origins]
    base_payload = baseline_payload(config, str(classification["id"]), origin_ids, 0)
    study = PreparedStudy(
        config=config,
        config_path=config_path,
        output_dir=output_dir.resolve(),
        api=api,
        model=model,
        classification=classification,
        origins=origins,
        detector=detector,
        sensor=sensor,
        model_signature=signature,
        plan={},
    )
    return CalibrationContext(
        config=config,
        config_path=config_path,
        output_dir=output_dir.resolve(),
        study=study,
        baseline_payload=base_payload,
        origin_ids=origin_ids,
        origin_names={str(item["id"]): str(item.get("name") or item["id"]) for item in origins},
        config_signature=digest(config),
    )


def round_to_step(value: float, step: float) -> float:
    return round(value / step) * step if step > 0 else value


def project_sum_with_bounds(
    values: Sequence[float],
    target_sum: float,
    minimum: float,
    maximum: float,
    step: float,
) -> list[float]:
    """Project a vector onto a bounded, quantized constant-sum surface."""
    if not values:
        return []
    if target_sum < minimum * len(values) - 1e-9 or target_sum > maximum * len(values) + 1e-9:
        raise StudyError("Normalized Fourier mean is incompatible with the configured bounds.")
    low = minimum - max(values) - abs(target_sum)
    high = maximum - min(values) + abs(target_sum)
    for _ in range(80):
        shift = (low + high) / 2
        total = sum(min(max(value + shift, minimum), maximum) for value in values)
        if total < target_sum:
            low = shift
        else:
            high = shift
    projected = [min(max(value + (low + high) / 2, minimum), maximum) for value in values]
    if step > 0:
        projected = [min(max(round_to_step(value, step), minimum), maximum) for value in projected]
        units = int(round((target_sum - sum(projected)) / step))
        direction = 1 if units > 0 else -1
        for _ in range(abs(units)):
            eligible = [
                index for index, value in enumerate(projected)
                if minimum - 1e-9 <= value + direction * step <= maximum + 1e-9
            ]
            if not eligible:
                break
            index = min(
                eligible,
                key=lambda item: abs((projected[item] + direction * step) - values[item]),
            )
            projected[index] += direction * step
    return [round(value, 9) for value in projected]


def normalize_peaks(context: CalibrationContext, values: Sequence[float]) -> list[float]:
    spec = context.config["search"]["fourier_peak_percent"]
    count = int(context.baseline_payload["vehicle_fourier_parameters"]["peak_count"])
    if len(values) != count:
        raise StudyError(f"Expected {count} vehicle peak values, received {len(values)}.")
    target_mean = float(spec.get("normalized_mean_percent", 100))
    return project_sum_with_bounds(
        values,
        target_mean * count,
        float(spec.get("minimum", 0)),
        float(spec.get("maximum", 300)),
        float(spec.get("step", 5)),
    )


def radical_inverse(index: int, base: int) -> float:
    result = 0.0
    factor = 1.0 / base
    while index:
        result += factor * (index % base)
        index //= base
        factor /= base
    return result


def halton_point(index: int, dimension: int) -> list[float]:
    if dimension > len(PRIMES):
        raise StudyError(f"Halton dimension {dimension} exceeds supported dimension {len(PRIMES)}.")
    return [radical_inverse(index, PRIMES[item]) for item in range(dimension)]


def simplex_from_unit(values: Sequence[float]) -> list[float]:
    exponential = [-math.log(max(min(value, 1 - 1e-12), 1e-12)) for value in values]
    total = sum(exponential)
    return [value / total * 100.0 for value in exponential]


def parameters_from_payload(context: CalibrationContext, payload: Mapping[str, Any]) -> dict[str, Any]:
    count = int(payload.get("vehicle_count") or 0)
    by_origin = {
        str(item.get("origin_id")): int(item.get("vehicle_count") or 0)
        for item in payload.get("vehicle_origin_allocations") or []
    }
    shares = [by_origin.get(origin_id, 0) / count * 100 if count else 0.0 for origin_id in context.origin_ids]
    peak_values = [
        float(value) * 100
        for value in (payload.get("vehicle_fourier_parameters") or {}).get("peak_heights") or []
    ]
    return {
        "vehicle_count": count,
        "origin_percentages": shares,
        "peak_heights_percent": peak_values,
        "random_seed": int(payload.get("random_seed") or context.config["baseline"].get("random_seed") or 0),
    }


def canonical_parameters(context: CalibrationContext, parameters: Mapping[str, Any]) -> dict[str, Any]:
    count_spec = context.config["search"]["vehicle_count"]
    count = int(round_to_step(float(parameters["vehicle_count"]), float(count_spec.get("step", 100))))
    count = min(max(count, int(count_spec["minimum"])), int(count_spec["maximum"]))
    shares = [max(float(value), 0.0) for value in parameters["origin_percentages"]]
    if len(shares) != len(context.origin_ids) or sum(shares) <= 0:
        raise StudyError("Candidate origin percentages do not match the current model origins.")
    shares = [value / sum(shares) * 100 for value in shares]
    allocations = allocate_counts(context.origin_ids, shares, count)
    exact_counts = {str(item["origin_id"]): int(item["vehicle_count"]) for item in allocations}
    exact_shares = [exact_counts[item] / count * 100 for item in context.origin_ids]
    return {
        "vehicle_count": count,
        "origin_percentages": exact_shares,
        "peak_heights_percent": normalize_peaks(context, parameters["peak_heights_percent"]),
        "random_seed": int(parameters.get("random_seed") or context.config["baseline"].get("random_seed") or 0),
    }


def payload_for_parameters(context: CalibrationContext, parameters: Mapping[str, Any]) -> dict[str, Any]:
    values = canonical_parameters(context, parameters)
    payload = copy.deepcopy(context.baseline_payload)
    count = int(values["vehicle_count"])
    pedestrians = int(payload["pedestrian_count"])
    payload["vehicle_count"] = count
    payload["total_people"] = count + pedestrians
    payload["vehicle_percentage"] = round(count / (count + pedestrians) * 100)
    payload["vehicle_origin_allocations"] = allocate_counts(
        context.origin_ids,
        values["origin_percentages"],
        count,
    )
    payload["vehicle_fourier_parameters"]["peak_heights"] = [
        value / 100 for value in values["peak_heights_percent"]
    ]
    payload["random_seed"] = int(values["random_seed"])
    return payload


def candidate_from_unit(
    context: CalibrationContext,
    phase: str,
    unit: Sequence[float],
    base: Mapping[str, Any],
) -> dict[str, Any]:
    search = context.config["search"]
    count_spec = search["vehicle_count"]
    peak_spec = search["fourier_peak_percent"]
    count = int(base["vehicle_count"])
    shares = list(map(float, base["origin_percentages"]))
    peaks = list(map(float, base["peak_heights_percent"]))
    cursor = 0
    if phase in {"volume_routing", "joint"}:
        low = float(count_spec["minimum"])
        high = float(count_spec["maximum"])
        if phase == "joint":
            radius = float(search.get("joint_count_radius", 1500))
            low = max(low, float(base["vehicle_count"]) - radius)
            high = min(high, float(base["vehicle_count"]) + radius)
        count = round_to_step(low + unit[cursor] * (high - low), float(count_spec.get("step", 100)))
        cursor += 1
        random_shares = simplex_from_unit(unit[cursor:cursor + len(context.origin_ids)])
        cursor += len(context.origin_ids)
        if phase == "joint":
            exploration = float(search.get("joint_origin_exploration", 0.6))
            shares = [
                (1 - exploration) * float(base["origin_percentages"][index])
                + exploration * random_shares[index]
                for index in range(len(random_shares))
            ]
        else:
            shares = random_shares
    if phase in {"shape", "joint"}:
        minimum = float(peak_spec.get("minimum", 0))
        maximum = float(peak_spec.get("maximum", 300))
        peak_count = len(peaks)
        generated = [minimum + unit[cursor + index] * (maximum - minimum) for index in range(peak_count)]
        if phase == "joint":
            radius = float(search.get("joint_peak_radius_percent", 100))
            generated = [
                min(max(generated[index], peaks[index] - radius), peaks[index] + radius)
                for index in range(peak_count)
            ]
        peaks = generated
    return canonical_parameters(context, {
        "vehicle_count": count,
        "origin_percentages": shares,
        "peak_heights_percent": peaks,
        "random_seed": int(context.config["baseline"].get("random_seed") or 20260119),
    })


def feature_vector(context: CalibrationContext, parameters: Mapping[str, Any], phase: str) -> list[float]:
    search = context.config["search"]
    result: list[float] = []
    if phase in {"volume_routing", "joint"}:
        spec = search["vehicle_count"]
        span = max(float(spec["maximum"]) - float(spec["minimum"]), 1.0)
        result.append((float(parameters["vehicle_count"]) - float(spec["minimum"])) / span)
        result.extend(float(value) / 100 for value in parameters["origin_percentages"])
    if phase in {"shape", "joint"}:
        spec = search["fourier_peak_percent"]
        span = max(float(spec.get("maximum", 300)) - float(spec.get("minimum", 0)), 1.0)
        result.extend(
            (float(value) - float(spec.get("minimum", 0))) / span
            for value in parameters["peak_heights_percent"]
        )
    return result


def euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(len(left))))


def cholesky(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            value = matrix[row][column] - sum(
                lower[row][item] * lower[column][item] for item in range(column)
            )
            if row == column:
                if value <= 0:
                    raise ValueError("Kernel matrix is not positive definite.")
                lower[row][column] = math.sqrt(value)
            else:
                lower[row][column] = value / lower[column][column]
    return lower


def forward_solve(lower: Sequence[Sequence[float]], values: Sequence[float]) -> list[float]:
    result = [0.0] * len(values)
    for row in range(len(values)):
        result[row] = (
            values[row] - sum(lower[row][column] * result[column] for column in range(row))
        ) / lower[row][row]
    return result


def backward_solve(lower: Sequence[Sequence[float]], values: Sequence[float]) -> list[float]:
    result = [0.0] * len(values)
    for row in range(len(values) - 1, -1, -1):
        result[row] = (
            values[row]
            - sum(lower[column][row] * result[column] for column in range(row + 1, len(values)))
        ) / lower[row][row]
    return result


class GaussianProcess:
    def __init__(self, features: Sequence[Sequence[float]], objectives: Sequence[float]) -> None:
        self.features = [list(row) for row in features]
        self.mean = statistics.fmean(objectives)
        self.scale = statistics.pstdev(objectives) or 1.0
        normalized = [(value - self.mean) / self.scale for value in objectives]
        distances = [
            euclidean(features[left], features[right])
            for left in range(len(features))
            for right in range(left)
            if euclidean(features[left], features[right]) > 1e-9
        ]
        self.length = min(max(statistics.median(distances) if distances else 0.5, 0.2), 2.0)
        kernel = [
            [self._kernel(features[row], features[column]) for column in range(len(features))]
            for row in range(len(features))
        ]
        jitter = 1e-8
        for _ in range(8):
            trial = [row[:] for row in kernel]
            for index in range(len(trial)):
                trial[index][index] += jitter
            try:
                self.lower = cholesky(trial)
                break
            except ValueError:
                jitter *= 10
        else:
            raise ValueError("Could not stabilize Gaussian-process kernel matrix.")
        self.alpha = backward_solve(self.lower, forward_solve(self.lower, normalized))

    def _kernel(self, left: Sequence[float], right: Sequence[float]) -> float:
        radius = euclidean(left, right) / self.length
        root_five_radius = math.sqrt(5.0) * radius
        return (1 + root_five_radius + 5 * radius * radius / 3) * math.exp(-root_five_radius)

    def predict(self, feature: Sequence[float]) -> tuple[float, float]:
        vector = [self._kernel(feature, row) for row in self.features]
        normalized_mean = sum(vector[index] * self.alpha[index] for index in range(len(vector)))
        projected = forward_solve(self.lower, vector)
        variance = max(1.0 - sum(value * value for value in projected), 1e-12)
        return self.mean + self.scale * normalized_mean, self.scale * math.sqrt(variance)


def normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2 * math.pi)


def normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def expected_improvement(mean: float, deviation: float, best: float, xi: float) -> float:
    if deviation <= 1e-12:
        return max(best - mean - xi, 0.0)
    improvement = best - mean - xi
    z = improvement / deviation
    return improvement * normal_cdf(z) + deviation * normal_pdf(z)


def smoothed(values: Sequence[float]) -> list[float]:
    if len(values) < 3:
        return list(values)
    return [
        statistics.fmean(values[max(index - 1, 0):min(index + 2, len(values))])
        for index in range(len(values))
    ]


def peak_timing_error(real: Sequence[float], simulated: Sequence[float], windows: int) -> float:
    if not real or len(real) != len(simulated) or windows < 1:
        return 1.0
    left, right = smoothed(real), smoothed(simulated)
    errors = []
    for window in range(windows):
        start = round(window * len(real) / windows)
        end = round((window + 1) * len(real) / windows)
        if end <= start:
            continue
        real_peak = max(range(start, end), key=left.__getitem__)
        simulated_peak = max(range(start, end), key=right.__getitem__)
        errors.append(abs(real_peak - simulated_peak) / max(end - start - 1, 1))
    return statistics.fmean(errors) if errors else 1.0


def score_result(
    context: CalibrationContext,
    result: Mapping[str, Any],
    references: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    expected_points = int(context.config["baseline"]["duration_hours"]) * 4
    detector_id = str(context.study.detector.get("id"))
    points = [
        item for item in result.get("detector_timeseries") or []
        if str(item.get("logical_id")) == detector_id and item.get("subject") == "vehicles"
    ]
    real_points = list((references.get("vehicles") or {}).get("points") or [])
    metrics = series_metrics(real_points, points)
    if int(metrics.get("point_count") or 0) != expected_points or len(points) != expected_points:
        return {
            "valid": False,
            "reason": (
                f"Expected {expected_points} aligned vehicle intervals, received "
                f"{int(metrics.get('point_count') or 0)}."
            ),
        }
    real_by_time = {
        round(float(item.get("time_seconds") or 0)): float(item.get("flow_per_hour") or 0)
        for item in real_points
    }
    simulated_by_time = {
        round(float(item.get("begin_seconds") or 0)): float(item.get("flow_per_hour") or 0)
        for item in points
    }
    shared = sorted(set(real_by_time) & set(simulated_by_time))
    real = [real_by_time[item] for item in shared]
    simulated = [simulated_by_time[item] for item in shared]
    real_mean = float(metrics["real_mean_flow_per_hour"])
    sim_mean = float(metrics["simulation_mean_flow_per_hour"])
    components = {
        "shape": float(metrics["shape_rmse"]),
        "point_rmse": float(metrics["rmse_flow_per_hour"]) / max(abs(real_mean), 1e-12),
        "volume": abs(sim_mean - real_mean) / max(abs(real_mean), 1e-12),
        "peak_timing": peak_timing_error(
            real,
            simulated,
            int(context.baseline_payload["vehicle_fourier_parameters"]["peak_count"]),
        ),
    }
    configured = context.config.get("objective") or {}
    weight_total = sum(float(configured.get(name) or 0) for name in components)
    objective = sum(
        float(configured.get(name) or 0) * value for name, value in components.items()
    ) / weight_total
    attempts = result.get("parking_attempt_summary") or {}
    vehicle_count = int((result.get("payload") or {}).get("vehicle_count") or 0)
    unserved = int(attempts.get("unserved_vehicle_count") or 0)
    return {
        "valid": True,
        "objective": objective,
        "components": components,
        "rmse_flow_per_hour": metrics.get("rmse_flow_per_hour"),
        "mae_flow_per_hour": metrics.get("mae_flow_per_hour"),
        "pearson_correlation": metrics.get("pearson_correlation"),
        "real_mean_flow_per_hour": real_mean,
        "simulation_mean_flow_per_hour": sim_mean,
        "volume_error_percent": components["volume"] * 100,
        "unserved_vehicle_count": unserved,
        "unserved_vehicle_percent": unserved / vehicle_count * 100 if vehicle_count else None,
        "point_count": len(shared),
    }


def locked_payload_matches(context: CalibrationContext, payload: Mapping[str, Any]) -> bool:
    ignored = {
        "vehicle_count", "total_people", "vehicle_percentage", "vehicle_origin_allocations",
        "vehicle_fourier_parameters", "random_seed",
    }
    baseline = context.baseline_payload
    return all(
        canonical_json(payload.get(key)) == canonical_json(baseline.get(key))
        for key in set(baseline) | set(payload)
        if key not in ignored
    )


def load_historical_observations(
    context: CalibrationContext,
    references: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    configured = context.config.get("historical_results_directory")
    if not configured:
        return []
    path = Path(str(configured))
    root = path if path.is_absolute() else context.config_path.parent / path
    results_dir = root / "results" if (root / "results").is_dir() else root
    model_context_path = root / "model_context.json"
    if model_context_path.is_file():
        saved_context = load_config(model_context_path)
        if str(saved_context.get("model_id")) != str(context.study.model.get("id")):
            return []
    observations = []
    count_spec = context.config["search"]["vehicle_count"]
    peak_spec = context.config["search"]["fourier_peak_percent"]
    target_peak_mean = float(peak_spec.get("normalized_mean_percent", 100))
    for result_path in sorted(results_dir.glob("*.json")):
        try:
            result = load_config(result_path)
            payload = result.get("payload") or {}
            if not locked_payload_matches(context, payload):
                continue
            raw = parameters_from_payload(context, payload)
            if not int(count_spec["minimum"]) <= int(raw["vehicle_count"]) <= int(count_spec["maximum"]):
                continue
            allocations = payload.get("vehicle_origin_allocations") or []
            if {str(item.get("origin_id")) for item in allocations} != set(context.origin_ids):
                continue
            peaks = list(map(float, raw["peak_heights_percent"]))
            if len(peaks) != int(context.baseline_payload["vehicle_fourier_parameters"]["peak_count"]):
                continue
            # Do not relabel an old non-normalized Fourier profile as a new
            # normalized candidate. The fixed 0.05 Fourier floor makes global
            # amplitude scaling slightly observable.
            if not math.isclose(statistics.fmean(peaks), target_peak_mean, abs_tol=1e-6):
                continue
            parameters = canonical_parameters(context, raw)
            score = score_result(context, result, references)
            if not score.get("valid"):
                continue
            observations.append({
                "source": "historical",
                "result_path": str(result_path),
                "parameters": parameters,
                "score": score,
            })
        except (OSError, ValueError, KeyError, StudyError):
            continue
    return observations


def initial_state(context: CalibrationContext) -> dict[str, Any]:
    context.output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(context.output_dir / "config.snapshot.json", context.config)
    atomic_write_json(context.output_dir / "model_context.json", {
        "model_id": context.study.model.get("id"),
        "model_name": context.study.model.get("name"),
        "model_signature": context.study.model_signature,
        "classification": {
            "id": context.study.classification.get("id"),
            "name": context.study.classification.get("name"),
        },
        "vehicle_origins": [
            {"id": item, "name": context.origin_names[item]} for item in context.origin_ids
        ],
        "detector": {
            "id": context.study.detector.get("id"),
            "name": context.study.detector.get("name"),
        },
        "sensor": {
            "id": context.study.sensor.get("id"),
            "name": context.study.sensor.get("name"),
        },
    })
    phases = {
        name: {
            "name": name,
            "status": "pending",
            "base_parameters": None,
            "candidate_ids": [],
            "batches_created": 0,
        }
        for name in CALIBRATION_PHASES
    }
    phases["validation"] = {
        "name": "validation",
        "status": "pending",
        "base_parameters": None,
        "candidate_ids": [],
        "batches_created": 0,
    }
    return {
        "version": VERSION,
        "study_name": context.config["study_name"],
        "config_signature": context.config_signature,
        "model_signature": context.study.model_signature,
        "model_id": context.study.model["id"],
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "current_phase": "volume_routing",
        "phases": phases,
        "candidates": {},
    }


def load_state(context: CalibrationContext, *, required: bool) -> dict[str, Any] | None:
    if not context.state_path.is_file():
        if required:
            raise StudyError(f"No calibration checkpoint exists at {context.state_path}.")
        return None
    state = load_config(context.state_path)
    if state.get("config_signature") != context.config_signature:
        raise StudyError("The calibration config changed. Use a new output directory or restore the snapshot.")
    if state.get("model_signature") != context.study.model_signature:
        raise StudyError("The saved model changed. Start a new calibration so incompatible runs are not mixed.")
    return state


def save_state(context: CalibrationContext, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(context.state_path, state)


def phase_budget(context: CalibrationContext, phase: str) -> int:
    if phase == "validation":
        spec = context.config.get("validation") or {}
        return int(spec.get("candidate_count", 4)) * len(spec.get("seeds") or [])
    return int(context.config["search"]["phases"][phase]["runs"])


def phase_dimension(context: CalibrationContext, phase: str) -> int:
    peak_count = int(context.baseline_payload["vehicle_fourier_parameters"]["peak_count"])
    if phase == "volume_routing":
        return 1 + len(context.origin_ids)
    if phase == "shape":
        return peak_count
    if phase == "joint":
        return 1 + len(context.origin_ids) + peak_count
    return 0


def valid_candidates(state: Mapping[str, Any], phases: Iterable[str] | None = None) -> list[dict[str, Any]]:
    allowed = set(phases) if phases is not None else None
    return [
        candidate for candidate in state["candidates"].values()
        if candidate.get("status") == "valid"
        and (allowed is None or candidate.get("phase") in allowed)
    ]


def best_candidate(state: Mapping[str, Any], phases: Iterable[str] | None = None) -> dict[str, Any] | None:
    candidates = valid_candidates(state, phases)
    return min(candidates, key=lambda item: float(item["score"]["objective"])) if candidates else None


def activate_phase(context: CalibrationContext, state: dict[str, Any], phase: str) -> None:
    phase_state = state["phases"][phase]
    if phase_state["status"] != "pending":
        return
    if phase == "volume_routing":
        base = canonical_parameters(context, parameters_from_payload(context, context.baseline_payload))
    elif phase == "shape":
        selected = best_candidate(state, ["volume_routing"])
        if selected is None:
            raise StudyError("Volume/routing phase produced no valid candidate.")
        base = copy.deepcopy(selected["parameters"])
    elif phase == "joint":
        selected = best_candidate(state, ["volume_routing", "shape"])
        if selected is None:
            raise StudyError("Earlier calibration phases produced no valid candidate.")
        base = copy.deepcopy(selected["parameters"])
    else:
        base = None
    phase_state["base_parameters"] = base
    phase_state["status"] = "active"


def historical_for_phase(
    context: CalibrationContext,
    history: Sequence[dict[str, Any]],
    phase: str,
    base: Mapping[str, Any],
) -> list[dict[str, Any]]:
    baseline_peaks = canonical_parameters(
        context, parameters_from_payload(context, context.baseline_payload)
    )["peak_heights_percent"]
    selected = []
    for item in history:
        parameters = item["parameters"]
        if phase == "volume_routing" and parameters["peak_heights_percent"] != baseline_peaks:
            continue
        if phase == "shape":
            if parameters["vehicle_count"] != base["vehicle_count"]:
                continue
            if any(
                abs(parameters["origin_percentages"][index] - base["origin_percentages"][index]) > 0.1
                for index in range(len(context.origin_ids))
            ):
                continue
        selected.append(item)
    return selected


def phase_observations(
    context: CalibrationContext,
    state: Mapping[str, Any],
    history: Sequence[dict[str, Any]],
    phase: str,
    base: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observations = historical_for_phase(context, history, phase, base)
    candidate_phases = {
        "volume_routing": {"volume_routing"},
        "shape": {"shape"},
        "joint": set(CALIBRATION_PHASES),
    }[phase]
    observations.extend({
        "source": "calibration",
        "parameters": candidate["parameters"],
        "score": candidate["score"],
    } for candidate in valid_candidates(state, candidate_phases))
    deduplicated: dict[str, dict[str, Any]] = {}
    for item in observations:
        key = digest(item["parameters"])
        previous = deduplicated.get(key)
        if previous is None or float(item["score"]["objective"]) < float(previous["score"]["objective"]):
            deduplicated[key] = item
    return list(deduplicated.values())


def candidate_pool(
    context: CalibrationContext,
    state: Mapping[str, Any],
    phase: str,
    count: int,
) -> list[dict[str, Any]]:
    phase_state = state["phases"][phase]
    base = phase_state["base_parameters"]
    dimension = phase_dimension(context, phase)
    phase_offset = {"volume_routing": 1009, "shape": 100_003, "joint": 1_000_003}[phase]
    start = phase_offset + int(phase_state["batches_created"]) * count
    pool = []
    seen = {digest(candidate["parameters"]) for candidate in state["candidates"].values()}
    for index in range(start, start + count * 2):
        parameters = candidate_from_unit(context, phase, halton_point(index, dimension), base)
        key = digest(parameters)
        if key in seen:
            continue
        seen.add(key)
        pool.append(parameters)
        if len(pool) >= count:
            break
    return pool


def select_batch(
    context: CalibrationContext,
    state: Mapping[str, Any],
    history: Sequence[dict[str, Any]],
    phase: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    pool_size = int(context.config["search"].get("candidate_pool_size") or 4096)
    pool = candidate_pool(context, state, phase, pool_size)
    if len(pool) < batch_size:
        raise StudyError(f"Could not generate {batch_size} unique candidates for {phase}.")
    phase_state = state["phases"][phase]
    base = phase_state["base_parameters"]
    observations = phase_observations(context, state, history, phase, base)
    features = [feature_vector(context, item["parameters"], phase) for item in observations]
    phase_valid_count = sum(
        state["candidates"][item].get("status") == "valid"
        for item in phase_state["candidate_ids"]
    )
    initial_required = int(
        context.config["search"]["phases"][phase]["initial_design_runs"]
    )
    pool_features = [feature_vector(context, item, phase) for item in pool]
    if phase_valid_count < initial_required or len(observations) < 4:
        design_features = [
            feature_vector(context, state["candidates"][candidate_id]["parameters"], phase)
            for candidate_id in phase_state["candidate_ids"]
        ]
        spacing_features = [*features, *design_features]
        acquisition = [
            min((euclidean(feature, known) for known in spacing_features), default=1.0)
            for feature in pool_features
        ]
    else:
        objectives = [float(item["score"]["objective"]) for item in observations]
        try:
            gp = GaussianProcess(features, objectives)
            best = min(objectives)
            xi = float(context.config["search"].get("expected_improvement_xi") or 0.01)
            acquisition = [
                expected_improvement(*gp.predict(feature), best, xi)
                for feature in pool_features
            ]
        except ValueError:
            acquisition = [
                min((euclidean(feature, known) for known in features), default=1.0)
                for feature in pool_features
            ]

    selected: list[dict[str, Any]] = []
    selected_features: list[list[float]] = []
    available = set(range(len(pool)))
    while available and len(selected) < batch_size:
        def diversified(index: int) -> float:
            distance = min(
                (euclidean(pool_features[index], item) for item in selected_features),
                default=1.0,
            )
            return acquisition[index] * (0.25 + distance)

        choice = max(available, key=diversified)
        available.remove(choice)
        selected.append(pool[choice])
        selected_features.append(pool_features[choice])
    return selected


def add_candidate(
    context: CalibrationContext,
    state: dict[str, Any],
    phase: str,
    parameters: Mapping[str, Any],
    batch: int,
    *,
    parent_candidate_id: str | None = None,
) -> str:
    canonical = canonical_parameters(context, parameters)
    payload = payload_for_parameters(context, canonical)
    candidate_id = digest({
        "phase": phase,
        "parameters": canonical,
        "batch": batch,
        "ordinal": len(state["candidates"]),
    })[:20]
    state["candidates"][candidate_id] = {
        "candidate_id": candidate_id,
        "phase": phase,
        "batch": batch,
        "parent_candidate_id": parent_candidate_id,
        "parameters": canonical,
        "payload_hash": digest(payload),
        "payload": payload,
        "status": "planned",
        "run_id": None,
        "attempt": 0,
        "previous_attempts": [],
        "created_at": None,
        "started_at": None,
        "completed_at": None,
        "execution_seconds": None,
        "failure_reason": None,
        "analytics_attempts": 0,
        "analytics_error": None,
        "result_file": None,
        "score": None,
    }
    state["phases"][phase]["candidate_ids"].append(candidate_id)
    return candidate_id


def create_calibration_batch(
    context: CalibrationContext,
    state: dict[str, Any],
    history: Sequence[dict[str, Any]],
    phase: str,
) -> int:
    phase_state = state["phases"][phase]
    remaining = phase_budget(context, phase) - len(phase_state["candidate_ids"])
    if remaining <= 0:
        return 0
    batch_size = min(4, remaining)
    selected = select_batch(context, state, history, phase, batch_size)
    batch = int(phase_state["batches_created"]) + 1
    for parameters in selected:
        add_candidate(context, state, phase, parameters, batch)
    phase_state["batches_created"] = batch
    return len(selected)


def create_validation_candidates(context: CalibrationContext, state: dict[str, Any]) -> int:
    phase_state = state["phases"]["validation"]
    if phase_state["candidate_ids"]:
        return 0
    spec = context.config.get("validation") or {}
    count = int(spec.get("candidate_count", 4))
    seeds = [int(item) for item in spec.get("seeds") or []]
    ranked = sorted(
        valid_candidates(state, CALIBRATION_PHASES),
        key=lambda item: float(item["score"]["objective"]),
    )
    selected = []
    seen = set()
    for candidate in ranked:
        key = digest({
            "vehicle_count": candidate["parameters"]["vehicle_count"],
            "origin_percentages": candidate["parameters"]["origin_percentages"],
            "peak_heights_percent": candidate["parameters"]["peak_heights_percent"],
        })
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= count:
            break
    if not selected:
        raise StudyError("No valid calibration candidates are available for validation.")
    if len(selected) < count:
        raise StudyError(
            f"Validation requested {count} finalists, but only {len(selected)} unique valid "
            "configurations are available."
        )
    phase_state["status"] = "active"
    phase_state["base_parameters"] = copy.deepcopy(selected[0]["parameters"])
    batch = 0
    for candidate in selected:
        for seed in seeds:
            batch += 1
            parameters = copy.deepcopy(candidate["parameters"])
            parameters["random_seed"] = seed
            add_candidate(
                context,
                state,
                "validation",
                parameters,
                (batch - 1) // 4 + 1,
                parent_candidate_id=candidate["candidate_id"],
            )
    phase_state["batches_created"] = math.ceil(len(phase_state["candidate_ids"]) / 4)
    return len(phase_state["candidate_ids"])


def reconcile_remote(context: CalibrationContext, state: dict[str, Any]) -> None:
    remote = {
        str(item.get("id")): item
        for item in context.study.api.request(
            f"/api/models/{context.study.model['id']}/simulations"
        )
    }
    for candidate in state["candidates"].values():
        run_id = candidate.get("run_id")
        if not run_id or run_id not in remote or candidate.get("status") == "valid":
            continue
        record = remote[run_id]
        candidate["status"] = str(record.get("status") or candidate["status"])
        for key in ("created_at", "started_at", "completed_at", "failure_reason"):
            candidate[key] = record.get(key)
        candidate["execution_seconds"] = elapsed_seconds(
            record.get("started_at"), record.get("completed_at")
        )


def reset_for_retry(candidate: dict[str, Any], reason: str) -> None:
    candidate.setdefault("previous_attempts", []).append({
        "run_id": candidate.get("run_id"),
        "status": candidate.get("status"),
        "failure_reason": reason,
        "created_at": candidate.get("created_at"),
        "started_at": candidate.get("started_at"),
        "completed_at": candidate.get("completed_at"),
    })
    candidate.update({
        "status": "planned",
        "run_id": None,
        "created_at": None,
        "started_at": None,
        "completed_at": None,
        "execution_seconds": None,
        "failure_reason": None,
        "analytics_attempts": 0,
        "analytics_error": None,
        "result_file": None,
        "score": None,
    })


def collect_results(
    context: CalibrationContext,
    state: dict[str, Any],
    references: Mapping[str, Mapping[str, Any]],
) -> None:
    retry_limit = int(context.config.get("max_failed_retries") or 1)
    for candidate in state["candidates"].values():
        status = candidate.get("status")
        if status == "failed":
            if int(candidate.get("attempt") or 0) <= retry_limit:
                reset_for_retry(candidate, str(candidate.get("failure_reason") or "simulation failed"))
            continue
        if status != "completed" or candidate.get("score") is not None:
            continue
        try:
            analytics = context.study.api.request(f"/api/analytics/{candidate['run_id']}")
            result = extract_result(context.study, candidate, analytics, dict(references))
            score = score_result(context, result, references)
            result["calibration_score"] = score
            result_path = context.output_dir / "results" / f"{candidate['candidate_id']}.json"
            atomic_write_json(result_path, result)
            candidate["result_file"] = str(result_path.relative_to(context.output_dir))
            candidate["score"] = score
            candidate["analytics_error"] = None
            if score.get("valid"):
                candidate["status"] = "valid"
            elif int(candidate.get("attempt") or 0) <= retry_limit:
                reset_for_retry(candidate, str(score.get("reason") or "invalid analytics"))
            else:
                candidate["status"] = "invalid"
                candidate["failure_reason"] = str(score.get("reason") or "invalid analytics")
        except ApiError as exc:
            candidate["analytics_attempts"] = int(candidate.get("analytics_attempts") or 0) + 1
            candidate["analytics_error"] = str(exc)
            maximum_attempts = int(context.config.get("max_analytics_attempts") or 120)
            if candidate["analytics_attempts"] >= maximum_attempts:
                if int(candidate.get("attempt") or 0) <= retry_limit:
                    reset_for_retry(candidate, f"analytics unavailable: {exc}")
                else:
                    candidate["status"] = "invalid"
                    candidate["failure_reason"] = f"analytics unavailable: {exc}"


def current_batch_candidates(state: Mapping[str, Any], phase: str) -> list[dict[str, Any]]:
    phase_state = state["phases"][phase]
    candidates = [
        state["candidates"][candidate_id]
        for candidate_id in phase_state["candidate_ids"]
    ]
    unfinished_batches = sorted({
        int(candidate.get("batch") or 0)
        for candidate in candidates
        if candidate.get("status") not in TERMINAL_CANDIDATE_STATUSES
    })
    batch = (
        unfinished_batches[0]
        if unfinished_batches
        else int(phase_state.get("batches_created") or 0)
    )
    return [candidate for candidate in candidates if int(candidate.get("batch") or 0) == batch]


def submit_available(context: CalibrationContext, state: dict[str, Any], phase: str) -> None:
    phase_candidates = sorted(
        (
            state["candidates"][candidate_id]
            for candidate_id in state["phases"][phase]["candidate_ids"]
        ),
        key=lambda item: (int(item.get("batch") or 0), str(item.get("candidate_id") or "")),
    )
    active = sum(
        candidate.get("status") in ACTIVE_STATUSES
        for candidate in state["candidates"].values()
    )
    slots = max(4 - active, 0)
    for candidate in [item for item in phase_candidates if item.get("status") == "planned"][:slots]:
        created = context.study.api.request(
            f"/api/models/{context.study.model['id']}/simulations",
            method="POST",
            payload=candidate["payload"],
        )
        candidate["run_id"] = str(created["id"])
        candidate["status"] = str(created.get("status") or "queued")
        candidate["attempt"] = int(candidate.get("attempt") or 0) + 1
        candidate["created_at"] = created.get("created_at") or utc_now()
        candidate["started_at"] = created.get("started_at")
        candidate["completed_at"] = created.get("completed_at")
        save_state(context, state)


def phase_candidates_finished(state: Mapping[str, Any], phase: str) -> bool:
    candidate_ids = state["phases"][phase]["candidate_ids"]
    return bool(candidate_ids) and all(
        state["candidates"][candidate_id].get("status") in TERMINAL_CANDIDATE_STATUSES
        for candidate_id in candidate_ids
    )


def advance_if_ready(context: CalibrationContext, state: dict[str, Any]) -> bool:
    phase = str(state["current_phase"])
    phase_state = state["phases"][phase]
    budget = phase_budget(context, phase)
    if len(phase_state["candidate_ids"]) < budget or not phase_candidates_finished(state, phase):
        return False
    phase_state["status"] = "completed"
    if phase == "volume_routing":
        state["current_phase"] = "shape"
    elif phase == "shape":
        state["current_phase"] = "joint"
    elif phase == "joint":
        state["current_phase"] = "validation"
    else:
        state["current_phase"] = "completed"
    return True


def candidate_counts(state: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in state["candidates"].values():
        status = str(candidate.get("status") or "planned")
        counts[status] = counts.get(status, 0) + 1
    return counts


def total_budget(context: CalibrationContext) -> int:
    return sum(phase_budget(context, phase) for phase in (*CALIBRATION_PHASES, "validation"))


def progress_line(context: CalibrationContext, state: Mapping[str, Any]) -> str:
    counts = candidate_counts(state)
    terminal = sum(counts.get(name, 0) for name in TERMINAL_CANDIDATE_STATUSES)
    total = total_budget(context)
    durations = [
        float(candidate["execution_seconds"])
        for candidate in state["candidates"].values()
        if candidate.get("execution_seconds") is not None and candidate.get("status") == "valid"
    ]
    remaining = max(total - terminal, 0)
    eta = statistics.fmean(durations) * remaining / 4 if durations else None
    created = parse_time(state.get("created_at"))
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    elapsed = (
        max((datetime.now(timezone.utc) - created).total_seconds(), 0.0)
        if created is not None else None
    )
    local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return (
        f"[{local} | elapsed {format_duration(elapsed)}] phase {state['current_phase']} | "
        f"{terminal}/{total} terminal | running {counts.get('running', 0)} | "
        f"queued {counts.get('queued', 0)} | planned {counts.get('planned', 0)} | "
        f"invalid {counts.get('invalid', 0)} | failed {counts.get('failed', 0)} | "
        f"ETA {format_duration(eta)}"
    )


def progress_signature(state: Mapping[str, Any]) -> tuple[Any, ...]:
    counts = candidate_counts(state)
    return (
        state.get("current_phase"),
        *(counts.get(name, 0) for name in ("valid", "invalid", "failed", "running", "queued", "planned")),
    )


def validation_rankings(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    parents = {
        candidate["candidate_id"]: candidate
        for candidate in valid_candidates(state, CALIBRATION_PHASES)
    }
    scores: dict[str, list[float]] = {
        candidate_id: [float(candidate["score"]["objective"])]
        for candidate_id, candidate in parents.items()
    }
    for candidate in valid_candidates(state, ["validation"]):
        parent = candidate.get("parent_candidate_id")
        if parent in scores:
            scores[parent].append(float(candidate["score"]["objective"]))
    rows = []
    for candidate_id, values in scores.items():
        if len(values) <= 1:
            continue
        rows.append({
            "parent_candidate_id": candidate_id,
            "mean_objective": statistics.fmean(values),
            "standard_deviation": statistics.pstdev(values),
            "sample_count": len(values),
            "candidate": parents[candidate_id],
        })
    return sorted(rows, key=lambda item: item["mean_objective"])


def write_outputs(context: CalibrationContext, state: Mapping[str, Any]) -> None:
    rows = []
    timeseries = []
    for candidate in state["candidates"].values():
        score = candidate.get("score") or {}
        components = score.get("components") or {}
        row = {
            "candidate_id": candidate["candidate_id"],
            "phase": candidate["phase"],
            "batch": candidate["batch"],
            "parent_candidate_id": candidate.get("parent_candidate_id"),
            "status": candidate.get("status"),
            "run_id": candidate.get("run_id"),
            "attempt": candidate.get("attempt"),
            "vehicle_count": candidate["parameters"]["vehicle_count"],
            "random_seed": candidate["parameters"]["random_seed"],
            "objective": score.get("objective"),
            "shape_error": components.get("shape"),
            "point_nrmse": components.get("point_rmse"),
            "volume_error": components.get("volume"),
            "peak_timing_error": components.get("peak_timing"),
            "rmse_flow_per_hour": score.get("rmse_flow_per_hour"),
            "pearson_correlation": score.get("pearson_correlation"),
            "simulation_mean_flow_per_hour": score.get("simulation_mean_flow_per_hour"),
            "real_mean_flow_per_hour": score.get("real_mean_flow_per_hour"),
            "unserved_vehicle_percent": score.get("unserved_vehicle_percent"),
            "execution_seconds": candidate.get("execution_seconds"),
            "failure_reason": candidate.get("failure_reason") or score.get("reason"),
        }
        for index, origin_id in enumerate(context.origin_ids):
            row[f"origin_{index + 1}_name"] = context.origin_names[origin_id]
            row[f"origin_{index + 1}_percent"] = candidate["parameters"]["origin_percentages"][index]
        for index, value in enumerate(candidate["parameters"]["peak_heights_percent"]):
            row[f"peak_{index + 1}_percent"] = value
        rows.append(row)
        relative = candidate.get("result_file")
        if relative and (context.output_dir / relative).is_file():
            result = load_config(context.output_dir / relative)
            for point in result.get("detector_timeseries") or []:
                if (
                    str(point.get("logical_id")) == str(context.study.detector.get("id"))
                    and point.get("subject") == "vehicles"
                ):
                    timeseries.append({
                        "candidate_id": candidate["candidate_id"],
                        "phase": candidate["phase"],
                        "run_id": candidate.get("run_id"),
                        **point,
                    })
    fields = list(rows[0]) if rows else ["candidate_id"]
    write_csv(context.output_dir / "candidates.csv", rows, fields)
    write_csv(
        context.output_dir / "vehicle_timeseries.csv",
        timeseries,
        [
            "candidate_id", "phase", "run_id", "detector_id", "logical_id", "logical_name",
            "subject", "begin_seconds", "end_seconds", "interval_count", "flow_per_hour",
        ],
    )
    rankings = validation_rankings(state)
    selected = rankings[0]["candidate"] if rankings else best_candidate(state, CALIBRATION_PHASES)
    if selected is not None:
        atomic_write_json(context.output_dir / "best_parameters.json", selected["parameters"])
        atomic_write_json(
            context.output_dir / "best_payload.json",
            payload_for_parameters(context, selected["parameters"]),
        )
    report_lines = [
        f"# Vehicle calibration: {context.config['study_name']}",
        "",
        f"- Model: {context.study.model.get('name')}",
        f"- Detector: {context.study.detector.get('name')}",
        f"- Sensor: {context.study.sensor.get('name')}",
        f"- Updated: {utc_now()}",
        f"- Candidates created: {len(state['candidates'])} / {total_budget(context)}",
        "",
        "## Best configurations",
        "",
        "| Rank | Candidate | Phase | Objective | RMSE /h | Correlation | Mean flow /h | Vehicles |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(
        valid_candidates(state, CALIBRATION_PHASES),
        key=lambda item: float(item["score"]["objective"]),
    )[:10]
    for index, candidate in enumerate(ranked, 1):
        score = candidate["score"]
        correlation = score.get("pearson_correlation")
        report_lines.append(
            f"| {index} | `{candidate['candidate_id']}` | {candidate['phase']} | "
            f"{float(score['objective']):.5f} | {float(score['rmse_flow_per_hour']):.3f} | "
            f"{float(correlation):.3f} | {float(score['simulation_mean_flow_per_hour']):.3f} | "
            f"{candidate['parameters']['vehicle_count']} |"
            if correlation is not None else
            f"| {index} | `{candidate['candidate_id']}` | {candidate['phase']} | "
            f"{float(score['objective']):.5f} | {float(score['rmse_flow_per_hour']):.3f} | n/a | "
            f"{float(score['simulation_mean_flow_per_hour']):.3f} | "
            f"{candidate['parameters']['vehicle_count']} |"
        )
    report_lines += ["", "## Validation across seeds", ""]
    if rankings:
        report_lines += [
            "| Rank | Parent candidate | Mean objective | Standard deviation | Samples |",
            "|---:|---|---:|---:|---:|",
        ]
        for index, item in enumerate(rankings, 1):
            report_lines.append(
                f"| {index} | `{item['parent_candidate_id']}` | {item['mean_objective']:.5f} | "
                f"{item['standard_deviation']:.5f} | {item['sample_count']} |"
            )
    else:
        report_lines.append("Validation has not completed yet.")
    report_lines += [
        "",
        "`best_parameters.json` contains the selected inputs. `best_payload.json` contains the complete API payload.",
        "Incomplete detector outputs are excluded rather than interpreted as zero traffic.",
        "",
    ]
    atomic_write_text(context.output_dir / "report.md", "\n".join(report_lines))


def execute(
    context: CalibrationContext,
    *,
    resume: bool,
    retry_failed: bool,
) -> None:
    state = load_state(context, required=resume)
    if state is None:
        state = initial_state(context)
        save_state(context, state)
    elif not resume:
        raise StudyError(f"A checkpoint already exists. Resume it: {context.state_path}")
    if retry_failed:
        for candidate in state["candidates"].values():
            if candidate.get("status") in {"failed", "invalid"}:
                reset_for_retry(candidate, "manual retry")
    references = reference_series(context.study)
    history = load_historical_observations(context, references)
    print(
        f"Loaded {len(history)} valid historical vehicle observations. "
        "Ctrl+C is safe; submitted server runs continue.",
        flush=True,
    )
    poll_seconds = max(float(context.config.get("poll_seconds") or 10), 1.0)
    last_signature: tuple[Any, ...] | None = None
    last_printed = 0.0
    try:
        while state["current_phase"] != "completed":
            phase = str(state["current_phase"])
            reconcile_remote(context, state)
            collect_results(context, state, references)
            if phase == "validation":
                create_validation_candidates(context, state)
            else:
                activate_phase(context, state, phase)
                phase_state = state["phases"][phase]
                initial_design = int(
                    context.config["search"]["phases"][phase]["initial_design_runs"]
                )
                while len(phase_state["candidate_ids"]) < initial_design:
                    create_calibration_batch(context, state, history, phase)
                if (
                    len(phase_state["candidate_ids"]) >= initial_design
                    and len(phase_state["candidate_ids"]) < phase_budget(context, phase)
                    and phase_candidates_finished(state, phase)
                ):
                    create_calibration_batch(context, state, history, phase)
            submit_available(context, state, phase)
            advance_if_ready(context, state)
            save_state(context, state)
            write_outputs(context, state)
            now = time.monotonic()
            signature = progress_signature(state)
            if signature != last_signature or now - last_printed >= 300:
                print(progress_line(context, state), flush=True)
                last_signature = signature
                last_printed = now
            if state["current_phase"] != "completed":
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        save_state(context, state)
        write_outputs(context, state)
        print(
            f"\nInterrupted safely. Resume with:\n  python3 {Path(__file__)} resume "
            f"--config {context.config_path}",
            flush=True,
        )
        return
    write_outputs(context, state)
    print(f"Calibration completed. Report: {context.output_dir / 'report.md'}")
    print(f"Best payload: {context.output_dir / 'best_payload.json'}")


def print_plan(context: CalibrationContext) -> None:
    references = reference_series(context.study)
    history = load_historical_observations(context, references)
    phases = context.config["search"]["phases"]
    validation = context.config.get("validation") or {}
    print(f"\nVehicle calibration: {context.config['study_name']}")
    print(f"Model: {context.study.model.get('name')} ({context.study.model.get('id')})")
    print(f"Detector → sensor: {context.study.detector.get('name')} → {context.study.sensor.get('name')}")
    print(f"Vehicle origins discovered dynamically: {len(context.origin_ids)}")
    for origin_id in context.origin_ids:
        print(f"  - {context.origin_names[origin_id]} [{origin_id}]")
    count = context.config["search"]["vehicle_count"]
    peaks = context.config["search"]["fourier_peak_percent"]
    print("\nSearch bounds:")
    print(
        f"  Vehicle count: {int(count['minimum'])}–{int(count['maximum'])}, "
        f"step {int(count.get('step', 100))}"
    )
    print(
        f"  Fourier peaks: {float(peaks.get('minimum', 0)):g}–"
        f"{float(peaks.get('maximum', 300)):g}%, step {float(peaks.get('step', 5)):g}%, "
        f"normalized mean {float(peaks.get('normalized_mean_percent', 100)):g}%"
    )
    print("  Origin allocations: dynamic simplex; shares always total 100%")
    print("\nPhases:")
    for phase in CALIBRATION_PHASES:
        print(
            f"  {phase:16} {int(phases[phase]['runs']):3d} simulations "
            f"({int(phases[phase]['initial_design_runs'])} initial-design runs)"
        )
    validation_runs = int(validation.get("candidate_count", 4)) * len(validation.get("seeds") or [])
    print(f"  {'validation':16} {validation_runs:3d} simulations")
    print(f"\nTotal planned new simulations: {total_budget(context)}")
    print("Maximum concurrent submissions: 4")
    print("Scheduling: independent work refills free slots; adaptive batches wait for analytics")
    print(f"Valid imported historical observations: {len(history)}")
    print(f"Checkpoint: {context.state_path}")
    print(f"Output directory: {context.output_dir}\n")


def confirmation(assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input("Type RUN to start/resume vehicle calibration, or press Enter to cancel: ").strip() == "RUN"
    except EOFError:
        return False


def analyze(context: CalibrationContext) -> None:
    state = load_state(context, required=True)
    assert state is not None
    references = reference_series(context.study)
    reconcile_remote(context, state)
    collect_results(context, state, references)
    save_state(context, state)
    write_outputs(context, state)
    print(f"Calibration outputs rebuilt in {context.output_dir}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "resume", "analyze"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        if name in {"run", "resume"}:
            command.add_argument("--yes", action="store_true")
        if name == "resume":
            command.add_argument("--retry-failed", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        context = prepare_context(arguments.config)
        if arguments.command == "plan":
            print_plan(context)
            return 0
        if arguments.command == "analyze":
            analyze(context)
            return 0
        print_plan(context)
        if not confirmation(arguments.yes):
            print("Cancelled; no simulations were submitted.")
            return 0
        execute(
            context,
            resume=arguments.command == "resume",
            retry_failed=bool(getattr(arguments, "retry_failed", False)),
        )
        return 0
    except StudyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
