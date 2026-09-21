#!/usr/bin/env python3
"""Developer tool for creating an Overpass query from parking JSON."""

import argparse
import json
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create an Overpass Turbo query from saved OSM parking way JSON."
    )
    parser.add_argument(
        "json_file",
        help="JSON file produced by list_osm_parking_ways.py"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output/parking_ways.overpassql",
        help="Output Overpass query file"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    json_path = Path(args.json_file)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    way_ids = [
        str(item["id"])
        for item in data
        if item.get("type") == "way" and item.get("id")
    ]

    if not way_ids:
        raise SystemExit("No way IDs found in JSON file.")

    ids_text = ",".join(way_ids)

    query = f"""[out:json][timeout:60];

(
  way(id:{ids_text});
);

out body geom;
"""

    output_path.write_text(query, encoding="utf-8")

    print(f"Wrote Overpass query: {output_path}")
    print(f"Way count: {len(way_ids)}")


if __name__ == "__main__":
    main()
