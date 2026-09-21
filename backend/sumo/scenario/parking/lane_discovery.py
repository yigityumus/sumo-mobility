"""Resolve logical OSM parking polygons to usable SUMO lanes automatically."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import sumolib

from .osm_discovery import (
    LENGTH_EPSILON_METRES,
    OSMData,
    analyse_parking_way,
    get_coordinates,
    point_polygon_distance,
)


def osm_way_id_from_sumo_edge(edge_id: str) -> int | None:
    value = edge_id.removeprefix("-").split("#", 1)[0]
    try:
        return int(value)
    except ValueError:
        return None


def _sampled_inside_ratio(
    shape: list[tuple[float, float]],
    polygon: list[tuple[float, float]],
    buffer_metres: float,
    sample_metres: float = 0.5,
) -> tuple[float, float]:
    total_length = 0.0
    inside_length = 0.0
    near_length = 0.0
    for first, second in zip(shape, shape[1:]):
        segment_length = math.dist(first, second)
        total_length += segment_length
        sample_count = max(1, math.ceil(segment_length / sample_metres))
        piece_length = segment_length / sample_count
        for index in range(sample_count):
            fraction = (index + 0.5) / sample_count
            point = (
                first[0] + (second[0] - first[0]) * fraction,
                first[1] + (second[1] - first[1]) * fraction,
            )
            distance = point_polygon_distance(point, polygon)
            if distance <= LENGTH_EPSILON_METRES:
                inside_length += piece_length
            if distance <= buffer_metres:
                near_length += piece_length
    if total_length <= 0:
        return 0.0, 0.0
    return inside_length / total_length, near_length / total_length


def load_sumo_network(path: Path):
    return sumolib.net.readNet(str(path))


def discover_parking_lanes(
    parking_way_id: int,
    osm_data: OSMData,
    sumo_network,
    *,
    minimum_way_inside_ratio: float = 0.5,
    minimum_lane_inside_ratio: float = 0.5,
    parking_buffer_metres: float = 3.0,
    minimum_lane_length: float = 3.0,
    nearest_access_lane_metres: float = 150.0,
) -> dict[str, Any]:
    analysis = analyse_parking_way(parking_way_id, osm_data)
    if "error" in analysis:
        raise ValueError(str(analysis["error"]))

    parking_way = osm_data.ways[parking_way_id]
    lon_lat_polygon = get_coordinates(parking_way.node_refs, osm_data.nodes)
    if lon_lat_polygon[0] != lon_lat_polygon[-1]:
        lon_lat_polygon.append(lon_lat_polygon[0])
    polygon_xy = [
        sumo_network.convertLonLat2XY(lon, lat)
        for lon, lat in lon_lat_polygon
    ]

    related_details = {
        int(item["osm_way_id"]): item
        for item in [*analysis["gate_ways"], *analysis["internal_ways"]]
    }
    parking_way_ids = {
        way_id
        for way_id, details in related_details.items()
        if float(details.get("inside_ratio") or 0) >= minimum_way_inside_ratio
    }
    excluded_way_ids = sorted(set(related_details) - parking_way_ids)

    lanes = []
    access_edge_ids = set()
    for edge in sumo_network.getEdges():
        edge_id = edge.getID()
        if edge_id.startswith(":"):
            continue
        source_way_id = osm_way_id_from_sumo_edge(edge_id)
        if source_way_id in excluded_way_ids and any(
            lane.allows("passenger") for lane in edge.getLanes()
        ):
            access_edge_ids.add(edge_id)
        if source_way_id not in parking_way_ids:
            continue
        for lane in edge.getLanes():
            if float(lane.getLength()) < minimum_lane_length:
                continue
            if hasattr(lane, "allows") and not lane.allows("passenger"):
                continue
            shape = list(lane.getShape())
            if len(shape) < 2:
                continue
            inside_ratio, near_ratio = _sampled_inside_ratio(
                shape,
                polygon_xy,
                parking_buffer_metres,
            )
            if inside_ratio < minimum_lane_inside_ratio:
                continue
            lanes.append({
                "lane_id": lane.getID(),
                "edge_id": edge_id,
                "osm_way_id": source_way_id,
                "length": float(lane.getLength()),
                "inside_ratio": inside_ratio,
                "near_ratio": near_ratio,
            })

    lanes.sort(key=lambda item: (item["osm_way_id"], item["edge_id"], item["lane_id"]))
    fallback_details = None
    if not lanes:
        # Multi-storey and underground parking polygons often only touch
        # delivery/pedestrian access ways, so netconvert produces no passenger
        # aisle inside the footprint. Represent those lots on the nearest
        # passenger-accessible service lane instead of silently dropping a
        # parking area selected by the model.
        nearby_lanes = []
        for edge in sumo_network.getEdges():
            edge_id = edge.getID()
            if edge_id.startswith(":"):
                continue
            source_way_id = osm_way_id_from_sumo_edge(edge_id)
            source_way = osm_data.ways.get(source_way_id) if source_way_id else None
            source_tags = source_way.tags if source_way is not None else {}
            service_rank = 0 if source_tags.get("highway") == "service" else 1
            for lane in edge.getLanes():
                if float(lane.getLength()) < minimum_lane_length or not lane.allows("passenger"):
                    continue
                shape = list(lane.getShape())
                if len(shape) < 2:
                    continue
                sample_points = [*shape]
                sample_points.extend(
                    ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
                    for first, second in zip(shape, shape[1:])
                )
                distance = min(
                    point_polygon_distance(point, polygon_xy)
                    for point in sample_points
                )
                if distance <= nearest_access_lane_metres:
                    nearby_lanes.append((
                        service_rank,
                        distance,
                        -float(lane.getLength()),
                        edge_id,
                        lane,
                        source_way_id,
                    ))
        if not nearby_lanes:
            raise ValueError(
                f"No passenger lane was found inside or within "
                f"{nearest_access_lane_metres:g} m of parking OSM way {parking_way_id}."
            )
        ordered_nearby_lanes = sorted(nearby_lanes, key=lambda item: item[:4])
        selected_fallback = ordered_nearby_lanes[0]
        for candidate in ordered_nearby_lanes[:100]:
            edge = sumo_network.getEdge(candidate[3])
            reverse_reachable = sumo_network.getReachable(
                edge,
                vclass="passenger",
                useIncoming=True,
            )
            if len(reverse_reachable) >= 20:
                selected_fallback = candidate
                break
        service_rank, distance, _negative_length, edge_id, lane, source_way_id = selected_fallback
        lanes.append({
            "lane_id": lane.getID(),
            "edge_id": edge_id,
            "osm_way_id": source_way_id,
            "length": float(lane.getLength()),
            "inside_ratio": 0.0,
            "near_ratio": 0.0,
        })
        access_edge_ids.add(edge_id)
        fallback_details = {
            "used": True,
            "reason": "no_passenger_lane_inside_parking_polygon",
            "lane_id": lane.getID(),
            "edge_id": edge_id,
            "distance_metres": round(distance, 3),
            "is_service_road": service_rank == 0,
        }

    edge_ids = sorted({str(item["edge_id"]) for item in lanes})
    access_edges = sorted(access_edge_ids)
    return {
        "parking_way_id": parking_way_id,
        "parking_name": analysis.get("parking_name"),
        "related_way_ids": analysis["all_related_way_ids"],
        "parking_way_ids": sorted(parking_way_ids),
        "excluded_way_ids": excluded_way_ids,
        "lane_ids": [str(item["lane_id"]) for item in lanes],
        "parking_edge_ids": edge_ids,
        # Trips need a safe fallback destination before the controller assigns
        # a physical space. Keep unassigned vehicles on the access road rather
        # than sending them into a potentially saturated internal aisle.
        "routing_edge_ids": edge_ids if fallback_details else (access_edges or edge_ids),
        "access_edge_ids": access_edges or edge_ids,
        "lanes": lanes,
        "thresholds": {
            "minimum_way_inside_ratio": minimum_way_inside_ratio,
            "minimum_lane_inside_ratio": minimum_lane_inside_ratio,
            "parking_buffer_metres": parking_buffer_metres,
            "minimum_lane_length": minimum_lane_length,
            "nearest_access_lane_metres": nearest_access_lane_metres,
        },
        "access_lane_fallback": fallback_details,
    }
