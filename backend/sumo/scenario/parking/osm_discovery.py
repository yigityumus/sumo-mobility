#!/usr/bin/env python3
"""Find OSM service-road ways associated with one or more parking polygons.

The script:
1. Reads a local .osm.xml or .osm.xml.gz file.
2. Builds a node -> parent ways index.
3. Finds service roads that share boundary nodes with each parking polygon.
4. Recursively follows connected service roads, then adds disconnected roads
   whose geometry is substantially inside the parking polygon.
5. Prints results and can optionally save them as JSON.

The geometry calculations are intentionally dependency-free and use a
campus-scale local projection with short line samples.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_FILE = "parking_related_ways.json"

# Internal connected ways must have at least this fraction of their length
# inside the parking polygon to be classified automatically as internal.
MIN_INSIDE_RATIO = 0.50

# Small tolerance around the polygon, in metres, for imperfect OSM geometry.
PARKING_BUFFER_METRES = 3.0

# Very short intersections are ignored to avoid floating-point noise.
LENGTH_EPSILON_METRES = 0.05
GEOMETRY_SAMPLE_METRES = 0.5


@dataclass(frozen=True)
class OSMWay:
    way_id: int
    node_refs: tuple[int, ...]
    tags: dict[str, str]


@dataclass
class OSMData:
    nodes: dict[int, tuple[float, float]]  # node_id -> (lon, lat)
    ways: dict[int, OSMWay]
    node_to_ways: dict[int, set[int]]


def open_osm(path: Path) -> BinaryIO:
    """Open OSM XML by detecting whether the contents are gzip-compressed."""
    with path.open("rb") as probe:
        magic = probe.read(2)

    if magic == b"\x1f\x8b":
        return gzip.open(path, "rb")

    return path.open("rb")


def load_osm(path: Path) -> OSMData:
    """Parse nodes and ways, then build a node -> parent ways index."""
    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, OSMWay] = {}

    with open_osm(path) as file:
        for _event, element in ET.iterparse(file, events=("end",)):
            if element.tag == "node":
                node_id = int(element.attrib["id"])
                lon = float(element.attrib["lon"])
                lat = float(element.attrib["lat"])
                nodes[node_id] = (lon, lat)
                element.clear()

            elif element.tag == "way":
                way_id = int(element.attrib["id"])
                node_refs = tuple(
                    int(child.attrib["ref"])
                    for child in element
                    if child.tag == "nd"
                )
                tags = {
                    child.attrib["k"]: child.attrib["v"]
                    for child in element
                    if child.tag == "tag"
                }
                ways[way_id] = OSMWay(
                    way_id=way_id,
                    node_refs=node_refs,
                    tags=tags,
                )
                element.clear()

    node_to_ways: dict[int, set[int]] = defaultdict(set)
    for way in ways.values():
        for node_id in way.node_refs:
            node_to_ways[node_id].add(way.way_id)

    return OSMData(
        nodes=nodes,
        ways=ways,
        node_to_ways=dict(node_to_ways),
    )


def is_vehicle_service_way(way: OSMWay) -> bool:
    """Return True for vehicle roads that may belong to a parking facility."""
    if way.tags.get("highway") not in {
        "service",
        "unclassified",
        "residential",
        "living_street",
    }:
        return False

    # Reject explicit motor-vehicle prohibitions. Extend this if your campus
    # uses more specialised access tags.
    if way.tags.get("motor_vehicle") in {"no", "private"}:
        return False
    if way.tags.get("vehicle") == "no":
        return False

    return True


def local_projector(reference_lon: float, reference_lat: float):
    """Create a small-area lon/lat -> metres projection.

    This equirectangular projection is sufficiently accurate for a campus-scale
    area and avoids requiring pyproj.
    """
    earth_radius_m = 6_371_008.8
    lat0_rad = math.radians(reference_lat)
    cos_lat0 = math.cos(lat0_rad)

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = earth_radius_m * math.radians(lon - reference_lon) * cos_lat0
        y = earth_radius_m * math.radians(lat - reference_lat)
        return x, y

    return project


def get_coordinates(
    node_refs: Iterable[int],
    nodes: dict[int, tuple[float, float]],
) -> list[tuple[float, float]]:
    """Resolve node references, skipping missing nodes."""
    return [nodes[node_id] for node_id in node_refs if node_id in nodes]


def build_parking_geometry(
    parking_way: OSMWay,
    nodes: dict[int, tuple[float, float]],
):
    lon_lat = get_coordinates(parking_way.node_refs, nodes)

    if len(lon_lat) < 4:
        raise ValueError(
            f"Parking way {parking_way.way_id} has insufficient geometry."
        )

    reference_lon = sum(lon for lon, _lat in lon_lat) / len(lon_lat)
    reference_lat = sum(lat for _lon, lat in lon_lat) / len(lon_lat)
    project = local_projector(reference_lon, reference_lat)

    projected = [project(lon, lat) for lon, lat in lon_lat]

    # Ensure the ring is closed even if the source data is malformed.
    if projected[0] != projected[-1]:
        projected.append(projected[0])

    return projected, project


def build_way_line(
    way: OSMWay,
    nodes: dict[int, tuple[float, float]],
    project,
) -> list[tuple[float, float]] | None:
    lon_lat = get_coordinates(way.node_refs, nodes)
    if len(lon_lat) < 2:
        return None

    line = [project(lon, lat) for lon, lat in lon_lat]
    if polyline_length(line) <= LENGTH_EPSILON_METRES:
        return None
    return line


def point_in_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> bool:
    x, y = point
    inside = False
    for first, second in zip(polygon, polygon[1:]):
        x1, y1 = first
        x2, y2 = second
        if (y1 > y) == (y2 > y):
            continue
        crossing_x = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
        if x < crossing_x:
            inside = not inside
    return inside


def point_segment_distance(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = first
    bx, by = second
    dx = bx - ax
    dy = by - ay
    squared_length = dx * dx + dy * dy
    if squared_length == 0:
        return math.hypot(px - ax, py - ay)
    position = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / squared_length))
    return math.hypot(px - (ax + position * dx), py - (ay + position * dy))


def point_polygon_distance(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> float:
    if point_in_polygon(point, polygon):
        return 0.0
    return min(
        point_segment_distance(point, first, second)
        for first, second in zip(polygon, polygon[1:])
    )


def polyline_length(line: list[tuple[float, float]]) -> float:
    return sum(math.dist(first, second) for first, second in zip(line, line[1:]))


def bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def bounds_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    padding: float = 0.0,
) -> bool:
    return not (
        first[2] < second[0] - padding
        or first[0] > second[2] + padding
        or first[3] < second[1] - padding
        or first[1] > second[3] + padding
    )


def geometry_metrics(
    line: list[tuple[float, float]],
    parking_polygon: list[tuple[float, float]],
) -> dict[str, float | bool]:
    total_length = polyline_length(line)
    inside_length = 0.0
    near_length = 0.0

    for first, second in zip(line, line[1:]):
        segment_length = math.dist(first, second)
        sample_count = max(1, math.ceil(segment_length / GEOMETRY_SAMPLE_METRES))
        sample_length = segment_length / sample_count
        for index in range(sample_count):
            fraction = (index + 0.5) / sample_count
            point = (
                first[0] + (second[0] - first[0]) * fraction,
                first[1] + (second[1] - first[1]) * fraction,
            )
            distance = point_polygon_distance(point, parking_polygon)
            if distance <= LENGTH_EPSILON_METRES:
                inside_length += sample_length
            if distance <= PARKING_BUFFER_METRES:
                near_length += sample_length

    outside_length = max(total_length - inside_length, 0.0)

    return {
        "length_m": total_length,
        "inside_length_m": inside_length,
        "outside_length_m": outside_length,
        "inside_ratio": inside_length / total_length,
        "near_ratio": near_length / total_length,
        "crosses_boundary": (
            inside_length > LENGTH_EPSILON_METRES
            and outside_length > LENGTH_EPSILON_METRES
        ),
    }


def find_direct_gate_ways(
    parking_way: OSMWay,
    data: OSMData,
    parking_polygon: list[tuple[float, float]],
    project,
) -> dict[int, dict]:
    """Find service ways sharing at least one parking boundary node."""
    candidates: dict[int, dict] = {}
    parking_nodes = set(parking_way.node_refs)

    for node_id in parking_nodes:
        for candidate_id in data.node_to_ways.get(node_id, set()):
            if candidate_id == parking_way.way_id:
                continue

            candidate = data.ways.get(candidate_id)
            if candidate is None or not is_vehicle_service_way(candidate):
                continue

            line = build_way_line(candidate, data.nodes, project)
            if line is None:
                continue

            metrics = geometry_metrics(line, parking_polygon)

            # A direct shared boundary node is already strong evidence. Keep it
            # if the road intersects the parking polygon or its small buffer.
            if metrics["near_ratio"] <= 0:
                continue

            entry = candidates.setdefault(
                candidate_id,
                {
                    "osm_way_id": candidate_id,
                    "classification": "gate",
                    "shared_boundary_nodes": [],
                    "connected_from": [],
                    "tags": candidate.tags,
                    **metrics,
                },
            )
            entry["shared_boundary_nodes"].append(node_id)

    for entry in candidates.values():
        entry["shared_boundary_nodes"] = sorted(
            set(entry["shared_boundary_nodes"])
        )

    return candidates


def find_internal_connected_ways(
    gate_ways: dict[int, dict],
    parking_way: OSMWay,
    data: OSMData,
    parking_polygon: list[tuple[float, float]],
    project,
) -> dict[int, dict]:
    """BFS from gate ways, constrained to roads spatially related to parking."""
    accepted: dict[int, dict] = dict(gate_ways)
    queue: deque[int] = deque(gate_ways)

    while queue:
        current_id = queue.popleft()
        current_way = data.ways[current_id]

        for node_id in current_way.node_refs:
            for candidate_id in data.node_to_ways.get(node_id, set()):
                if candidate_id in accepted:
                    continue
                if candidate_id == parking_way.way_id:
                    continue

                candidate = data.ways.get(candidate_id)
                if candidate is None or not is_vehicle_service_way(candidate):
                    continue

                line = build_way_line(candidate, data.nodes, project)
                if line is None:
                    continue

                metrics = geometry_metrics(line, parking_polygon)
                service_type = candidate.tags.get("service")

                # Main automatic acceptance rule:
                # - at least half of the way lies inside the parking polygon; or
                # - it is explicitly a parking aisle and lies almost entirely
                #   within the polygon's small tolerance buffer.
                accepted_by_geometry = (
                    metrics["inside_ratio"] >= MIN_INSIDE_RATIO
                    or (
                        service_type == "parking_aisle"
                        and metrics["near_ratio"] >= 0.80
                    )
                )

                if not accepted_by_geometry:
                    continue

                accepted[candidate_id] = {
                    "osm_way_id": candidate_id,
                    "classification": "internal",
                    "shared_boundary_nodes": [],
                    "connected_from": [current_id],
                    "connection_node": node_id,
                    "tags": candidate.tags,
                    **metrics,
                }
                queue.append(candidate_id)

    return accepted


def add_spatial_internal_ways(
    accepted: dict[int, dict],
    parking_way: OSMWay,
    data: OSMData,
    parking_polygon: list[tuple[float, float]],
    project,
) -> dict[int, dict]:
    """Include disconnected service aisles whose geometry is inside the lot.

    OSM parking aisles do not always share nodes with the parking polygon or
    with each other. A purely topological walk therefore misses valid lanes in
    larger parking facilities.
    """
    parking_bounds = bounds(parking_polygon)
    for candidate_id, candidate in data.ways.items():
        if candidate_id in accepted or candidate_id == parking_way.way_id:
            continue
        if not is_vehicle_service_way(candidate):
            continue
        line = build_way_line(candidate, data.nodes, project)
        if line is None:
            continue
        # This cheap rejection matters when dozens of parking polygons are
        # processed from a campus- or city-sized OSM file.
        if not bounds_overlap(bounds(line), parking_bounds, PARKING_BUFFER_METRES):
            continue
        metrics = geometry_metrics(line, parking_polygon)
        if metrics["inside_ratio"] < MIN_INSIDE_RATIO:
            continue
        accepted[candidate_id] = {
            "osm_way_id": candidate_id,
            "classification": "internal",
            "shared_boundary_nodes": [],
            "connected_from": [],
            "connection_node": None,
            "selection_method": "spatial_overlap",
            "tags": candidate.tags,
            **metrics,
        }
    return accepted


def analyse_parking_way(parking_way_id: int, data: OSMData) -> dict:
    parking_way = data.ways.get(parking_way_id)
    if parking_way is None:
        return {
            "parking_way_id": parking_way_id,
            "error": "Parking way was not found in the OSM file.",
        }

    if parking_way.tags.get("amenity") != "parking":
        return {
            "parking_way_id": parking_way_id,
            "error": (
                "The way exists but is not tagged amenity=parking. "
                f"Tags: {parking_way.tags}"
            ),
        }

    try:
        parking_polygon, project = build_parking_geometry(
            parking_way,
            data.nodes,
        )
    except ValueError as exc:
        return {
            "parking_way_id": parking_way_id,
            "error": str(exc),
        }

    gate_ways = find_direct_gate_ways(
        parking_way,
        data,
        parking_polygon,
        project,
    )

    related_ways = find_internal_connected_ways(
        gate_ways,
        parking_way,
        data,
        parking_polygon,
        project,
    )
    related_ways = add_spatial_internal_ways(
        related_ways,
        parking_way,
        data,
        parking_polygon,
        project,
    )

    gates = sorted(
        (
            details
            for details in related_ways.values()
            if details["classification"] == "gate"
        ),
        key=lambda item: item["osm_way_id"],
    )
    internal = sorted(
        (
            details
            for details in related_ways.values()
            if details["classification"] == "internal"
        ),
        key=lambda item: item["osm_way_id"],
    )

    return {
        "parking_way_id": parking_way_id,
        "parking_name": parking_way.tags.get("name"),
        "parking_tags": parking_way.tags,
        "gate_way_ids": [item["osm_way_id"] for item in gates],
        "internal_way_ids": [item["osm_way_id"] for item in internal],
        "all_related_way_ids": sorted(related_ways),
        "gate_ways": gates,
        "internal_ways": internal,
    }


def print_result(result: dict) -> None:
    print("\n" + "=" * 72)
    print(f"Parking OSM way: {result['parking_way_id']}")

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    print(f"Name: {result.get('parking_name') or '(unnamed)'}")

    print("\nDirect gate/access ways:")
    if not result["gate_ways"]:
        print("  None found")
    else:
        for item in result["gate_ways"]:
            print(
                f"  - {item['osm_way_id']} "
                f"shared_nodes={item['shared_boundary_nodes']} "
                f"inside_ratio={item['inside_ratio']:.2f} "
                f"service={item['tags'].get('service')}"
            )

    print("\nConnected internal service ways:")
    if not result["internal_ways"]:
        print("  None found")
    else:
        for item in result["internal_ways"]:
            print(
                f"  - {item['osm_way_id']} "
                f"connected_from={item['connected_from']} "
                f"inside_ratio={item['inside_ratio']:.2f} "
                f"service={item['tags'].get('service')}"
            )

    print("\nAll related way IDs:")
    print("  " + ", ".join(map(str, result["all_related_way_ids"])))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find OSM service-road ways associated with parking polygons."
        )
    )
    parser.add_argument(
        "--osm",
        type=Path,
        required=True,
        help="Path to .osm.xml or .osm.xml.gz",
    )
    parser.add_argument(
        "--parking-ids",
        type=int,
        nargs="+",
        required=True,
        help="One or more OSM parking way IDs.",
    )
    parser.add_argument(
        "--save",
        nargs="?",
        const=DEFAULT_OUTPUT_FILE,
        default=None,
        metavar="OUTPUT.json",
        help=(
            "Save results to JSON. Optionally provide a filename; otherwise "
            f"{DEFAULT_OUTPUT_FILE!r} is used."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.osm.exists():
        raise FileNotFoundError(
            f"OSM file not found: {args.osm.resolve()}"
        )

    print(f"Reading: {args.osm}")
    data = load_osm(args.osm)
    print(
        f"Loaded {len(data.nodes):,} nodes and "
        f"{len(data.ways):,} ways."
    )

    results = []
    for parking_way_id in args.parking_ids:
        result = analyse_parking_way(parking_way_id, data)
        results.append(result)
        print_result(result)

    if args.save:
        output_path = Path(args.save)
        output_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nSaved results to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
