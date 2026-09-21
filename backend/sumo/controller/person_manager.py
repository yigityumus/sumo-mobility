"""Create car occupants as pedestrians after their vehicles begin parking."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import traci
import traci.constants as tc


class PersonManager:
    def __init__(self, plan_path: Path, access_path: Path, event_logger) -> None:
        with plan_path.open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        self.car_plans = {
            str(row["vehicle_id"]): row
            for row in rows
            if row.get("arrival_mode") == "vehicle" and row.get("vehicle_id")
        }
        access = json.loads(access_path.read_text(encoding="utf-8"))
        self.parking_access = access.get("parking_access") or {}
        self.buildings = access.get("buildings") or []
        self.spawned_vehicle_ids: set[str] = set()
        self.event_logger = event_logger

    @property
    def accessible_physical_parking_ids(self) -> set[str]:
        return set(self.parking_access)

    def spawn_parked_occupant(self, vehicle_id: str, physical_parking_id: str, now: float) -> bool:
        if vehicle_id in self.spawned_vehicle_ids:
            return True
        plan = self.car_plans.get(vehicle_id)
        if plan is None:
            return False
        access = self.parking_access.get(physical_parking_id)
        if access is None:
            self._write_event(now, plan, physical_parking_id, "person_creation_failed", "No pedestrian access was resolved for the physical parking area.")
            return False

        person_id = str(plan["person_id"])
        from_edge = str(access["pedestrian_edge_id"])
        depart_pos = float(access["departure_position"])
        component_id = str(access.get("pedestrian_component_id") or "")
        try:
            planned_building = next(
                (
                    building
                    for building in self.buildings
                    if str(building.get("id")) == str(plan.get("building_id"))
                ),
                plan,
            )
            destinations = [planned_building] + [
                building
                for building in self.buildings
                if str(building.get("id")) != str(plan.get("building_id"))
            ]
            stages = ()
            selected_destination = planned_building
            for destination in destinations:
                destination_accesses = destination.get("pedestrian_accesses") or [destination]
                compatible_accesses = [
                    candidate
                    for candidate in destination_accesses
                    if not component_id
                    or str(candidate.get("pedestrian_component_id") or "") == component_id
                ]
                for destination_access in compatible_accesses:
                    to_edge = str(
                        destination_access.get("destination_edge")
                        or destination_access.get("pedestrian_edge_id")
                    )
                    arrival_pos = float(
                        destination_access.get("destination_position")
                        or destination_access.get("arrival_position")
                    )
                    stages = traci.simulation.findIntermodalRoute(
                        from_edge,
                        to_edge,
                        modes="",
                        depart=now,
                        departPos=depart_pos,
                        arrivalPos=arrival_pos,
                        pType="campus_pedestrian",
                    )
                    if stages:
                        selected_destination = destination
                        break
                if stages:
                    break
            if not stages:
                raise RuntimeError(f"No walking route from parking access edge '{from_edge}' to a selected building.")
            traci.person.add(
                person_id,
                from_edge,
                depart_pos,
                depart=tc.DEPARTFLAG_NOW,
                typeID="campus_pedestrian",
            )
            for stage in stages:
                traci.person.appendStage(person_id, stage)
        except Exception as exc:
            # Remove a partially added person so a malformed plan does not
            # strand the TraCI loop forever.
            try:
                if person_id in traci.person.getIDList():
                    traci.person.remove(person_id)
            except Exception:
                pass
            self._write_event(now, plan, physical_parking_id, "person_creation_failed", str(exc))
            return False

        self.spawned_vehicle_ids.add(vehicle_id)
        actual_plan = {
            **plan,
            "building_id": selected_destination.get("id") or selected_destination.get("building_id"),
            "building_name": selected_destination.get("name") or selected_destination.get("building_name"),
        }
        reason = (
            "vehicle_parked"
            if str(actual_plan["building_id"]) == str(plan.get("building_id"))
            else "planned_building_unreachable_from_parking; used_reachable_selected_building"
        )
        self._write_event(now, actual_plan, physical_parking_id, "walking_to_building", reason)
        return True

    def _write_event(self, now: float, plan: dict, parking_id: str, event: str, reason: str) -> None:
        self.event_logger.write(
            time=now,
            person_id=plan.get("person_id", ""),
            vehicle_id=plan.get("vehicle_id", ""),
            event=event,
            physical_parking=parking_id,
            building_id=plan.get("building_id", ""),
            building_name=plan.get("building_name", ""),
            reason=reason,
        )
