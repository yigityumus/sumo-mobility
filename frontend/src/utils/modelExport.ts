import type {
  CampusBoundaryFeature,
  RequestInfo,
} from "../types/campus";
import { getFeatureId, selectedFeatureCollection } from "./osmFeatures";

export function buildingExportGeoJson({
  modelName,
  buildings,
  selectedBuildingIds,
  boundaryFeature,
  dataSourceLabel,
  buildingClassifications,
}: any) {
  const collection = selectedFeatureCollection(
    buildings,
    selectedBuildingIds,
    boundaryFeature,
    "buildings",
    dataSourceLabel,
  );
  const selectedIds = new Set(collection.features.map(getFeatureId));

  return {
    ...collection,
    configuration: {
      schema_version: 1,
      model_name: modelName,
      classifications: (buildingClassifications ?? []).map((classification: any) => ({
        ...classification,
        assignments: Object.fromEntries(
          Object.entries(classification.assignments ?? {}).filter(([buildingId]) =>
            selectedIds.has(buildingId),
          ),
        ),
      })),
    },
  };
}

export function parkingExportGeoJson({
  modelName,
  parkingAreas,
  selectedParkingIds,
  boundaryFeature,
  dataSourceLabel,
  parkingSpecs,
  parkingClassifications,
}: any) {
  const collection = selectedFeatureCollection(
    parkingAreas,
    selectedParkingIds,
    boundaryFeature,
    "parking_areas",
    dataSourceLabel,
  );
  const selectedIds = new Set(collection.features.map(getFeatureId));

  return {
    ...collection,
    configuration: {
      schema_version: 1,
      model_name: modelName,
      parking_specs: Object.fromEntries(
        Object.entries(parkingSpecs ?? {}).filter(([parkingId]) =>
          selectedIds.has(parkingId),
        ),
      ),
      classifications: (parkingClassifications ?? []).map((classification: any) => ({
        ...classification,
        assignments: Object.fromEntries(
          Object.entries(classification.assignments ?? {}).filter(([parkingId]) => selectedIds.has(parkingId)),
        ),
      })),
    },
  };
}

type ModelConfigInput = {
  id: string | null;
  name: string;
  createdAt: string | null;
  updatedAt: string | null;
  dataSourceLabel: string;
  requestInfo: RequestInfo | null;
  boundaryFeature: CampusBoundaryFeature;
  selectedBuildingIds: ReadonlySet<unknown>;
  selectedParkingIds: ReadonlySet<unknown>;
  sourceOsmFilename: string;
  sourceOsmIsUploaded: boolean;
  buildings: { features: unknown[] };
  parkingAreas: { features: unknown[] };
  includedFiles: string[];
  detectors?: unknown[];
  publicTransportOrigins?: unknown[];
  vehicleGenerationPoints?: unknown[];
};

export function modelConfigJson({
  id,
  name,
  createdAt,
  updatedAt,
  dataSourceLabel,
  requestInfo,
  boundaryFeature,
  selectedBuildingIds,
  selectedParkingIds,
  sourceOsmFilename,
  sourceOsmIsUploaded,
  buildings,
  parkingAreas,
  includedFiles,
  detectors,
  publicTransportOrigins,
  vehicleGenerationPoints,
}: ModelConfigInput) {
  return {
    schema_version: 1,
    exported_at: new Date().toISOString(),
    included_files: includedFiles,
    model: {
      id,
      name,
      createdAt,
      updatedAt,
      dataSourceLabel,
      requestInfo,
      boundaryFeature,
      selectedBuildingIds: [...selectedBuildingIds],
      selectedParkingIds: [...selectedParkingIds],
      sourceOsmFilename,
      sourceOsmIsUploaded,
      buildingCount: buildings.features.length,
      parkingAreaCount: parkingAreas.features.length,
      detectors: detectors ?? [],
      publicTransportOrigins: publicTransportOrigins ?? [],
      vehicleGenerationPoints: vehicleGenerationPoints ?? [],
    },
  };
}
