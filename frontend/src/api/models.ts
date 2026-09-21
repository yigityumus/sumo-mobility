import type { CampusModel, DetectorLaneCandidate, ModelExportOptions } from "../types/campus";
import { requestBlob, requestJson, postForm, postJson } from "./client";
import {
  deleteCampusModel,
  getCampusModel,
  listCampusModels,
  saveCampusModel,
} from "../utils/modelStorage";

export const MODEL_STORAGE_MODE = (import.meta.env.VITE_MODEL_STORAGE ?? "server").toLowerCase();

export function isServerModelStorage() {
  return MODEL_STORAGE_MODE === "server";
}

function stripBlobFields(model: CampusModel) {
  const { sourceOsmBlob: _sourceOsmBlob, ...rest } = model;
  return rest;
}

async function maybeAppendSourceOsm(formData: FormData, model: CampusModel) {
  const blob = model.sourceOsmBlob;
  if (!blob) {
    return;
  }

  const filename = model.sourceOsmFilename || "source.osm.xml";
  if (blob instanceof File) {
    formData.append("source_osm_file", blob, filename);
    return;
  }

  formData.append("source_osm_file", blob, filename);
}

async function listModelsServer() {
  return requestJson<any[]>("/api/models", {}, "Could not list saved models.");
}

async function getModelServer(modelId: string) {
  return requestJson<CampusModel>(`/api/models/${encodeURIComponent(modelId)}`, {}, "Could not load model.");
}

async function saveModelServer(model: CampusModel) {
  const formData = new FormData();
  formData.append("model_json", JSON.stringify(stripBlobFields(model)));
  await maybeAppendSourceOsm(formData, model);
  return postForm<CampusModel>("/api/models", formData, "Could not save model.");
}

async function deleteModelServer(modelId: string) {
  return requestJson<void>(
    `/api/models/${encodeURIComponent(modelId)}`,
    { method: "DELETE" },
    "Could not delete model.",
  );
}

export async function listModels() {
  if (isServerModelStorage()) {
    return listModelsServer();
  }
  return listCampusModels();
}

export async function getModel(modelId: string) {
  if (isServerModelStorage()) {
    return getModelServer(modelId);
  }
  return getCampusModel(modelId) as Promise<CampusModel | null>;
}

export async function saveModel(model: CampusModel) {
  if (isServerModelStorage()) {
    return saveModelServer(model);
  }
  return saveCampusModel(model);
}

export async function deleteModel(modelId: string) {
  if (isServerModelStorage()) {
    return deleteModelServer(modelId);
  }
  return deleteCampusModel(modelId);
}

export async function getModelSourceOsm(modelId: string) {
  return requestBlob(
    `/api/models/${encodeURIComponent(modelId)}/source-osm`,
    {},
    "Could not retrieve model source OSM.",
  );
}

export async function downloadModelExport(modelId: string, options: ModelExportOptions) {
  const query = new URLSearchParams({
    osm: String(options.osm),
    buildings: String(options.buildings),
    parking_areas: String(options.parkingAreas),
    model_config: String(options.modelConfig),
  });
  return requestBlob(
    `/api/models/${encodeURIComponent(modelId)}/export?${query.toString()}`,
    {},
    "Could not export model ZIP.",
  );
}

export async function estimateModelParkingCapacity(modelId: string, parkingId: string) {
  return postJson<{ model: CampusModel; result: any }>(
    `/api/models/${encodeURIComponent(modelId)}/parking/estimate-capacity`,
    { parking_id: parkingId },
    "Could not estimate parking capacity.",
  );
}

export async function estimateModelUnknownParkingCapacities(modelId: string) {
  return postJson<{ model: CampusModel; summary: any }>(
    `/api/models/${encodeURIComponent(modelId)}/parking/estimate-all-unknown`,
    {},
    "Could not estimate unknown parking capacities.",
  );
}

export async function resolveDetectorLanes(modelId: string, location: { longitude: number; latitude: number }, radiusMetres = 30) {
  return postJson<{ candidates: DetectorLaneCandidate[]; network_cached: boolean }>(
    `/api/models/${encodeURIComponent(modelId)}/detectors/resolve`,
    { ...location, radius_metres: radiusMetres },
    "Could not resolve nearby SUMO lanes.",
  );
}
