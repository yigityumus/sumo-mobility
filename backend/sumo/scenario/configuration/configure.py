#!/usr/bin/env python3
"""Add model-network generation points and parking targets to a run scenario."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sumolib
import yaml


def _report_path(parking: dict, project_root: Path) -> Path:
    value = parking.get("report_path")
    if not value:
        raise ValueError(
            f"Parking area '{parking.get('id', '<unknown>')}' has no report_path"
        )
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _usable_edges(network, vehicle_class: str):
    return [
        edge
        for edge in network.getEdges()
        if not edge.getID().startswith(":")
        and edge.allows(vehicle_class)
        and edge.getLength() >= 3
    ]


def _ordered_origins(edges, excluded_ids: set[str]):
    return sorted(
        (edge for edge in edges if edge.getID() not in excluded_ids),
        key=lambda edge: (
            not edge.is_fringe(checkJunctions=True),
            -edge.getLength(),
            edge.getID(),
        ),
    )


def _reachable_origins(network, candidates, destinations, limit: int = 2):
    for destination in destinations:
        reverse_reachable = network.getReachable(
            destination,
            vclass="passenger",
            useIncoming=True,
        )
        origins = [
            candidate
            for candidate in candidates
            if candidate in reverse_reachable
        ][:limit]
        if origins:
            return origins, destination
    return [], None


def _configured_vehicle_origins(network, configured: list[dict] | None) -> list[dict]:
    """Resolve saved map points to exact passenger edges and departure positions."""
    resolved = []
    used_edges: set[str] = set()
    for index, point in enumerate(configured or [], start=1):
        selection = point.get("laneSelection") or point.get("lane_selection") or {}
        lane_id = str(selection.get("laneId") or selection.get("lane_id") or "")
        if not lane_id:
            raise ValueError(
                f"Vehicle generation point {index} has no saved passenger lane. "
                "Refresh or replace it on the map."
            )
        try:
            lane = network.getLane(lane_id)
        except KeyError as exc:
            raise ValueError(
                f"Vehicle generation point '{point.get('name') or index}' uses unknown lane '{lane_id}'."
            ) from exc
        edge = lane.getEdge()
        edge_id = str(edge.getID())
        if edge_id.startswith(":") or not lane.allows("passenger"):
            raise ValueError(
                f"Vehicle generation point '{point.get('name') or index}' must use a non-junction passenger lane."
            )
        if edge_id in used_edges:
            raise ValueError(
                f"Vehicle generation points must use distinct directed edges; '{edge_id}' was selected more than once."
            )
        used_edges.add(edge_id)
        requested_position = float(
            point.get("positionMetres")
            if point.get("positionMetres") is not None
            else point.get("position_metres") or 0.1
        )
        departure_position = min(
            max(requested_position, 0.1),
            max(float(lane.getLength()) - 0.1, 0.1),
        )
        resolved.append({
            "id": f"vehicle_origin_{index}",
            "configured_id": str(point.get("id") or ""),
            "name": str(point.get("name") or f"Vehicle origin {index}"),
            "from_edge": edge_id,
            "depart_lane": int(lane.getIndex()),
            "depart_position": round(departure_position, 3),
        })
    return resolved


def configure(
    scenario_path: Path,
    parking_config_path: Path,
    network_path: Path,
) -> None:
    scenario_path = scenario_path.expanduser().resolve()
    parking_config_path = parking_config_path.expanduser().resolve()
    network_path = network_path.expanduser().resolve()
    project_root = Path(__file__).resolve().parents[2]

    scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    parking_config = yaml.safe_load(
        parking_config_path.read_text(encoding="utf-8")
    ) or {}
    parkings = [
        parking
        for parking in parking_config.get("parking_areas", [])
        if parking.get("enabled", True)
    ]
    vehicle_total = int((scenario.get("demand_totals") or {}).get("vehicles", 0))
    if not parkings and vehicle_total > 0:
        raise ValueError("Vehicle demand requires at least one selected parking area.")

    network = sumolib.net.readNet(str(network_path))
    edge_by_id = {edge.getID(): edge for edge in network.getEdges()}
    metadata_by_parking = {}
    excluded_ids: set[str] = set()
    for parking in parkings:
        report_path = _report_path(parking, project_root)
        metadata_path = report_path.with_suffix(".metadata.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        routing_ids = metadata.get("routing_edge_ids") or metadata.get("parking_edge_ids") or []
        destinations = [edge_by_id[edge_id] for edge_id in routing_ids if edge_id in edge_by_id]
        if not destinations:
            raise ValueError(
                f"Parking area '{parking.get('name') or parking.get('id')}' has no usable routing edge."
            )
        metadata_by_parking[str(parking["id"])] = destinations
        excluded_ids.update(str(edge_id) for edge_id in metadata.get("parking_edge_ids") or [])

    passenger_candidates = _ordered_origins(
        _usable_edges(network, "passenger"), excluded_ids
    )
    configured_origins = _configured_vehicle_origins(
        network,
        scenario.get("vehicle_generation_points"),
    )
    origin_allocations = scenario.get("vehicle_origin_allocations") or []
    if origin_allocations:
        allocation_by_id = {
            str(item.get("origin_id") or ""): int(item.get("vehicle_count") or 0)
            for item in origin_allocations
        }
        configured_ids = {
            str(origin.get("configured_id") or "") for origin in configured_origins
        }
        if set(allocation_by_id) != configured_ids:
            raise ValueError(
                "Vehicle origin allocation IDs do not match the configured generation points."
            )
        for origin in configured_origins:
            origin["vehicle_count"] = allocation_by_id[str(origin["configured_id"])]
    generation_by_parking = {}
    routing_by_parking = {}
    all_origins = {}
    for parking in parkings:
        parking_id = str(parking["id"])
        if configured_origins:
            generation_by_parking[parking_id] = configured_origins
            routing_by_parking[parking_id] = [
                destination.getID()
                for destination in metadata_by_parking[parking_id]
            ]
        else:
            origins, destination = _reachable_origins(
                network,
                passenger_candidates,
                metadata_by_parking[parking_id],
            )
            if not origins:
                raise ValueError(
                    f"Parking area '{parking.get('name') or parking_id}' is not reachable "
                    "from a passenger entry edge in the generated model network."
                )
            points = []
            for index, edge in enumerate(origins, start=1):
                point = {
                    "id": f"car_{parking_id}_{index}",
                    "from_edge": edge.getID(),
                }
                points.append(point)
                all_origins[edge.getID()] = {
                    "id": f"car_entry_{len(all_origins) + 1}",
                    "from_edge": edge.getID(),
                }
            generation_by_parking[parking_id] = points
            routing_by_parking[parking_id] = [destination.getID()]

    pedestrian_edges = _ordered_origins(_usable_edges(network, "pedestrian"), set())
    pedestrian_points = []
    if pedestrian_edges:
        origin = pedestrian_edges[0]
        destination = origin
        reachable = network.getReachable(origin, vclass="pedestrian")
        for candidate in reversed(pedestrian_edges):
            if candidate in reachable:
                destination = candidate
                break
        pedestrian_points.append({
            "id": "pedestrian_entry_1",
            "from_edge": origin.getID(),
            "to_edge": destination.getID(),
        })

    scenario["car_generation_points"] = configured_origins or list(all_origins.values())
    scenario["parking_generation_points"] = generation_by_parking
    scenario["parking_routing_edges"] = routing_by_parking
    scenario["pedestrian_generation_points"] = pedestrian_points
    scenario["parking_assignment"] = {
        **(scenario.get("parking_assignment") or {}),
        "targets": [str(parking["id"]) for parking in parkings],
    }
    scenario_path.write_text(
        yaml.safe_dump(scenario, sort_keys=False),
        encoding="utf-8",
    )
    print(
        f"Configured {len(parkings)} parking target(s), "
        f"{len(all_origins)} vehicle entry edge(s), and "
        f"{len(pedestrian_points)} pedestrian route(s)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--parking-config", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    arguments = parser.parse_args()
    configure(arguments.config, arguments.parking_config, arguments.network)


if __name__ == "__main__":
    main()
