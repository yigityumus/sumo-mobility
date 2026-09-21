"""TraCI pedestrian-zone counting for SUMO's nonInteracting model.

SUMO's non-interacting walkers are edge-positioned and report no lane ID. A
native E2 detector is lane-bound, so it can miss every walker in this mode.
This tracker samples person road/position values, handles whole-zone jumps, and
writes an E2-compatible output file for the existing analytics pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class PedestrianZone:
    detector_id: str
    edge_id: str
    lane_id: str
    start_position: float
    end_position: float
    period_seconds: float


@dataclass(frozen=True)
class PersonPosition:
    road_id: str
    lane_position: float
    speed: float = 0.0
    lane_id: str = ""
    stage_type: int = 2


class FastPedestrianDetector:
    """Count bidirectional entries into configured pedestrian E2 zones."""

    def __init__(self, zones: list[PedestrianZone]) -> None:
        self.zones = tuple(zones)
        self._zones_by_edge: dict[str, list[PedestrianZone]] = {}
        for zone in self.zones:
            self._zones_by_edge.setdefault(zone.edge_id, []).append(zone)
        self._previous: dict[str, PersonPosition] = {}
        self._inside: dict[str, set[str]] = {}
        self._buckets: dict[tuple[str, float, float], list[float]] = {}
        self.last_observation_time = 0.0

    @classmethod
    def from_snapshot(cls, path: Path) -> "FastPedestrianDetector":
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        zones: list[PedestrianZone] = []
        represented_edge_measurements: set[tuple[str, str]] = set()
        for detector in snapshot.get("detectors") or []:
            period = max(float(detector.get("period_seconds") or 900), 1.0)
            for measurement in detector.get("measurements") or []:
                if (
                    measurement.get("subject") != "pedestrians"
                    or measurement.get("detector_type") != "e2"
                ):
                    continue
                measurement_id = str(measurement.get("id") or "")
                for physical in measurement.get("physical_detectors") or []:
                    detector_id = str(physical.get("id") or "")
                    edge_id = str(physical.get("edge_id") or "")
                    lane_id = str(physical.get("lane_id") or "")
                    if not detector_id or not edge_id or not lane_id:
                        continue
                    # nonInteracting persons have no lane ID. Parallel walking
                    # lanes on the same edge therefore represent one observable
                    # edge-level zone and must not be summed more than once.
                    edge_measurement = (measurement_id or detector_id, edge_id)
                    if edge_measurement in represented_edge_measurements:
                        continue
                    start = float(physical.get("start_position_metres") or 0)
                    end = float(physical.get("end_position_metres") or 0)
                    if end < start:
                        start, end = end, start
                    if end - start < 0.001:
                        continue
                    represented_edge_measurements.add(edge_measurement)
                    zones.append(PedestrianZone(
                        detector_id=detector_id,
                        edge_id=edge_id,
                        lane_id=lane_id,
                        start_position=start,
                        end_position=end,
                        period_seconds=period,
                    ))
        return cls(zones)

    @property
    def total_entries(self) -> int:
        return int(sum(values[0] for values in self._buckets.values()))

    @property
    def edge_ids(self) -> frozenset[str]:
        return frozenset(self._zones_by_edge)

    def observe(
        self,
        time_seconds: float,
        positions: Mapping[str, PersonPosition],
    ) -> None:
        """Observe one instant, including whole-zone jumps between samples."""
        current_ids = set(positions)
        for person_id in set(self._previous) - current_ids:
            self._previous.pop(person_id, None)
            self._inside.pop(person_id, None)

        for person_id, current in positions.items():
            if current.stage_type != 2:
                self._previous.pop(person_id, None)
                self._inside.pop(person_id, None)
                continue
            previous = self._previous.get(person_id)
            previously_inside = self._inside.get(person_id, set())
            currently_inside: set[str] = set()
            candidates: dict[str, PedestrianZone] = {}
            for zone in self._zones_by_edge.get(current.road_id, ()):
                candidates[zone.detector_id] = zone
            if previous is not None:
                for zone in self._zones_by_edge.get(previous.road_id, ()):
                    candidates[zone.detector_id] = zone

            for zone in candidates.values():
                is_inside = (
                    current.road_id == zone.edge_id
                    and zone.start_position <= current.lane_position <= zone.end_position
                )
                if is_inside:
                    currently_inside.add(zone.detector_id)

                entered = is_inside and zone.detector_id not in previously_inside
                if (
                    not entered
                    and previous is not None
                    and previous.road_id == zone.edge_id
                    and current.road_id == zone.edge_id
                    and zone.detector_id not in previously_inside
                ):
                    low = min(previous.lane_position, current.lane_position)
                    high = max(previous.lane_position, current.lane_position)
                    entered = low < zone.start_position and high > zone.end_position

                if entered:
                    self._record_entry(zone, float(time_seconds), current.speed)

            self._previous[person_id] = current
            self._inside[person_id] = currently_inside
        self.last_observation_time = max(
            self.last_observation_time,
            float(time_seconds),
        )

    def _record_entry(
        self,
        zone: PedestrianZone,
        time_seconds: float,
        speed: float,
    ) -> None:
        begin = math.floor(time_seconds / zone.period_seconds) * zone.period_seconds
        end = begin + zone.period_seconds
        bucket = self._buckets.setdefault(
            (zone.detector_id, begin, end),
            [0.0, 0.0],
        )
        bucket[0] += 1.0
        bucket[1] += max(float(speed), 0.0)

    def snapshot(self) -> dict[str, Any]:
        return {
            "previous": {
                person_id: {
                    "road_id": position.road_id,
                    "lane_position": position.lane_position,
                    "speed": position.speed,
                    "lane_id": position.lane_id,
                    "stage_type": position.stage_type,
                }
                for person_id, position in self._previous.items()
            },
            "inside": {
                person_id: sorted(detectors)
                for person_id, detectors in self._inside.items()
            },
            "buckets": [
                [detector_id, begin, end, values[0], values[1]]
                for (detector_id, begin, end), values in self._buckets.items()
            ],
            "last_observation_time": self.last_observation_time,
        }

    def restore(self, state: Mapping[str, Any]) -> None:
        self._previous = {
            person_id: PersonPosition(
                road_id=str(value["road_id"]),
                lane_position=float(value["lane_position"]),
                speed=float(value.get("speed") or 0),
                lane_id=str(value.get("lane_id") or ""),
                stage_type=int(value.get("stage_type") or 2),
            )
            for person_id, value in (state.get("previous") or {}).items()
        }
        self._inside = {
            person_id: set(detectors)
            for person_id, detectors in (state.get("inside") or {}).items()
        }
        self._buckets = {
            (str(row[0]), float(row[1]), float(row[2])): [
                float(row[3]),
                float(row[4]),
            ]
            for row in state.get("buckets") or []
        }
        self.last_observation_time = float(
            state.get("last_observation_time") or 0
        )

    def write_e2_xml(
        self,
        path: Path,
        *,
        simulation_begin: float,
        simulation_end: float,
    ) -> None:
        """Write all configured intervals in SUMO E2-compatible XML."""
        root = ET.Element("detector")
        effective_end = max(
            float(simulation_end),
            self.last_observation_time,
            float(simulation_begin),
        )
        for zone in sorted(self.zones, key=lambda item: item.detector_id):
            interval_begin = (
                math.floor(float(simulation_begin) / zone.period_seconds)
                * zone.period_seconds
            )
            while interval_begin < effective_end:
                interval_end = min(
                    interval_begin + zone.period_seconds,
                    effective_end,
                )
                values = self._buckets.get(
                    (
                        zone.detector_id,
                        interval_begin,
                        interval_begin + zone.period_seconds,
                    ),
                    [0.0, 0.0],
                )
                count = int(values[0])
                mean_speed = values[1] / count if count else -1.0
                ET.SubElement(root, "interval", {
                    "begin": f"{interval_begin:.2f}",
                    "end": f"{interval_end:.2f}",
                    "id": zone.detector_id,
                    "nVehEntered": str(count),
                    "nVehSeen": str(count),
                    "meanSpeed": f"{mean_speed:.6f}",
                    "meanOccupancy": "0.0",
                })
                interval_begin += zone.period_seconds

        path.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(root, space="  ")
        temporary_path = path.with_suffix(path.suffix + ".traci.tmp")
        ET.ElementTree(root).write(
            temporary_path,
            encoding="UTF-8",
            xml_declaration=True,
        )
        temporary_path.replace(path)
