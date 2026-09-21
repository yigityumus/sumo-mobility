"""Parking-capacity estimation for campus models."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .osm import OsmXmlError, maybe_decompress_osm_bytes

SLOT_WIDTH_METRES = 2.3
MIN_INTERNAL_WAY_INSIDE_RATIO = 0.5
MIN_SPATIAL_WAY_INSIDE_RATIO = 0.5
MIN_SPATIAL_PARKING_AISLE_LENGTH_METRES = 3
CALCULATED_CAPACITY_SOURCE = "calculated_related_lane_length_2_3m"
INTERNAL_ROADS_NOT_FOUND = "not_found"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _tags(element: ET.Element) -> dict[str, str]:
    tags: dict[str, str] = {}
    for child in element:
        if _strip_namespace(child.tag) != "tag":
            continue
        key = child.get("k")
        value = child.get("v")
        if key is not None and value is not None:
            tags[key] = value
    return tags


def parse_osm_for_capacity(content: bytes) -> dict[str, Any]:
    try:
        root = ET.fromstring(maybe_decompress_osm_bytes(content))
    except ET.ParseError as exc:
        raise OsmXmlError("The source OSM file could not be parsed as XML.") from exc

    nodes: dict[str, dict[str, float | str]] = {}
    ways: dict[str, dict[str, Any]] = {}
    node_to_way_ids: dict[str, set[str]] = {}

    for child in root:
        tag = _strip_namespace(child.tag)
        if tag == "node":
            node_id = child.get("id")
            lat = child.get("lat")
            lon = child.get("lon")
            if node_id is None or lat is None or lon is None:
                continue
            try:
                nodes[node_id] = {"id": node_id, "lat": float(lat), "lon": float(lon)}
            except ValueError:
                continue
        elif tag == "way":
            way_id = child.get("id")
            if way_id is None:
                continue
            node_refs: list[str] = []
            for grandchild in child:
                if _strip_namespace(grandchild.tag) != "nd":
                    continue
                ref = grandchild.get("ref")
                if ref:
                    node_refs.append(ref)
            ways[way_id] = {"id": way_id, "nodeRefs": node_refs, "tags": _tags(child)}
            for node_ref in node_refs:
                node_to_way_ids.setdefault(node_ref, set()).add(way_id)

    return {"nodes": nodes, "ways": ways, "nodeToWayIds": node_to_way_ids}


def parse_osm_way_id_from_feature_id(feature_id: str) -> str | None:
    osm_type, _, raw_id = str(feature_id).partition("/")
    if osm_type != "way" or not raw_id:
        return None
    return raw_id


def feature_id(feature: dict[str, Any]) -> str:
    if feature.get("id") is not None:
        return str(feature["id"])
    props = feature.get("properties") or {}
    return f"{props.get('type', 'unknown')}/{props.get('id', 'unknown')}"


def is_vehicle_service_way(way: dict[str, Any] | None) -> bool:
    if not way or (way.get("tags") or {}).get("highway") != "service":
        return False
    access = (way.get("tags") or {}).get("access") or (way.get("tags") or {}).get("vehicle") or (way.get("tags") or {}).get("motor_vehicle")
    return str(access or "").lower() != "no"


def create_projection(points: list[dict[str, Any]]):
    average_latitude = sum(float(point["lat"]) for point in points) / max(len(points), 1)
    cos_latitude = math.cos(math.radians(average_latitude))

    def project(point: dict[str, Any]) -> dict[str, float]:
        return {
            "x": float(point["lon"]) * 111_320 * cos_latitude,
            "y": float(point["lat"]) * 110_540,
        }

    return project


def point_in_polygon(point: dict[str, float], polygon: list[dict[str, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi = polygon[i]["x"]
        yi = polygon[i]["y"]
        xj = polygon[j]["x"]
        yj = polygon[j]["y"]
        intersects = (yi > point["y"]) != (yj > point["y"]) and point["x"] < ((xj - xi) * (point["y"] - yi)) / ((yj - yi) or 1e-20) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def distance_metres(left: dict[str, float], right: dict[str, float]) -> float:
    return math.sqrt((left["x"] - right["x"]) ** 2 + (left["y"] - right["y"]) ** 2)


def way_geometry(way: dict[str, Any], nodes: dict[str, Any], project) -> list[dict[str, Any]]:
    geometry = []
    for node_ref in way.get("nodeRefs") or []:
        node = nodes.get(node_ref)
        if node:
            geometry.append({"id": node["id"], "projected": project(node)})
    return geometry


def way_length_stats(way: dict[str, Any], nodes: dict[str, Any], project, polygon: list[dict[str, float]]) -> dict[str, float]:
    geometry = way_geometry(way, nodes, project)
    total_length = 0.0
    inside_length = 0.0
    for index in range(len(geometry) - 1):
        start = geometry[index]["projected"]
        end = geometry[index + 1]["projected"]
        length = distance_metres(start, end)
        midpoint = {"x": (start["x"] + end["x"]) / 2, "y": (start["y"] + end["y"]) / 2}
        total_length += length
        if point_in_polygon(midpoint, polygon):
            inside_length += length
    return {
        "totalLength": total_length,
        "insideLength": inside_length,
        "insideRatio": inside_length / total_length if total_length > 0 else 0.0,
    }


def parking_polygon_from_way(parking_way: dict[str, Any], nodes: dict[str, Any]) -> list[dict[str, Any]]:
    polygon_nodes = [nodes[node_ref] for node_ref in parking_way.get("nodeRefs") or [] if node_ref in nodes]
    if len(polygon_nodes) < 4:
        raise ValueError(f"Parking way {parking_way.get('id')} does not have enough nodes for a polygon.")
    return polygon_nodes


def should_accept_spatial_internal_way(way: dict[str, Any], stats: dict[str, float]) -> bool:
    if not is_vehicle_service_way(way):
        return False
    tags = way.get("tags") or {}
    if stats["insideRatio"] >= MIN_SPATIAL_WAY_INSIDE_RATIO:
        return True
    return tags.get("service") == "parking_aisle" and stats["insideLength"] >= MIN_SPATIAL_PARKING_AISLE_LENGTH_METRES


def _sort_ids(ids) -> list[str]:
    return sorted([str(item) for item in ids], key=lambda value: int(value) if value.isdigit() else value)


def find_related_parking_ways(parking_way: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    nodes = data["nodes"]
    ways = data["ways"]
    node_to_way_ids = data["nodeToWayIds"]
    polygon_nodes = parking_polygon_from_way(parking_way, nodes)
    project = create_projection(polygon_nodes)
    polygon = [project(point) for point in polygon_nodes]
    parking_node_refs = set(parking_way.get("nodeRefs") or [])

    stats_cache: dict[str, dict[str, float]] = {}
    def stats_for_way(way: dict[str, Any]) -> dict[str, float]:
        way_id = str(way["id"])
        if way_id not in stats_cache:
            stats_cache[way_id] = way_length_stats(way, nodes, project, polygon)
        return stats_cache[way_id]

    gate_way_ids: set[str] = set()
    gate_way_details_by_id: dict[str, dict[str, Any]] = {}

    for node_ref in parking_node_refs:
        parent_ways = node_to_way_ids.get(node_ref) or set()
        for way_id in parent_ways:
            if way_id == parking_way["id"]:
                continue
            way = ways.get(way_id)
            if not is_vehicle_service_way(way):
                continue
            stats = stats_for_way(way)
            gate_way_ids.add(way_id)
            current = gate_way_details_by_id.get(way_id) or {
                "wayId": way_id,
                "sharedNodeIds": [],
                "service": (way.get("tags") or {}).get("service"),
                "insideRatio": stats["insideRatio"],
                "insideLength": stats["insideLength"],
            }
            current["sharedNodeIds"].append(node_ref)
            gate_way_details_by_id[way_id] = current

    accepted_way_ids = set(gate_way_ids)
    internal_way_ids: set[str] = set()
    internal_way_details: list[dict[str, Any]] = []
    queue = list(gate_way_ids)

    while queue:
        current_way_id = queue.pop(0)
        current_way = ways.get(current_way_id)
        if not current_way:
            continue
        for node_ref in current_way.get("nodeRefs") or []:
            parent_ways = node_to_way_ids.get(node_ref) or set()
            for candidate_way_id in parent_ways:
                if candidate_way_id in accepted_way_ids or candidate_way_id == parking_way["id"]:
                    continue
                candidate_way = ways.get(candidate_way_id)
                if not is_vehicle_service_way(candidate_way):
                    continue
                stats = stats_for_way(candidate_way)
                if stats["insideRatio"] < MIN_INTERNAL_WAY_INSIDE_RATIO:
                    continue
                accepted_way_ids.add(candidate_way_id)
                internal_way_ids.add(candidate_way_id)
                queue.append(candidate_way_id)
                internal_way_details.append({
                    "wayId": candidate_way_id,
                    "connectedFrom": current_way_id,
                    "service": (candidate_way.get("tags") or {}).get("service"),
                    "insideRatio": stats["insideRatio"],
                    "insideLength": stats["insideLength"],
                })

    spatial_only_way_ids: set[str] = set()
    spatial_only_way_details: list[dict[str, Any]] = []
    for candidate_way_id, candidate_way in ways.items():
        if candidate_way_id == parking_way["id"] or candidate_way_id in accepted_way_ids:
            continue
        stats = stats_for_way(candidate_way)
        if not should_accept_spatial_internal_way(candidate_way, stats):
            continue
        accepted_way_ids.add(candidate_way_id)
        spatial_only_way_ids.add(candidate_way_id)
        spatial_only_way_details.append({
            "wayId": candidate_way_id,
            "service": (candidate_way.get("tags") or {}).get("service"),
            "insideRatio": stats["insideRatio"],
            "insideLength": stats["insideLength"],
        })

    related_way_ids = _sort_ids(accepted_way_ids)
    related_way_lengths = []
    total_inside_length = 0.0
    for way_id in related_way_ids:
        way = ways.get(way_id)
        if not way:
            continue
        stats = stats_for_way(way)
        total_inside_length += stats["insideLength"]
        if way_id in gate_way_ids:
            detection = "boundary_shared_node_gate"
        elif way_id in internal_way_ids:
            detection = "connected_internal_way"
        elif way_id in spatial_only_way_ids:
            detection = "spatial_inside_fallback"
        else:
            detection = "related"
        related_way_lengths.append({
            "way_id": way_id,
            "inside_length_m": round(stats["insideLength"], 2),
            "total_length_m": round(stats["totalLength"], 2),
            "inside_ratio": round(stats["insideRatio"], 3),
            "service": (way.get("tags") or {}).get("service"),
            "detection": detection,
        })

    return {
        "gateWayIds": _sort_ids(gate_way_ids),
        "gateWayDetails": sorted(gate_way_details_by_id.values(), key=lambda item: int(item["wayId"]) if str(item["wayId"]).isdigit() else str(item["wayId"])),
        "internalWayIds": _sort_ids(internal_way_ids),
        "internalWayDetails": internal_way_details,
        "spatialOnlyWayIds": _sort_ids(spatial_only_way_ids),
        "spatialOnlyWayDetails": spatial_only_way_details,
        "relatedWayIds": related_way_ids,
        "relatedWayLengths": related_way_lengths,
        "totalInsideLength": total_inside_length,
    }


def estimate_capacity_for_feature(feature: dict[str, Any], osm_data: dict[str, Any]) -> dict[str, Any]:
    parking_feature_id = feature_id(feature)
    osm_way_id = parse_osm_way_id_from_feature_id(parking_feature_id)
    if not osm_way_id:
        return {"capacity": None, "error": "Only OSM way-based parking polygons can be estimated automatically.", "relatedWayIds": []}

    parking_way = osm_data["ways"].get(osm_way_id)
    if not parking_way:
        return {"capacity": None, "error": f"Parking way {osm_way_id} was not found in the source OSM file.", "relatedWayIds": []}

    related = find_related_parking_ways(parking_way, osm_data)
    capacity = math.floor(float(related["totalInsideLength"]) / SLOT_WIDTH_METRES)
    if capacity <= 0:
        return {"capacity": None, "error": "No related internal service-way length was found for this parking area.", **related}

    return {
        "capacity": capacity,
        "capacitySource": CALCULATED_CAPACITY_SOURCE,
        "method": {
            "name": "related_service_way_length_2_3m",
            "slot_width_m": SLOT_WIDTH_METRES,
            "total_inside_length_m": round(float(related["totalInsideLength"]), 2),
            "formula": "floor(total_inside_related_service_way_length_m / 2.3)",
        },
        **related,
    }


def internal_roads_from_result(result: dict[str, Any]) -> str | list[str]:
    ids = [str(item) for item in result.get("relatedWayIds") or []]
    return ids if ids else INTERNAL_ROADS_NOT_FOUND


def apply_capacity_result_to_model(model: dict[str, Any], parking_id: str, result: dict[str, Any]) -> dict[str, Any]:
    parking_specs = dict(model.get("parkingSpecs") or {})
    current = dict(parking_specs.get(parking_id) or {})
    current["internalRoads"] = internal_roads_from_result(result)
    current["changeDate"] = now_iso()
    if result.get("capacity"):
        current["capacity"] = result["capacity"]
        current["capacitySource"] = result.get("capacitySource") or CALCULATED_CAPACITY_SOURCE
        current["capacityMethod"] = result.get("method")
    parking_specs[parking_id] = current
    model["parkingSpecs"] = parking_specs
    model["updatedAt"] = now_iso()
    return model


def estimate_model_parking(model: dict[str, Any], parking_id: str, source_osm: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    features = (model.get("parkingAreas") or {}).get("features") or []
    feature = next((item for item in features if feature_id(item) == parking_id), None)
    if not feature:
        raise ValueError("The selected parking area could not be found in this model.")
    osm_data = parse_osm_for_capacity(source_osm)
    result = estimate_capacity_for_feature(feature, osm_data)
    updated_model = apply_capacity_result_to_model(dict(model), parking_id, result)
    return updated_model, result


def estimate_model_unknown_parkings(model: dict[str, Any], source_osm: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    osm_data = parse_osm_for_capacity(source_osm)
    parking_specs = model.get("parkingSpecs") or {}
    features = (model.get("parkingAreas") or {}).get("features") or []
    updated_model = dict(model)
    results = []
    filled = 0
    skipped = 0

    for feature in features:
        parking_id = feature_id(feature)
        spec = parking_specs.get(parking_id) or {}
        if spec.get("capacity"):
            continue
        result = estimate_capacity_for_feature(feature, osm_data)
        updated_model = apply_capacity_result_to_model(updated_model, parking_id, result)
        if result.get("capacity"):
            filled += 1
        else:
            skipped += 1
        results.append({"parking_id": parking_id, **result})

    return updated_model, {"filled": filled, "skipped": skipped, "results": results}
