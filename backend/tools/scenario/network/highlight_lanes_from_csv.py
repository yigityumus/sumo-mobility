#!/usr/bin/env python3
"""Developer tool for highlighting SUMO lanes listed in a CSV file."""

import argparse
import csv
import gzip
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_LANE_COLUMNS = [
    "lane",
    "lane_id",
    "laneID",
    "Lane ID",
    "SUMO lane",
    "sumo_lane",
]


def open_xml(path):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")


def lane_allows_vclass(lane_elem, vclass):
    allow = lane_elem.get("allow", "").split()
    disallow = lane_elem.get("disallow", "").split()

    if allow:
        return vclass in allow

    if disallow:
        return vclass not in disallow

    return True


def parse_shape(shape_text):
    points = []

    for pair in shape_text.split():
        x, y = pair.split(",")
        points.append((float(x), float(y)))

    return points


def midpoint_from_shape(shape_text):
    points = parse_shape(shape_text)

    if not points:
        return 0.0, 0.0

    return points[len(points) // 2]


def load_lanes_from_net(net_file):
    with open_xml(net_file) as f:
        root = ET.parse(f).getroot()

    lanes = {}

    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")

        if edge_id.startswith(":"):
            continue

        for lane in edge.findall("lane"):
            lane_id = lane.get("id")

            if lane_id:
                lanes[lane_id] = {
                    "edge_id": edge_id,
                    "lane_id": lane_id,
                    "elem": lane,
                    "shape": lane.get("shape", ""),
                    "length": lane.get("length", ""),
                    "allow": lane.get("allow", ""),
                    "disallow": lane.get("disallow", ""),
                }

    return lanes


def detect_lane_column(fieldnames):
    for col in DEFAULT_LANE_COLUMNS:
        if col in fieldnames:
            return col

    return None


def read_lane_ids_from_csv(csv_file, lane_column):
    csv_file = Path(csv_file)

    with csv_file.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise SystemExit("Error: CSV file has no header row.")

        if lane_column is None:
            lane_column = detect_lane_column(reader.fieldnames)

        if lane_column is None:
            print("Could not auto-detect lane column.")
            print("Available columns:")
            for col in reader.fieldnames:
                print(f"  - {col}")
            raise SystemExit(
                "Use --lane-column COLUMN_NAME to specify the lane ID column."
            )

        if lane_column not in reader.fieldnames:
            raise SystemExit(f"Error: column not found in CSV: {lane_column}")

        lane_ids = []

        for row in reader:
            value = row.get(lane_column, "").strip()

            if not value:
                continue

            # Support cells like: 39980931#11_0, -39980931#11_0
            # Also support accidental whitespace or semicolon lists.
            for token in value.replace(";", ",").split(","):
                token = token.strip()
                if token:
                    lane_ids.append(token)

    # Preserve order, remove duplicates.
    seen = set()
    unique_lane_ids = []

    for lane_id in lane_ids:
        if lane_id not in seen:
            seen.add(lane_id)
            unique_lane_ids.append(lane_id)

    return unique_lane_ids, lane_column


def safe_xml_id(text):
    return (
        text.replace("#", "_")
        .replace("-", "minus_")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
    )


def write_overlay(
    output_file,
    report_file,
    lane_ids,
    net_lanes,
    vclass,
    passenger_color,
    non_passenger_color,
    width,
    add_labels,
):
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if report_file:
        report_file = Path(report_file)
        report_file.parent.mkdir(parents=True, exist_ok=True)

    found = 0
    missing = 0
    allowed_count = 0
    not_allowed_count = 0

    report_rows = []

    with output_file.open("w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<additional>\n")

        for lane_id in lane_ids:
            lane_info = net_lanes.get(lane_id)

            if lane_info is None:
                missing += 1
                report_rows.append({
                    "lane_id": lane_id,
                    "edge_id": "",
                    "exists_in_net": "no",
                    "allows_vclass": "",
                    "vclass": vclass,
                    "length": "",
                    "allow": "",
                    "disallow": "",
                })
                continue

            found += 1

            lane_elem = lane_info["elem"]
            shape = lane_info["shape"]

            if not shape:
                continue

            allows = lane_allows_vclass(lane_elem, vclass)

            if allows:
                color = passenger_color
                allowed_count += 1
                status = "allows"
            else:
                color = non_passenger_color
                not_allowed_count += 1
                status = "does_not_allow"

            xml_id = safe_xml_id(lane_id)

            lane_width = float(lane_elem.get("width", width))
            highlight_width = lane_width * 0.25

            f.write(
                f'    <poly id="highlight_{xml_id}" '
                f'color="{color}" '
                f'fill="false" '
                f'layer="100" '
                f'lineWidth="{highlight_width}" '
                f'shape="{shape}"/>\n'
            )

            if add_labels:
                x, y = midpoint_from_shape(shape)

                # The POI id is the lane label. In sumo-gui, enable POI names/IDs
                # if labels are not visible by default.
                f.write(
                    f'    <poi id="lane_{xml_id}" '
                    f'type="{status}_{vclass}" '
                    f'color="{color}" '
                    f'layer="101" '
                    f'x="{x:.2f}" '
                    f'y="{y:.2f}"/>\n'
                )

            report_rows.append({
                "lane_id": lane_id,
                "edge_id": lane_info["edge_id"],
                "exists_in_net": "yes",
                "allows_vclass": "yes" if allows else "no",
                "vclass": vclass,
                "length": lane_info["length"],
                "allow": lane_info["allow"],
                "disallow": lane_info["disallow"],
            })

        f.write("</additional>\n")

    if report_file:
        with report_file.open("w", encoding="utf-8", newline="") as f:
            fieldnames = [
                "lane_id",
                "edge_id",
                "exists_in_net",
                "allows_vclass",
                "vclass",
                "length",
                "allow",
                "disallow",
            ]

            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)

    print(f"Wrote overlay: {output_file}")

    if report_file:
        print(f"Wrote report:  {report_file}")

    print()
    print(f"Input lane IDs:         {len(lane_ids)}")
    print(f"Found in network:       {found}")
    print(f"Missing from network:   {missing}")
    print(f"Allows {vclass}:        {allowed_count}")
    print(f"Does not allow {vclass}: {not_allowed_count}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Highlight lanes from a CSV in SUMO GUI. "
            "Blue if lane allows passenger, red if not."
        )
    )

    parser.add_argument(
        "--csv",
        required=True,
        help="CSV file containing lane IDs."
    )

    parser.add_argument(
        "--net-file",
        required=True,
        help="SUMO network file, e.g. network/net/<source_name>.net.xml.gz"
    )

    parser.add_argument(
        "--lane-column",
        default=None,
        help="CSV column containing lane IDs. If omitted, script tries to auto-detect."
    )

    parser.add_argument(
        "--vclass",
        default="passenger",
        help="Vehicle class to test. Default: passenger"
    )

    parser.add_argument(
        "--output",
        default="network/config/highlight_csv_lanes.add.xml",
        help="Output SUMO additional file."
    )

    parser.add_argument(
        "--report",
        default="output/highlight_csv_lanes_report.csv",
        help="Output report CSV."
    )

    parser.add_argument(
        "--passenger-color",
        default="blue",
        help="Color for lanes that allow the vClass. Default: blue."
    )

    parser.add_argument(
        "--non-passenger-color",
        default="red",
        help="Color for lanes that do not allow the vClass. Default: red."
    )

    parser.add_argument(
        "--width",
        default="4",
        help="Overlay line width. Default: 4."
    )

    parser.add_argument(
        "--no-labels",
        action="store_true",
        help="Do not add POI labels for lane IDs."
    )

    args = parser.parse_args()

    net_lanes = load_lanes_from_net(args.net_file)
    lane_ids, detected_column = read_lane_ids_from_csv(args.csv, args.lane_column)

    print(f"Using lane column: {detected_column}")
    print(f"Loaded {len(net_lanes)} lanes from network.")

    write_overlay(
        output_file=args.output,
        report_file=args.report,
        lane_ids=lane_ids,
        net_lanes=net_lanes,
        vclass=args.vclass,
        passenger_color=args.passenger_color,
        non_passenger_color=args.non_passenger_color,
        width=args.width,
        add_labels=not args.no_labels,
    )


if __name__ == "__main__":
    main()
