from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import traci

if TYPE_CHECKING:
    from parking_group_manager import ParkingGroupManager


def make_sumo_cmd(
    cfg: dict,
    run_dir: Path,
    sumocfg_file: Path,
) -> list[str]:
    sim = cfg["simulation"]
    sumo_binary = str(sim.get("sumo_binary", "sumo"))

    command = [
        sumo_binary,
        "-c",
        str(sumocfg_file),
        "--begin",
        str(sim.get("begin", 0)),
        # The configured end is the demand window, not a forced simulation
        # cutoff. TraCI closes SUMO after getMinExpectedNumber() reaches zero.
        "--end",
        "-1",
        "--step-length",
        str(sim.get("step_length", 1)),
        "--pedestrian.model",
        str(sim.get("pedestrian_model", "striping")),
        "--seed",
        str((cfg.get("controller") or {}).get("random_seed", 42)),
        # Keep SUMO's own diagnostics separate from the controller traceback.
        # This file is uploaded with the rest of the run artifacts.
        "--log",
        str(run_dir / "sumo.log"),
        # Keep parking entry/exit manoeuvres from intentionally blocking the
        # aisle. Queues can still form from normal car-following and junction
        # conflicts, but not from simulated parking manoeuvre time.
        "--parking.maneuver",
        "false",
        "--tripinfo-output",
        str(run_dir / "tripinfo.xml"),
        "--summary-output",
        str(run_dir / "summary.xml"),
        "--vehroute-output",
        str(run_dir / "vehroute.xml"),
        "--vehroute-output.exit-times",
        "true",
    ]

    if Path(sumo_binary).name == "sumo-gui":
        # XQuartz and other X11 servers may otherwise restore a position from
        # another display layout. Force a useful first window onto the visible
        # desktop while leaving the user free to move or resize it afterward.
        command.extend(
            [
                "--window-pos",
                str(sim.get("gui_window_position", "80,80")),
                "--window-size",
                str(sim.get("gui_window_size", "1100,750")),
            ]
        )

    return command


def set_new_parking_stop(veh_id: str, parking_id: str, duration: float) -> None:
    if not hasattr(traci.vehicle, "setParkingAreaStop"):
        raise RuntimeError(
            "Your TraCI build does not expose traci.vehicle.setParkingAreaStop(). "
            "You may need to adapt this to traci.vehicle.setStop(..., parkingArea=...)."
        )

    traci.vehicle.setParkingAreaStop(veh_id, parking_id, duration=duration)


def route_vehicle_to_physical_parking(veh_id: str, parking: "ParkingGroupManager", physical_id: str) -> None:
    area = parking.physical_by_id[physical_id]
    traci.vehicle.changeTarget(veh_id, area.edge_id)
