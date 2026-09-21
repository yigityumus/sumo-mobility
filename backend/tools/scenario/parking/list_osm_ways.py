#!/usr/bin/env python3
"""Developer tool for listing parking-related ways in an OSM extract."""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="List all OSM way IDs tagged with amenity=parking."
    )

    parser.add_argument(
        "osm_file",
        help="Path to the .osm file"
    )

    parser.add_argument(
        "--save",
        nargs="?",
        const=True,
        default=False,
        help=(
            "Save results as JSON. "
            "Use '--save' for automatic filename, or '--save output.json'."
        )
    )

    return parser.parse_args()


def validate_osm_file(path: Path):
    if not path.exists():
        print(f"Error: file does not exist: {path}", file=sys.stderr)
        sys.exit(1)

    if path.suffix.lower() != ".osm":
        print("Error: input file must have .osm extension", file=sys.stderr)
        sys.exit(1)

    if not path.is_file():
        print(f"Error: not a file: {path}", file=sys.stderr)
        sys.exit(1)


def get_tags(element):
    return {
        tag.get("k"): tag.get("v")
        for tag in element.findall("tag")
        if tag.get("k") is not None
    }


def find_parking_ways(osm_file: Path):
    try:
        tree = ET.parse(osm_file)
    except ET.ParseError as e:
        print(f"Error: could not parse XML: {e}", file=sys.stderr)
        sys.exit(1)

    root = tree.getroot()
    results = []

    for way in root.findall("way"):
        tags = get_tags(way)

        if tags.get("amenity") != "parking":
            continue

        way_id = way.get("id")
        name = tags.get("name", "")

        result = {
            "index": len(results) + 1,
            "type": "way",
            "id": way_id,
            "name": name,
            "access": tags.get("access", ""),
            "capacity": tags.get("capacity", ""),
            "fee": tags.get("fee", ""),
            "parking": tags.get("parking", ""),
            "surface": tags.get("surface", ""),
            "node_count": len(way.findall("nd")),
            "url": f"https://www.openstreetmap.org/way/{way_id}",
        }

        results.append(result)

    return results


def print_table(results):
    if not results:
        print("No OSM ways with amenity=parking were found.")
        return

    columns = [
        ("#", "index"),
        ("Way ID", "id"),
        ("Name", "name"),
        ("Access", "access"),
        ("Capacity", "capacity"),
        ("Fee", "fee"),
        ("Parking", "parking"),
        ("Surface", "surface"),
        ("Nodes", "node_count"),
        ("URL", "url"),
    ]

    widths = {}

    for header, key in columns:
        max_data_width = max(len(str(row.get(key, ""))) for row in results)
        widths[key] = max(len(header), max_data_width)

    header_line = " | ".join(
        header.ljust(widths[key]) for header, key in columns
    )

    separator_line = "-+-".join(
        "-" * widths[key] for _, key in columns
    )

    print(f"\nFound {len(results)} OSM way(s) with amenity=parking.\n")
    print(header_line)
    print(separator_line)

    for row in results:
        print(
            " | ".join(
                str(row.get(key, "")).ljust(widths[key])
                for _, key in columns
            )
        )


def save_json(results, osm_file: Path, save_arg):
    if save_arg is False:
        return

    if save_arg is True:
        output_path = osm_file.with_name(osm_file.stem + "_parking_ways.json")
    else:
        output_path = Path(save_arg)

        if output_path.suffix.lower() != ".json":
            print("Error: save file must have .json extension", file=sys.stderr)
            sys.exit(1)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved JSON to: {output_path}")


def main():
    args = parse_args()
    osm_file = Path(args.osm_file)

    validate_osm_file(osm_file)

    results = find_parking_ways(osm_file)
    print_table(results)
    save_json(results, osm_file, args.save)


if __name__ == "__main__":
    main()
