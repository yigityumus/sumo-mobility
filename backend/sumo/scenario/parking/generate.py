#!/usr/bin/env python3
"""Generate parking areas for one model simulation run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .osm_discovery import load_osm
from .area_generator import (
    generate_parking_from_lane_ids,
    load_net_lanes,
)
from .lane_discovery import (
    discover_parking_lanes,
    load_sumo_network,
)


BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _effective_capacity(parking: dict) -> int | None:
    capacity = parking.get("capacity") or {}
    selected = capacity.get("value")
    if selected is None:
        selected = capacity.get("original_capacity")
    return int(selected) if selected is not None else None


def _configured_path(parking: dict, direct_key: str) -> Path:
    direct_value = parking.get(direct_key)
    if not direct_value:
        raise ValueError(
            f"Parking area '{parking.get('id', '<unknown>')}' is missing "
            f"'{direct_key}'"
        )
    path = Path(str(direct_value)).expanduser()
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def generate(
    config_path: Path,
    network_path: Path,
    osm_path: Path,
) -> list[dict]:
    config_path = config_path.expanduser().resolve()
    network_path = network_path.expanduser().resolve()
    osm_path = osm_path.expanduser().resolve()

    config = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    ) or {}

    parking_areas = config.get("parking_areas", [])

    if not isinstance(parking_areas, list):
        raise ValueError(
            f"'parking_areas' must be a list in {config_path}"
        )

    enabled_areas = [
        parking
        for parking in parking_areas
        if parking.get("enabled", True)
    ]

    if not enabled_areas:
        print("No enabled parking areas; skipping parking generation for walking-only demand.")
        return []

    print(f"Loading OSM road topology from {osm_path}")
    osm_data = load_osm(osm_path)
    print(f"Loading SUMO network from {network_path}")
    sumo_network = load_sumo_network(network_path)
    net_lanes = load_net_lanes(network_path)

    for parking in enabled_areas:
        logical_id = parking["id"]
        name = parking.get("name", logical_id)
        osm_way_id = parking["osm_way_id"]
        prefix = parking.get("parking_id_prefix", logical_id)

        additional_path = _configured_path(
            parking, "additional_path"
        )
        report_path = _configured_path(
            parking, "report_path"
        )

        capacity_config = parking.get("capacity", {})
        space_length = float(capacity_config.get("space_length", 2.3))
        
        # Get user-defined capacity if available
        user_capacity = _effective_capacity(parking)

        print()
        print(f"Generating parking: {name}")
        discovery_config = parking.get("lane_discovery") or {}
        discovery = discover_parking_lanes(
            int(osm_way_id),
            osm_data,
            sumo_network,
            minimum_way_inside_ratio=float(
                discovery_config.get("minimum_way_inside_ratio", 0.5)
            ),
            minimum_lane_inside_ratio=float(
                discovery_config.get("minimum_lane_inside_ratio", 0.5)
            ),
            parking_buffer_metres=float(
                discovery_config.get("parking_buffer_metres", 3.0)
            ),
            minimum_lane_length=float(
                discovery_config.get("minimum_lane_length", 3.0)
            ),
            nearest_access_lane_metres=float(
                discovery_config.get("nearest_access_lane_metres", 150.0)
            ),
        )
        generation = generate_parking_from_lane_ids(
            lane_ids=discovery["lane_ids"],
            net_lanes=net_lanes,
            osm_file=osm_path,
            osm_way_id=str(osm_way_id),
            parking_prefix=str(prefix),
            parking_name=str(name),
            parking_space_length=space_length,
            user_capacity=user_capacity,
            output_file=additional_path,
            report_file=report_path,
        )
        metadata = {
            **discovery,
            "logical_parking_id": logical_id,
            "parking_name": name,
            "generation": generation,
        }
        metadata_path = report_path.with_suffix(".metadata.json")
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"Automatically discovered {generation['lane_count']} parking lane(s); "
            f"excluded boundary/access OSM way(s): {discovery['excluded_way_ids']}"
        )
        print(f"Capacity mode: {generation['capacity_source_detail']}")
        print(f"Total generated capacity: {generation['total_capacity']}")
        print(f"Wrote parking additional file: {additional_path}")
        print(f"Wrote parking report: {report_path}")
        print(f"Wrote lane discovery metadata: {metadata_path}")
    return enabled_areas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parking-config",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--network",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--osm",
        type=Path,
        required=True,
    )
    arguments = parser.parse_args()
    generate(arguments.parking_config, arguments.network, arguments.osm)


if __name__ == "__main__":
    main()
