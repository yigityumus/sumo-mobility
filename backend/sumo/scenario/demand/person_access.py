#!/usr/bin/env python3
"""Resolve selected buildings and parking areas to pedestrian network access points."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import sumolib
from sumolib import geomhelper
import yaml


MAX_PERSON_ACCESS_DISTANCE_METRES = 50.0
SMALL_PARKING_MAX_CAPACITY = 16
MEDIUM_PARKING_MAX_CAPACITY = 80


def _parking_capacity_band(total_capacity: int) -> tuple[str, int]:
    if total_capacity > MEDIUM_PARKING_MAX_CAPACITY:
        return "large", 0
    if total_capacity > SMALL_PARKING_MAX_CAPACITY:
        return "medium", 1
    return "small", 2


def _coordinates(geometry: dict) -> list[tuple[float, float]]:
    kind = geometry.get("type")
    values = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [(float(point[0]), float(point[1])) for ring in values for point in ring]
    if kind == "MultiPolygon":
        return [(float(point[0]), float(point[1])) for polygon in values for ring in polygon for point in ring]
    if kind == "Point" and len(values) >= 2:
        return [(float(values[0]), float(values[1]))]
    return []


def _feature_point(feature: dict) -> tuple[float, float]:
    points = _coordinates(feature.get("geometry") or {})
    if not points:
        raise ValueError(f"Building {feature.get('id', '<unknown>')} has no usable coordinates")
    # An average of boundary vertices is stable and adequate as a seed for
    # snapping to the nearest sidewalk. The actual destination is the snapped lane.
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _feature_id(feature: dict) -> str:
    if feature.get("id") is not None:
        return str(feature["id"])
    properties = feature.get("properties") or {}
    osm_type = properties.get("osm_type") or properties.get("type") or "way"
    osm_id = properties.get("osm_id") or properties.get("id")
    return f"{osm_type}/{osm_id}" if osm_id is not None else ""


def _feature_name(feature: dict) -> str:
    properties = feature.get("properties") or {}
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else {}
    return str(properties.get("name") or tags.get("name") or _feature_id(feature) or "Unnamed building")


def _feature_tags(feature: dict) -> dict:
    properties = feature.get("properties") or {}
    tags = properties.get("tags")
    return tags if isinstance(tags, dict) else properties


def _building_levels(feature: dict) -> float:
    """Return OSM building:levels, defaulting missing legacy data to one level."""
    raw_value = _feature_tags(feature).get("building:levels", 1)
    try:
        levels = float(str(raw_value).strip())
    except (TypeError, ValueError):
        return 1.0
    return levels if math.isfinite(levels) and levels >= 0 else 1.0


def _ring_area_square_metres(ring: list) -> float:
    coordinates = [
        (float(point[0]), float(point[1]))
        for point in ring
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    if len(coordinates) < 3:
        return 0.0

    earth_radius_m = 6_371_008.8
    reference_lon = sum(point[0] for point in coordinates) / len(coordinates)
    reference_lat = sum(point[1] for point in coordinates) / len(coordinates)
    cos_latitude = math.cos(math.radians(reference_lat))
    projected = [
        (
            earth_radius_m * math.radians(longitude - reference_lon) * cos_latitude,
            earth_radius_m * math.radians(latitude - reference_lat),
        )
        for longitude, latitude in coordinates
    ]
    return abs(sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(projected, projected[1:] + projected[:1])
    )) / 2


def _polygon_area_square_metres(rings: list) -> float:
    if not rings:
        return 0.0
    outer_area = _ring_area_square_metres(rings[0])
    holes_area = sum(_ring_area_square_metres(ring) for ring in rings[1:])
    return max(outer_area - holes_area, 0.0)


def _building_footprint_area_square_metres(feature: dict) -> float:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return _polygon_area_square_metres(coordinates)
    if geometry.get("type") == "MultiPolygon":
        return sum(_polygon_area_square_metres(polygon) for polygon in coordinates)
    return 0.0


def _capacity_constant(distribution: dict) -> float:
    raw_value = distribution.get("capacityConstant", 1)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return 1.0
    return max(value, 0.0) if math.isfinite(value) else 1.0


def _destination_capacity_profile(feature: dict, distribution: dict) -> dict:
    footprint_area = _building_footprint_area_square_metres(feature)
    levels = _building_levels(feature)
    capacity_constant = _capacity_constant(distribution)
    destination_capacity = footprint_area * levels * capacity_constant
    pedestrian_share = max(0, float(distribution.get("pedestrian", 50))) / 100
    vehicle_share = max(0, float(distribution.get("vehicle", 50))) / 100
    return {
        "footprint_area_square_metres": round(footprint_area, 3),
        "building_levels": levels,
        "capacity_constant": capacity_constant,
        "destination_capacity": round(destination_capacity, 3),
        "pedestrian_weight": destination_capacity * pedestrian_share,
        "vehicle_weight": destination_capacity * vehicle_share,
    }


def _lane_position(lane, point: tuple[float, float]) -> tuple[float, float]:
    position, distance = geomhelper.polygonOffsetAndDistanceToPoint(point, list(lane.getShape()))
    position = min(max(float(position), 0.1), max(float(lane.getLength()) - 0.1, 0.1))
    return position, float(distance)


def _pedestrian_candidates(
    network,
    point: tuple[float, float],
    max_radius: float = MAX_PERSON_ACCESS_DISTANCE_METRES,
) -> list[tuple]:
    radius = min(max(float(max_radius), 1.0), MAX_PERSON_ACCESS_DISTANCE_METRES)
    seen: set[str] = set()
    candidates = []
    for lane, neighbour_distance in network.getNeighboringLanes(
        *point,
        radius,
        includeJunctions=False,
    ):
        if lane.getID() in seen or lane.getEdge().getID().startswith(":") or not lane.allows("pedestrian"):
            continue
        position, distance = _lane_position(lane, point)
        seen.add(lane.getID())
        candidates.append((distance if distance >= 0 else neighbour_distance, lane, position))
    return sorted(candidates, key=lambda item: (item[0], item[1].getID()))


def _pedestrian_component_sizes(network) -> dict[str, int]:
    """Return the undirected pedestrian-network component size for every edge.

    Pedestrians may traverse SUMO edges in either direction.  Walking areas and
    crossings are therefore loaded and included here even though they are not
    valid building/parking snap targets themselves.
    """
    edges = {
        edge.getID(): edge
        for edge in network.getEdges(withInternal=True)
        if edge.allows("pedestrian")
    }
    adjacency = {edge_id: set() for edge_id in edges}
    for edge_id, edge in edges.items():
        for neighbour in edge.getAllowedOutgoing("pedestrian"):
            neighbour_id = neighbour.getID()
            if neighbour_id not in edges:
                continue
            adjacency[edge_id].add(neighbour_id)
            adjacency[neighbour_id].add(edge_id)

    component_sizes: dict[str, int] = {}
    seen: set[str] = set()
    for edge_id in sorted(edges):
        if edge_id in seen:
            continue
        component: list[str] = []
        stack = [edge_id]
        seen.add(edge_id)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour_id in adjacency[current]:
                if neighbour_id not in seen:
                    seen.add(neighbour_id)
                    stack.append(neighbour_id)
        size = len(component)
        component_sizes.update({member: size for member in component})
    return component_sizes


def _best_pedestrian_candidate(
    candidates: list[tuple],
    component_sizes: dict[str, int],
) -> tuple:
    """Prefer a well-connected nearby lane over an isolated nearer stub."""
    return min(
        candidates,
        key=lambda item: (
            -int(component_sizes.get(item[1].getEdge().getID(), 0)),
            float(item[0]),
            item[1].getID(),
        ),
    )


def _classification_data(model: dict, classification_id: str | None) -> tuple[dict, dict, dict]:
    classifications = model.get("buildingClassifications") or []
    classification = (
        next(
            (item for item in classifications if str(item.get("id")) == str(classification_id)),
            {},
        )
        if classification_id
        else {}
    )
    type_names = {
        str(item.get("id")): str(item.get("name") or "")
        for item in classification.get("types") or []
        if item.get("id")
    }
    return (
        classification.get("assignments") or {},
        classification.get("demandDistribution") or {},
        type_names,
    )


def _normalise_type_name(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _routable_destination_ids(
    network_path: Path,
    origins: list[dict],
    destinations: list[dict],
) -> dict[str, list[str]]:
    """Ask SUMO's router which origin/destination walks are actually valid."""
    routes = ET.Element("routes")
    pair_by_person_id: dict[str, tuple[str, str]] = {}
    for origin_index, origin in enumerate(origins):
        for destination_index, destination in enumerate(destinations):
            if origin["pedestrian_edge_id"] == destination["pedestrian_edge_id"]:
                continue
            person_id = f"access.{origin_index}.{destination_index}"
            person = ET.SubElement(routes, "person", {
                "id": person_id,
                "depart": "0",
                "departPos": str(origin["departure_position"]),
            })
            ET.SubElement(person, "walk", {
                "from": str(origin["pedestrian_edge_id"]),
                "to": str(destination["pedestrian_edge_id"]),
                "arrivalPos": str(destination["arrival_position"]),
            })
            pair_by_person_id[person_id] = (str(origin["id"]), str(destination["id"]))

    reachable: dict[str, list[str]] = {str(origin["id"]): [] for origin in origins}
    if not pair_by_person_id:
        return reachable

    with tempfile.TemporaryDirectory(prefix="sumo-person-access-") as directory:
        input_path = Path(directory) / "candidate_walks.rou.xml"
        output_path = Path(directory) / "routable_walks.rou.xml"
        ET.ElementTree(routes).write(input_path, encoding="utf-8", xml_declaration=True)
        completed = subprocess.run(
            [
                sumolib.checkBinary("duarouter"),
                "--net-file", str(network_path),
                "--route-files", str(input_path),
                "--output-file", str(output_path),
                "--ignore-errors", "true",
                "--no-warnings", "true",
                "--no-step-log", "true",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not output_path.is_file():
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown router error"
            raise RuntimeError(f"Could not validate pedestrian routes with duarouter: {detail}")
        for person in ET.parse(output_path).getroot().findall("person"):
            pair = pair_by_person_id.get(str(person.get("id")))
            if pair is not None:
                origin_id, destination_id = pair
                reachable[origin_id].append(destination_id)

    return {
        origin_id: sorted(set(destination_ids))
        for origin_id, destination_ids in reachable.items()
    }


def _physical_parking_areas(parking_config_path: Path) -> list[dict]:
    config = yaml.safe_load(parking_config_path.read_text(encoding="utf-8")) or {}
    values = []
    for logical in config.get("parking_areas") or []:
        if not logical.get("enabled", True):
            continue
        additional_path = Path(str(logical.get("additional_path") or ""))
        if not additional_path.is_absolute():
            additional_path = (parking_config_path.parent / additional_path).resolve()
        if not additional_path.is_file():
            continue
        for element in ET.parse(additional_path).getroot().findall("parkingArea"):
            values.append({
                "id": str(element.get("id")),
                "logical_parking_id": str(logical.get("id")),
                "lane_id": str(element.get("lane")),
                "start_pos": float(element.get("startPos") or 0),
                "end_pos": float(element.get("endPos") or -1),
                "capacity": max(
                    int(float(element.get("roadsideCapacity") or 1)),
                    1,
                ),
            })
    capacity_by_logical: dict[str, int] = {}
    for parking in values:
        logical_id = str(parking["logical_parking_id"])
        capacity_by_logical[logical_id] = (
            capacity_by_logical.get(logical_id, 0) + int(parking["capacity"])
        )
    for parking in values:
        parking["logical_total_capacity"] = capacity_by_logical[
            str(parking["logical_parking_id"])
        ]
    return values


def _pedestrian_path(
    network,
    source_edge,
    destination_edge,
    *,
    from_position: float | None,
    to_position: float | None,
) -> tuple:
    """Return a bidirectional pedestrian path without SUMO's same-edge bug."""
    if source_edge == destination_edge:
        if from_position is None or to_position is None:
            distance = float(source_edge.getLength())
        else:
            distance = abs(float(to_position) - float(from_position))
        return (source_edge,), distance
    return network.getShortestPath(
        source_edge,
        destination_edge,
        vClass="pedestrian",
        ignoreDirection=True,
        fromPos=from_position,
        toPos=to_position,
    )


def _attach_building_parking_candidates(
    network,
    buildings: list[dict],
    parking_access: dict[str, dict],
) -> None:
    """Order logical parking areas by the shortest routable pedestrian distance."""
    for building in buildings:
        destination_edge = network.getEdge(str(building["pedestrian_edge_id"]))
        candidate_by_logical: dict[str, dict] = {}
        for access in parking_access.values():
            source_edge = network.getEdge(str(access["pedestrian_edge_id"]))
            route, route_distance = _pedestrian_path(
                network,
                source_edge,
                destination_edge,
                from_position=access.get("departure_position"),
                to_position=building.get("arrival_position"),
            )
            if route is None or route_distance is None:
                continue
            logical_id = str(access["logical_parking_id"])
            distance = float(route_distance)
            total_capacity = max(int(access.get("logical_total_capacity") or 1), 1)
            capacity_band, band_priority = _parking_capacity_band(total_capacity)
            previous = candidate_by_logical.get(logical_id)
            if previous is None or distance < float(previous["distance_metres"]):
                candidate_by_logical[logical_id] = {
                    "parking_id": logical_id,
                    "distance_metres": round(distance, 3),
                    "total_capacity": total_capacity,
                    "capacity_band": capacity_band,
                    "band_priority": band_priority,
                }
        building["parking_candidates"] = [
            candidate
            for candidate in sorted(
                candidate_by_logical.values(),
                key=lambda item: (
                    int(item["band_priority"]),
                    float(item["distance_metres"]),
                    str(item["parking_id"]),
                ),
            )
        ]


def resolve(model_snapshot: Path, network_path: Path, scenario_path: Path, parking_config_path: Path, output_path: Path) -> dict:
    model = json.loads(model_snapshot.read_text(encoding="utf-8"))
    scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    network = sumolib.net.readNet(
        str(network_path),
        withPedestrianConnections=True,
    )
    pedestrian_component_sizes = _pedestrian_component_sizes(network)
    selected_ids = {str(value) for value in model.get("selectedBuildingIds") or []}
    all_features = (model.get("buildings") or {}).get("features", [])
    feature_by_id = {_feature_id(feature): feature for feature in all_features}
    selected_features = [
        feature for feature in all_features
        if _feature_id(feature) in selected_ids
    ]
    if not selected_features:
        raise ValueError("Person demand requires at least one selected building destination in the model.")

    assignments, distributions, type_names = _classification_data(
        model,
        scenario.get("building_classification_id"),
    )
    person_demand = scenario.get("person_demand") or {}
    max_access_distance = min(
        max(float(person_demand.get("max_access_distance_metres", MAX_PERSON_ACCESS_DISTANCE_METRES)), 1),
        MAX_PERSON_ACCESS_DISTANCE_METRES,
    )
    uses_dedicated_origins = "publicTransportOrigins" in model
    dedicated_origins = model.get("publicTransportOrigins") or []
    source_counts = scenario.get("pedestrian_source_counts")
    has_explicit_source_counts = isinstance(source_counts, dict)
    residential_requested = int((source_counts or {}).get("residential", 0))
    public_transport_requested = int(
        (source_counts or {}).get(
            "public_transport",
            (scenario.get("demand_totals") or {}).get("pedestrians", 0),
        )
    )
    if has_explicit_source_counts:
        origin_type_configs = (
            [{"name": "Residential", "mode": "residential", "weight": 1}]
            if residential_requested > 0
            else []
        )
    else:
        # Compatibility for historical scenarios created before explicit
        # source counts. Models with dedicated origins previously used only
        # those origins; older models used configured origin building types.
        origin_type_configs = [] if uses_dedicated_origins else (
            person_demand.get("origin_types") or [
                {"name": "Metro Station", "mode": "public_transport", "weight": 1},
                {"name": "Residential", "mode": "residential", "weight": 1},
            ]
        )
    origin_config_by_type = {
        _normalise_type_name(item.get("name")): {
            "mode": str(item.get("mode") or _normalise_type_name(item.get("name")).replace(" ", "_")),
            "weight": max(float(item.get("weight", 1)), 0),
            "type_name": str(item.get("name") or ""),
        }
        for item in origin_type_configs
        if isinstance(item, dict) and _normalise_type_name(item.get("name"))
    }
    unresolved_destinations = []
    unresolved_origins = []
    for feature in selected_features:
        building_id = _feature_id(feature)
        type_id = str(assignments.get(building_id) or "")
        type_name = type_names.get(type_id, "")
        type_key = _normalise_type_name(type_name)
        longitude, latitude = _feature_point(feature)
        point_xy = network.convertLonLat2XY(longitude, latitude)
        candidates = _pedestrian_candidates(network, point_xy, max_access_distance)
        if not candidates:
            raise ValueError(
                f"Selected {type_name or 'unclassified'} building "
                f"'{_feature_name(feature)}' has no pedestrian lane within "
                f"{max_access_distance:g} m."
            )
        is_classified = bool(type_id and type_id in type_names)
        distribution = (
            distributions.get(type_id)
            if is_classified
            else None
        ) or {"pedestrian": 50, "vehicle": 50, "capacityConstant": 1}
        item = {
            "id": building_id,
            "name": _feature_name(feature),
            "longitude": longitude,
            "latitude": latitude,
            "classification_type_id": type_id if is_classified else "",
            "classification_type_name": type_name if is_classified else "Unclassified",
            **_destination_capacity_profile(feature, distribution),
            "_candidates": candidates,
        }
        # Every selected building is a valid destination. A selected
        # classification changes its mode split and capacity constant; it never
        # removes a selected building from the resolved destination inventory.
        # A zero resulting capacity does, however, give that building zero
        # probability when agents are assigned destinations.
        unresolved_destinations.append(item)
        if type_key in origin_config_by_type:
            origin_item = {**item, **origin_config_by_type[type_key]}
            if origin_item.get("mode") == "residential":
                origin_item.update({
                    "source_type": "residential_building",
                    "building_id": building_id,
                })
            unresolved_origins.append(origin_item)

    if uses_dedicated_origins and (
        public_transport_requested > 0 or not has_explicit_source_counts
    ):
        for index, origin in enumerate(dedicated_origins):
            if not isinstance(origin, dict):
                continue
            origin_id = str(origin.get("id") or f"public-transport-origin-{index + 1}")
            location = origin.get("location") or {}
            longitude = location.get("longitude") if isinstance(location, dict) else None
            latitude = location.get("latitude") if isinstance(location, dict) else None
            building_id = str(origin.get("buildingId") or "")
            building_feature = feature_by_id.get(building_id)
            if (longitude is None or latitude is None) and building_feature is not None:
                longitude, latitude = _feature_point(building_feature)
            if longitude is None or latitude is None:
                raise ValueError(
                    f"Public transportation origin '{origin.get('name') or origin_id}' has no usable coordinates."
                )
            longitude = float(longitude)
            latitude = float(latitude)
            point_xy = network.convertLonLat2XY(longitude, latitude)
            candidates = _pedestrian_candidates(network, point_xy, max_access_distance)
            if not candidates:
                raise ValueError(
                    f"Public transportation origin '{origin.get('name') or origin_id}' has no pedestrian lane "
                    f"within {max_access_distance:g} m. Move it closer to a walkable road or path."
                )
            unresolved_origins.append({
                "id": origin_id,
                "name": str(origin.get("name") or f"Public transport origin {index + 1}"),
                "longitude": longitude,
                "latitude": latitude,
                "classification_type_id": "",
                "classification_type_name": "Public Transportation Origin",
                "type_name": "Public Transportation Origin",
                "source_type": str(origin.get("sourceType") or "point"),
                "building_id": building_id or None,
                "mode": "public_transport",
                "weight": max(float(origin.get("weight", 1)), 0),
                "pedestrian_weight": 1,
                "vehicle_weight": 0,
                "_candidates": candidates,
            })

    buildings = []
    for unresolved in unresolved_destinations:
        distance, lane, position = _best_pedestrian_candidate(
            unresolved.pop("_candidates"),
            pedestrian_component_sizes,
        )
        pedestrian_xy = geomhelper.positionAtShapeOffset(
            list(lane.getShape()),
            position,
        )
        buildings.append({
            **unresolved,
            "pedestrian_edge_id": lane.getEdge().getID(),
            "pedestrian_lane_id": lane.getID(),
            "arrival_position": round(position, 3),
            "snap_distance_metres": round(float(distance), 3),
            "pedestrian_x": round(float(pedestrian_xy[0]), 3),
            "pedestrian_y": round(float(pedestrian_xy[1]), 3),
        })

    candidate_origins = []
    for unresolved in unresolved_origins:
        distance, lane, position = _best_pedestrian_candidate(
            unresolved.pop("_candidates"),
            pedestrian_component_sizes,
        )
        candidate_origins.append({
            **unresolved,
            "pedestrian_edge_id": lane.getEdge().getID(),
            "pedestrian_lane_id": lane.getID(),
            "departure_position": round(position, 3),
            "snap_distance_metres": round(float(distance), 3),
        })

    pedestrian_total = int((scenario.get("demand_totals") or {}).get("pedestrians", 0))
    if pedestrian_total and not candidate_origins:
        raise ValueError(
            "Pedestrian demand requires at least one saved, walkable origin from "
            "the requested residential or public-transport sources."
        )

    reachable_destinations = _routable_destination_ids(
        network_path,
        candidate_origins,
        buildings,
    )
    origins = []
    excluded_origins = []
    for origin in candidate_origins:
        destination_ids = reachable_destinations.get(str(origin["id"])) or []
        if not destination_ids:
            excluded_origins.append(origin)
            continue
        origins.append({**origin, "reachable_destination_ids": destination_ids})

    if pedestrian_total and has_explicit_source_counts:
        origins_by_mode = {
            mode: [origin for origin in origins if str(origin.get("mode")) == mode]
            for mode in ("residential", "public_transport")
        }
        if residential_requested > 0 and not origins_by_mode["residential"]:
            raise ValueError(
                "Residential pedestrian demand was requested, but no selected, "
                "walkable Residential building can reach a destination."
            )
        if public_transport_requested > 0 and not origins_by_mode["public_transport"]:
            raise ValueError(
                "Public-transport pedestrian demand was requested, but no saved, "
                "walkable Public Transportation Origin can reach a destination."
            )
    elif pedestrian_total:
        resolved_type_keys = {
            _normalise_type_name(origin.get("type_name"))
            for origin in origins
        }
        missing_origin_types = [
            config["type_name"]
            for key, config in origin_config_by_type.items()
            if key not in resolved_type_keys
        ]
        if missing_origin_types:
            raise ValueError(
                "Pedestrian demand has no selected, routable origin building for type(s): "
                + ", ".join(missing_origin_types)
            )

    parking_access = {}
    inaccessible_parking_areas = []

    for parking in _physical_parking_areas(parking_config_path):
        vehicle_lane = network.getLane(parking["lane_id"])
        lane_length = float(vehicle_lane.getLength())
        end_pos = parking["end_pos"] if parking["end_pos"] >= 0 else lane_length + parking["end_pos"]
        vehicle_position = min(max((parking["start_pos"] + end_pos) / 2, 0.1), max(lane_length - 0.1, 0.1))
        point_xy = geomhelper.positionAtShapeOffset(list(vehicle_lane.getShape()), vehicle_position)
        candidates = _pedestrian_candidates(network, point_xy, max_access_distance)
        if not candidates:
            inaccessible_parking_areas.append(parking)
            continue
        distance, lane, position = _best_pedestrian_candidate(
            candidates,
            pedestrian_component_sizes,
        )
        pedestrian_xy = geomhelper.positionAtShapeOffset(
            list(lane.getShape()),
            position,
        )
        parking_access[parking["id"]] = {
            **parking,
            "pedestrian_edge_id": lane.getEdge().getID(),
            "pedestrian_lane_id": lane.getID(),
            "departure_position": round(position, 3),
            "snap_distance_metres": round(float(distance), 3),
            "pedestrian_x": round(float(pedestrian_xy[0]), 3),
            "pedestrian_y": round(float(pedestrian_xy[1]), 3),
        }

    _attach_building_parking_candidates(network, buildings, parking_access)
    vehicle_total = int((scenario.get("demand_totals") or {}).get("vehicles", 0))
    if vehicle_total and not any(building["parking_candidates"] for building in buildings):
        raise ValueError(
            "Vehicle demand requires at least one selected destination building "
            "reachable on foot from a selected parking area."
        )

    result = {
        # Keep a legacy entry value for older snapshots/readers. New demand
        # generation uses the explicit per-building origins below.
        "entry": (
            {
                "edge_id": origins[0]["pedestrian_edge_id"],
                "position": origins[0]["departure_position"],
            }
            if origins
            else None
        ),
        "origins": origins,
        "buildings": buildings,
        "parking_access": parking_access,
        "origin_count": len(origins),
        "origin_counts_by_mode": {
            mode: sum(str(origin.get("mode")) == mode for origin in origins)
            for mode in ("residential", "public_transport")
        },
        "requested_pedestrian_source_counts": {
            "residential": residential_requested,
            "public_transport": public_transport_requested,
        },
        "building_count": len(buildings),
        "parking_access_count": len(parking_access),
        "max_access_distance_metres": max_access_distance,
        "accessible_logical_parking_ids": sorted({
            str(parking["logical_parking_id"])
            for parking in parking_access.values()
        }),
        "inaccessible_parking_areas": [
            {
                "id": parking["id"],
                "logical_parking_id": parking["logical_parking_id"],
                "reason": "no_pedestrian_lane_within_access_limit",
            }
            for parking in inaccessible_parking_areas
        ],
        "excluded_buildings": [],
        "excluded_origins": [
            {
                "id": origin["id"],
                "name": origin["name"],
                "type": origin["type_name"],
                "reason": "no_pedestrian_route_to_selected_destination",
            }
            for origin in excluded_origins
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Resolved {len(origins)} pedestrian origins, {len(buildings)} building destinations, "
        f"and {len(parking_access)} parking pedestrian accesses."
    )
    if excluded_origins:
        print(
            f"Warning: excluded {len(excluded_origins)} origin building(s) without a pedestrian route "
            "to a configured destination."
        )
    if inaccessible_parking_areas:
        print(
            f"Warning: excluded {len(inaccessible_parking_areas)} physical parking area(s) "
            f"without a pedestrian lane within {max_access_distance:g} m."
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--parking-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    resolve(arguments.model_snapshot, arguments.network, arguments.scenario, arguments.parking_config, arguments.output)


if __name__ == "__main__":
    main()
