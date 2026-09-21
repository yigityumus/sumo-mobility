#!/usr/bin/env python3
"""Run one model-scoped SUMO simulation with TraCI parking control."""
from __future__ import annotations

import argparse
import copy
import json
import random
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    import traci
    import traci.constants as tc
except ImportError as exc:
    raise SystemExit(
        "Could not import traci. Ensure SUMO tools are on PYTHONPATH."
    ) from exc

from .fast_pedestrian_detector import FastPedestrianDetector, PersonPosition
from .metrics_logger import CsvLogger
from .parking_group_manager import ParkingGroupManager
from .person_manager import PersonManager
from sumo.parking_choice import parking_choice_config, rank_parking_candidates
from .sumo_runtime import (
    make_sumo_cmd,
    route_vehicle_to_physical_parking,
    set_new_parking_stop,
)
from .vehicle_tracker import VehicleTracker


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RECOVERABLE_SUMO_SIGNALS = frozenset({"SIGSEGV", "SIGBUS"})


def _start_sumo(
    sumo_cmd: list[str],
    trace_path: Path | None,
    *,
    load_state_path: Path | None = None,
) -> subprocess.Popen | None:
    command = list(sumo_cmd)
    if load_state_path is not None:
        command.extend(["--load-state", str(load_state_path)])
    print("Starting:", " ".join(command))
    trace_options = (
        {"traceFile": str(trace_path), "traceGetters": True}
        if trace_path is not None
        else {}
    )
    traci.start(command, **trace_options)
    return getattr(traci.getConnection(), "_process", None)


def _archive_sumo_attempt(output_dir: Path, attempt: int) -> None:
    """Keep native SUMO output from a crashed attempt before restart."""
    for name in (
        "sumo.log",
        "tripinfo.xml",
        "summary.xml",
        "vehroute.xml",
        "traci.trace.py",
        "sumo_process.json",
    ):
        source = output_dir / name
        if not source.exists():
            continue
        archived = output_dir / f"{source.stem}.attempt-{attempt}{source.suffix}"
        source.replace(archived)


def _walking_completion_candidates(
    *,
    step_length: float,
    minimum_distance: float,
    person_ids: tuple[str, ...] | None = None,
    subscription_results: dict[str, dict[int, Any]] | None = None,
    final_stage_cache: dict[str, tuple[str, float]] | None = None,
) -> list[str]:
    """Find walkers that may complete their final stage on the next step."""
    candidates: list[str] = []
    if person_ids is None:
        try:
            person_ids = tuple(traci.person.getIDList())
        except Exception:
            return candidates
    stage_cache = final_stage_cache if final_stage_cache is not None else {}

    for person_id in person_ids:
        try:
            result = (subscription_results or {}).get(person_id) or {}
            remaining_stages = result.get(tc.VAR_STAGES_REMAINING)
            if remaining_stages is None:
                remaining_stages = traci.person.getRemainingStages(person_id)
            if int(remaining_stages) != 1:
                stage_cache.pop(person_id, None)
                continue
            final_stage = stage_cache.get(person_id)
            if final_stage is None:
                stage = traci.person.getStage(person_id, 0)
                if int(stage.type) != int(tc.STAGE_WALKING) or not stage.edges:
                    continue
                final_stage = (str(stage.edges[-1]), float(stage.arrivalPos))
                stage_cache[person_id] = final_stage
            final_edge, arrival_position = final_stage
            road_id = str(
                result.get(tc.VAR_ROAD_ID)
                if result.get(tc.VAR_ROAD_ID) is not None
                else traci.person.getRoadID(person_id)
            )
            if road_id.lstrip("-") != final_edge.lstrip("-"):
                continue
            lane_position_value = result.get(tc.VAR_LANEPOSITION)
            lane_position = float(
                lane_position_value
                if lane_position_value is not None
                else traci.person.getLanePosition(person_id)
            )
            speed_value = result.get(tc.VAR_SPEED)
            speed = max(
                float(
                    speed_value
                    if speed_value is not None
                    else traci.person.getSpeed(person_id)
                ),
                0.0,
            )
            risk_distance = max(
                float(minimum_distance),
                speed * max(float(step_length), 0.001) * 1.5,
            )
            if abs(lane_position - arrival_position) <= risk_distance:
                candidates.append(str(person_id))
        except Exception:
            # Persons can finish between the ID-list and detail queries.
            continue
    return sorted(set(candidates))


def _subscription_results(
    domain: Any,
    object_ids: tuple[str, ...],
    subscribed_ids: set[str],
    variables: tuple[int, ...],
) -> dict[str, dict[int, Any]]:
    """Subscribe new objects once and return all values in one TraCI call."""
    current_ids = set(object_ids)
    subscribed_ids.intersection_update(current_ids)
    for object_id in sorted(current_ids - subscribed_ids):
        try:
            domain.subscribe(object_id, variables)
        except Exception:
            # Objects may leave between getIDList and subscribe. Missing
            # subscription data falls back to a direct getter where required.
            continue
        subscribed_ids.add(object_id)
    try:
        results = domain.getAllSubscriptionResults()
    except Exception:
        return {}
    return dict(results or {})


def _remove_vehicle_without_stale_subscription(
    vehicle_id: str,
    subscribed_ids: set[str],
) -> None:
    """Unsubscribe before removal so SUMO never evaluates a dead vehicle getter."""
    try:
        traci.vehicle.unsubscribe(vehicle_id)
    except Exception:
        pass
    subscribed_ids.discard(vehicle_id)
    try:
        traci.vehicle.remove(vehicle_id)
    except Exception:
        pass


def _parking_decision_target(
    current_target: str,
    unattempted_candidates: list[str],
    access_edge_parkings: set[str],
    *,
    decision_mode: str,
) -> tuple[str | None, str]:
    """Choose the intended lot at arrival, or a candidate physically passed en route."""
    if decision_mode != "access_edge":
        return (current_target or None), "target"
    if current_target in access_edge_parkings:
        return current_target, "target"
    pass_by = next(
        (
            parking_id
            for parking_id in unattempted_candidates
            if parking_id != current_target and parking_id in access_edge_parkings
        ),
        None,
    )
    return (pass_by, "pass_by" if pass_by else "")


def _sumo_process_diagnostics(
    process: subprocess.Popen | None,
    *,
    phase: str,
    controller_error: str | None = None,
    wait_for_exit: bool = False,
) -> dict[str, Any]:
    return_code = None
    if process is not None:
        return_code = process.poll()
        if return_code is None and wait_for_exit:
            try:
                return_code = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return_code = process.poll()

    signal_number = -return_code if return_code is not None and return_code < 0 else None
    signal_name = None
    if signal_number is not None:
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIGNAL_{signal_number}"

    if process is None:
        exit_kind = "not_started"
    elif return_code is None:
        exit_kind = "running"
    elif return_code < 0:
        exit_kind = "signal"
    else:
        exit_kind = "exit_code"

    return {
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "phase": phase,
        "pid": process.pid if process is not None else None,
        "return_code": return_code,
        "exit_kind": exit_kind,
        "signal_number": signal_number,
        "signal_name": signal_name,
        "controller_error": controller_error,
    }


def _write_sumo_process_diagnostics(
    path: Path,
    process: subprocess.Popen | None,
    *,
    phase: str,
    controller_error: str | None = None,
    wait_for_exit: bool = False,
) -> dict[str, Any]:
    diagnostics = _sumo_process_diagnostics(
        process,
        phase=phase,
        controller_error=controller_error,
        wait_for_exit=wait_for_exit,
    )
    path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    return diagnostics


def _format_sumo_process_diagnostics(diagnostics: dict[str, Any]) -> str:
    if diagnostics["exit_kind"] == "signal":
        return (
            f"SUMO terminated by {diagnostics['signal_name']} "
            f"(return code {diagnostics['return_code']})."
        )
    if diagnostics["exit_kind"] == "exit_code":
        return f"SUMO exited with return code {diagnostics['return_code']}."
    if diagnostics["exit_kind"] == "running":
        return "SUMO closed the TraCI connection while its process still appeared to be running."
    return "SUMO process diagnostics were unavailable because the process did not start."


def _write_progress(
    path: Path,
    *,
    simulated_seconds: float,
    progress_percent: float,
    phase: str,
    planned_agents: int,
    completed_agents: int,
    remaining_agents: int,
    active_agents: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps({
            "simulated_seconds": simulated_seconds,
            "progress_percent": progress_percent,
            "phase": phase,
            "planned_agents": planned_agents,
            "completed_agents": completed_agents,
            "remaining_agents": remaining_agents,
            "active_agents": active_agents,
        }),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def run(
    config_path: Path,
    output_dir: Path,
    progress_file: Path,
    sumocfg_path: Path,
    parking_config_path: Path,
    vehicle_plan_path: Path,
    person_access_config_path: Path | None = None,
    person_plan_path: Path | None = None,
    detector_snapshot_path: Path | None = None,
) -> None:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    if "simulation" not in cfg:
        raise ValueError(f"Missing 'simulation' section in {config_path}")

    if "controller" not in cfg:
        raise ValueError(f"Missing 'controller' section in {config_path}")

    tracker = VehicleTracker(vehicle_plan_path.resolve())
    
    controller_cfg = cfg.get("controller", {})
    parking_duration_min = float(controller_cfg.get("parking_duration_min", controller_cfg.get("parking_duration", 300)))
    parking_duration_max = float(controller_cfg.get("parking_duration_max", controller_cfg.get("parking_duration", 300)))

    if parking_duration_min < 0:
        raise ValueError("parking_duration_min cannot be negative.")

    if parking_duration_max < parking_duration_min:
        raise ValueError("parking_duration_max must be greater than or equal to parking_duration_min.")

    random_seed = controller_cfg.get("random_seed")
    if random_seed is not None:
        random.seed(int(random_seed))
    parking_choice_seed = int(random_seed if random_seed is not None else 42)
    parking_choice_cfg = parking_choice_config(
        controller_cfg.get("parking_choice")
    )

    recovery_cfg = controller_cfg.get("sumo_recovery") or {}
    recovery_enabled = bool(recovery_cfg.get("enabled", True))
    recovery_checkpoint_interval = max(
        float(recovery_cfg.get("checkpoint_interval_seconds", 60)),
        1.0,
    )
    recovery_candidate_distance = max(
        float(recovery_cfg.get("completion_candidate_distance_metres", 2.0)),
        0.1,
    )
    recovery_max_attempts = max(int(recovery_cfg.get("max_attempts", 10)), 0)
    diagnostic_tracing = bool(controller_cfg.get("diagnostic_tracing", False))
    
    decision_mode = controller_cfg.get(
        "decision_mode",
        "access_edge",
    )

    policy = controller_cfg.get(
        "policy",
        "nearest_available",
    )

    supported_policies = {
        "balanced_available",
        "random_available",
        "nearest_available",
    }

    if policy not in supported_policies:
        raise ValueError(
            f"Unsupported parking policy: {policy}. "
            f"Expected one of {sorted(supported_policies)}"
        )
    
    out_dir = output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    parking_events = CsvLogger(
        out_dir / "parking_events.csv",
        [
            "time",
            "vehicle_id",
            "event",
            "logical_parking",
            "physical_parking",
            "old_parking",
            "new_parking",
            "reason",
            "parking_duration",
            "attempt_index",
            "distance_to_building_metres",
            "total_capacity",
            "capacity_band",
            "selection_context",
            "choice_model",
            "driver_profile",
            "choice_utility",
            "systematic_utility",
            "drive_time_to_parking_seconds",
            "perceived_free_spaces",
            "perceived_free_ratio",
            "occupancy_known",
        ],
    )

    occupancy_log = CsvLogger(
        out_dir / "parking_occupancy.csv",
        [
            "time",
            "logical_parking_id",
            "physical_parking_id",
            "capacity",
            "occupied",
            "reserved",
            "free",
            "capacity_source",
        ],
    )

    person_events = CsvLogger(
        out_dir / "person_events.csv",
        [
            "time",
            "person_id",
            "vehicle_id",
            "event",
            "physical_parking",
            "building_id",
            "building_name",
            "reason",
        ],
    )

    recovery_events = CsvLogger(
        out_dir / "sumo_recoveries.csv",
        [
            "time",
            "attempt",
            "signal",
            "checkpoint_time",
            "quarantined_person_ids",
            "reason",
        ],
    )

    person_based_demand = bool(cfg.get("person_based_demand"))
    person_manager = None
    if person_based_demand:
        if person_access_config_path is None or person_plan_path is None:
            raise ValueError("Person-based demand requires person access and person plan files.")
        person_manager = PersonManager(
            person_plan_path.resolve(),
            person_access_config_path.resolve(),
            person_events,
        )

    sumo_cmd = make_sumo_cmd(cfg, out_dir, sumocfg_path)
    sumo_log_path = out_dir / "sumo.log"
    traci_trace_path = out_dir / "traci.trace.py"
    sumo_process_path = out_dir / "sumo_process.json"
    recovery_state_path = out_dir / "sumo_recovery_state.xml.gz"
    sumo_process = _start_sumo(
        sumo_cmd,
        traci_trace_path if diagnostic_tracing else None,
    )
    _write_sumo_process_diagnostics(
        sumo_process_path,
        sumo_process,
        phase="running",
    )
    print(f"SUMO log: {sumo_log_path}")
    print(
        f"TraCI trace: {traci_trace_path}"
        if diagnostic_tracing
        else "TraCI trace: disabled (enable diagnostic_tracing for full command capture)"
    )
    print(f"SUMO process diagnostics: {sumo_process_path}")

    simulation_cfg = cfg["simulation"]
    simulation_begin = float(simulation_cfg.get("begin", 0))
    simulation_end = float(simulation_cfg["end"])
    simulation_step_length = max(float(simulation_cfg.get("step_length", 1)), 0.001)
    simulation_duration = max(simulation_end - simulation_begin, 1.0)
    demand_totals = cfg.get("demand_totals") or {}
    planned_agents = max(
        int(demand_totals.get("vehicles") or 0)
        + int(demand_totals.get("pedestrians") or 0),
        0,
    )
    completed_vehicle_ids: set[str] = set()
    completed_person_ids: set[str] = set()
    last_progress_percent = -1.0
    last_progress_write = 0.0
    if progress_file is not None:
        _write_progress(
            progress_file,
            simulated_seconds=0.0,
            progress_percent=0.0,
            phase="demand",
            planned_agents=planned_agents,
            completed_agents=0,
            remaining_agents=planned_agents,
            active_agents=0,
        )

    parking = ParkingGroupManager(
        config_path=parking_config_path.resolve(),
        project_root=BACKEND_ROOT,
    )
    vehicle_assignment: dict[str, str] = {}
    vehicle_parking_duration: dict[str, float] = {}
    active_reservations: set[str] = set()
    completed_parking: set[str] = set()
    no_available_logged: set[tuple[str, str]] = set()
    quarantined_person_ids: set[str] = set()
    recovery_attempts = 0
    controller_checkpoint: dict[str, Any] | None = None
    subscribed_vehicle_ids: set[str] = set()
    subscribed_person_ids: set[str] = set()
    final_walking_stage_cache: dict[str, tuple[str, float]] = {}
    last_checkpoint_time = simulation_begin
    last_simulation_time = simulation_begin
    controller_error: str | None = None
    fast_pedestrian_detector: FastPedestrianDetector | None = None
    if (
        str(simulation_cfg.get("pedestrian_model") or "striping")
        == "nonInteracting"
        and detector_snapshot_path is not None
        and detector_snapshot_path.is_file()
    ):
        candidate = FastPedestrianDetector.from_snapshot(detector_snapshot_path)
        if candidate.zones:
            fast_pedestrian_detector = candidate
            print(
                "Fast pedestrian detector compatibility counter enabled for "
                f"{len(candidate.zones)} zone(s).",
                flush=True,
            )

    def capture_controller_state(checkpoint_time: float) -> dict[str, Any]:
        return {
            "time": float(checkpoint_time),
            "completed_vehicle_ids": set(completed_vehicle_ids),
            "completed_person_ids": set(completed_person_ids),
            "last_progress_percent": float(last_progress_percent),
            "last_progress_write": float(last_progress_write),
            "vehicle_assignment": dict(vehicle_assignment),
            "vehicle_parking_duration": dict(vehicle_parking_duration),
            "active_reservations": set(active_reservations),
            "completed_parking": set(completed_parking),
            "no_available_logged": set(no_available_logged),
            "parking_reserved": dict(parking.reserved),
            "tracker": copy.deepcopy(tracker),
            "person_spawned_vehicle_ids": (
                set(person_manager.spawned_vehicle_ids)
                if person_manager is not None
                else set()
            ),
            "random_state": random.getstate(),
            "parking_events_position": parking_events.checkpoint(),
            "occupancy_log_position": occupancy_log.checkpoint(),
            "person_events_position": person_events.checkpoint(),
            "fast_pedestrian_detector": (
                fast_pedestrian_detector.snapshot()
                if fast_pedestrian_detector is not None
                else None
            ),
        }

    def choose_physical_parking(vehicle_id: str, logical_id: str) -> str | None:
        if policy == "random_available":
            return parking.choose_random_available_physical_parking(
                vehicle_id,
                logical_id,
            )
        if policy == "balanced_available":
            return parking.choose_balanced_available_physical_parking(
                vehicle_id,
                logical_id,
            )
        return parking.choose_available_physical_parking_near_vehicle(
            vehicle_id,
            logical_id,
        )

    def parking_candidate_event_fields(
        vehicle_id: str,
        logical_id: str,
        selection_context: str,
        choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        choice = choice or tracker.parking_candidate_detail(vehicle_id, logical_id)

        def value(key: str) -> Any:
            result = choice.get(key)
            return "" if result is None else result

        return {
            "distance_to_building_metres": (
                tracker.parking_candidate_distance(vehicle_id, logical_id) or ""
            ),
            "total_capacity": (
                tracker.parking_candidate_capacity(vehicle_id, logical_id) or ""
            ),
            "capacity_band": tracker.parking_candidate_band(
                vehicle_id,
                logical_id,
            ),
            "selection_context": selection_context,
            "choice_model": parking_choice_cfg["model"],
            "driver_profile": value("driver_profile"),
            "choice_utility": value("choice_utility"),
            "systematic_utility": value("systematic_utility"),
            "drive_time_to_parking_seconds": value("drive_time_seconds"),
            "perceived_free_spaces": value("perceived_free_spaces"),
            "perceived_free_ratio": value("perceived_free_ratio"),
            "occupancy_known": value("occupancy_known"),
        }

    def mark_vehicle_unserved(
        vehicle_id: str,
        time_seconds: float,
        logical_id: str,
        attempt_index: int,
        reason: str,
    ) -> None:
        parking_events.write(
            time=time_seconds,
            vehicle_id=vehicle_id,
            event="parking_unserved",
            logical_parking=logical_id,
            physical_parking="",
            old_parking=logical_id,
            new_parking="",
            reason=reason,
            parking_duration="",
            attempt_index=attempt_index,
            **parking_candidate_event_fields(
                vehicle_id,
                logical_id,
                "exhausted",
            ),
        )
        tracker.mark_unserved(vehicle_id, time_seconds)
        completed_parking.add(vehicle_id)
        completed_vehicle_ids.add(vehicle_id)
        _remove_vehicle_without_stale_subscription(
            vehicle_id,
            subscribed_vehicle_ids,
        )

    def reroute_to_next_candidate(
        vehicle_id: str,
        time_seconds: float,
        previous_target: str,
        reason: str,
    ) -> bool:
        """Choose a reachable alternative using live, imperfect parking knowledge."""
        while True:
            candidate_ids = [
                parking_id
                for parking_id in tracker.unattempted_parking_candidates(vehicle_id)
                if parking_id in parking.groups
            ]
            if not candidate_ids:
                return False

            routable: list[dict[str, Any]] = []
            for parking_id in candidate_ids:
                route = parking.logical_parking_route(vehicle_id, parking_id)
                if route is None:
                    tracker.mark_candidate_rejected(vehicle_id, parking_id)
                    parking_events.write(
                        time=time_seconds,
                        vehicle_id=vehicle_id,
                        event="parking_candidate_rejected",
                        logical_parking=parking_id,
                        physical_parking="",
                        old_parking=previous_target,
                        new_parking="",
                        reason="no_vehicle_route_to_candidate",
                        parking_duration="",
                        attempt_index=len(
                            tracker.data[vehicle_id]["attempted_parking_ids"]
                        ),
                        **parking_candidate_event_fields(
                            vehicle_id,
                            parking_id,
                            "fallback_unreachable",
                        ),
                    )
                    continue
                _destination_edge, travel_time = route
                candidate = tracker.parking_candidate_detail(
                    vehicle_id,
                    parking_id,
                )
                candidate.update({
                    "parking_id": parking_id,
                    "distance_metres": tracker.parking_candidate_distance(
                        vehicle_id,
                        parking_id,
                    ),
                    "total_capacity": parking.total_capacity(parking_id),
                    "free_spaces": parking.total_free_spaces(parking_id),
                    "drive_time_seconds": travel_time,
                })
                routable.append(candidate)

            if not routable:
                return False
            decision_index = tracker.next_parking_decision_index(vehicle_id)
            ranked = rank_parking_candidates(
                vehicle_id,
                routable,
                config=parking_choice_cfg,
                seed=parking_choice_seed,
                decision_index=decision_index,
                failed_attempts=len(
                    tracker.data[vehicle_id]["attempted_parking_ids"]
                ),
            )
            ranked_ids = {str(item["parking_id"]) for item in ranked}
            for candidate in routable:
                rejected_id = str(candidate["parking_id"])
                if rejected_id in ranked_ids:
                    continue
                tracker.mark_candidate_rejected(vehicle_id, rejected_id)
                parking_events.write(
                    time=time_seconds,
                    vehicle_id=vehicle_id,
                    event="parking_candidate_rejected",
                    logical_parking=rejected_id,
                    physical_parking="",
                    old_parking=previous_target,
                    new_parking="",
                    reason="known_full_from_parking_information",
                    parking_duration="",
                    attempt_index=len(
                        tracker.data[vehicle_id]["attempted_parking_ids"]
                    ),
                    **parking_candidate_event_fields(
                        vehicle_id,
                        rejected_id,
                        "fallback_known_full",
                        candidate,
                    ),
                )
            if not ranked:
                return False

            selected = ranked[0]
            next_target = str(selected["parking_id"])
            destination_edge = parking.route_vehicle_to_logical_parking(
                vehicle_id,
                next_target,
            )
            if destination_edge is not None:
                tracker.mark_target_changed(
                    vehicle_id,
                    time_seconds,
                    next_target,
                    parking.parking_name(next_target),
                )
                parking_events.write(
                    time=time_seconds,
                    vehicle_id=vehicle_id,
                    event="parking_target_changed",
                    logical_parking=next_target,
                    physical_parking="",
                    old_parking=previous_target,
                    new_parking=next_target,
                    reason=reason,
                    parking_duration="",
                    attempt_index=len(
                        tracker.data[vehicle_id]["attempted_parking_ids"]
                    ),
                    **parking_candidate_event_fields(
                        vehicle_id,
                        next_target,
                        "fallback_weighted_choice",
                        selected,
                    ),
                )
                return True

            tracker.mark_candidate_rejected(vehicle_id, next_target)
            parking_events.write(
                time=time_seconds,
                vehicle_id=vehicle_id,
                event="parking_candidate_rejected",
                logical_parking=next_target,
                physical_parking="",
                old_parking=previous_target,
                new_parking="",
                reason="no_vehicle_route_to_candidate",
                parking_duration="",
                attempt_index=len(
                    tracker.data[vehicle_id]["attempted_parking_ids"]
                ),
                **parking_candidate_event_fields(
                    vehicle_id,
                    next_target,
                    "fallback_unreachable",
                    selected,
                ),
            )

    try:
        parking.load()
        if person_manager is not None:
            parking.restrict_selectable_physical_areas(
                person_manager.accessible_physical_parking_ids
            )

        if recovery_enabled and recovery_max_attempts > 0:
            traci.simulation.saveState(str(recovery_state_path))
            controller_checkpoint = capture_controller_state(simulation_begin)
            print(
                "SUMO recovery enabled: "
                f"checkpoint every {recovery_checkpoint_interval:g}s, "
                f"maximum {recovery_max_attempts} attempt(s).",
                flush=True,
            )

        while traci.simulation.getMinExpectedNumber() > 0:
            for person_id in sorted(quarantined_person_ids):
                try:
                    if person_id in traci.person.getIDList():
                        traci.person.remove(person_id)
                        completed_person_ids.add(person_id)
                except Exception:
                    continue

            if recovery_enabled or fast_pedestrian_detector is not None:
                current_person_ids = tuple(traci.person.getIDList())
                person_subscription_results = _subscription_results(
                    traci.person,
                    current_person_ids,
                    subscribed_person_ids,
                    (
                        tc.VAR_STAGES_REMAINING,
                        tc.VAR_ROAD_ID,
                        tc.VAR_LANE_ID,
                        tc.VAR_LANEPOSITION,
                        tc.VAR_SPEED,
                    ),
                )
                if fast_pedestrian_detector is not None:
                    person_positions: dict[str, PersonPosition] = {}
                    for person_id in current_person_ids:
                        try:
                            result = person_subscription_results.get(person_id) or {}
                            road_id_value = result.get(tc.VAR_ROAD_ID)
                            lane_id_value = result.get(tc.VAR_LANE_ID)
                            lane_position_value = result.get(tc.VAR_LANEPOSITION)
                            speed_value = result.get(tc.VAR_SPEED)
                            road_id = str(
                                road_id_value
                                if road_id_value is not None
                                else traci.person.getRoadID(person_id)
                            )
                            if road_id not in fast_pedestrian_detector.edge_ids:
                                continue
                            stage_type = int(traci.person.getStage(person_id, 0).type)
                            person_positions[person_id] = PersonPosition(
                                road_id=road_id,
                                lane_position=float(
                                    lane_position_value
                                    if lane_position_value is not None
                                    else traci.person.getLanePosition(person_id)
                                ),
                                speed=float(
                                    speed_value
                                    if speed_value is not None
                                    else traci.person.getSpeed(person_id)
                                ),
                                lane_id=str(
                                    lane_id_value
                                    if lane_id_value is not None
                                    else traci.person.getLaneID(person_id)
                                ),
                                stage_type=stage_type,
                            )
                        except Exception:
                            # A person may arrive between the ID and state query.
                            continue
                    fast_pedestrian_detector.observe(
                        traci.simulation.getTime(),
                        person_positions,
                    )
            if recovery_enabled:
                current_person_id_set = set(current_person_ids)
                for departed_person_id in set(final_walking_stage_cache) - current_person_id_set:
                    final_walking_stage_cache.pop(departed_person_id, None)
                completion_candidates = _walking_completion_candidates(
                    step_length=simulation_step_length,
                    minimum_distance=recovery_candidate_distance,
                    person_ids=current_person_ids,
                    subscription_results=person_subscription_results,
                    final_stage_cache=final_walking_stage_cache,
                )
            else:
                completion_candidates = []
            try:
                traci.simulationStep()
            except traci.exceptions.FatalTraCIError as exc:
                diagnostics = _write_sumo_process_diagnostics(
                    sumo_process_path,
                    sumo_process,
                    phase="recovery_candidate",
                    controller_error=f"{type(exc).__name__}: {exc}",
                    wait_for_exit=True,
                )
                can_recover = (
                    recovery_enabled
                    and diagnostics.get("signal_name") in RECOVERABLE_SUMO_SIGNALS
                    and controller_checkpoint is not None
                    and bool(completion_candidates)
                    and recovery_attempts < recovery_max_attempts
                    and recovery_state_path.is_file()
                )
                if not can_recover:
                    raise

                recovery_attempts += 1
                crashed_attempt = recovery_attempts
                checkpoint = controller_checkpoint
                crash_simulation_time = last_simulation_time
                crash_signal = str(diagnostics.get("signal_name") or "native fault")
                print(
                    f"Recovering SUMO from {crash_signal}; quarantining final-stage "
                    f"pedestrian candidate(s): {', '.join(completion_candidates)}",
                    flush=True,
                )
                try:
                    traci.close(False)
                except Exception:
                    pass
                _archive_sumo_attempt(out_dir, crashed_attempt)

                completed_vehicle_ids = set(checkpoint["completed_vehicle_ids"])
                completed_person_ids = set(checkpoint["completed_person_ids"])
                last_progress_percent = float(checkpoint["last_progress_percent"])
                last_progress_write = float(checkpoint["last_progress_write"])
                vehicle_assignment = dict(checkpoint["vehicle_assignment"])
                vehicle_parking_duration = dict(checkpoint["vehicle_parking_duration"])
                active_reservations = set(checkpoint["active_reservations"])
                completed_parking = set(checkpoint["completed_parking"])
                no_available_logged = set(checkpoint["no_available_logged"])
                parking.reserved = dict(checkpoint["parking_reserved"])
                tracker = copy.deepcopy(checkpoint["tracker"])
                if person_manager is not None:
                    person_manager.spawned_vehicle_ids = set(
                        checkpoint["person_spawned_vehicle_ids"]
                    )
                random.setstate(checkpoint["random_state"])
                parking_events.restore(int(checkpoint["parking_events_position"]))
                occupancy_log.restore(int(checkpoint["occupancy_log_position"]))
                person_events.restore(int(checkpoint["person_events_position"]))
                if fast_pedestrian_detector is not None:
                    detector_state = checkpoint.get("fast_pedestrian_detector")
                    if detector_state is not None:
                        fast_pedestrian_detector.restore(detector_state)
                last_simulation_time = float(checkpoint["time"])
                last_checkpoint_time = float(checkpoint["time"])

                quarantined_person_ids.update(completion_candidates)
                completed_person_ids.update(quarantined_person_ids)
                recovery_events.write(
                    time=crash_simulation_time,
                    attempt=recovery_attempts,
                    signal=diagnostics.get("signal_name") or "",
                    checkpoint_time=checkpoint["time"],
                    quarantined_person_ids=";".join(completion_candidates),
                    reason=(
                        f"SUMO striping-model {crash_signal} during final "
                        "walking-stage completion"
                    ),
                )
                recovery_events.flush()
                for person_id in completion_candidates:
                    person_events.write(
                        time=crash_simulation_time,
                        person_id=person_id,
                        vehicle_id="",
                        event="simulation_recovery_quarantined",
                        physical_parking="",
                        building_id="",
                        building_name="",
                        reason=(
                            f"SUMO {crash_signal} while the person was completing "
                            "its final walking stage"
                        ),
                    )
                person_events.flush()

                attempt_trace_path = out_dir / f"traci.trace.recovery-{recovery_attempts}.py"
                sumo_process = _start_sumo(
                    sumo_cmd,
                    attempt_trace_path if diagnostic_tracing else None,
                    load_state_path=recovery_state_path,
                )
                subscribed_vehicle_ids.clear()
                subscribed_person_ids.clear()
                final_walking_stage_cache.clear()
                _write_sumo_process_diagnostics(
                    sumo_process_path,
                    sumo_process,
                    phase=f"recovered_attempt_{recovery_attempts}",
                )
                if progress_file is not None:
                    completed_agents = min(len(completed_person_ids), planned_agents)
                    _write_progress(
                        progress_file,
                        simulated_seconds=max(last_simulation_time - simulation_begin, 0.0),
                        progress_percent=round(max(last_progress_percent, 0.0), 3),
                        phase="recovering",
                        planned_agents=planned_agents,
                        completed_agents=completed_agents,
                        remaining_agents=max(planned_agents - completed_agents, 0),
                        active_agents=0,
                    )
                continue
            t = traci.simulation.getTime()
            last_simulation_time = t
            completed_vehicle_ids.update(traci.simulation.getArrivedIDList())
            completed_person_ids.update(traci.simulation.getArrivedPersonIDList())

            if progress_file is not None:
                simulated_seconds = max(t - simulation_begin, 0.0)
                completed_agents = min(
                    len(completed_person_ids)
                    if person_based_demand
                    else len(completed_vehicle_ids) + len(completed_person_ids),
                    planned_agents,
                )
                remaining_agents = max(planned_agents - completed_agents, 0)
                active_agents = (
                    int(traci.vehicle.getIDCount())
                    + int(traci.person.getIDCount())
                )
                phase = "demand" if t < simulation_end else "finishing"
                demand_progress = min(
                    simulated_seconds / simulation_duration,
                    1.0,
                )
                completion_progress = (
                    completed_agents / planned_agents
                    if planned_agents
                    else demand_progress
                )
                if phase == "demand":
                    # Agent completion can stay near zero while cars are parked,
                    # even though SUMO is advancing normally. Follow simulated
                    # time during the configured window so progress stays useful.
                    progress_percent = demand_progress * 90.0
                else:
                    # Reserve the final 10% for agents that are still travelling
                    # after the configured demand window.
                    progress_percent = 90.0 + min(completion_progress, 1.0) * 9.9
                now = time.monotonic()
                if (
                    abs(progress_percent - last_progress_percent) >= 0.1
                    or now - last_progress_write >= 1
                ):
                    _write_progress(
                        progress_file,
                        simulated_seconds=simulated_seconds,
                        progress_percent=round(progress_percent, 3),
                        phase=phase,
                        planned_agents=planned_agents,
                        completed_agents=completed_agents,
                        remaining_agents=remaining_agents,
                        active_agents=active_agents,
                    )
                    last_progress_percent = progress_percent
                    last_progress_write = now

            if int(t) % 60 == 0:
                for group in parking.groups.values():
                    for area in group.physical_areas:
                        occ = parking.occupied(area.sumo_id)
                        cap = parking.capacity(area.sumo_id)
                        res = parking.reserved.get(area.sumo_id, 0)

                        occupancy_log.write(
                            time=t,
                            logical_parking_id=group.logical_id,
                            physical_parking_id=area.sumo_id,
                            capacity=cap,
                            occupied=occ,
                            reserved=res,
                            free=cap - occ - res,
                            capacity_source=area.capacity_source,
                        )

            current_vehicle_ids = tuple(traci.vehicle.getIDList())
            vehicle_subscription_results = _subscription_results(
                traci.vehicle,
                current_vehicle_ids,
                subscribed_vehicle_ids,
                (tc.VAR_ROAD_ID,),
            )
            for veh_id in current_vehicle_ids:
                logical_target = tracker.target(veh_id)
                if not logical_target or logical_target not in parking.groups:
                    tracker.mark_active(veh_id, t)
                    continue

                parking_name = parking.parking_name(logical_target)
                tracker.mark_active(veh_id, t, parking_name)

                road_id_value = (
                    vehicle_subscription_results.get(veh_id) or {}
                ).get(tc.VAR_ROAD_ID)
                road_id = str(
                    road_id_value
                    if road_id_value is not None
                    else traci.vehicle.getRoadID(veh_id)
                )
                if (
                    tracker.current_segment_type(veh_id) != "parked"
                    and parking.is_inside_logical_parking(road_id, logical_target)
                ):
                    tracker.mark_inside_parking(
                        veh_id,
                        t,
                        logical_target,
                        parking_name,
                    )

                # A demand vehicle receives one logical parking visit. SUMO
                # keeps it alive for a step after its parking stop ends, so
                # remember completion separately from the active assignment.
                if veh_id in completed_parking:
                    continue

                if veh_id in vehicle_assignment:
                    continue

                access_edge_parkings = parking.logical_parkings_for_access_edge(
                    road_id
                )
                attempt_target, selection_context = _parking_decision_target(
                    logical_target,
                    tracker.unattempted_parking_candidates(veh_id),
                    access_edge_parkings,
                    decision_mode=decision_mode,
                )
                if not attempt_target or attempt_target not in parking.groups:
                    continue

                has_free_space = parking.logical_has_free_space(attempt_target)
                selected_physical = (
                    choose_physical_parking(veh_id, attempt_target)
                    if has_free_space
                    else None
                )
                failure_reason = (
                    ""
                    if selected_physical is not None
                    else "no_reachable_physical_area"
                    if has_free_space
                    else "logical_parking_full"
                )
                attempt_index = tracker.mark_parking_attempt(
                    veh_id,
                    attempt_target,
                    t,
                )
                parking_events.write(
                    time=t,
                    vehicle_id=veh_id,
                    event="parking_attempt",
                    logical_parking=attempt_target,
                    physical_parking=selected_physical or "",
                    old_parking=logical_target,
                    new_parking="",
                    reason=failure_reason or "space_available",
                    parking_duration="",
                    attempt_index=attempt_index,
                    **parking_candidate_event_fields(
                        veh_id,
                        attempt_target,
                        selection_context,
                    ),
                )

                if selected_physical is None:
                    no_available_logged.add((veh_id, attempt_target))
                    # A lesser-preference lot encountered on the road is only
                    # a quick check. If full, keep driving toward the chosen lot.
                    if selection_context == "pass_by":
                        continue
                    if reroute_to_next_candidate(
                        veh_id,
                        t,
                        attempt_target,
                        failure_reason,
                    ):
                        continue
                    mark_vehicle_unserved(
                        veh_id,
                        t,
                        attempt_target,
                        attempt_index,
                        "all_destination_parking_candidates_exhausted",
                    )
                    continue

                if attempt_target != logical_target:
                    previous_target = logical_target
                    tracker.mark_target_changed(
                        veh_id,
                        t,
                        attempt_target,
                        parking.parking_name(attempt_target),
                    )
                    parking_events.write(
                        time=t,
                        vehicle_id=veh_id,
                        event="parking_target_changed",
                        logical_parking=attempt_target,
                        physical_parking="",
                        old_parking=previous_target,
                        new_parking=attempt_target,
                        reason="available_parking_passed_en_route",
                        parking_duration="",
                        attempt_index=attempt_index,
                        **parking_candidate_event_fields(
                            veh_id,
                            attempt_target,
                            "pass_by_selected",
                        ),
                    )
                    logical_target = attempt_target

                try:
                    route_vehicle_to_physical_parking(veh_id, parking, selected_physical)
                    parking_duration = (
                        max(simulation_end - t, 1.0)
                        if person_based_demand
                        else random.uniform(parking_duration_min, parking_duration_max)
                    )
                    set_new_parking_stop(veh_id, selected_physical, parking_duration)
                    parking.reserve(selected_physical)
                    vehicle_assignment[veh_id] = selected_physical
                    vehicle_parking_duration[veh_id] = parking_duration
                    active_reservations.add(veh_id)

                    if hasattr(tracker, "mark_reroute"):
                        tracker.mark_reroute(veh_id, t, selected_physical)

                    parking_events.write(
                        time=t,
                        vehicle_id=veh_id,
                        event="assigned_physical_parking",
                        logical_parking=logical_target,
                        physical_parking=selected_physical,
                        old_parking=logical_target,
                        new_parking=selected_physical,
                        reason=f"decision_mode={decision_mode}",
                        parking_duration=f"{parking_duration:.2f}",
                    )

                except Exception as exc:
                    parking.release(selected_physical)
                    parking_events.write(
                        time=t,
                        vehicle_id=veh_id,
                        event="parking_assignment_failed",
                        logical_parking=logical_target,
                        physical_parking=selected_physical,
                        old_parking=logical_target,
                        new_parking=selected_physical,
                        reason=str(exc),
                        parking_duration="",
                    )
                    if not reroute_to_next_candidate(
                        veh_id,
                        t,
                        logical_target,
                        "physical_parking_assignment_failed",
                    ):
                        mark_vehicle_unserved(
                            veh_id,
                            t,
                            logical_target,
                            attempt_index,
                            "all_destination_parking_candidates_exhausted",
                        )

            if hasattr(traci.simulation, "getStopStartingVehiclesIDList"):
                for veh_id in traci.simulation.getStopStartingVehiclesIDList():
                    physical_id = vehicle_assignment.get(veh_id)
                    if not physical_id:
                        continue
                    logical_target = tracker.target(veh_id)
                    if veh_id in active_reservations:
                        parking.release(physical_id)
                        active_reservations.discard(veh_id)
                    tracker.mark_parked(
                        veh_id,
                        t,
                        physical_id,
                        logical_target or "",
                        parking.parking_name(logical_target) if logical_target else "",
                    )
                    parking_events.write(
                        time=t,
                        vehicle_id=veh_id,
                        event="parking_started",
                        logical_parking=logical_target or "",
                        physical_parking=physical_id,
                        old_parking=logical_target or "",
                        new_parking=physical_id,
                        reason="stop_started",
                        parking_duration=f"{vehicle_parking_duration.get(veh_id, 0):.2f}",
                    )
                    if person_manager is not None:
                        person_manager.spawn_parked_occupant(veh_id, physical_id, t)

            if hasattr(traci.simulation, "getStopEndingVehiclesIDList"):
                for veh_id in traci.simulation.getStopEndingVehiclesIDList():
                    physical_id = vehicle_assignment.get(veh_id)
                    logical_target = tracker.target(veh_id)

                    # Fallback for SUMO versions without stop-start events and
                    # for any reservation that was not observed starting.
                    if veh_id in active_reservations:
                        parking.release(physical_id)
                        active_reservations.discard(veh_id)
                        if physical_id:
                            tracker.mark_parked(
                                veh_id,
                                t,
                                physical_id,
                                logical_target or "",
                                parking.parking_name(logical_target) if logical_target else "",
                            )

                    parking_events.write(
                        time=t,
                        vehicle_id=veh_id,
                        event="parking_ended",
                        logical_parking=logical_target or "",
                        physical_parking=physical_id or "",
                        old_parking=physical_id or "",
                        new_parking="",
                        reason="stop_ended",
                        parking_duration=f"{vehicle_parking_duration.get(veh_id, 0):.2f}" if veh_id in vehicle_parking_duration else "",
                    )

                    completed_parking.add(veh_id)
                    tracker.mark_parking_ended(veh_id, t)
                    vehicle_assignment.pop(veh_id, None)
                    vehicle_parking_duration.pop(veh_id, None)

                    if logical_target:
                        no_available_logged.discard((veh_id, logical_target))

            # A vehicle with no assigned stop can reach its generated route
            # endpoint while the whole logical lot is full. Preserve that as
            # an explicit capacity outcome rather than leaving it "active".
            for veh_id in traci.simulation.getArrivedIDList():
                if veh_id in completed_parking or veh_id in vehicle_assignment:
                    continue
                logical_target = tracker.target(veh_id)
                if not logical_target or logical_target not in parking.groups:
                    continue
                tracker.mark_unserved(veh_id, t)
                parking_events.write(
                    time=t,
                    vehicle_id=veh_id,
                    event="parking_unserved",
                    logical_parking=logical_target,
                    physical_parking="",
                    old_parking=logical_target,
                    new_parking="",
                    reason="logical_parking_full_before_route_arrival",
                    parking_duration="",
                )

            if (
                recovery_enabled
                and recovery_max_attempts > 0
                and t - last_checkpoint_time >= recovery_checkpoint_interval
            ):
                traci.simulation.saveState(str(recovery_state_path))
                controller_checkpoint = capture_controller_state(t)
                last_checkpoint_time = t

        if progress_file is not None:
            _write_progress(
                progress_file,
                simulated_seconds=max(
                    traci.simulation.getTime() - simulation_begin,
                    0.0,
                ),
                progress_percent=100.0,
                phase="completed",
                planned_agents=planned_agents,
                completed_agents=planned_agents,
                remaining_agents=0,
                active_agents=0,
            )
    except Exception as exc:
        controller_error = f"{type(exc).__name__}: {exc}"
        diagnostics = _write_sumo_process_diagnostics(
            sumo_process_path,
            sumo_process,
            phase="controller_exception",
            controller_error=controller_error,
            wait_for_exit=True,
        )
        process_message = _format_sumo_process_diagnostics(diagnostics)
        print(f"SUMO process exit diagnostics: {process_message}", flush=True)
        if isinstance(exc, traci.exceptions.FatalTraCIError):
            raise RuntimeError(
                f"{process_message} TraCI reported: {exc}"
            ) from exc
        raise
    finally:
        tracker.finalize(last_simulation_time)
        try:
            traci.close()
        except Exception as close_error:
            print(f"TraCI close warning: {close_error}", flush=True)
        if fast_pedestrian_detector is not None and controller_error is None:
            pedestrian_output = out_dir / "detectors" / "e2_pedestrians.xml"
            fast_pedestrian_detector.write_e2_xml(
                pedestrian_output,
                simulation_begin=simulation_begin,
                simulation_end=max(simulation_end, last_simulation_time),
            )
            print(
                "Fast pedestrian compatibility detector wrote "
                f"{fast_pedestrian_detector.total_entries} entries to "
                f"{pedestrian_output}",
                flush=True,
            )
        final_diagnostics = _write_sumo_process_diagnostics(
            sumo_process_path,
            sumo_process,
            phase="failed" if controller_error else "completed",
            controller_error=controller_error,
            wait_for_exit=True,
        )
        print(
            "Final SUMO process diagnostics: "
            + _format_sumo_process_diagnostics(final_diagnostics),
            flush=True,
        )
        parking_events.close()
        occupancy_log.close()
        person_events.close()
        recovery_events.close()
        tracker.write_search_times(out_dir / "search_times.csv")
        tracker.write_trip_segments(out_dir / "vehicle_trip_segments.csv")
        print(f"Wrote outputs to {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--progress-file", type=Path, required=True)
    parser.add_argument("--sumocfg", type=Path, required=True)
    parser.add_argument("--parking-config", type=Path, required=True)
    parser.add_argument("--vehicle-plan", type=Path, required=True)
    parser.add_argument("--person-access-config", type=Path)
    parser.add_argument("--person-plan", type=Path)
    parser.add_argument("--detector-snapshot", type=Path)
    args = parser.parse_args()

    config_path = args.config
    if not config_path.is_absolute():
        config_path = BACKEND_ROOT / config_path
    
    run(
        config_path.resolve(),
        output_dir=args.output_dir,
        progress_file=args.progress_file,
        sumocfg_path=args.sumocfg,
        parking_config_path=args.parking_config,
        vehicle_plan_path=args.vehicle_plan,
        person_access_config_path=args.person_access_config,
        person_plan_path=args.person_plan,
        detector_snapshot_path=args.detector_snapshot,
    )
