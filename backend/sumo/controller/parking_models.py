from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PhysicalParkingArea:
    logical_id: str
    sumo_id: str
    lane_id: str
    edge_id: str
    capacity: int
    capacity_source: str = ""
    capacity_source_detail: str = ""


@dataclass
class LogicalParkingArea:
    logical_id: str
    name: str
    osm_way_id: str | None
    parking_id_prefix: str
    physical_areas: list[PhysicalParkingArea] = field(default_factory=list)
    access_edges: set[str] = field(default_factory=set)
    internal_edges: set[str] = field(default_factory=set)
