#!/usr/bin/env python3
"""Generate run-specific detectors from saved model definitions.

Vehicle E3 measurements use SUMO entry/exit detectors. Pedestrian measurements
use direction-agnostic E2 lane-area detectors because pedestrians may traverse
the configured area in either direction.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from sumolib import geomhelper

from .lanes import lane_on_selected_edge, resolve_detector_lanes
from ..parking.lane_discovery import load_sumo_network


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_") or "detector"


def _project_position(network, lane, longitude: float, latitude: float) -> tuple[float, float]:
    x, y = network.convertLonLat2XY(longitude, latitude)
    position, distance = geomhelper.polygonOffsetAndDistanceToPoint((x, y), list(lane.getShape()))
    position = min(max(float(position), 0.1), max(float(lane.getLength()) - 0.1, 0.1))
    return position, float(distance)


def _resolve_point(
    network,
    point: dict,
    detector_name: str,
    vehicle_class: str = "passenger",
) -> tuple[str, str, list, float, float]:
    location = point.get("location") or {}
    longitude = float(location["longitude"])
    latitude = float(location["latitude"])
    selection = point.get("laneSelection") or {}
    preferred_edge_id = str(selection.get("edgeId") or "")
    lane_index = selection.get("laneIndex")
    mode = str(selection.get("mode") or "lane")
    if mode == "lanes":
        lanes = []
        for lane_id in selection.get("laneIds") or []:
            try:
                lane = network.getLane(str(lane_id))
            except KeyError:
                continue
            if lane.allows(vehicle_class) and not lane.getEdge().getID().startswith(":"):
                lanes.append(lane)
        if not lanes:
            subject = "pedestrian" if vehicle_class == "pedestrian" else "vehicle"
            raise ValueError(f"Detector '{detector_name}' has no selected {subject} lanes.")
        return preferred_edge_id, mode, lanes, longitude, latitude

    candidate_lane = None
    selected_lane_id = selection.get("laneId")
    if selected_lane_id:
        try:
            selected_lane = network.getLane(str(selected_lane_id))
            if selected_lane.allows(vehicle_class):
                candidate_lane = selected_lane
        except KeyError:
            pass
    if candidate_lane is None:
        candidate_lane = lane_on_selected_edge(
            network, preferred_edge_id, lane_index, vehicle_class
        )
    if candidate_lane is None:
        nearby = resolve_detector_lanes(
            network,
            longitude,
            latitude,
            radius_metres=100,
            limit=1,
            allowed_classes=(vehicle_class,),
        )
        if not nearby:
            raise ValueError(f"Detector '{detector_name}' has no passenger lane within 100 m.")
        candidate_lane = network.getLane(nearby[0]["lane_id"])
        preferred_edge_id = candidate_lane.getEdge().getID()

    lanes = (
        [lane for lane in candidate_lane.getEdge().getLanes() if lane.allows(vehicle_class)]
        if mode == "edge_all"
        else [candidate_lane]
    )
    if not lanes:
        raise ValueError(f"Detector '{detector_name}' selected an edge without passenger lanes.")
    return preferred_edge_id, mode, lanes, longitude, latitude


def _physical_cross_sections(network, lanes: list, longitude: float, latitude: float) -> list[dict]:
    cross_sections = []
    for lane in lanes:
        position, distance = _project_position(network, lane, longitude, latitude)
        cross_sections.append({
            "lane_id": lane.getID(),
            "edge_id": lane.getEdge().getID(),
            "lane_index": int(lane.getIndex()),
            "position_metres": round(position, 3),
            "distance_metres": round(distance, 3),
        })
    return cross_sections


def _pedestrian_zones(entries: list[dict], exits: list[dict]) -> list[dict]:
    """Pair same-lane boundaries and normalize them into bidirectional zones."""
    entries_by_lane = {str(item["lane_id"]): item for item in entries}
    exits_by_lane = {str(item["lane_id"]): item for item in exits}
    zones = []
    for lane_id in sorted(entries_by_lane.keys() & exits_by_lane.keys()):
        entry = entries_by_lane[lane_id]
        exit_point = exits_by_lane[lane_id]
        start = min(
            float(entry["position_metres"]),
            float(exit_point["position_metres"]),
        )
        end = max(
            float(entry["position_metres"]),
            float(exit_point["position_metres"]),
        )
        if end - start < 0.1:
            continue
        zones.append({
            "lane_id": lane_id,
            "edge_id": entry.get("edge_id") or exit_point.get("edge_id"),
            "lane_index": entry.get("lane_index"),
            "start_position_metres": round(start, 3),
            "end_position_metres": round(end, 3),
            "entry_position_metres": entry["position_metres"],
            "exit_position_metres": exit_point["position_metres"],
        })
    return zones


def _directional_vehicle_cross_sections(
    first_boundary: list[dict],
    second_boundary: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Orient same-lane E3 boundaries in the lane's direction of travel.

    Map users select two geographic boundaries. On a two-way street, the first
    geographic boundary is an entry for one directed lane and an exit for its
    opposite lane. SUMO lane positions always increase in travel direction, so
    same-lane boundary pairs can be oriented without guessing from edge IDs.
    """
    first_by_lane = {str(item["lane_id"]): item for item in first_boundary}
    second_by_lane = {str(item["lane_id"]): item for item in second_boundary}
    paired_lane_ids = first_by_lane.keys() & second_by_lane.keys()
    entries = [
        item for item in first_boundary
        if str(item["lane_id"]) not in paired_lane_ids
    ]
    exits = [
        item for item in second_boundary
        if str(item["lane_id"]) not in paired_lane_ids
    ]
    for lane_id in sorted(paired_lane_ids):
        first = first_by_lane[lane_id]
        second = second_by_lane[lane_id]
        if float(first["position_metres"]) <= float(second["position_metres"]):
            entries.append(first)
            exits.append(second)
        else:
            entries.append(second)
            exits.append(first)
    return entries, exits


def generate(
    model_snapshot: Path,
    network_path: Path,
    output_path: Path,
    detector_output: Path,
    snapshot_output: Path,
    e3_detector_output: Path | None = None,
    pedestrian_zone_output: Path | None = None,
) -> dict:
    model = json.loads(model_snapshot.read_text(encoding="utf-8"))
    detectors = model.get("detectors") or []
    network = load_sumo_network(network_path)
    e3_detector_output = e3_detector_output or detector_output.with_name("e3.xml")
    pedestrian_zone_output = (
        pedestrian_zone_output
        or detector_output.with_name("e2_pedestrians.xml")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    detector_output.parent.mkdir(parents=True, exist_ok=True)
    e3_detector_output.parent.mkdir(parents=True, exist_ok=True)
    pedestrian_zone_output.parent.mkdir(parents=True, exist_ok=True)
    snapshot_output.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("additional")
    resolved_logical = []
    used_logical_ids: set[str] = set()
    used_xml_ids: set[str] = set()
    e1_physical_count = 0
    e3_cross_section_count = 0
    pedestrian_zone_count = 0

    for detector_index, detector in enumerate(detectors):
        detector_type = str(detector.get("type") or "e1")
        if detector_type not in {"e1", "e3"}:
            continue
        detector_name = str(detector.get("name") or f"Detector {detector_index + 1}")
        logical_id = _safe_id(str(detector.get("id") or f"detector_{detector_index + 1}"))
        base_id = logical_id
        suffix = 2
        while logical_id in used_logical_ids:
            logical_id = f"{base_id}_{suffix}"
            suffix += 1
        used_logical_ids.add(logical_id)
        period = max(1, int(detector.get("periodSeconds") or 900))

        if detector_type == "e1":
            edge_id, mode, lanes, longitude, latitude = _resolve_point(
                network, detector, detector_name
            )
            physical = _physical_cross_sections(network, lanes, longitude, latitude)
            for physical_index, cross_section in enumerate(physical):
                physical_id = logical_id if len(physical) == 1 else f"{logical_id}__lane_{cross_section['lane_index']}"
                if physical_id in used_xml_ids:
                    physical_id = f"{logical_id}_{physical_index + 1}"
                used_xml_ids.add(physical_id)
                cross_section["id"] = physical_id
                ET.SubElement(root, "inductionLoop", {
                    "id": physical_id,
                    "lane": cross_section["lane_id"],
                    "pos": f"{cross_section['position_metres']:.3f}",
                    "period": str(period),
                    "file": str(detector_output.resolve()),
                    "friendlyPos": "true",
                })
            e1_physical_count += len(physical)
            resolved_logical.append({
                "id": str(detector.get("id") or logical_id),
                "sumo_id": logical_id,
                "name": detector_name,
                "type": "e1",
                "location": {"longitude": longitude, "latitude": latitude},
                "period_seconds": period,
                "selection_mode": mode,
                "selected_edge_id": edge_id,
                "physical_detectors": physical,
            })
            continue

        entry = detector.get("entry") or {}
        exit_point = detector.get("exit") or {}
        detects = [
            target for target in (detector.get("detects") or ["vehicles"])
            if target in {"vehicles", "pedestrians"}
        ] or ["vehicles"]
        measurements = []
        for target in detects:
            vehicle_class = "pedestrian" if target == "pedestrians" else "passenger"
            entry_edge, entry_mode, entry_lanes, entry_longitude, entry_latitude = _resolve_point(
                network, entry, f"{detector_name} entry", vehicle_class
            )
            exit_edge, exit_mode, exit_lanes, exit_longitude, exit_latitude = _resolve_point(
                network, exit_point, f"{detector_name} exit", vehicle_class
            )
            entries = _physical_cross_sections(network, entry_lanes, entry_longitude, entry_latitude)
            exits = _physical_cross_sections(network, exit_lanes, exit_longitude, exit_latitude)
            measurement_id = logical_id if len(detects) == 1 else f"{logical_id}__{target}"
            if target == "pedestrians":
                zones = _pedestrian_zones(entries, exits)
                if not zones:
                    raise ValueError(
                        f"Detector '{detector_name}' needs at least one pedestrian lane "
                        "selected at both markers so its bidirectional zone can be measured."
                    )
                for zone_index, zone in enumerate(zones):
                    physical_id = (
                        measurement_id
                        if len(zones) == 1
                        else f"{measurement_id}__zone_{zone_index + 1}"
                    )
                    while physical_id in used_xml_ids:
                        physical_id = f"{physical_id}_e2"
                    used_xml_ids.add(physical_id)
                    zone["id"] = physical_id
                    ET.SubElement(root, "laneAreaDetector", {
                        "id": physical_id,
                        "lane": zone["lane_id"],
                        "pos": f"{zone['start_position_metres']:.3f}",
                        "endPos": f"{zone['end_position_metres']:.3f}",
                        "period": str(period),
                        "file": str(pedestrian_zone_output.resolve()),
                        "detectPersons": "walk",
                        "friendlyPos": "true",
                    })
                pedestrian_zone_count += len(zones)
                measurements.append({
                    "id": measurement_id,
                    "subject": target,
                    "detector_type": "e2",
                    "aggregation": "sum_nVehEntered",
                    "physical_detectors": zones,
                    "entries": entries,
                    "exits": exits,
                    "entry_selection_mode": entry_mode,
                    "entry_selected_edge_id": entry_edge,
                    "exit_selection_mode": exit_mode,
                    "exit_selected_edge_id": exit_edge,
                })
                continue

            vehicle_entries, vehicle_exits = _directional_vehicle_cross_sections(
                entries,
                exits,
            )
            while measurement_id in used_xml_ids:
                measurement_id = f"{measurement_id}_e3"
            used_xml_ids.add(measurement_id)
            attributes = {
                "id": measurement_id,
                "period": str(period),
                "file": str(e3_detector_output.resolve()),
            }
            e3_element = ET.SubElement(root, "entryExitDetector", attributes)
            for cross_section in vehicle_entries:
                ET.SubElement(e3_element, "detEntry", {
                    "lane": cross_section["lane_id"],
                    "pos": f"{cross_section['position_metres']:.3f}",
                    "friendlyPos": "true",
                })
            for cross_section in vehicle_exits:
                ET.SubElement(e3_element, "detExit", {
                    "lane": cross_section["lane_id"],
                    "pos": f"{cross_section['position_metres']:.3f}",
                    "friendlyPos": "true",
                })
            e3_cross_section_count += len(vehicle_entries) + len(vehicle_exits)
            measurements.append({
                "id": measurement_id,
                "subject": target,
                "detector_type": "e3",
                "entries": vehicle_entries,
                "exits": vehicle_exits,
                "entry_selection_mode": entry_mode,
                "entry_selected_edge_id": entry_edge,
                "exit_selection_mode": exit_mode,
                "exit_selected_edge_id": exit_edge,
            })
        resolved_logical.append({
            "id": str(detector.get("id") or logical_id),
            "sumo_id": logical_id,
            "name": detector_name,
            "type": "e3",
            "period_seconds": period,
            "detects": detects,
            "measurements": measurements,
        })

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_path, encoding="UTF-8", xml_declaration=True)
    snapshot = {
        "detectors": resolved_logical,
        "logical_count": len(resolved_logical),
        "e1_count": sum(detector["type"] == "e1" for detector in resolved_logical),
        "e3_count": sum(detector["type"] == "e3" for detector in resolved_logical),
        "physical_count": (
            e1_physical_count + e3_cross_section_count + pedestrian_zone_count
        ),
        "e1_physical_count": e1_physical_count,
        "e3_cross_section_count": e3_cross_section_count,
        "pedestrian_zone_count": pedestrian_zone_count,
    }
    snapshot_output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {output_path} "
        f"({snapshot['e1_count']} E1 logical / {e1_physical_count} loops, "
        f"{snapshot['e3_count']} E3 logical / {e3_cross_section_count} vehicle "
        f"cross-sections / {pedestrian_zone_count} pedestrian zones)"
    )
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detector-output", type=Path, required=True, help="E1 output XML path")
    parser.add_argument("--e3-detector-output", type=Path, help="E3 output XML path (defaults beside E1)")
    parser.add_argument(
        "--pedestrian-zone-output",
        type=Path,
        help="Pedestrian lane-area output XML path (defaults beside E1)",
    )
    parser.add_argument("--snapshot-output", type=Path, required=True)
    arguments = parser.parse_args()
    generate(
        arguments.model_snapshot,
        arguments.network,
        arguments.output,
        arguments.detector_output,
        arguments.snapshot_output,
        e3_detector_output=arguments.e3_detector_output,
        pedestrian_zone_output=arguments.pedestrian_zone_output,
    )


if __name__ == "__main__":
    main()
