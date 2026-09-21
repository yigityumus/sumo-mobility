#!/usr/bin/env python3
"""Generate SUMO demand files for one model simulation run."""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from statistics import NormalDist
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

import yaml
import sumolib

from domain.demand.fourier import configurable_departure_times
from sumo.parking_choice import parking_choice_config, rank_parking_candidates

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def indent(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "    "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "    "
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def period_from_rate(rate_per_hour: float) -> float:
    if rate_per_hour <= 0:
        raise ValueError("rate_per_hour must be > 0")
    return 3600.0 / rate_per_hour


def distributed_departure_times(
    total: int,
    begin: float,
    end: float,
    model: str,
    parameters: dict | None = None,
) -> list[float]:
    """Return deterministic departure times whose density matches the selected model."""
    if total <= 0:
        return []
    if end <= begin:
        raise ValueError("simulation end must be greater than begin")

    quantiles = [(index + 0.5) / total for index in range(total)]
    if model == "constant":
        normalized_times = quantiles
    elif model == "linear":
        # A linearly increasing rate has CDF F(t) = t² and inverse sqrt(F).
        normalized_times = [math.sqrt(quantile) for quantile in quantiles]
    elif model == "normal":
        # Center the bell curve at half-time and keep it within ±3σ of the run.
        distribution = NormalDist()
        lower_cdf = distribution.cdf(-3)
        cdf_span = distribution.cdf(3) - lower_cdf
        normalized_times = [
            0.5 + distribution.inv_cdf(lower_cdf + quantile * cdf_span) / 6
            for quantile in quantiles
        ]
    elif model == "fourier":
        parameters = parameters or {}
        return configurable_departure_times(
            total,
            begin,
            end,
            peak_count=int(parameters.get("peak_count", 2)),
            peak_width_hours=float(parameters.get("peak_width_hours", 1.5)),
            harmonics=int(parameters.get("harmonics", 6)),
            peak_heights=parameters.get("peak_heights"),
        )
    else:
        raise ValueError(f"Unsupported traffic model: {model}")

    duration = end - begin
    return [begin + duration * value for value in normalized_times]


def _pedestrian_origin_sequence(
    total: int,
    origins: list[dict],
    requested_source_counts: dict | None,
    rng: random.Random,
) -> list[dict]:
    """Choose origins while honoring exact per-source pedestrian totals."""
    origins_by_mode: dict[str, list[dict]] = {}
    mode_weights: dict[str, float] = {}
    for origin in origins:
        mode = str(origin.get("mode") or "pedestrian")
        origins_by_mode.setdefault(mode, []).append(origin)
        mode_weights[mode] = max(float(origin.get("weight", 1)), 0)
    if not origins_by_mode:
        raise ValueError("Pedestrian demand requires at least one resolved origin.")

    if isinstance(requested_source_counts, dict):
        mode_counts = {
            "residential": int(requested_source_counts.get("residential", 0)),
            "public_transport": int(
                requested_source_counts.get("public_transport", 0)
            ),
        }
        if any(count < 0 for count in mode_counts.values()):
            raise ValueError("Pedestrian source counts cannot be negative.")
        if sum(mode_counts.values()) != total:
            raise ValueError(
                "Residential and public-transport source counts must add up to "
                f"the pedestrian total ({sum(mode_counts.values())} != {total})."
            )
        for mode, count in mode_counts.items():
            if count > 0 and not origins_by_mode.get(mode):
                raise ValueError(
                    f"Pedestrian source '{mode}' requested {count} people but has "
                    "no resolved, routable origin."
                )
    else:
        # Historical scenarios distributed pedestrians using origin weights.
        if not any(mode_weights.values()):
            mode_weights = {mode: 1.0 for mode in origins_by_mode}
        weight_total = sum(mode_weights.values())
        exact_counts = {
            mode: total * mode_weights[mode] / weight_total
            for mode in origins_by_mode
        }
        mode_counts = {mode: int(value) for mode, value in exact_counts.items()}
        remaining = total - sum(mode_counts.values())
        remainder_order = sorted(
            origins_by_mode,
            key=lambda mode: (-(exact_counts[mode] - mode_counts[mode]), mode),
        )
        for mode in remainder_order[:remaining]:
            mode_counts[mode] += 1

    sequence = [
        rng.choice(origins_by_mode[mode])
        for mode in sorted(mode_counts)
        for _ in range(mode_counts[mode])
    ]
    rng.shuffle(sequence)
    return sequence


def _vehicle_origin_sequence(total: int, origins: list[dict]) -> list[dict]:
    """Distribute exact per-origin counts smoothly across the departure window."""
    if total <= 0:
        return []
    if not origins:
        raise ValueError("Vehicle demand requires at least one generation point.")
    has_explicit_counts = ["vehicle_count" in origin for origin in origins]
    if not any(has_explicit_counts):
        return [origins[index % len(origins)] for index in range(total)]
    if not all(has_explicit_counts):
        raise ValueError("Every vehicle generation point must have an allocation count.")

    counts = [int(origin.get("vehicle_count") or 0) for origin in origins]
    if any(count < 0 for count in counts):
        raise ValueError("Vehicle generation point allocation counts cannot be negative.")
    if sum(counts) != total:
        raise ValueError(
            "Vehicle generation point allocation counts must add up to vehicle demand "
            f"({sum(counts)} != {total})."
        )

    scheduled = [
        ((allocation_index + 0.5) / count, origin_index, allocation_index)
        for origin_index, count in enumerate(counts)
        for allocation_index in range(count)
    ]
    scheduled.sort()
    return [origins[origin_index] for _, origin_index, _ in scheduled]


def write_xml(path: Path, root: ET.Element) -> None:
    indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def _resolve_path(path: Path) -> Path:
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (BACKEND_ROOT / path).resolve()


def _parking_report_path(parking: dict) -> Path:
    direct_value = parking.get("report_path")
    if not direct_value:
        raise ValueError(
            f"Parking area '{parking.get('id', '<unknown>')}' has no "
            "report_path"
        )
    return _resolve_path(Path(str(direct_value)))


def generate(
    config_path: Path,
    *,
    parking_config_path: Path,
    network_path: Path | None,
    person_access_config_path: Path | None,
    passenger_out: Path,
    pedestrian_out: Path,
    plan_out: Path,
    person_plan_out: Path | None,
) -> None:
    config_path = _resolve_path(config_path)
    cfg = yaml.safe_load(config_path.read_text())
    sim = cfg["simulation"]
    begin = float(sim.get("begin", 0))
    end = float(sim["end"])
    parking_duration = str(cfg.get("controller", {}).get("parking_duration", 300))

    passenger_out = _resolve_path(passenger_out)
    pedestrian_out = _resolve_path(pedestrian_out)
    plan_out = _resolve_path(plan_out)
    person_plan_out = _resolve_path(person_plan_out) if person_plan_out else None

    demand_totals = cfg.get("demand_totals")
    traffic_models = cfg.get("traffic_models") or {}
    traffic_model_parameters = cfg.get("traffic_model_parameters") or {}
    car_period = period_from_rate(cfg["rates"]["cars_per_hour_per_point"])
    ped_period = period_from_rate(cfg["rates"]["pedestrians_per_hour_per_point"])

    parking_config_path = _resolve_path(parking_config_path)
    network_path = _resolve_path(network_path) if network_path else None

    person_based_demand = bool(cfg.get("person_based_demand"))
    person_access = None
    buildings: list[dict] = []
    pedestrian_origins: list[dict] = []
    if person_based_demand:
        if person_access_config_path is None or person_plan_out is None:
            raise ValueError(
                "Person-based demand requires --person-access-config and --person-plan-output."
            )
        person_access_config_path = _resolve_path(person_access_config_path)
        person_access = json.loads(person_access_config_path.read_text(encoding="utf-8"))
        buildings = person_access.get("buildings") or []
        pedestrian_origins = person_access.get("origins") or []
        if not buildings:
            raise ValueError("Person-based demand requires at least one resolved building destination.")

    parking_config = yaml.safe_load(
        parking_config_path.read_text(encoding="utf-8")
    ) or {}
    routing_overrides = cfg.get("parking_routing_edges") or {}

    parking_areas = [
        parking
        for parking in parking_config.get("parking_areas", [])
        if parking.get("enabled", True)
    ]

    accessible_logical_ids: set[str] | None = None
    if person_based_demand:
        accessible_logical_ids = {
            str(value)
            for value in person_access.get("accessible_logical_parking_ids") or []
        }
        parking_areas = [
            parking
            for parking in parking_areas
            if str(parking.get("id")) in accessible_logical_ids
        ]

    if not parking_areas and int((demand_totals or {}).get("vehicles", 0)) > 0:
        raise ValueError(f"No enabled parking areas found in {parking_config_path}")

    parking_assignment = cfg.get("parking_assignment") or {}
    configured_targets = parking_assignment.get("targets") or []
    if configured_targets:
        target_ids = {
            str(target.get("parking_id") or target.get("id"))
            if isinstance(target, dict)
            else str(target)
            for target in configured_targets
        }
        if accessible_logical_ids is not None:
            target_ids &= accessible_logical_ids
        parking_areas = [
            parking for parking in parking_areas
            if str(parking.get("id")) in target_ids
        ]
        missing_targets = target_ids - {str(parking.get("id")) for parking in parking_areas}
        if missing_targets:
            raise ValueError(f"Unknown or disabled parking assignment targets: {sorted(missing_targets)}")

    for parking in parking_areas:
        metadata_path = _parking_report_path(parking).with_suffix(".metadata.json")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Parking lane metadata is missing or invalid for {parking.get('id')}: "
                f"run the parking generator first ({metadata_path})."
            ) from exc
        routing_edges = (
            routing_overrides.get(str(parking.get("id")))
            or metadata.get("routing_edge_ids")
            or metadata.get("parking_edge_ids")
        )
        if not isinstance(routing_edges, list) or not routing_edges:
            raise ValueError(f"Parking area '{parking.get('id')}' has no discovered routing edges")
        parking["_routing_edges"] = [str(edge) for edge in routing_edges]

    random_seed = int(cfg.get("controller", {}).get("random_seed", 42))
    rng = random.Random(random_seed)
    choice_config = parking_choice_config(
        (cfg.get("controller") or {}).get("parking_choice")
    )
    parking_by_id = {str(parking["id"]): parking for parking in parking_areas}
    exact_target_sequence: list[dict] | None = None
    target_counts = parking_assignment.get("target_counts")
    if isinstance(demand_totals, dict) and target_counts is not None:
        if not isinstance(target_counts, dict):
            raise ValueError("parking_assignment.target_counts must be a mapping")
        vehicle_total = int(demand_totals.get("vehicles", 0))
        exact_target_sequence = []
        for parking_id, requested_count in target_counts.items():
            parking_id = str(parking_id)
            if parking_id not in parking_by_id:
                raise ValueError(f"Unknown parking target in target_counts: {parking_id}")
            count = int(requested_count)
            if count < 0:
                raise ValueError(f"Parking target count cannot be negative: {parking_id}")
            exact_target_sequence.extend([parking_by_id[parking_id]] * count)
        if len(exact_target_sequence) != vehicle_total:
            raise ValueError(
                "parking_assignment.target_counts must add up to demand_totals.vehicles "
                f"({len(exact_target_sequence)} != {vehicle_total})"
            )
        rng.shuffle(exact_target_sequence)

    # Passenger route file
    routes = ET.Element("routes")
    vt = cfg.get("vehicle_types", {}).get("passenger", {"id": "passenger", "vClass": "passenger"})
    ET.SubElement(routes, "vType", {k: str(v) for k, v in vt.items()})

    plan_rows: list[dict[str, str]] = []
    person_plan_rows: list[dict[str, str | float]] = []
    person_plan_by_vehicle: dict[str, dict[str, str | float]] = {}
    trip_rows: list[dict[str, Any]] = []

    car_generation_points = cfg.get("car_generation_points", [])
    vehicle_network = (
        sumolib.net.readNet(str(network_path))
        if network_path is not None
        else None
    )
    driving_route_cache: dict[tuple[str, str], tuple[float, str] | None] = {}

    def driving_route(from_edge_id: str, parking_id: str) -> tuple[float, str] | None:
        key = (from_edge_id, parking_id)
        if key in driving_route_cache:
            return driving_route_cache[key]
        if vehicle_network is None:
            destination = parking_by_id[parking_id]["_routing_edges"][0]
            result = (0.0, destination)
            driving_route_cache[key] = result
            return result
        try:
            source_edge = vehicle_network.getEdge(from_edge_id)
        except KeyError:
            driving_route_cache[key] = None
            return None
        routes: list[tuple[float, str]] = []
        for destination_id in parking_by_id[parking_id]["_routing_edges"]:
            try:
                destination_edge = vehicle_network.getEdge(destination_id)
                route, distance = vehicle_network.getShortestPath(
                    source_edge,
                    destination_edge,
                    vClass="passenger",
                )
            except KeyError:
                continue
            if route is not None and distance is not None:
                routes.append((float(distance), destination_id))
        result = min(routes, key=lambda item: (item[0], item[1])) if routes else None
        driving_route_cache[key] = result
        return result

    def choose_building(mode: str, candidates: list[dict] | None = None) -> dict:
        candidate_buildings = buildings if candidates is None else candidates
        if mode == "vehicle" and person_based_demand:
            candidate_buildings = [
                building
                for building in candidate_buildings
                if building.get("parking_candidates")
            ]
            if not candidate_buildings:
                raise ValueError(
                    "No selected destination building is reachable on foot from "
                    "a selected parking area."
                )
        weight_key = "vehicle_weight" if mode == "vehicle" else "pedestrian_weight"
        weights = [max(float(building.get(weight_key, 0)), 0) for building in candidate_buildings]
        if not any(weights):
            weights = [1.0] * len(candidate_buildings)
        return rng.choices(candidate_buildings, weights=weights, k=1)[0]

    def append_vehicle_trip(gen: dict, index: int, depart_time: float) -> None:
        generation_point_id = str(gen["id"])
        from_edge = str(gen["from_edge"])
        vehicle_id = f"{generation_point_id}.{index}"
        if person_based_demand:
            routable_buildings = [
                building
                for building in buildings
                if any(
                    str(candidate.get("parking_id")) in parking_by_id
                    and driving_route(
                        from_edge,
                        str(candidate.get("parking_id")),
                    ) is not None
                    for candidate in building.get("parking_candidates") or []
                )
            ]
            if not routable_buildings:
                raise ValueError(
                    f"No destination building has parking reachable by car from "
                    f"generation point '{generation_point_id}'."
                )
            destination_building = choose_building("vehicle", routable_buildings)
        else:
            destination_building = None
        if destination_building is not None:
            parking_candidates = [
                dict(candidate)
                for candidate in destination_building.get("parking_candidates") or []
                if str(candidate.get("parking_id")) in parking_by_id
            ]
            if not parking_candidates:
                raise ValueError(
                    f"Destination building '{destination_building.get('name')}' has no "
                    "reachable selected parking area."
                )
            routable_candidates: list[dict[str, Any]] = []
            for candidate in parking_candidates:
                parking_id = str(candidate["parking_id"])
                route = driving_route(from_edge, parking_id)
                if route is None:
                    continue
                candidate["driving_distance_metres"] = round(route[0], 3)
                candidate["initial_destination_edge"] = route[1]
                routable_candidates.append(candidate)
            ranked_candidates = rank_parking_candidates(
                vehicle_id,
                routable_candidates,
                config=choice_config,
                seed=random_seed,
                decision_index=0,
            )
            if not ranked_candidates:
                raise ValueError(
                    f"Destination building '{destination_building.get('name')}' has no "
                    f"parking area reachable by car from generation point '{generation_point_id}'."
                )
            parking_candidates = []
            for rank, candidate in enumerate(ranked_candidates, start=1):
                parking_candidates.append({
                    **candidate,
                    "initial_choice_rank": rank,
                })
            selected_candidate = parking_candidates[0]
            selected_parking = parking_by_id[str(selected_candidate["parking_id"])]
        else:
            selected_parking = (
                exact_target_sequence[index]
                if exact_target_sequence is not None
                else rng.choice(parking_areas)
            )
            parking_candidates = [{
                "parking_id": str(selected_parking["id"]),
                "distance_metres": None,
            }]
        parking_id = str(selected_parking["id"])
        destination_edge = str(
            parking_candidates[0].get("initial_destination_edge")
            or rng.choice(selected_parking["_routing_edges"])
        )
        trip_rows.append({
            "vehicle_id": vehicle_id,
            "generation_point": generation_point_id,
            "depart": depart_time,
            "from_edge": from_edge,
            "depart_lane": gen.get("depart_lane"),
            "depart_position": gen.get("depart_position"),
            "to_edge": destination_edge,
            "parking_id": parking_id,
            "parking_candidates": parking_candidates,
        })
        if destination_building is not None:
            person_plan = {
                "person_id": f"person.{vehicle_id}",
                "vehicle_id": vehicle_id,
                "arrival_mode": "vehicle",
                "building_id": str(destination_building["id"]),
                "building_name": str(destination_building["name"]),
                "destination_edge": str(destination_building["pedestrian_edge_id"]),
                "destination_lane": str(destination_building["pedestrian_lane_id"]),
                "destination_position": float(destination_building["arrival_position"]),
            }
            person_plan_rows.append(person_plan)
            person_plan_by_vehicle[vehicle_id] = person_plan

    if isinstance(demand_totals, dict):
        vehicle_total = int(demand_totals.get("vehicles", 0))
        if vehicle_total and not car_generation_points:
            raise ValueError("Vehicle demand was requested, but no car_generation_points are configured.")
        vehicle_departures = distributed_departure_times(
            vehicle_total,
            begin,
            end,
            str(traffic_models.get("vehicles", "linear")),
            traffic_model_parameters.get("vehicles") or {},
        )
        vehicle_origins = _vehicle_origin_sequence(
            vehicle_total,
            car_generation_points,
        )
        for index, (depart_time, generation_point) in enumerate(
            zip(vehicle_departures, vehicle_origins, strict=True)
        ):
            append_vehicle_trip(generation_point, index, depart_time)
    else:
        for gen in car_generation_points:
            vehicle_count = int(math.ceil((end - begin) / car_period))
            for index in range(vehicle_count):
                depart_time = begin + index * car_period
                if depart_time >= end:
                    break
                append_vehicle_trip(gen, index, depart_time)

    # SUMO route files must be ordered by departure time.
    trip_rows.sort(
        key=lambda row: (
            float(row["depart"]),
            str(row["vehicle_id"]),
        )
    )

    for trip in trip_rows:
        depart_time = float(trip["depart"])

        trip_attributes = {
            "id": str(trip["vehicle_id"]),
            "type": str(vt.get("id", "passenger")),
            "depart": str(
                int(depart_time)
                if depart_time.is_integer()
                else depart_time
            ),
            "from": str(trip["from_edge"]),
            "to": str(trip["to_edge"]),
        }
        if trip.get("depart_lane") is not None:
            trip_attributes["departLane"] = str(trip["depart_lane"])
        if trip.get("depart_position") is not None:
            trip_attributes["departPos"] = str(trip["depart_position"])
        ET.SubElement(routes, "trip", trip_attributes)

        plan_rows.append(
            {
                "vehicle_id": str(trip["vehicle_id"]),
                "generation_point": str(
                    trip["generation_point"]
                ),
                "initial_parking": str(trip["parking_id"]),
                "final_activity": str(
                    person_plan_by_vehicle.get(str(trip["vehicle_id"]), {}).get(
                        "building_id",
                        "synthetic_destination",
                    )
                ),
                "parking_candidates_json": json.dumps(
                    trip.get("parking_candidates") or [],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        )


    write_xml(passenger_out, routes)

    # Pedestrian route file
    persons = ET.Element("routes")
    pedestrian_type_id = "campus_pedestrian"
    ET.SubElement(persons, "vType", {
        "id": pedestrian_type_id,
        "vClass": "pedestrian",
        "guiShape": "pedestrian",
        "color": "255,128,0",
        "length": "1.0",
        "width": "0.6",
    })
    pedestrian_generation_points = cfg.get("pedestrian_generation_points", [])
    if isinstance(demand_totals, dict):
        pedestrian_total = int(demand_totals.get("pedestrians", 0))
        if pedestrian_total and person_based_demand and not pedestrian_origins:
            raise ValueError(
                "Pedestrian demand was requested, but no residential or public-transport origins were resolved."
            )
        if pedestrian_total and not person_based_demand and not pedestrian_generation_points:
            raise ValueError(
                "Pedestrian demand was requested, but no pedestrian_generation_points are configured."
            )
        pedestrian_departures = distributed_departure_times(
            pedestrian_total,
            begin,
            end,
            str(traffic_models.get("pedestrians", "linear")),
            traffic_model_parameters.get("pedestrians") or {},
        )
        origin_sequence = (
            _pedestrian_origin_sequence(
                pedestrian_total,
                pedestrian_origins,
                cfg.get("pedestrian_source_counts"),
                rng,
            )
            if person_based_demand and pedestrian_total
            else []
        )
        building_by_id = {str(building["id"]): building for building in buildings}
        for index, depart_time in enumerate(pedestrian_departures):
            gen = (
                pedestrian_generation_points[index % len(pedestrian_generation_points)]
                if not person_based_demand
                else None
            )
            origin = origin_sequence[index] if person_based_demand else None
            if origin is not None:
                reachable_buildings = [
                    building_by_id[building_id]
                    for building_id in origin.get("reachable_destination_ids") or []
                    if building_id in building_by_id
                ]
                if not reachable_buildings:
                    raise ValueError(
                        f"Pedestrian origin '{origin.get('name')}' has no reachable destination buildings."
                    )
                destination_building = choose_building("pedestrian", reachable_buildings)
                destination_accesses = destination_building.get("pedestrian_accesses") or [destination_building]
                origin_component_id = origin.get("pedestrian_component_id")
                destination_access = (
                    next(
                        access
                        for access in destination_accesses
                        if str(access.get("pedestrian_component_id")) == str(origin_component_id)
                    )
                    if origin_component_id is not None
                    else destination_accesses[0]
                )
            else:
                destination_building = None
                destination_access = None
            person_id = f"walk.person.{index}" if person_based_demand else f"{gen['id']}.{index}"
            person_attributes = {
                "id": person_id,
                "depart": str(int(depart_time) if depart_time.is_integer() else depart_time),
                "type": pedestrian_type_id,
            }
            if destination_building is not None:
                person_attributes["departPos"] = str(origin["departure_position"])
            person = ET.SubElement(persons, "person", person_attributes)
            if destination_building is None:
                ET.SubElement(person, "walk", {"from": gen["from_edge"], "to": gen["to_edge"]})
            else:
                ET.SubElement(person, "walk", {
                    "from": str(origin["pedestrian_edge_id"]),
                    "to": str(destination_access["pedestrian_edge_id"]),
                    "arrivalPos": str(destination_access["arrival_position"]),
                })
                person_plan_rows.append({
                    "person_id": person_id,
                    "vehicle_id": "",
                    "arrival_mode": "pedestrian",
                    "origin_mode": str(origin["mode"]),
                    "origin_id": str(origin["id"]),
                    "origin_name": str(origin["name"]),
                    "origin_source_type": str(origin.get("source_type") or "legacy_building"),
                    "origin_building_id": str(
                        origin.get("building_id")
                        or (origin["id"] if not origin.get("source_type") else "")
                    ),
                    "origin_building_name": str(origin["name"])
                    if origin.get("building_id") or not origin.get("source_type")
                    else "",
                    "building_id": str(destination_building["id"]),
                    "building_name": str(destination_building["name"]),
                    "destination_edge": str(destination_access["pedestrian_edge_id"]),
                    "destination_lane": str(destination_access["pedestrian_lane_id"]),
                    "destination_position": float(destination_access["arrival_position"]),
                })
    else:
        for gen in pedestrian_generation_points:
            pf = ET.SubElement(persons, "personFlow", {
                "id": gen["id"],
                "begin": str(begin),
                "end": str(end),
                "period": str(int(ped_period) if ped_period.is_integer() else ped_period),
            })
            ET.SubElement(pf, "walk", {"from": gen["from_edge"], "to": gen["to_edge"]})
    write_xml(pedestrian_out, persons)

    plan_out.parent.mkdir(parents=True, exist_ok=True)
    with plan_out.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "vehicle_id",
                "generation_point",
                "initial_parking",
                "final_activity",
                "parking_candidates_json",
            ],
        )
        writer.writeheader()
        writer.writerows(plan_rows)

    if person_plan_out is not None:
        person_plan_out.parent.mkdir(parents=True, exist_ok=True)
        with person_plan_out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "person_id",
                    "vehicle_id",
                    "arrival_mode",
                    "origin_mode",
                    "origin_id",
                    "origin_name",
                    "origin_source_type",
                    "origin_building_id",
                    "origin_building_name",
                    "building_id",
                    "building_name",
                    "destination_edge",
                    "destination_lane",
                    "destination_position",
                ],
            )
            writer.writeheader()
            writer.writerows(person_plan_rows)

    print(f"Wrote {passenger_out}")
    print(f"Wrote {pedestrian_out}")
    print(f"Wrote {plan_out}")
    if person_plan_out is not None:
        print(f"Wrote {person_plan_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--parking-config", type=Path, required=True)
    parser.add_argument("--network", type=Path)
    parser.add_argument("--person-access-config", type=Path)
    parser.add_argument("--passenger-output", type=Path, required=True)
    parser.add_argument("--pedestrian-output", type=Path, required=True)
    parser.add_argument("--plan-output", type=Path, required=True)
    parser.add_argument("--person-plan-output", type=Path)
    args = parser.parse_args()
    generate(
        args.config,
        parking_config_path=args.parking_config,
        network_path=args.network,
        person_access_config_path=args.person_access_config,
        passenger_out=args.passenger_output,
        pedestrian_out=args.pedestrian_output,
        plan_out=args.plan_output,
        person_plan_out=args.person_plan_output,
    )
