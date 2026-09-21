"""Resolve geographic detector locations to lanes in a generated SUMO network."""

from __future__ import annotations

import math
from typing import Any

from sumolib import geomhelper


def _heading_degrees(shape: list[tuple[float, float]], offset: float) -> float:
    if len(shape) < 2:
        return 0.0
    travelled = 0.0
    for first, second in zip(shape, shape[1:]):
        length = math.dist(first, second)
        if travelled + length >= offset or second == shape[-1]:
            return (math.degrees(math.atan2(second[0] - first[0], second[1] - first[1])) + 360) % 360
        travelled += length
    return 0.0


def resolve_detector_lanes(
    network,
    longitude: float,
    latitude: float,
    *,
    radius_metres: float = 30.0,
    limit: int = 12,
    allowed_classes: tuple[str, ...] = ("passenger",),
) -> list[dict[str, Any]]:
    """Return nearby lanes for the requested SUMO classes, ordered by distance."""
    x, y = network.convertLonLat2XY(longitude, latitude)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lane, neighbour_distance in network.getNeighboringLanes(
        x, y, radius_metres, includeJunctions=False
    ):
        lane_id = lane.getID()
        edge = lane.getEdge()
        edge_id = edge.getID()
        if (
            lane_id in seen
            or edge_id.startswith(":")
            or not any(lane.allows(vehicle_class) for vehicle_class in allowed_classes)
        ):
            continue
        shape = list(lane.getShape())
        if len(shape) < 2:
            continue
        position, perpendicular_distance = geomhelper.polygonOffsetAndDistanceToPoint((x, y), shape)
        position = min(max(float(position), 0.1), max(float(lane.getLength()) - 0.1, 0.1))
        snapped_x, snapped_y = geomhelper.positionAtShapeOffset(shape, position)
        snapped_lon, snapped_lat = network.convertXY2LonLat(snapped_x, snapped_y)
        geographic_shape = []
        for shape_x, shape_y in shape:
            shape_longitude, shape_latitude = network.convertXY2LonLat(shape_x, shape_y)
            geographic_shape.append({
                "longitude": float(shape_longitude),
                "latitude": float(shape_latitude),
            })
        seen.add(lane_id)
        candidates.append({
            "lane_id": lane_id,
            "edge_id": edge_id,
            "lane_index": int(lane.getIndex()),
            "position_metres": round(position, 3),
            "distance_metres": round(float(perpendicular_distance if perpendicular_distance >= 0 else neighbour_distance), 3),
            "lane_length_metres": round(float(lane.getLength()), 3),
            "edge_name": str(edge.getName() or ""),
            "heading_degrees": round(_heading_degrees(shape, position), 1),
            "allows_passenger": bool(lane.allows("passenger")),
            "allows_pedestrian": bool(lane.allows("pedestrian")),
            "shape": geographic_shape,
            "snapped": {"longitude": float(snapped_lon), "latitude": float(snapped_lat)},
        })
    candidates.sort(key=lambda item: (item["distance_metres"], item["edge_id"], item["lane_index"]))
    return candidates[:limit]


def lane_on_selected_edge(network, edge_id: str, lane_index: int | None, vehicle_class: str = "passenger"):
    try:
        edge = network.getEdge(edge_id)
    except KeyError:
        return None
    allowed_lanes = [lane for lane in edge.getLanes() if lane.allows(vehicle_class)]
    if lane_index is not None:
        for lane in allowed_lanes:
            if int(lane.getIndex()) == int(lane_index):
                return lane
    return allowed_lanes[0] if allowed_lanes else None
