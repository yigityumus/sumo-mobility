from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import traci
import traci.constants as tc

from sumo.controller.main import (
    _remove_vehicle_without_stale_subscription,
    _subscription_results,
)


@unittest.skipUnless(shutil.which("sumo") and shutil.which("netconvert"), "SUMO is required")
class SubscriptionIntegrationTests(unittest.TestCase):
    def test_installed_sumo_returns_batched_vehicle_and_person_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nodes = root / "nodes.xml"
            edges = root / "edges.xml"
            network = root / "network.net.xml"
            routes = root / "routes.rou.xml"
            sumo_log = root / "sumo.log"
            nodes.write_text(
                "<nodes><node id='n0' x='0' y='0'/><node id='n1' x='1000' y='0'/></nodes>",
                encoding="utf-8",
            )
            edges.write_text(
                "<edges><edge id='e0' from='n0' to='n1' numLanes='1' speed='13.9' allow='passenger pedestrian'/></edges>",
                encoding="utf-8",
            )
            routes.write_text(
                """<routes>
                <vType id="car" vClass="passenger"/>
                <route id="route" edges="e0"/>
                <vehicle id="vehicle.1" type="car" route="route" depart="0"/>
                <person id="person.1" depart="0"><walk edges="e0"/></person>
                </routes>""",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "netconvert",
                    "--node-files",
                    str(nodes),
                    "--edge-files",
                    str(edges),
                    "--output-file",
                    str(network),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            try:
                traci.start([
                    "sumo",
                    "--net-file",
                    str(network),
                    "--route-files",
                    str(routes),
                    "--pedestrian.model",
                    "nonInteracting",
                    "--no-step-log",
                    "true",
                    "--no-warnings",
                    "true",
                    "--log",
                    str(sumo_log),
                ])
                traci.simulationStep()
                subscribed_vehicle_ids: set[str] = set()
                vehicle_results = _subscription_results(
                    traci.vehicle,
                    tuple(traci.vehicle.getIDList()),
                    subscribed_vehicle_ids,
                    (tc.VAR_ROAD_ID,),
                )
                person_results = _subscription_results(
                    traci.person,
                    tuple(traci.person.getIDList()),
                    set(),
                    (
                        tc.VAR_STAGES_REMAINING,
                        tc.VAR_ROAD_ID,
                        tc.VAR_LANE_ID,
                        tc.VAR_LANEPOSITION,
                        tc.VAR_SPEED,
                    ),
                )

                self.assertEqual(vehicle_results["vehicle.1"][tc.VAR_ROAD_ID], "e0")
                self.assertEqual(person_results["person.1"][tc.VAR_ROAD_ID], "e0")
                # nonInteracting persons are edge-positioned and deliberately
                # have no lane. This is why native lane-bound E2 detectors miss
                # them and the controller needs an edge-based counter.
                self.assertEqual(person_results["person.1"][tc.VAR_LANE_ID], "")
                self.assertEqual(traci.person.getStage("person.1", 0).type, tc.STAGE_WALKING)
                self.assertEqual(person_results["person.1"][tc.VAR_STAGES_REMAINING], 1)
                _remove_vehicle_without_stale_subscription(
                    "vehicle.1",
                    subscribed_vehicle_ids,
                )
                traci.simulationStep()
                self.assertNotIn("vehicle.1", traci.vehicle.getIDList())
            finally:
                traci.close(False)
            self.assertNotIn("is not known", sumo_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
