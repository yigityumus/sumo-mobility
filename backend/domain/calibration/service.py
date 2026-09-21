"""Sequential, locked-configuration Fourier peak calibration."""

from __future__ import annotations

import json
import math
import secrets
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.reference_data.series import RealWorldDataError, get_real_world_series
from domain.simulations.service import (
    create_simulation_run,
    mark_simulation_queue_failure,
    update_simulation_calibration,
)
from shared.database import (
    persist_flow_calibration,
    read_flow_calibration,
    read_flow_calibrations,
)
from shared.message_broker import MessageBrokerError, publish_message


MIN_HEIGHT = 0.0
MAX_HEIGHT = 3.0


class FlowCalibrationError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe_request(request: dict[str, Any]) -> dict[str, Any]:
    result = dict(request)
    start_at = result.get("simulation_start_at")
    if isinstance(start_at, datetime):
        result["simulation_start_at"] = start_at.isoformat()
    if result.get("random_seed") is None:
        result["random_seed"] = secrets.randbelow(2_147_483_646) + 1
    return json.loads(json.dumps(result))


def _run_calibration_metadata(
    session: dict[str, Any], iteration: int, profiles: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": session["id"],
        "name": session["name"],
        "iteration": iteration,
        "total_iterations": session["total_iterations"],
        "source_id": session["source_id"],
        "detector_logical_id": session["detector_logical_id"],
        "subjects": session["subjects"],
        "step_percentage": session.get("step_percentage", 1.0),
        "update_strategy": "adaptive_hill",
        "profiles": profiles,
        "result": None,
    }


def _fail_session(session: dict[str, Any], reason: str) -> dict[str, Any]:
    session.update({
        "status": "failed",
        "failure_reason": reason,
        "updated_at": _now_iso(),
    })
    persist_flow_calibration(session)
    return session


def _create_iteration_run(
    model_storage_dir: Path,
    model: dict[str, Any],
    session: dict[str, Any],
    iteration: int,
    profiles: dict[str, Any],
    source_osm_path: Path | None = None,
) -> dict[str, Any]:
    request = dict(session["simulation_request"])
    request["vehicle_fourier_parameters"] = profiles["vehicles"]
    request["pedestrian_fourier_parameters"] = profiles["pedestrians"]
    start_at = request.get("simulation_start_at")
    if isinstance(start_at, str):
        request["simulation_start_at"] = datetime.fromisoformat(start_at)
    return create_simulation_run(
        model_storage_dir,
        model,
        vehicle_count=int(request["vehicle_count"]),
        pedestrian_count=int(request["pedestrian_count"]),
        duration_hours=int(request["duration_hours"]),
        mode=str(request["mode"]),
        vehicle_traffic_model="fourier",
        pedestrian_traffic_model="fourier",
        vehicle_fourier_parameters=profiles["vehicles"],
        pedestrian_fourier_parameters=profiles["pedestrians"],
        parking_choice=request["parking_choice"],
        total_people=int(request["total_people"]),
        vehicle_percentage=int(request["vehicle_percentage"]),
        building_classification_id=request.get("building_classification_id"),
        residential_pedestrian_count=int(request["residential_pedestrian_count"]),
        public_transport_pedestrian_count=int(request["public_transport_pedestrian_count"]),
        simulation_start_at=request["simulation_start_at"],
        simulation_timezone=str(request["simulation_timezone"]),
        pedestrian_model=str(request["pedestrian_model"]),
        diagnostic_tracing=bool(request["diagnostic_tracing"]),
        random_seed=int(request["random_seed"]),
        vehicle_origin_allocations=request.get("vehicle_origin_allocations"),
        calibration=_run_calibration_metadata(session, iteration, profiles),
        source_osm_path=source_osm_path,
    )


def _publish_run(
    session: dict[str, Any],
    run: dict[str, Any],
    *,
    model_storage_dir: Path,
    rabbitmq_url: str,
    simulation_queue_name: str,
) -> None:
    try:
        publish_message(
            rabbitmq_url,
            simulation_queue_name,
            {
                "type": "simulation.run.requested",
                "model_id": run["model_id"],
                "run_id": run["id"],
            },
        )
    except MessageBrokerError as exc:
        reason = "The calibration iteration could not be queued because RabbitMQ is unavailable."
        mark_simulation_queue_failure(
            model_storage_dir, str(run["model_id"]), str(run["id"]), reason
        )
        session.update({"status": "failed", "failure_reason": reason, "updated_at": _now_iso()})
        persist_flow_calibration(session)
        raise FlowCalibrationError(reason) from exc


def create_flow_calibration(
    model_storage_dir: Path,
    model: dict[str, Any],
    *,
    name: str,
    source_id: str,
    detector_logical_id: str,
    subjects: list[str],
    total_iterations: int,
    step_percentage: float,
    simulation_request: dict[str, Any],
    rabbitmq_url: str,
    simulation_queue_name: str,
) -> dict[str, Any]:
    if not rabbitmq_url:
        raise FlowCalibrationError("Flow calibration requires queued worker mode.")
    request = _json_safe_request(simulation_request)
    profiles = {
        "vehicles": request["vehicle_fourier_parameters"],
        "pedestrians": request["pedestrian_fourier_parameters"],
    }
    calibration_id = str(uuid.uuid4())
    now = _now_iso()
    session = {
        "id": calibration_id,
        "name": name.strip() or f"Flow calibration {now[:16]}",
        "model_id": str(model["id"]),
        "model_name": str(model.get("name") or "Unnamed model"),
        "status": "running",
        "source_id": source_id,
        "detector_logical_id": detector_logical_id,
        "subjects": subjects,
        "total_iterations": total_iterations,
        "step_percentage": float(step_percentage),
        "update_strategy": "adaptive_hill",
        "completed_iterations": 0,
        "simulation_request": request,
        "current_profiles": profiles,
        "run_ids": [],
        "iteration_results": [],
        "failure_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    if not persist_flow_calibration(session):
        raise FlowCalibrationError("Could not persist the calibration session.")
    try:
        run = _create_iteration_run(model_storage_dir, model, session, 1, profiles)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        _fail_session(session, str(exc))
        raise FlowCalibrationError(str(exc)) from exc
    session["run_ids"] = [run["id"]]
    session["updated_at"] = _now_iso()
    persist_flow_calibration(session)
    _publish_run(
        session,
        run,
        model_storage_dir=model_storage_dir,
        rabbitmq_url=rabbitmq_url,
        simulation_queue_name=simulation_queue_name,
    )
    return session


def list_flow_calibration_sessions(model_id: str) -> list[dict[str, Any]]:
    return read_flow_calibrations(model_id) or []


def _mean_in_window(
    points: list[dict[str, Any]],
    start: float,
    end: float,
    time_key: str,
) -> float:
    values = [
        float(point.get("flow_per_hour") or 0.0)
        for point in points
        if start <= float(point.get(time_key) or 0.0) < end
    ]
    return statistics.fmean(values) if values else 0.0


def _correlation(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or statistics.pstdev(left) == 0 or statistics.pstdev(right) == 0:
        return 1.0 if left == right else 0.0
    return min(max(statistics.correlation(left, right), -1.0), 1.0)


def _fit_hill_response(
    samples: list[tuple[float, float]],
) -> dict[str, float] | None:
    """Fit y = baseline + maximum*x^n/(K^n+x^n) by a small grid search."""
    distinct = sorted({(round(float(x), 8), float(y)) for x, y in samples if x > 0 and y >= 0})
    if len({item[0] for item in distinct}) < 3:
        return None
    xs = [item[0] for item in distinct]
    ys = [item[1] for item in distinct]
    mean_y = statistics.fmean(ys)
    total_variation = sum((value - mean_y) ** 2 for value in ys)
    if total_variation <= 1e-9:
        return None
    minimum_x = max(min(xs), 0.1)
    maximum_x = max(xs)
    k_min = max(minimum_x / 4.0, 0.1)
    k_max = max(maximum_x * 4.0, k_min * 1.01)
    candidates: list[dict[str, float]] = []
    for baseline_fraction in (0.0, 0.25, 0.5, 0.75):
        baseline = min(ys) * baseline_fraction
        for hill_coefficient in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0):
            for index in range(25):
                fraction = index / 24
                half_saturation = k_min * (k_max / k_min) ** fraction
                basis = [
                    x ** hill_coefficient
                    / (half_saturation ** hill_coefficient + x ** hill_coefficient)
                    for x in xs
                ]
                denominator = sum(value * value for value in basis)
                if denominator <= 1e-12:
                    continue
                maximum = max(
                    sum(value * (observed - baseline) for value, observed in zip(basis, ys))
                    / denominator,
                    0.0,
                )
                predicted = [baseline + maximum * value for value in basis]
                squared_error = sum(
                    (observed - estimate) ** 2
                    for observed, estimate in zip(ys, predicted)
                )
                candidates.append({
                    "baseline": baseline,
                    "maximum": maximum,
                    "half_saturation_percentage": half_saturation,
                    "hill_coefficient": hill_coefficient,
                    "r_squared": 1.0 - squared_error / total_variation,
                    "squared_error": squared_error,
                })
    if not candidates:
        return None
    best = min(candidates, key=lambda item: item["squared_error"])
    if best["r_squared"] < 0.5 or best["maximum"] <= 0:
        return None
    return best


def _hill_input_for_target(model: dict[str, float], target: float) -> float:
    available = target - model["baseline"]
    if available <= 0:
        return 0.0
    fraction = available / model["maximum"]
    if fraction >= 0.995:
        return MAX_HEIGHT * 100
    fraction = min(max(fraction, 1e-9), 0.995)
    return model["half_saturation_percentage"] * (
        fraction / (1.0 - fraction)
    ) ** (1.0 / model["hill_coefficient"])


def _local_elasticity(samples: list[tuple[float, float]]) -> float | None:
    ordered = sorted({(round(float(x), 8), float(y)) for x, y in samples if x > 0 and y > 0})
    elasticities = []
    for (first_x, first_y), (second_x, second_y) in zip(ordered, ordered[1:]):
        denominator = math.log(second_x / first_x)
        if abs(denominator) <= 1e-9:
            continue
        value = math.log(second_y / first_y) / denominator
        if 0.05 <= value <= 3.0:
            elasticities.append(value)
    if not elasticities:
        return None
    return min(max(statistics.median(elasticities), 0.15), 1.5)


def _quantize_percentage(old: float, proposed: float, step: float) -> float:
    old = min(max(old, MIN_HEIGHT * 100), MAX_HEIGHT * 100)
    proposed = min(max(proposed, MIN_HEIGHT * 100), MAX_HEIGHT * 100)
    difference = proposed - old
    if math.isclose(difference, 0.0, abs_tol=1e-9):
        return old
    units = max(1, round(abs(difference) / step))
    candidate = old + math.copysign(units * step, difference)
    candidate = min(max(candidate, MIN_HEIGHT * 100), MAX_HEIGHT * 100)
    if 0 < abs(candidate - old) < step - 1e-9:
        return old
    return round(candidate, 8)


def _propose_peak_percentage(
    *,
    old_percentage: float,
    real_flow: float,
    simulated_flow: float,
    samples: list[tuple[float, float]],
) -> tuple[float, str, dict[str, float] | None, float | None]:
    if simulated_flow <= 0:
        return old_percentage, "undefined_zero_flow", None, None
    ratio = max(real_flow / simulated_flow, 0.0)
    hill = _fit_hill_response(samples)
    if hill is not None:
        return _hill_input_for_target(hill, real_flow), "hill", hill, None
    elasticity = _local_elasticity(samples)
    if elasticity is not None:
        return (
            old_percentage * ratio ** (1.0 / elasticity),
            "local_elasticity",
            None,
            elasticity,
        )
    if old_percentage <= 0 and real_flow > simulated_flow:
        return 1.0, "proportional", None, None
    return old_percentage * ratio, "proportional", None, None


def compare_and_update_profile(
    profile: dict[str, Any],
    real_points: list[dict[str, Any]],
    simulation_points: list[dict[str, Any]],
    duration_seconds: int,
    *,
    step_percentage: float = 1.0,
    history: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Update peak percentages using an adaptive saturation response model."""
    peak_count = int(profile["peak_count"])
    spacing = duration_seconds / peak_count
    heights = [float(value) for value in profile["peak_heights"]]
    if len(heights) != peak_count:
        raise FlowCalibrationError("A Fourier profile must contain one percentage per peak.")
    peaks = []
    next_heights = []
    real_values = []
    simulated_values = []
    for index, old_height in enumerate(heights):
        start = index * spacing
        end = (index + 1) * spacing
        real_flow = _mean_in_window(real_points, start, end, "time_seconds")
        simulated_flow = _mean_in_window(
            simulation_points, start, end, "begin_seconds"
        )
        old_percentage = old_height * 100
        response_samples = [
            (
                float(item["peaks"][index]["old_percentage"]),
                float(item["peaks"][index]["simulation_flow_per_hour"]),
            )
            for item in (history or [])
            if len(item.get("peaks") or []) > index
        ]
        response_samples.append((old_percentage, simulated_flow))
        proposed_percentage, update_method, hill_model, elasticity = _propose_peak_percentage(
            old_percentage=old_percentage,
            real_flow=real_flow,
            simulated_flow=simulated_flow,
            samples=response_samples,
        )
        new_percentage = _quantize_percentage(
            old_percentage, proposed_percentage, max(float(step_percentage), 0.1)
        )
        new_height = new_percentage / 100
        raw_ratio = real_flow / simulated_flow if simulated_flow > 0 else None
        applied_ratio = (
            new_percentage / old_percentage
            if old_percentage > 0 and simulated_flow > 0
            else None
        )
        if update_method == "hill" and hill_model is not None:
            power = new_percentage ** hill_model["hill_coefficient"]
            half_power = (
                hill_model["half_saturation_percentage"]
                ** hill_model["hill_coefficient"]
            )
            predicted_next_flow = (
                hill_model["baseline"]
                + hill_model["maximum"] * power / (half_power + power)
                if half_power + power > 0
                else hill_model["baseline"]
            )
        elif old_percentage > 0 and simulated_flow > 0:
            exponent = elasticity if elasticity is not None else 1.0
            predicted_next_flow = simulated_flow * (
                new_percentage / old_percentage
            ) ** exponent
        else:
            predicted_next_flow = None
        real_values.append(real_flow)
        simulated_values.append(simulated_flow)
        next_heights.append(new_height)
        peaks.append({
            "peak_index": index + 1,
            "window_start_seconds": start,
            "window_end_seconds": end,
            "center_seconds": start + spacing / 2,
            "real_flow_per_hour": real_flow,
            "simulation_flow_per_hour": simulated_flow,
            "raw_ratio": raw_ratio,
            "applied_ratio": applied_ratio,
            "ratio_capped": not math.isclose(new_percentage, proposed_percentage),
            "adjustment_quantized": not math.isclose(
                new_percentage, proposed_percentage
            ),
            "old_percentage": old_percentage,
            "proposed_percentage": proposed_percentage,
            "new_percentage": new_percentage,
            "step_percentage": step_percentage,
            "update_method": update_method,
            "estimated_elasticity": elasticity,
            "hill_model": hill_model,
            "predicted_next_flow_per_hour": predicted_next_flow,
            "residual_flow_per_hour": simulated_flow - real_flow,
            "absolute_error_flow_per_hour": abs(simulated_flow - real_flow),
            "percentage_error": (
                (simulated_flow - real_flow) / real_flow if real_flow > 0 else None
            ),
        })
    errors = [simulated - real for real, simulated in zip(real_values, simulated_values)]
    mean_real = max(statistics.fmean(real_values), 1.0)
    mae = statistics.fmean(abs(value) for value in errors)
    rmse = math.sqrt(statistics.fmean(value * value for value in errors))
    volume_error = abs(sum(simulated_values) - sum(real_values)) / max(sum(real_values), 1.0)
    correlation = _correlation(real_values, simulated_values)
    squared_error = sum(value * value for value in errors)
    total_variation = sum(
        (value - statistics.fmean(real_values)) ** 2 for value in real_values
    )
    percentage_errors = [
        abs(simulated - real) / real
        for real, simulated in zip(real_values, simulated_values)
        if real > 0
    ]
    smape_terms = [
        2 * abs(simulated - real) / (abs(real) + abs(simulated))
        for real, simulated in zip(real_values, simulated_values)
        if abs(real) + abs(simulated) > 0
    ]
    metrics = {
        "mae_flow_per_hour": mae,
        "rmse_flow_per_hour": rmse,
        "normalized_mae": mae / mean_real,
        "normalized_rmse": rmse / mean_real,
        "volume_error": volume_error,
        "correlation": correlation,
        "shape_error": (1.0 - correlation) / 2.0,
        "mean_bias_flow_per_hour": statistics.fmean(errors),
        "normalized_bias": statistics.fmean(errors) / mean_real,
        "mean_absolute_percentage_error": (
            statistics.fmean(percentage_errors) if percentage_errors else 0.0
        ),
        "symmetric_mean_absolute_percentage_error": (
            statistics.fmean(smape_terms) if smape_terms else 0.0
        ),
        "nash_sutcliffe_efficiency": (
            1.0 - squared_error / total_variation if total_variation > 0 else 0.0
        ),
        "real_mean_flow_per_hour": statistics.fmean(real_values),
        "simulation_mean_flow_per_hour": statistics.fmean(simulated_values),
        "peak_count": peak_count,
        "peak_spacing_seconds": spacing,
    }
    updated = {
        **profile,
        # Count, width, harmonics, totals, seed, and every other setting stay locked.
        "peak_heights": next_heights,
    }
    return updated, {"metrics": metrics, "peaks": peaks}


def advance_flow_calibration(
    model_storage_dir: Path,
    record: dict[str, Any],
    analytics: dict[str, Any] | None,
    *,
    rabbitmq_url: str,
    simulation_queue_name: str,
) -> dict[str, Any] | None:
    calibration = record.get("calibration") or {}
    calibration_id = str(calibration.get("id") or "")
    if not calibration_id:
        return None
    session = read_flow_calibration(calibration_id)
    if session is None or session.get("status") != "running":
        return session
    iteration = int(calibration["iteration"])
    if int(session.get("completed_iterations") or 0) >= iteration:
        return session
    if record.get("status") != "completed" or analytics is None:
        session.update({
            "status": "failed",
            "failure_reason": record.get("failure_reason") or "A calibration simulation failed.",
            "updated_at": _now_iso(),
        })
        persist_flow_calibration(session)
        return session

    request = session["simulation_request"]
    start_at = datetime.fromisoformat(str(request["simulation_start_at"]))
    weekday = start_at.weekday()
    start_time_seconds = start_at.hour * 3600 + start_at.minute * 60 + start_at.second
    duration_seconds = int(request["duration_hours"]) * 3600
    current_profiles = calibration["profiles"]
    next_profiles = json.loads(json.dumps(current_profiles))
    subject_results: dict[str, Any] = {}
    zero_subjects = []
    definitions = analytics.get("detectors", {}).get("definitions", [])
    comparison_series = analytics.get("detectors", {}).get("comparison_series", {})
    try:
        for subject in session["subjects"]:
            definition = next((
                item for item in definitions
                if str(item.get("logical_id")) == str(session["detector_logical_id"])
                and item.get("subject") == subject
            ), None)
            if definition is None:
                raise FlowCalibrationError(
                    f"Detector {session['detector_logical_id']} does not measure {subject}."
                )
            real = get_real_world_series(
                source_id=str(session["source_id"]),
                mode="weekly_average",
                subject=subject,
                duration_seconds=duration_seconds,
                start_weekday=weekday,
                start_time_seconds=start_time_seconds,
            )
            simulated = comparison_series.get(str(definition["id"]), [])
            next_profile, result = compare_and_update_profile(
                current_profiles[subject],
                real["points"],
                simulated,
                duration_seconds,
                step_percentage=float(session.get("step_percentage") or 1.0),
                history=[
                    item["subjects"][subject]
                    for item in session.get("iteration_results") or []
                    if subject in (item.get("subjects") or {})
                ],
            )
            next_profiles[subject] = next_profile
            subject_results[subject] = result
            if (
                sum(float(point.get("flow_per_hour") or 0) for point in simulated) == 0
                and sum(float(point.get("flow_per_hour") or 0) for point in real["points"]) > 0
            ):
                zero_subjects.append(subject)
    except (FlowCalibrationError, RealWorldDataError, KeyError, TypeError, ValueError) as exc:
        return _fail_session(session, str(exc))

    run_calibration = {**calibration, "result": {"subjects": subject_results}}
    update_simulation_calibration(
        model_storage_dir, str(record["model_id"]), str(record["id"]), run_calibration
    )
    analytics["run"]["calibration"] = run_calibration
    session["completed_iterations"] = iteration
    session["current_profiles"] = next_profiles
    session["iteration_results"].append({
        "iteration": iteration,
        "run_id": record["id"],
        "subjects": subject_results,
    })
    session["updated_at"] = _now_iso()
    if zero_subjects:
        names = ", ".join(zero_subjects)
        return _fail_session(session, (
            f"Cannot compute a finite peak ratio: simulated {names} detector flow is zero "
            "while the physical sensor flow is positive. Move or widen the detector coverage "
            "or calibrate that subject separately after routes cross the detector."
        ))
    if iteration >= int(session["total_iterations"]):
        session["status"] = "completed"
        persist_flow_calibration(session)
        return session

    run_dir = model_storage_dir / str(record["model_id"]) / "simulations" / str(record["id"])
    model_snapshot = run_dir / "model.snapshot.json"
    source_snapshot = run_dir / "inputs" / "source.osm.xml"
    if not model_snapshot.is_file() or not source_snapshot.is_file():
        return _fail_session(
            session, "The locked model snapshot is unavailable for the next iteration."
        )
    model = json.loads(model_snapshot.read_text(encoding="utf-8"))
    try:
        next_run = _create_iteration_run(
            model_storage_dir,
            model,
            session,
            iteration + 1,
            next_profiles,
            source_osm_path=source_snapshot,
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return _fail_session(session, str(exc))
    session["run_ids"].append(next_run["id"])
    persist_flow_calibration(session)
    _publish_run(
        session,
        next_run,
        model_storage_dir=model_storage_dir,
        rabbitmq_url=rabbitmq_url,
        simulation_queue_name=simulation_queue_name,
    )
    return session
