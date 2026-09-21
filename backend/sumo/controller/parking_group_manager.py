from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path
from typing import Any
import yaml

import traci

from .parking_models import LogicalParkingArea, PhysicalParkingArea


class ParkingGroupManager:
    """Map one logical parking lot to many physical SUMO parkingArea IDs."""

    def __init__(self, config_path: Path, project_root: Path) -> None:
        if project_root is None:
            raise ValueError("project_root must be provided")
        
        self.project_root = project_root.resolve()
        self.config_path = self._resolve_path(config_path)
        
        self.groups: dict[str, LogicalParkingArea] = {}
        self.physical_to_logical: dict[str, str] = {}
        self.physical_by_id: dict[str, PhysicalParkingArea] = {}
        self.reserved: dict[str, int] = {}
        self.edge_to_logical: dict[str, set[str]] = {}
        self.selectable_physical_ids: set[str] | None = None

        

        

    def load(self) -> None:
        self.groups.clear()
        self.physical_to_logical.clear()
        self.physical_by_id.clear()
        self.reserved.clear()
        self.edge_to_logical.clear()

        if not self.config_path.is_file():
            raise FileNotFoundError(f"Parking configuration file not found: {self.config_path}")
        
        config = yaml.safe_load(
            self.config_path.read_text(encoding="utf-8")
        ) or {}

        parking_areas = config.get("parking_areas", [])

        if not isinstance(parking_areas, list):
            raise ValueError(f"'parking_areas' must be a list in {self.config_path}")

        loaded_sumo_parking_ids = set(traci.parkingarea.getIDList())
        print(f"SUMO loaded {len(loaded_sumo_parking_ids)} parkingArea object(s).")

        for parking_cfg in parking_areas:
            if not parking_cfg.get("enabled", True): 
                continue
            group = self._load_one_group(parking_cfg, loaded_sumo_parking_ids)
            self.groups[group.logical_id] = group

            for area in group.physical_areas:
                self.physical_to_logical[area.sumo_id] = (group.logical_id)
                self.physical_by_id[area.sumo_id] = area
                self.reserved[area.sumo_id] = 0
                group.internal_edges.add(area.edge_id)

            for edge_id in group.internal_edges:
                self.edge_to_logical.setdefault(edge_id, set()).add(group.logical_id)

            print(
                f"Loaded logical parking '{group.logical_id}' "
                f"with {len(group.physical_areas)} physical parkingArea(s), "
                f"{len(group.access_edges)} access edge(s), "
                f"total capacity={self.total_capacity(group.logical_id)}."
            )

    def _load_one_group(
        self,
        parking_cfg: dict[str, Any],
        loaded_sumo_parking_ids: set[str],
    ) -> LogicalParkingArea:
        logical_id = parking_cfg["id"]
        prefix = parking_cfg.get("parking_id_prefix", logical_id)

        group = LogicalParkingArea(
            logical_id=logical_id,
            name=parking_cfg.get("name", logical_id),
            osm_way_id=str(parking_cfg.get("osm_way_id"))
            if parking_cfg.get("osm_way_id") is not None
            else None,
            parking_id_prefix=prefix,
        )

        report_path_value = parking_cfg.get("report_path")

        if report_path_value:
            report_path = self._resolve_path(Path(str(report_path_value)))
        else:
            raise ValueError(
                f"Parking area '{logical_id}' is missing "
                "'report_path'"
            )

        self._load_physical_areas_from_report(
            group,
            report_path,
            loaded_sumo_parking_ids,
        )

        metadata_path = report_path.with_suffix(".metadata.json")
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid parking lane metadata: {metadata_path}") from exc
            discovered_access_edges = metadata.get("access_edge_ids") or []
            group.access_edges.update(str(edge) for edge in discovered_access_edges)
            discovered_internal_edges = (
                metadata.get("parking_edge_ids")
                or metadata.get("routing_edge_ids")
                or []
            )
            group.internal_edges.update(str(edge) for edge in discovered_internal_edges)

        explicit_access_edges = parking_cfg.get("access_edges") or []
        group.access_edges.update(str(edge) for edge in explicit_access_edges)

        if parking_cfg.get("access_edges_from_report", False):
            for area in group.physical_areas:
                group.access_edges.add(area.edge_id)

        return group

    def _resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return self.project_root / path

    def _load_physical_areas_from_report(
        self,
        group: LogicalParkingArea,
        report_path: Path,
        loaded_sumo_parking_ids: set[str],
    ) -> None:
        report_path = self._resolve_path(report_path)
        if not report_path.exists():
            raise FileNotFoundError(f"Parking report file not found: {report_path}")

        with report_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)

            required_columns = {"lane_id", "edge_id", "capacity"}
            missing = required_columns - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"Parking report file {report_path} is missing columns: {sorted(missing)}"
                )

            for index, row in enumerate(reader, start=1):
                lane_id = row["lane_id"].strip()
                edge_id = row["edge_id"].strip()

                try:
                    capacity = max(1, int(float(row["capacity"])))
                except (TypeError, ValueError):
                    capacity = 1

                sumo_id = self._find_matching_sumo_parking_id(
                    prefix=group.parking_id_prefix,
                    lane_id=lane_id,
                    index=index,
                    loaded_sumo_parking_ids=loaded_sumo_parking_ids,
                )

                if sumo_id is None:
                    print(
                        "WARNING: no loaded SUMO parkingArea found for "
                        f"logical={group.logical_id}, lane={lane_id}. "
                        "Check that the generated .add.xml is included in the active generated .sumocfg file."
                    )
                    continue

                try:
                    loaded_capacity = int(traci.parkingarea.getVehicleCapacity(sumo_id))
                    capacity = loaded_capacity
                except Exception:
                    pass

                group.physical_areas.append(
                    PhysicalParkingArea(
                        logical_id=group.logical_id,
                        sumo_id=sumo_id,
                        lane_id=lane_id,
                        edge_id=edge_id,
                        capacity=capacity,
                        capacity_source=row.get("capacity_source", ""),
                        capacity_source_detail=row.get("capacity_source_detail", ""),
                    )
                )

    def _load_physical_areas_from_traci_prefix(
        self,
        group: LogicalParkingArea,
        prefix: str,
    ) -> None:
        for parking_id in traci.parkingarea.getIDList():
            if not parking_id.startswith(prefix):
                continue

            lane_id = traci.parkingarea.getLaneID(parking_id)
            edge_id = lane_id.rsplit("_", 1)[0]

            try:
                capacity = int(traci.parkingarea.getVehicleCapacity(parking_id))
            except Exception:
                capacity = 1

            group.physical_areas.append(
                PhysicalParkingArea(
                    logical_id=group.logical_id,
                    sumo_id=parking_id,
                    lane_id=lane_id,
                    edge_id=edge_id,
                    capacity=capacity,
                    capacity_source="traci_loaded_parkingarea",
                    capacity_source_detail="Read from loaded SUMO parkingArea object",
                )
            )

    def _find_matching_sumo_parking_id(
        self,
        prefix: str,
        lane_id: str,
        index: int,
        loaded_sumo_parking_ids: set[str],
    ) -> str | None:
        safe_lane = self._safe_id(lane_id)

        exact = f"{prefix}_{index:03d}_{safe_lane}"
        if exact in loaded_sumo_parking_ids:
            return exact

        matches = [
            parking_id
            for parking_id in loaded_sumo_parking_ids
            if parking_id.startswith(prefix) and parking_id.endswith(safe_lane)
        ]

        if matches:
            return sorted(matches)[0]

        return None

    @staticmethod
    def _safe_id(text: str) -> str:
        return (
            text.replace("-", "minus_")
            .replace("#", "_")
            .replace(":", "_")
            .replace(".", "_")
            .replace("/", "_")
        )

    def get_group(self, logical_id: str) -> LogicalParkingArea:
        if logical_id not in self.groups:
            raise KeyError(f"Unknown logical parking area: {logical_id}")
        return self.groups[logical_id]

    def is_access_edge(self, edge_id: str, logical_id: str | None = None) -> bool:
        if logical_id is not None:
            return edge_id in self.get_group(logical_id).access_edges

        return any(edge_id in group.access_edges for group in self.groups.values())

    def logical_parkings_for_access_edge(self, edge_id: str) -> set[str]:
        return {
            logical_id
            for logical_id, group in self.groups.items()
            if edge_id in group.access_edges
        }

    def is_inside_logical_parking(self, edge_id: str, logical_id: str) -> bool:
        return logical_id in self.edge_to_logical.get(edge_id, set())

    def parking_name(self, logical_id: str) -> str:
        group = self.groups.get(logical_id)
        return group.name if group is not None else logical_id

    def occupied(self, physical_id: str) -> int:
        try:
            # SUMO defines this value as vehicles stopped at the named parking
            # area. Moving, queued, and ordinarily halted vehicles on the same
            # lane are not included.
            return int(traci.parkingarea.getVehicleCount(physical_id))
        except Exception:
            return 0

    def capacity(self, physical_id: str) -> int:
        try:
            return int(traci.parkingarea.getVehicleCapacity(physical_id))
        except Exception:
            return self.physical_by_id[physical_id].capacity

    def free_spaces(self, physical_id: str) -> int:
        return self.capacity(physical_id) - self.occupied(physical_id) - self.reserved.get(physical_id, 0)

    def reserve(self, physical_id: str) -> None:
        self.reserved[physical_id] = self.reserved.get(physical_id, 0) + 1

    def release(self, physical_id: str | None) -> None:
        if not physical_id:
            return
        if physical_id in self.reserved and self.reserved[physical_id] > 0:
            self.reserved[physical_id] -= 1

    def total_capacity(self, logical_id: str) -> int:
        return sum(self.capacity(area.sumo_id) for area in self.get_group(logical_id).physical_areas)

    def total_occupancy(self, logical_id: str) -> int:
        return sum(self.occupied(area.sumo_id) for area in self.get_group(logical_id).physical_areas)

    def total_reserved(self, logical_id: str) -> int:
        return sum(self.reserved.get(area.sumo_id, 0) for area in self.get_group(logical_id).physical_areas)

    def logical_has_free_space(self, logical_id: str) -> bool:
        return any(
            self._is_selectable(area.sumo_id) and self.free_spaces(area.sumo_id) > 0
            for area in self.get_group(logical_id).physical_areas
        )

    def total_free_spaces(self, logical_id: str) -> int:
        return sum(
            max(self.free_spaces(area.sumo_id), 0)
            for area in self.get_group(logical_id).physical_areas
            if self._is_selectable(area.sumo_id)
        )

    def restrict_selectable_physical_areas(self, physical_ids: set[str]) -> None:
        self.selectable_physical_ids = set(physical_ids)

    def _is_selectable(self, physical_id: str) -> bool:
        return self.selectable_physical_ids is None or physical_id in self.selectable_physical_ids

    def choose_available_physical_parking(self, logical_id: str) -> str | None:
        group = self.get_group(logical_id)
        for area in group.physical_areas:
            if self._is_selectable(area.sumo_id) and self.free_spaces(area.sumo_id) > 0:
                return area.sumo_id
        return None

    def choose_available_physical_parking_near_vehicle(self, veh_id: str, logical_id: str) -> str | None:
        group = self.get_group(logical_id)

        best_parking_id = None
        best_distance = float("inf")

        for area in group.physical_areas:
            if not self._is_selectable(area.sumo_id):
                continue
            if self.free_spaces(area.sumo_id) <= 0:
                continue
            
            distance = self._route_cost(veh_id, area.edge_id)

            if distance >= 0 and distance < best_distance:
                best_distance = distance
                best_parking_id = area.sumo_id

        return best_parking_id

    def route_vehicle_to_logical_parking(
        self,
        veh_id: str,
        logical_id: str,
    ) -> str | None:
        """Route toward the nearest reachable aisle without reserving a space."""
        route = self.logical_parking_route(veh_id, logical_id)
        if route is None:
            return None
        destination_edge, _travel_time = route
        try:
            traci.vehicle.changeTarget(veh_id, destination_edge)
        except (traci.TraCIException, ValueError, TypeError):
            return None
        return destination_edge

    def logical_parking_route(
        self,
        veh_id: str,
        logical_id: str,
    ) -> tuple[str, float] | None:
        """Return the best reachable access edge and current travel time."""
        try:
            current_edge = traci.vehicle.getRoadID(veh_id)
            vehicle_type = traci.vehicle.getTypeID(veh_id)
        except (traci.TraCIException, ValueError, TypeError):
            return None

        group = self.get_group(logical_id)
        if not any(self._is_selectable(area.sumo_id) for area in group.physical_areas):
            return None
        destination_edges = set(group.access_edges) or {
            area.edge_id
            for area in group.physical_areas
            if self._is_selectable(area.sumo_id)
        }
        candidates: list[tuple[float, str]] = []
        for destination_edge in destination_edges:
            try:
                route = traci.simulation.findRoute(
                    current_edge,
                    destination_edge,
                    vType=vehicle_type,
                )
            except (traci.TraCIException, ValueError, TypeError):
                continue
            if route.edges:
                candidates.append((float(route.travelTime), destination_edge))
        if not candidates:
            return None
        travel_time, destination_edge = min(
            candidates,
            key=lambda item: (item[0], item[1]),
        )
        return destination_edge, travel_time
    
    def choose_random_available_physical_parking(self, veh_id: str, logical_id: str) -> str | None:
        group = self.get_group(logical_id)

        available = [
            area.sumo_id
            for area in group.physical_areas
            if self._is_selectable(area.sumo_id)
            and self.free_spaces(area.sumo_id) > 0
            and math.isfinite(self._route_cost(veh_id, area.edge_id))
        ]

        if not available:
            return None

        return random.choice(available)

    def choose_balanced_available_physical_parking(
        self,
        veh_id: str,
        logical_id: str,
    ) -> str | None:
        """Spread inbound traffic before using route cost as a tie-breaker."""
        candidates: list[tuple[tuple[float, float, float, float], str]] = []
        for area in self.get_group(logical_id).physical_areas:
            if not self._is_selectable(area.sumo_id):
                continue
            capacity = max(self.capacity(area.sumo_id), 1)
            occupied = self.occupied(area.sumo_id)
            reserved = self.reserved.get(area.sumo_id, 0)
            free = capacity - occupied - reserved
            if free <= 0:
                continue
            route_cost = self._route_cost(veh_id, area.edge_id)
            if not math.isfinite(route_cost):
                continue
            utilization = (occupied + reserved) / capacity
            # Reservations represent cars already travelling toward the same
            # aisle. Prefer zero/low inbound pressure, then lower utilization,
            # then the shorter reachable route.
            score = (float(reserved), utilization, route_cost, -float(free))
            candidates.append((score, area.sumo_id))

        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _route_cost(veh_id: str, destination_edge: str) -> float:
        try:
            current_edge = traci.vehicle.getRoadID(veh_id)
            vehicle_type = traci.vehicle.getTypeID(veh_id)
            route = traci.simulation.findRoute(
                current_edge,
                destination_edge,
                vType=vehicle_type,
            )
            if not route.edges:
                return float("inf")
            return float(route.travelTime)
        except (traci.TraCIException, ValueError, TypeError):
            return float("inf")
