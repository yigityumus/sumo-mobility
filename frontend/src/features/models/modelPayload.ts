import { resolveExportFolderName } from "../../utils/zipExport.ts";

export function stripKnownOsmExtension(filename?: string | null) {
  return String(filename ?? "")
    .replace(/\.osm\.xml\.gz$/i, "")
    .replace(/\.osm\.xml$/i, "")
    .replace(/\.osm\.gz$/i, "")
    .replace(/\.osm$/i, "")
    .replace(/\.xml\.gz$/i, "")
    .replace(/\.xml$/i, "")
    .replace(/\.gz$/i, "");
}

export function buildAreaModelPayload({
  currentModelId,
  modelName,
  requestInfo,
  dataSourceLabel,
  boundaryFeature,
  buildings,
  parkingAreas,
  selectedBuildingIds,
  selectedParkingIds,
  parkingSpecs,
  buildingClassifications,
  parkingClassifications,
  detectors,
  publicTransportOrigins,
  vehicleGenerationPoints,
  sourceOsmFilename,
  sourceOsmIsUploaded,
  sourceOsmBlob,
}: any) {
  const now = new Date().toISOString();
  const id = currentModelId ?? crypto.randomUUID();
  const enteredName = String(modelName ?? "").trim();
  const name =
    enteredName ||
    stripKnownOsmExtension(requestInfo?.filename) ||
    resolveExportFolderName("");

  return {
    id,
    name,
    createdAt: currentModelId ? undefined : now,
    updatedAt: now,
    dataSourceLabel,
    requestInfo,
    boundaryFeature,
    buildings,
    parkingAreas,
    selectedBuildingIds: [...selectedBuildingIds],
    selectedParkingIds: [...selectedParkingIds],
    parkingSpecs,
    buildingClassifications,
    parkingClassifications,
    detectors,
    publicTransportOrigins,
    vehicleGenerationPoints,
    sourceOsmFilename,
    sourceOsmIsUploaded,
    // Do not fetch/cache a full OSM extract while saving. That network work is
    // reserved for export and parking-capacity estimation.
    sourceOsmBlob,
  };
}
