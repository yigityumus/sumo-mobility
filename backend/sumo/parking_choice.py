"""Behavioral parking choice shared by demand generation and the controller.

The model is intentionally independent from TraCI.  Callers provide candidate
attributes and this module applies a reproducible random-utility choice.  The
weights are hypotheses until calibrated against observed parking choices, but
they reproduce the important mechanics of SUMO's parking rerouter: travel and
walking cost, capacity, free-space information, imperfect knowledge,
frustration after failures, and heterogeneous drivers.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any


DEFAULT_PARKING_CHOICE: dict[str, Any] = {
    "model": "weighted_random_utility",
    "walking_speed_metres_per_second": 1.35,
    "assumed_driving_speed_metres_per_second": 8.33,
    "knowledge_probability": 0.50,
    "uninformed_occupancy_mean": 0.60,
    "uninformed_occupancy_stddev": 0.15,
    "frustration_step": 0.35,
    "stochastic_scale": 0.30,
    "weights": {
        "drive_time": 0.8,
        "walk_time": 1.0,
        "capacity": 0.8,
        "absolute_free_space": 1.3,
        "relative_free_space": 1.5,
    },
}


_DRIVER_PROFILES: tuple[tuple[str, dict[str, float]], ...] = (
    (
        "convenience_seeker",
        {
            "share": 0.22,
            "drive_time": 0.9,
            "walk_time": 1.65,
            "capacity": 0.85,
            "availability": 0.8,
            "knowledge": 0.8,
            "noise": 0.9,
        },
    ),
    (
        "risk_averse",
        {
            "share": 0.22,
            "drive_time": 0.9,
            "walk_time": 0.85,
            "capacity": 1.2,
            "availability": 1.55,
            "knowledge": 1.05,
            "noise": 0.75,
        },
    ),
    (
        "informed_commuter",
        {
            "share": 0.20,
            "drive_time": 1.1,
            "walk_time": 1.1,
            "capacity": 0.9,
            "availability": 1.25,
            "knowledge": 2.2,
            "noise": 0.65,
        },
    ),
    (
        "uninformed_visitor",
        {
            "share": 0.18,
            "drive_time": 0.9,
            "walk_time": 0.9,
            "capacity": 1.3,
            "availability": 0.7,
            "knowledge": 0.35,
            "noise": 1.45,
        },
    ),
    (
        "balanced",
        {
            "share": 0.18,
            "drive_time": 1.0,
            "walk_time": 1.0,
            "capacity": 1.0,
            "availability": 1.0,
            "knowledge": 1.0,
            "noise": 1.0,
        },
    ),
)


def parking_choice_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Merge and validate a scenario parking-choice configuration."""
    raw = raw or {}
    config = {**DEFAULT_PARKING_CHOICE, **raw}
    config["weights"] = {
        **DEFAULT_PARKING_CHOICE["weights"],
        **(raw.get("weights") or {}),
    }
    if config["model"] != "weighted_random_utility":
        raise ValueError(
            "Unsupported parking choice model: "
            f"{config['model']}. Expected 'weighted_random_utility'."
        )
    for key in (
        "walking_speed_metres_per_second",
        "assumed_driving_speed_metres_per_second",
    ):
        if float(config[key]) <= 0:
            raise ValueError(f"controller.parking_choice.{key} must be greater than 0")
    for key in ("knowledge_probability", "uninformed_occupancy_mean"):
        value = float(config[key])
        if not 0 <= value <= 1:
            raise ValueError(f"controller.parking_choice.{key} must be between 0 and 1")
    for key in ("uninformed_occupancy_stddev", "frustration_step", "stochastic_scale"):
        if float(config[key]) < 0:
            raise ValueError(f"controller.parking_choice.{key} cannot be negative")
    for key, value in config["weights"].items():
        if float(value) < 0:
            raise ValueError(
                f"controller.parking_choice.weights.{key} cannot be negative"
            )
    return config


def _stable_unit(seed: int, *parts: object) -> float:
    payload = "\x1f".join([str(seed), *(str(part) for part in parts)]).encode()
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return min(max((value + 0.5) / 2**64, 1e-12), 1 - 1e-12)


def _stable_normal(seed: int, *parts: object) -> float:
    first = _stable_unit(seed, *parts, "normal-a")
    second = _stable_unit(seed, *parts, "normal-b")
    return math.sqrt(-2 * math.log(first)) * math.cos(2 * math.pi * second)


def driver_profile(vehicle_id: str, seed: int) -> tuple[str, dict[str, float]]:
    value = _stable_unit(seed, vehicle_id, "driver-profile")
    cumulative = 0.0
    for name, profile in _DRIVER_PROFILES:
        cumulative += profile["share"]
        if value <= cumulative:
            return name, profile
    return _DRIVER_PROFILES[-1]


def _normalised(values: list[float], *, larger_is_better: bool) -> list[float]:
    if not values:
        return []
    low = min(values)
    span = max(values) - low
    if span <= 1e-12:
        return [0.5] * len(values)
    normalised = [(value - low) / span for value in values]
    return normalised if larger_is_better else [1 - value for value in normalised]


def rank_parking_candidates(
    vehicle_id: str,
    candidates: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    seed: int = 42,
    decision_index: int = 0,
    failed_attempts: int = 0,
) -> list[dict[str, Any]]:
    """Return eligible candidates from most to least attractive.

    A Gumbel error term turns utility maximisation into a reproducible
    multinomial-logit draw.  Remote occupancy is exact only for drivers who
    know it; local/pass-by observations can set ``occupancy_visible``.
    """
    if not candidates:
        return []
    cfg = parking_choice_config(config)
    profile_name, profile = driver_profile(vehicle_id, seed)
    knowledge = min(
        1.0,
        float(cfg["knowledge_probability"]) * profile["knowledge"]
        + failed_attempts * float(cfg["frustration_step"]),
    )
    walk_speed = float(cfg["walking_speed_metres_per_second"])
    drive_speed = float(cfg["assumed_driving_speed_metres_per_second"])

    prepared: list[dict[str, Any]] = []
    for candidate in candidates:
        parking_id = str(candidate.get("parking_id") or "")
        if not parking_id:
            continue
        capacity = max(int(candidate.get("total_capacity") or 1), 1)
        free_value = candidate.get("free_spaces")
        actual_free = (
            min(max(int(free_value), 0), capacity)
            if free_value is not None
            else None
        )
        visible = bool(candidate.get("occupancy_visible", False))
        occupancy_known = visible or (
            actual_free is not None
            and _stable_unit(
                seed,
                vehicle_id,
                decision_index,
                parking_id,
                "knowledge",
            ) < knowledge
        )
        if occupancy_known and actual_free == 0:
            continue
        if occupancy_known and actual_free is not None:
            perceived_free = actual_free
        else:
            occupancy = float(cfg["uninformed_occupancy_mean"]) + (
                float(cfg["uninformed_occupancy_stddev"])
                * _stable_normal(
                    seed,
                    vehicle_id,
                    parking_id,
                    "perceived-occupancy",
                )
            )
            occupancy = min(max(occupancy, 0.05), 0.98)
            perceived_free = max(round(capacity * (1 - occupancy)), 1)

        drive_seconds_value = candidate.get("drive_time_seconds")
        if drive_seconds_value is None:
            driving_distance = candidate.get("driving_distance_metres")
            drive_seconds = (
                float(driving_distance) / drive_speed
                if driving_distance is not None
                else 0.0
            )
        else:
            drive_seconds = max(float(drive_seconds_value), 0.0)
        walk_seconds = max(
            float(candidate.get("distance_metres") or 0.0) / walk_speed,
            0.0,
        )
        prepared.append(
            {
                **candidate,
                "parking_id": parking_id,
                "total_capacity": capacity,
                "drive_time_seconds": drive_seconds,
                "walk_time_seconds": walk_seconds,
                "actual_free_spaces": actual_free,
                "perceived_free_spaces": perceived_free,
                "perceived_free_ratio": perceived_free / capacity,
                "occupancy_known": occupancy_known,
                "driver_profile": profile_name,
            }
        )

    if not prepared:
        return []

    drive_scores = _normalised(
        [float(item["drive_time_seconds"]) for item in prepared],
        larger_is_better=False,
    )
    walk_scores = _normalised(
        [float(item["walk_time_seconds"]) for item in prepared],
        larger_is_better=False,
    )
    capacity_scores = _normalised(
        [math.log1p(int(item["total_capacity"])) for item in prepared],
        larger_is_better=True,
    )
    absolute_free_scores = _normalised(
        [math.log1p(int(item["perceived_free_spaces"])) for item in prepared],
        larger_is_better=True,
    )
    relative_free_scores = _normalised(
        [float(item["perceived_free_ratio"]) for item in prepared],
        larger_is_better=True,
    )
    weights = cfg["weights"]
    availability_multiplier = profile["availability"] * (
        1 + failed_attempts * float(cfg["frustration_step"])
    )
    inconvenience_multiplier = 1 / (1 + failed_attempts * 0.08)

    for index, item in enumerate(prepared):
        systematic_utility = (
            float(weights["drive_time"])
            * profile["drive_time"]
            * inconvenience_multiplier
            * drive_scores[index]
            + float(weights["walk_time"])
            * profile["walk_time"]
            * inconvenience_multiplier
            * walk_scores[index]
            + float(weights["capacity"])
            * profile["capacity"]
            * capacity_scores[index]
            + float(weights["absolute_free_space"])
            * availability_multiplier
            * absolute_free_scores[index]
            + float(weights["relative_free_space"])
            * availability_multiplier
            * relative_free_scores[index]
        )
        random_unit = _stable_unit(
            seed,
            vehicle_id,
            decision_index,
            item["parking_id"],
            "choice-error",
        )
        gumbel_error = -math.log(-math.log(random_unit))
        item["systematic_utility"] = round(systematic_utility, 6)
        item["choice_utility"] = round(
            systematic_utility
            + float(cfg["stochastic_scale"]) * profile["noise"] * gumbel_error,
            6,
        )

    return sorted(
        prepared,
        key=lambda item: (-float(item["choice_utility"]), item["parking_id"]),
    )
