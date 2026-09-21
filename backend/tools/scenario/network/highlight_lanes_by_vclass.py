#!/usr/bin/env python3
"""Developer tool for highlighting SUMO lanes by vehicle class."""

import argparse
import gzip
import xml.etree.ElementTree as ET
from pathlib import Path


def open_xml(path):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")


def lane_allows_class(lane, vclass):
    allow = lane.get("allow", "").split()
    disallow = lane.get("disallow", "").split()

    if allow:
        return vclass in allow

    if disallow:
        return vclass not in disallow

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Create a SUMO additional file that highlights lanes allowing a given vClass."
    )

    parser.add_argument(
        "-n", "--net-file",
        required=True,
        help="SUMO network file, e.g. network/net/<source_name>.net.xml.gz"
    )

    parser.add_argument(
        "-c", "--vclass",
        required=True,
        help="Vehicle class to highlight, e.g. delivery, passenger, bicycle"
    )

    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output additional file, e.g. network/config/highlight_delivery_lanes.add.xml"
    )

    parser.add_argument(
        "--color",
        default="red",
        help="Highlight color. Default: red"
    )

    parser.add_argument(
        "--width",
        default="3",
        help="Line width. Default: 3"
    )

    args = parser.parse_args()

    with open_xml(args.net_file) as f:
        root = ET.parse(f).getroot()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0

    with output_path.open("w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<additional>\n")

        for edge in root.findall("edge"):
            edge_id = edge.get("id", "")
            if edge_id.startswith(":"):
                continue

            for lane in edge.findall("lane"):
                lane_id = lane.get("id")
                shape = lane.get("shape")

                if not lane_id or not shape:
                    continue

                if not lane_allows_class(lane, args.vclass):
                    continue

                poly_id = f"highlight_{args.vclass}_{lane_id}"

                f.write(
                    f'    <poly id="{poly_id}" '
                    f'color="{args.color}" '
                    f'fill="false" '
                    f'layer="100" '
                    f'lineWidth="{args.width}" '
                    f'shape="{shape}"/>\n'
                )

                count += 1

        f.write("</additional>\n")

    print(f"Highlighted {count} lane(s) allowing vClass='{args.vclass}'")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
