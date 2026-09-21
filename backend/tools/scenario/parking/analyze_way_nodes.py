#!/usr/bin/env python3
"""Developer tool for inspecting OSM nodes associated with parking ways."""

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


ROAD_TAGS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "living_street",
    "road", "track"
}

ACCESS_ROAD_SERVICES = {
    "parking_aisle", "driveway", "alley", "drive-through"
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze nodes of selected OSM parking ways. "
            "For each parking way, shows which boundary nodes are shared "
            "with roads, access roads, barriers, entrances, or other objects."
        )
    )

    parser.add_argument(
        "osm_file",
        help="Path to .osm file"
    )

    parser.add_argument(
        "--ways",
        nargs="+",
        required=True,
        help="Parking way IDs to analyze, e.g. --ways 32707693 32707694"
    )

    parser.add_argument(
        "--json",
        default=None,
        help="Optional JSON output path"
    )

    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV output path"
    )

    return parser.parse_args()


def get_tags(elem):
    return {
        tag.get("k"): tag.get("v")
        for tag in elem.findall("tag")
        if tag.get("k") is not None
    }


def classify_way(tags):
    highway = tags.get("highway")
    service = tags.get("service")
    amenity = tags.get("amenity")
    barrier = tags.get("barrier")
    entrance = tags.get("entrance")
    access = tags.get("access")

    if amenity == "parking":
        return "parking_area"

    if highway in ROAD_TAGS:
        if highway == "service" and service in ACCESS_ROAD_SERVICES:
            return "access_road"
        if highway == "service":
            return "service_road"
        return "road"

    if barrier:
        return "barrier"

    if entrance:
        return "entrance"

    if access:
        return "access_tagged_object"

    return "other_way"


def classify_node(node_tags, connected_way_infos):
    if node_tags.get("entrance"):
        return "explicit_entrance_node"

    if node_tags.get("barrier"):
        return "barrier_node"

    if node_tags.get("amenity") == "parking":
        return "parking_node"

    connected_classes = {info["class"] for info in connected_way_infos}

    if "access_road" in connected_classes:
        return "shared_with_access_road"

    if "service_road" in connected_classes:
        return "shared_with_service_road"

    if "road" in connected_classes:
        return "shared_with_road"

    if "barrier" in connected_classes:
        return "shared_with_barrier"

    if "entrance" in connected_classes:
        return "shared_with_entrance"

    if len(connected_way_infos) > 1:
        return "shared_with_other_way"

    return "parking_polygon_boundary_only"


def main():
    args = parse_args()
    osm_path = Path(args.osm_file)

    if not osm_path.exists():
        print(f"Error: file does not exist: {osm_path}", file=sys.stderr)
        sys.exit(1)

    if osm_path.suffix.lower() != ".osm":
        print("Error: input file must be a .osm file", file=sys.stderr)
        sys.exit(1)

    selected_way_ids = set(str(w) for w in args.ways)

    print(f"Loading OSM file: {osm_path}")

    try:
        root = ET.parse(osm_path).getroot()
    except ET.ParseError as e:
        print(f"Error: could not parse OSM XML: {e}", file=sys.stderr)
        sys.exit(1)

    nodes = {}
    ways = {}
    node_to_ways = defaultdict(list)

    for elem in root:
        if elem.tag == "node":
            nodes[elem.get("id")] = {
                "id": elem.get("id"),
                "lat": elem.get("lat"),
                "lon": elem.get("lon"),
                "tags": get_tags(elem),
            }

        elif elem.tag == "way":
            way_id = elem.get("id")
            refs = [nd.get("ref") for nd in elem.findall("nd")]
            tags = get_tags(elem)

            ways[way_id] = {
                "id": way_id,
                "refs": refs,
                "tags": tags,
                "class": classify_way(tags),
            }

            for ref in refs:
                node_to_ways[ref].append(way_id)

    results = []

    for parking_way_id in sorted(selected_way_ids, key=lambda x: int(x) if x.isdigit() else x):
        parking_way = ways.get(parking_way_id)

        if parking_way is None:
            print(f"\nWARNING: way {parking_way_id} not found in OSM file")
            continue

        tags = parking_way["tags"]

        if tags.get("amenity") != "parking":
            print(
                f"\nWARNING: way {parking_way_id} exists, but is not tagged amenity=parking"
            )

        parking_name = tags.get("name", "")
        parking_url = f"https://www.openstreetmap.org/way/{parking_way_id}"

        print("\n" + "=" * 120)
        print(f"Parking way: {parking_way_id}")
        print(f"Name: {parking_name if parking_name else '(no name)'}")
        print(f"URL: {parking_url}")
        print(f"Tags: access={tags.get('access', '')}, parking={tags.get('parking', '')}, "
              f"fee={tags.get('fee', '')}, surface={tags.get('surface', '')}, "
              f"capacity={tags.get('capacity', '')}")
        print(f"Boundary node count: {len(parking_way['refs'])}")
        print("-" * 120)

        rows = []

        for order, node_id in enumerate(parking_way["refs"], start=1):
            node = nodes.get(node_id, {
                "id": node_id,
                "lat": "",
                "lon": "",
                "tags": {},
            })

            connected_way_ids = node_to_ways.get(node_id, [])

            connected_infos = []
            for connected_way_id in connected_way_ids:
                if connected_way_id == parking_way_id:
                    continue

                connected_way = ways.get(connected_way_id)
                if connected_way is None:
                    continue

                connected_tags = connected_way["tags"]
                connected_class = connected_way["class"]

                connected_infos.append({
                    "id": connected_way_id,
                    "class": connected_class,
                    "highway": connected_tags.get("highway", ""),
                    "service": connected_tags.get("service", ""),
                    "amenity": connected_tags.get("amenity", ""),
                    "name": connected_tags.get("name", ""),
                    "access": connected_tags.get("access", ""),
                    "url": f"https://www.openstreetmap.org/way/{connected_way_id}",
                })

            node_role = classify_node(node["tags"], connected_infos)

            connected_summary_parts = []
            for info in connected_infos:
                label_parts = [f"way {info['id']}", info["class"]]

                if info["highway"]:
                    label_parts.append(f"highway={info['highway']}")

                if info["service"]:
                    label_parts.append(f"service={info['service']}")

                if info["amenity"]:
                    label_parts.append(f"amenity={info['amenity']}")

                if info["name"]:
                    label_parts.append(f"name={info['name']}")

                connected_summary_parts.append(" ".join(label_parts))

            connected_summary = "; ".join(connected_summary_parts)

            node_tag_summary = ", ".join(
                f"{k}={v}" for k, v in node["tags"].items()
            )

            row = {
                "parking_way_id": parking_way_id,
                "parking_name": parking_name,
                "parking_url": parking_url,
                "node_order": order,
                "node_id": node_id,
                "lat": node.get("lat", ""),
                "lon": node.get("lon", ""),
                "node_role": node_role,
                "node_tags": node_tag_summary,
                "connected_ways": connected_summary,
                "node_url": f"https://www.openstreetmap.org/node/{node_id}",
            }

            rows.append(row)
            results.append(row)

        print_table(rows)

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)

        with json_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\nSaved JSON: {json_path}")

    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "parking_way_id",
            "parking_name",
            "parking_url",
            "node_order",
            "node_id",
            "lat",
            "lon",
            "node_role",
            "node_tags",
            "connected_ways",
            "node_url",
        ]

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"Saved CSV: {csv_path}")


def print_table(rows):
    if not rows:
        print("No nodes found.")
        return

    columns = [
        ("#", "node_order", 4),
        ("Node ID", "node_id", 14),
        ("Role", "node_role", 30),
        ("Node tags", "node_tags", 32),
        ("Connected ways", "connected_ways", 70),
    ]

    def shorten(text, max_width):
        text = str(text or "")
        if len(text) <= max_width:
            return text
        return text[: max_width - 3] + "..."

    header = " | ".join(title.ljust(width) for title, _, width in columns)
    sep = "-+-".join("-" * width for _, _, width in columns)

    print(header)
    print(sep)

    for row in rows:
        print(
            " | ".join(
                shorten(row.get(key, ""), width).ljust(width)
                for _, key, width in columns
            )
        )


if __name__ == "__main__":
    main()
