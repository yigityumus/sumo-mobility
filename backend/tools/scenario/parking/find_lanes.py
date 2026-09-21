#!/usr/bin/env python3
"""Developer tool for finding SUMO lanes near an OSM parking polygon."""

import argparse
import csv
import gzip
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def ensure_sumo_tools():
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        raise RuntimeError(
            "SUMO_HOME is not set. Run:\n"
            "export SUMO_HOME=/usr/share/sumo\n"
            "export PYTHONPATH=$SUMO_HOME/tools:$PYTHONPATH"
        )

    tools_path = Path(sumo_home) / "tools"
    if str(tools_path) not in sys.path:
        sys.path.append(str(tools_path))


ensure_sumo_tools()

import sumolib  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Find SUMO lanes inside or near an OSM parking polygon."
    )

    parser.add_argument(
        "--osm",
        required=True,
        help="Path to a model/run .osm or .osm.xml.gz file"
    )

    parser.add_argument(
        "--net",
        required=True,
        help="Path to a model/run SUMO .net.xml.gz file"
    )

    parser.add_argument(
        "--parking-way",
        required=True,
        help="OSM parking way ID, e.g. 32707693"
    )

    parser.add_argument(
        "--near-distance",
        type=float,
        default=10.0,
        help="Also include lanes within this distance from polygon boundary, in meters. Default: 10"
    )

    parser.add_argument(
        "--min-length",
        type=float,
        default=3.0,
        help="Minimum lane length to include. Default: 3 m"
    )

    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV output path"
    )

    parser.add_argument(
        "--json",
        default=None,
        help="Optional JSON output path"
    )

    return parser.parse_args()


def open_xml(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def tags_of(elem):
    return {
        tag.get("k"): tag.get("v")
        for tag in elem.findall("tag")
        if tag.get("k") is not None
    }


def load_osm_parking_polygon(osm_path: Path, parking_way_id: str):
    with open_xml(osm_path) as f:
        root = ET.parse(f).getroot()

    nodes = {}
    parking_way = None

    for elem in root:
        if elem.tag == "node":
            nodes[elem.get("id")] = {
                "lat": float(elem.get("lat")),
                "lon": float(elem.get("lon")),
                "tags": tags_of(elem),
            }

        elif elem.tag == "way" and elem.get("id") == parking_way_id:
            parking_way = elem

    if parking_way is None:
        raise SystemExit(f"Parking way {parking_way_id} not found in {osm_path}")

    parking_tags = tags_of(parking_way)

    if parking_tags.get("amenity") != "parking":
        print(
            f"WARNING: way {parking_way_id} does not have amenity=parking. "
            f"Tags: {parking_tags}"
        )

    refs = [nd.get("ref") for nd in parking_way.findall("nd")]

    lonlat_polygon = []
    for ref in refs:
        if ref not in nodes:
            raise SystemExit(f"Node {ref} referenced by way {parking_way_id} not found")
        lonlat_polygon.append((nodes[ref]["lon"], nodes[ref]["lat"]))

    return parking_tags, refs, lonlat_polygon


def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    n = len(polygon)

    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]

        if ((y1 > y) != (y2 > y)):
            x_intersect = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < x_intersect:
                inside = not inside

    return inside


def distance_point_to_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b

    dx = bx - ax
    dy = by - ay

    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))

    closest_x = ax + t * dx
    closest_y = ay + t * dy

    return math.hypot(px - closest_x, py - closest_y)


def distance_point_to_polygon(point, polygon):
    if point_in_polygon(point, polygon):
        return 0.0

    distances = []
    for i in range(len(polygon)):
        a = polygon[i]
        b = polygon[(i + 1) % len(polygon)]
        distances.append(distance_point_to_segment(point, a, b))

    return min(distances)


def sample_lane_points(shape):
    points = list(shape)

    for a, b in zip(shape, shape[1:]):
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        points.append(mid)

    return points


def lane_allows(lane, vehicle_class):
    try:
        return vehicle_class in lane.getPermissions()
    except Exception:
        return None


def classify_lane(shape, polygon_xy, near_distance):
    points = sample_lane_points(shape)

    inside_count = sum(point_in_polygon(p, polygon_xy) for p in points)
    min_distance = min(distance_point_to_polygon(p, polygon_xy) for p in points)

    if inside_count > 0:
        return "inside_polygon", min_distance

    if min_distance <= near_distance:
        return "near_polygon", min_distance

    return "outside", min_distance


def main():
    args = parse_args()

    osm_path = Path(args.osm)
    net_path = Path(args.net)
    parking_way_id = str(args.parking_way)

    parking_tags, node_refs, lonlat_polygon = load_osm_parking_polygon(
        osm_path, parking_way_id
    )

    net = sumolib.net.readNet(str(net_path))

    polygon_xy = [
        net.convertLonLat2XY(lon, lat)
        for lon, lat in lonlat_polygon
    ]

    results = []

    for edge in net.getEdges():
        edge_id = edge.getID()

        if edge_id.startswith(":"):
            continue

        for lane in edge.getLanes():
            lane_id = lane.getID()
            length = float(lane.getLength())

            if length < args.min_length:
                continue

            shape = lane.getShape()
            if not shape:
                continue

            role, min_distance = classify_lane(
                shape,
                polygon_xy,
                args.near_distance
            )

            if role == "outside":
                continue

            result = {
                "parking_way_id": parking_way_id,
                "parking_name": parking_tags.get("name", ""),
                "edge_id": edge_id,
                "lane_id": lane_id,
                "role": role,
                "distance_m": round(min_distance, 2),
                "length_m": round(length, 2),
                "allows_passenger": lane_allows(lane, "passenger"),
                "allows_delivery": lane_allows(lane, "delivery"),
                "allows_bicycle": lane_allows(lane, "bicycle"),
                "osm_parking_url": f"https://www.openstreetmap.org/way/{parking_way_id}",
            }

            results.append(result)

    results.sort(key=lambda r: (r["role"] != "inside_polygon", r["distance_m"], -r["length_m"]))

    print()
    print(f"Parking way: {parking_way_id}")
    print(f"Name: {parking_tags.get('name', '(no name)')}")
    print(f"OSM URL: https://www.openstreetmap.org/way/{parking_way_id}")
    print(f"Boundary nodes: {len(node_refs)}")
    print(f"Candidate lanes found: {len(results)}")
    print()

    print_table(results)

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)

        with out.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "parking_way_id",
                "parking_name",
                "edge_id",
                "lane_id",
                "role",
                "distance_m",
                "length_m",
                "allows_passenger",
                "allows_delivery",
                "allows_bicycle",
                "osm_parking_url",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"\nSaved CSV: {out}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)

        with out.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"Saved JSON: {out}")


def print_table(rows):
    if not rows:
        print("No candidate lanes found.")
        return

    columns = [
        ("#", 4, lambda i, r: str(i)),
        ("Lane ID", 24, lambda i, r: r["lane_id"]),
        ("Edge ID", 20, lambda i, r: r["edge_id"]),
        ("Role", 16, lambda i, r: r["role"]),
        ("Dist m", 8, lambda i, r: str(r["distance_m"])),
        ("Len m", 8, lambda i, r: str(r["length_m"])),
        ("Passenger", 10, lambda i, r: str(r["allows_passenger"])),
        ("Delivery", 10, lambda i, r: str(r["allows_delivery"])),
    ]

    def shorten(text, width):
        text = str(text)
        return text if len(text) <= width else text[: width - 3] + "..."

    header = " | ".join(name.ljust(width) for name, width, _ in columns)
    sep = "-+-".join("-" * width for _, width, _ in columns)

    print(header)
    print(sep)

    for i, row in enumerate(rows, start=1):
        print(
            " | ".join(
                shorten(fn(i, row), width).ljust(width)
                for _, width, fn in columns
            )
        )


if __name__ == "__main__":
    main()
