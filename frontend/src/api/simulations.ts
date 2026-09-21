import type { SimulationQueueStatus, SimulationRun, SimulationRunRequest } from "../types/campus";
import { postJson, requestJson } from "./client";

export function listSimulationRuns(modelId: string) {
  return requestJson<SimulationRun[]>(
    `/api/models/${encodeURIComponent(modelId)}/simulations`,
    {},
    "Could not load simulation history.",
  );
}

export function getSimulationQueueStatus() {
  return requestJson<SimulationQueueStatus>(
    "/api/simulations/queue",
    {},
    "Could not load simulation queue status.",
  );
}

export function startSimulationRun(modelId: string, request: SimulationRunRequest) {
  return postJson<SimulationRun>(
    `/api/models/${encodeURIComponent(modelId)}/simulations`,
    request,
    "Could not start the simulation.",
  );
}

export function deleteSimulationRun(modelId: string, runId: string) {
  return requestJson<void>(
    `/api/models/${encodeURIComponent(modelId)}/simulations/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
    "Could not delete the simulation run.",
  );
}

export function stopSimulationRun(modelId: string, runId: string) {
  return postJson<SimulationRun>(
    `/api/models/${encodeURIComponent(modelId)}/simulations/${encodeURIComponent(runId)}/stop`,
    {},
    "Could not stop the simulation.",
  );
}
