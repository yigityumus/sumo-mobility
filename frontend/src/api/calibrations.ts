import type {
  CalibrationSubject,
  FlowCalibrationSession,
  SimulationRunRequest,
} from "../types/campus";
import { postJson, requestJson } from "./client";

export function listFlowCalibrations(modelId: string) {
  return requestJson<FlowCalibrationSession[]>(
    `/api/models/${encodeURIComponent(modelId)}/flow-calibrations`,
    {},
    "Could not load flow calibrations.",
  );
}

export function startFlowCalibration(modelId: string, request: {
  name: string;
  real_world_source_id: string;
  detector_logical_id: string;
  subjects: CalibrationSubject[];
  iterations: number;
  step_percentage: number;
  simulation: SimulationRunRequest;
}) {
  return postJson<FlowCalibrationSession>(
    `/api/models/${encodeURIComponent(modelId)}/flow-calibrations`,
    request,
    "Could not start flow calibration.",
  );
}
