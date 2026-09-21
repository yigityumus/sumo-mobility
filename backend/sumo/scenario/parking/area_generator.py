"""Generate physical SUMO parkingArea objects from discovered lane IDs."""

from __future__ import annotations

import csv
import gzip
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def open_xml(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def get_tags(element: ET.Element) -> dict[str, str]:
    return {
        str(tag.get("k")): str(tag.get("v"))
        for tag in element.findall("tag")
        if tag.get("k") is not None and tag.get("v") is not None
    }


def load_net_lanes(net_file: Path) -> dict[str, dict[str, str | float]]:
    with open_xml(net_file) as handle:
        root = ET.parse(handle).getroot()

    lanes: dict[str, dict[str, str | float]] = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if edge_id.startswith(":"):
            continue
        for lane in edge.findall("lane"):
            lane_id = lane.get("id")
            if not lane_id:
                continue
            lanes[lane_id] = {
                "lane_id": lane_id,
                "edge_id": edge_id,
                "length": float(lane.get("length", "0")),
                "allow": lane.get("allow", ""),
                "disallow": lane.get("disallow", ""),
            }
    return lanes


def load_osm_capacity(osm_file: Path | None, osm_way_id: str | None) -> int | None:
    if osm_file is None or osm_way_id is None:
        return None

    with open_xml(osm_file) as handle:
        root = ET.parse(handle).getroot()
    for way in root.findall("way"):
        if way.get("id") != str(osm_way_id):
            continue
        capacity = get_tags(way).get("capacity")
        if not capacity:
            return None
        try:
            return int(float(capacity))
        except ValueError:
            print(
                f"Warning: capacity tag exists but is not numeric: {capacity}",
                file=sys.stderr,
            )
            return None
    return None


def distribute_capacity_by_length(
    lane_ids: list[str],
    net_lanes: dict[str, dict[str, str | float]],
    total_capacity: int,
) -> dict[str, int]:
    lengths = [float(net_lanes[lane_id]["length"]) for lane_id in lane_ids]
    total_length = sum(lengths)
    if total_length <= 0:
        return {lane_id: 1 for lane_id in lane_ids}

    raw = [
        (lane_id, total_capacity * float(net_lanes[lane_id]["length"]) / total_length)
        for lane_id in lane_ids
    ]
    capacities: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    for lane_id, value in raw:
        base = max(1, math.floor(value))
        capacities[lane_id] = base
        remainders.append((value - base, lane_id))

    current_total = sum(capacities.values())
    if current_total < total_capacity:
        remainders.sort(reverse=True)
        while current_total < total_capacity:
            for _remainder, lane_id in remainders:
                if current_total >= total_capacity:
                    break
                capacities[lane_id] += 1
                current_total += 1
    elif current_total > total_capacity:
        remainders.sort()
        for _remainder, lane_id in remainders:
            if current_total <= total_capacity:
                break
            removable = min(capacities[lane_id] - 1, current_total - total_capacity)
            capacities[lane_id] -= removable
            current_total -= removable

    return capacities


def estimate_capacity_by_lane_length(
    lane_ids: list[str],
    net_lanes: dict[str, dict[str, str | float]],
    parking_space_length: float,
) -> dict[str, int]:
    return {
        lane_id: max(1, int(float(net_lanes[lane_id]["length"]) // parking_space_length))
        for lane_id in lane_ids
    }


def safe_id(text: str) -> str:
    return (
        text.replace("-", "minus_")
        .replace("#", "_")
        .replace(":", "_")
        .replace(".", "_")
        .replace("/", "_")
    )


def write_parking_add_xml(
    output_file: Path,
    lane_ids: list[str],
    net_lanes: dict[str, dict[str, str | float]],
    capacities: dict[str, int],
    parking_prefix: str,
    parking_name: str,
    osm_way_id: str | None,
    capacity_source: str,
    capacity_source_detail: str,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("additional")
    for index, lane_id in enumerate(lane_ids, start=1):
        lane_info = net_lanes[lane_id]
        root.append(ET.Comment(
            f" osm_way_id={osm_way_id}; edge={lane_info['edge_id']}; "
            f"lane_length={float(lane_info['length']):.2f}; "
            f"capacity={capacities[lane_id]}; capacity_source={capacity_source}; "
            f"capacity_source_detail={capacity_source_detail} "
        ))
        ET.SubElement(root, "parkingArea", {
            "id": f"{parking_prefix}_{index:03d}_{safe_id(lane_id)}",
            "name": f"{parking_name} {index:03d}",
            "lane": lane_id,
            "startPos": "0",
            "endPos": "-1",
            "roadsideCapacity": str(capacities[lane_id]),
        })

    ET.indent(root, space="    ")
    ET.ElementTree(root).write(
        output_file,
        encoding="UTF-8",
        xml_declaration=True,
    )


def write_report_csv(
    report_file: Path,
    lane_ids: list[str],
    net_lanes: dict[str, dict[str, str | float]],
    capacities: dict[str, int],
    capacity_source: str,
    capacity_source_detail: str,
) -> None:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with report_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "parking_id_suffix", "lane_id", "edge_id", "length", "capacity",
            "capacity_source", "capacity_source_detail", "allow", "disallow",
        ])
        for index, lane_id in enumerate(lane_ids, start=1):
            lane_info = net_lanes[lane_id]
            writer.writerow([
                f"{index:03d}", lane_id, lane_info["edge_id"],
                f"{float(lane_info['length']):.2f}", capacities[lane_id],
                capacity_source, capacity_source_detail,
                lane_info["allow"], lane_info["disallow"],
            ])


def generate_parking_from_lane_ids(
    *,
    lane_ids: list[str],
    net_lanes: dict[str, dict[str, str | float]],
    osm_file: Path | None,
    osm_way_id: str | None,
    parking_prefix: str,
    parking_name: str,
    parking_space_length: float,
    user_capacity: int | None,
    output_file: Path,
    report_file: Path,
) -> dict[str, str | int]:
    missing_lane_ids = [lane_id for lane_id in lane_ids if lane_id not in net_lanes]
    if missing_lane_ids:
        raise ValueError(
            f"Discovered lanes are missing from the SUMO network: {missing_lane_ids}"
        )
    if not lane_ids:
        raise ValueError(f"No parking lanes were discovered for {parking_name}.")

    if user_capacity is not None:
        capacities = distribute_capacity_by_length(lane_ids, net_lanes, user_capacity)
        capacity_source = "user_defined"
        capacity_source_detail = (
            f"User-defined capacity={user_capacity}; distributed_by=lane_length"
        )
    else:
        osm_capacity = load_osm_capacity(osm_file, osm_way_id)
        if osm_capacity is not None:
            capacities = distribute_capacity_by_length(lane_ids, net_lanes, osm_capacity)
            capacity_source = "osm_capacity"
            capacity_source_detail = (
                f"OSM way {osm_way_id} capacity={osm_capacity}; distributed_by=lane_length"
            )
        else:
            capacities = estimate_capacity_by_lane_length(
                lane_ids, net_lanes, parking_space_length
            )
            capacity_source = "calculated_from_lane_length"
            capacity_source_detail = (
                "No OSM capacity tag found; "
                f"capacity=floor(lane_length / {parking_space_length})"
            )

    write_parking_add_xml(
        output_file, lane_ids, net_lanes, capacities, parking_prefix, parking_name,
        osm_way_id, capacity_source, capacity_source_detail,
    )
    write_report_csv(
        report_file, lane_ids, net_lanes, capacities,
        capacity_source, capacity_source_detail,
    )
    return {
        "lane_count": len(lane_ids),
        "total_capacity": sum(capacities.values()),
        "capacity_source": capacity_source,
        "capacity_source_detail": capacity_source_detail,
    }
