import { getFeatureId } from "../utils/osmFeatures.ts";
import { normalizeBuildingClassificationsForSignature } from "../utils/buildingSpecs.ts";
import { normalizeParkingClassificationsForSignature } from "../utils/parkingClassifications.ts";

function sortedArray(value: Iterable<unknown>) {
  return [...value].map(String).sort();
}

function normalizeJson(value: any): any {
  if (Array.isArray(value)) return value.map(normalizeJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, normalizeJson(item)]),
    );
  }
  return value;
}

function normalizeFeaturesForSignature(collection: any) {
  return [...(collection?.features ?? [])]
    .map((feature) => normalizeJson(feature))
    .sort((left, right) => getFeatureId(left).localeCompare(getFeatureId(right)));
}

function normalizeParkingSpecsForSignature(parkingSpecs = {}) {
  return Object.fromEntries(
    Object.entries(parkingSpecs)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([id, spec]: [string, any]) => [
        id,
        {
          access: spec.access ?? null,
          accessSource: spec.accessSource ?? null,
          capacity: spec.capacity ?? null,
          capacitySource: spec.capacitySource ?? null,
          capacityMethod: spec.capacityMethod ?? null,
          internalRoads: spec.internalRoads ?? "not_checked",
          changeDate: spec.changeDate ?? null,
        },
      ]),
  );
}

function normalizeBuildingSpecsForSignature(buildingClassifications = []) {
  return normalizeBuildingClassificationsForSignature(buildingClassifications);
}

export function modelSignatureValue({
  modelName,
  boundaryFeature,
  buildings,
  parkingAreas,
  selectedBuildingIds,
  selectedParkingIds,
  sourceOsmFilename,
  requestInfo,
  parkingSpecs,
  buildingClassifications,
  parkingClassifications,
  detectors,
  publicTransportOrigins,
  vehicleGenerationPoints,
}: any) {
  return {
    modelName: String(modelName ?? "").trim(),
    boundaryGeometry: boundaryFeature?.geometry ?? null,
    buildingIds: sortedArray((buildings?.features ?? []).map(getFeatureId)),
    parkingIds: sortedArray((parkingAreas?.features ?? []).map(getFeatureId)),
    buildingFeatures: normalizeFeaturesForSignature(buildings),
    parkingFeatures: normalizeFeaturesForSignature(parkingAreas),
    selectedBuildingIds: sortedArray(selectedBuildingIds ?? []),
    selectedParkingIds: sortedArray(selectedParkingIds ?? []),
    sourceOsmFilename: sourceOsmFilename ?? null,
    sourceRevision: requestInfo?.refreshedAt ?? null,
    parkingSpecs: normalizeParkingSpecsForSignature(parkingSpecs),
    buildingClassifications: normalizeBuildingSpecsForSignature(buildingClassifications),
    parkingClassifications: normalizeParkingClassificationsForSignature(parkingClassifications),
    detectors: [...(detectors ?? [])].sort((left, right) => String(left.id).localeCompare(String(right.id))),
    publicTransportOrigins: publicTransportOrigins === undefined
      ? null
      : [...publicTransportOrigins].sort((left, right) => String(left.id).localeCompare(String(right.id))),
    vehicleGenerationPoints: vehicleGenerationPoints === undefined
      ? null
      : [...vehicleGenerationPoints].sort((left, right) => String(left.id).localeCompare(String(right.id))),
  };
}

export function createModelSignature(value: any) {
  return JSON.stringify(modelSignatureValue(value));
}

export function hasModelContent({ boundaryFeature, buildings, parkingAreas, modelName }: any) {
  return Boolean(
    boundaryFeature ||
      buildings?.features?.length ||
      parkingAreas?.features?.length ||
      String(modelName ?? "").trim(),
  );
}
