import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import HomeRoute from "./features/home/HomeRoute.tsx";
import WorkspaceView from "./features/workspace/WorkspaceView.tsx";
import SimulationPage from "./features/simulation/SimulationPage.tsx";
import AnalyticsPage from "./features/analytics/AnalyticsPage.tsx";
import DocumentationPage from "./features/documentation/DocumentationPage.tsx";
import {
  convertOsmCampusFeatures,
  downloadBlob,
  extractOuterRing,
  getBuildingDisplayName,
  getBuildingSearchText,
  getFeatureId,
  getParkingSearchText,
  isUnnamedBuilding,
  isUnnamedParkingArea,
} from "./utils/osmFeatures.ts";
import {
  buildParkingSpecs,
  highlightedParkingIdsFromFilters,
  updateParkingSpec,
} from "./utils/parkingSpecs.ts";
import {
  addBuildingType,
  deleteBuildingClassification,
  deleteBuildingType,
  normalizeBuildingClassifications,
  setBuildingAssignment,
  updateBuildingClassificationName,
  updateBuildingTypeDemandDistribution,
  updateBuildingTypeName,
} from "./utils/buildingSpecs.ts";
import {
  addParkingType,
  deleteParkingClassification,
  deleteParkingType,
  normalizeParkingClassifications,
  setParkingAssignment,
  updateParkingClassificationName,
  updateParkingTypeName,
} from "./utils/parkingClassifications.ts";
import {
  estimateParkingCapacityFromOsmData,
  parseOsmCapacitySource,
} from "./utils/parkingCapacityEstimator.ts";
import { downloadOsmExtract, extractCampusFeatures, uploadOsmFile as uploadOsmFileApi } from "./api/osm";
import {
  deleteModel,
  downloadModelExport,
  estimateModelParkingCapacity,
  estimateModelUnknownParkingCapacities,
  getModel,
  getModelSourceOsm,
  isServerModelStorage,
  listModels,
  resolveDetectorLanes,
  saveModel,
} from "./api/models";
import {
  createZipBlob,
  jsonBlob,
  resolveExportFolderName,
} from "./utils/zipExport.ts";
import {
  isHomeRoute,
  isDocumentationRoute,
  isSimulationRoute,
  isAnalyticsRoute,
  modelIdFromRoute,
  routeForModel,
  routeForSimulation,
  simulationModelIdFromRoute,
} from "./app/routes.ts";
import { createModelSignature, hasModelContent } from "./app/modelSignature.ts";
import { useLoadProgress, waitForNextFrame } from "./app/loadProgress.ts";
import {
  buildAreaModelPayload,
  stripKnownOsmExtension,
} from "./features/models/modelPayload.ts";
import {
  buildingExportGeoJson,
  modelConfigJson,
  parkingExportGeoJson,
} from "./utils/modelExport.ts";
import type {
  DetectorLaneCandidate,
  DetectorPoint,
  E1Detector,
  E3Detector,
  ModelExportOptions,
  PublicTransportOrigin,
  TrafficDetector,
  VehicleGenerationPoint,
} from "./types/campus.ts";

const EMPTY_COLLECTION = {
  type: "FeatureCollection",
  features: [],
};
const SELECTED_MODEL_STORAGE_KEY = "sumo-campus-builder:selected-model-id";
const ANALYTICS_RETURN_MODEL_STORAGE_KEY = "sumo-campus-builder:analytics-return-model-id";
const emptyDetectorCandidates = (): Record<"e1" | "entry" | "exit", DetectorLaneCandidate[]> => ({
  e1: [],
  entry: [],
  exit: [],
});

function featureLocation(feature): { longitude: number; latitude: number } {
  const points: Array<[number, number]> = [];
  const collect = (value) => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      points.push([value[0], value[1]]);
      return;
    }
    value.forEach(collect);
  };
  collect(feature?.geometry?.coordinates);
  if (!points.length) throw new Error("This building has no usable map coordinates.");
  return {
    longitude: points.reduce((sum, point) => sum + point[0], 0) / points.length,
    latitude: points.reduce((sum, point) => sum + point[1], 0) / points.length,
  };
}

function toggleId(setter, id) {
  setter((current) => {
    const next = new Set(current);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    return next;
  });
}

function selectFilteredIds(setter, features) {
  setter((current) => {
    const next = new Set(current);
    features.forEach((feature) => next.add(getFeatureId(feature)));
    return next;
  });
}

function deselectFilteredIds(setter, features) {
  setter((current) => {
    const next = new Set(current);
    features.forEach((feature) => next.delete(getFeatureId(feature)));
    return next;
  });
}

function deselectMatchingIds(setter, features, predicate) {
  setter((current) => {
    const next = new Set(current);
    features.forEach((feature) => {
      if (predicate(feature)) {
        next.delete(getFeatureId(feature));
      }
    });
    return next;
  });
}

function campusCollectionsFromPayload(payload) {
  return payload.features
    ? {
        buildings: payload.features.buildings ?? EMPTY_COLLECTION,
        parkingAreas:
          payload.features.parking_areas ??
          payload.features.parkingAreas ??
          EMPTY_COLLECTION,
      }
    : convertOsmCampusFeatures(payload.osm);
}


export default function App() {
  const [boundaryFeature, setBoundaryFeature] = useState(null);
  const [buildings, setBuildings] = useState(EMPTY_COLLECTION);
  const [parkingAreas, setParkingAreas] = useState(EMPTY_COLLECTION);
  const [selectedBuildingIds, setSelectedBuildingIds] = useState(new Set());
  const [selectedParkingIds, setSelectedParkingIds] = useState(new Set());
  const [buildingSearch, setBuildingSearch] = useState("");
  const [parkingSearch, setParkingSearch] = useState("");
  const [parkingSpecs, setParkingSpecs] = useState({});
  const [buildingClassifications, setBuildingClassifications] = useState([]);
  const [activeBuildingClassificationId, setActiveBuildingClassificationId] = useState(null);
  const [buildingSpecMessage, setBuildingSpecMessage] = useState("");
  const [parkingClassifications, setParkingClassifications] = useState([]);
  const [activeParkingClassificationId, setActiveParkingClassificationId] = useState(null);
  const [detectors, setDetectors] = useState<TrafficDetector[]>([]);
  const [activeDetectorId, setActiveDetectorId] = useState<string | null>(null);
  const [detectorCandidates, setDetectorCandidates] = useState(emptyDetectorCandidates);
  const [detectorPlacementType, setDetectorPlacementType] = useState<"e1" | "e3" | null>(null);
  const [e3EntryDraft, setE3EntryDraft] = useState<DetectorPoint | null>(null);
  const detectorPlacementActive = detectorPlacementType !== null;
  const [detectorResolving, setDetectorResolving] = useState(false);
  const [detectorMessage, setDetectorMessage] = useState("");
  const [publicTransportOrigins, setPublicTransportOrigins] = useState<PublicTransportOrigin[] | undefined>([]);
  const [publicTransportPointPlacementActive, setPublicTransportPointPlacementActive] = useState(false);
  const [vehicleGenerationPoints, setVehicleGenerationPoints] = useState<VehicleGenerationPoint[] | undefined>([]);
  const [activeVehicleGenerationPointId, setActiveVehicleGenerationPointId] = useState<string | null>(null);
  const [vehicleGenerationCandidates, setVehicleGenerationCandidates] = useState<DetectorLaneCandidate[]>([]);
  const [vehicleGenerationPointPlacementActive, setVehicleGenerationPointPlacementActive] = useState(false);
  const [vehicleGenerationResolving, setVehicleGenerationResolving] = useState(false);
  const [vehicleGenerationMessage, setVehicleGenerationMessage] = useState("");
  const [activeAccessFilters, setActiveAccessFilters] = useState(new Set());
  const [activeCapacityFilters, setActiveCapacityFilters] = useState(new Set());
  const [expandedParkingSpecId, setExpandedParkingSpecId] = useState(null);
  const [estimatingCapacity, setEstimatingCapacity] = useState(false);
  const [parkingSpecMessage, setParkingSpecMessage] = useState("");
  const [sidebarMode, setSidebarMode] = useState("default");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [downloadingOsm, setDownloadingOsm] = useState(false);
  const [refreshingOsm, setRefreshingOsm] = useState(false);
  const [error, setError] = useState("");
  const [requestInfo, setRequestInfo] = useState(null);
  const [dataSourceLabel, setDataSourceLabel] = useState("OpenStreetMap via Overpass API");
  const [sourceOsmBlob, setSourceOsmBlob] = useState(null);
  const [sourceOsmFilename, setSourceOsmFilename] = useState("area_osm_extract.osm.xml");
  const [sourceOsmIsUploaded, setSourceOsmIsUploaded] = useState(false);
  const [savedModels, setSavedModels] = useState([]);
  const [modelName, setModelName] = useState("");
  const [currentModelId, setCurrentModelId] = useState(null);
  const [modelCreatedAt, setModelCreatedAt] = useState(null);
  const [modelUpdatedAt, setModelUpdatedAt] = useState(null);
  const [savingModel, setSavingModel] = useState(false);
  const [loadingModel, setLoadingModel] = useState(false);
  const [exportingAll, setExportingAll] = useState(false);
  const [savedModelSignature, setSavedModelSignature] = useState(null);
  const [newModelMode, setNewModelMode] = useState(false);
  const [routePath, setRoutePath] = useState(() => window.location.pathname || "/");
  const attemptedModelRouteRef = useRef<string | null>(null);
  const [modelActionDialog, setModelActionDialog] = useState(null);
  const {
    loadProgress,
    resetLoadProgress,
    startLoadProgress,
    activateLoadProgressStep,
    completeLoadProgress,
    failLoadProgress,
  } = useLoadProgress();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const filteredBuildings = useMemo(() => {
    const normalizedSearch = buildingSearch.trim().toLocaleLowerCase();
    if (!normalizedSearch) {
      return buildings.features;
    }

    return buildings.features.filter((feature) =>
      getBuildingSearchText(feature).includes(normalizedSearch),
    );
  }, [buildings, buildingSearch]);

  const filteredParkingAreas = useMemo(() => {
    const normalizedSearch = parkingSearch.trim().toLocaleLowerCase();
    if (!normalizedSearch) {
      return parkingAreas.features;
    }

    return parkingAreas.features.filter((feature) =>
      getParkingSearchText(feature).includes(normalizedSearch),
    );
  }, [parkingAreas, parkingSearch]);

  const highlightedParkingIds = useMemo(
    () =>
      highlightedParkingIdsFromFilters({
        parkingAreas,
        parkingSpecs,
        activeAccessFilters,
        activeCapacityFilters,
      }),
    [parkingAreas, parkingSpecs, activeAccessFilters, activeCapacityFilters],
  );

  const expandedParkingIds = useMemo(
    () => (expandedParkingSpecId ? new Set([expandedParkingSpecId]) : new Set()),
    [expandedParkingSpecId],
  );

  const activeBuildingClassification = useMemo(() => {
    if (sidebarMode !== "buildingSpecs") {
      return null;
    }

    return (buildingClassifications ?? []).find(
      (classification) => classification.id === activeBuildingClassificationId,
    ) ?? buildingClassifications?.[0] ?? null;
  }, [activeBuildingClassificationId, buildingClassifications, sidebarMode]);

  const activeParkingClassification = useMemo(() => {
    if (sidebarMode !== "parkingSpecs") return null;
    return (parkingClassifications ?? []).find(
      (classification) => classification.id === activeParkingClassificationId,
    ) ?? parkingClassifications?.[0] ?? null;
  }, [activeParkingClassificationId, parkingClassifications, sidebarMode]);

  useEffect(() => {
    const handlePopState = () => setRoutePath(window.location.pathname || "/");
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigateTo = useCallback((pathname, { replace = false } = {}) => {
    if (window.location.pathname === pathname) {
      setRoutePath(pathname);
      return;
    }

    if (replace) {
      window.history.replaceState(null, "", pathname);
    } else {
      window.history.pushState(null, "", pathname);
    }
    setRoutePath(pathname);
  }, []);

  const currentModelSignature = useMemo(
    () =>
      createModelSignature({
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
      }),
    [
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
    ],
  );

  const currentModelHasContent = hasModelContent({
    boundaryFeature,
    buildings,
    parkingAreas,
    modelName,
  });

  const hasUnsavedChanges =
    currentModelHasContent && currentModelSignature !== savedModelSignature;

  useEffect(() => {
    const handleBeforeUnload = (event) => {
      if (!hasUnsavedChanges) {
        return;
      }

      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedChanges]);

  const refreshSavedModels = useCallback(async () => {
    try {
      const models = await listModels();
      setSavedModels(models);

    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not read saved area models.",
      );
    }
  }, []);

  useEffect(() => {
    refreshSavedModels();
  }, [refreshSavedModels]);



  const unnamedBuildingCount = useMemo(
    () => buildings.features.filter(isUnnamedBuilding).length,
    [buildings],
  );

  const unnamedParkingCount = useMemo(
    () => parkingAreas.features.filter(isUnnamedParkingArea).length,
    [parkingAreas],
  );

  const selectedUnnamedBuildingCount = useMemo(
    () => buildings.features.filter(
      (feature) => isUnnamedBuilding(feature) && selectedBuildingIds.has(getFeatureId(feature)),
    ).length,
    [buildings, selectedBuildingIds],
  );

  const selectedUnnamedParkingCount = useMemo(
    () => parkingAreas.features.filter(
      (feature) => isUnnamedParkingArea(feature) && selectedParkingIds.has(getFeatureId(feature)),
    ).length,
    [parkingAreas, selectedParkingIds],
  );

  const resetLoadedFeatures = useCallback(() => {
    setBuildings(EMPTY_COLLECTION);
    setParkingAreas(EMPTY_COLLECTION);
    setSelectedBuildingIds(new Set());
    setSelectedParkingIds(new Set());
    setBuildingSearch("");
    setParkingSearch("");
    setParkingSpecs({});
    setBuildingClassifications([]);
    setActiveBuildingClassificationId(null);
    setParkingClassifications([]);
    setActiveParkingClassificationId(null);
    setDetectors([]);
    setActiveDetectorId(null);
    setDetectorCandidates(emptyDetectorCandidates());
    setDetectorPlacementType(null);
    setE3EntryDraft(null);
    setDetectorMessage("");
    setPublicTransportOrigins([]);
    setPublicTransportPointPlacementActive(false);
    setVehicleGenerationPoints([]);
    setActiveVehicleGenerationPointId(null);
    setVehicleGenerationCandidates([]);
    setVehicleGenerationPointPlacementActive(false);
    setVehicleGenerationMessage("");
    setBuildingSpecMessage("");
    setActiveAccessFilters(new Set());
    setActiveCapacityFilters(new Set());
    setExpandedParkingSpecId(null);
    setParkingSpecMessage("");
    setSidebarMode("default");
  }, []);

  const startNewModel = useCallback(() => {
    if (
      hasUnsavedChanges &&
      !window.confirm(
        "The current model has unsaved changes. Start a new model and discard those changes?",
      )
    ) {
      return;
    }

    setBoundaryFeature(null);
    resetLoadedFeatures();
    setError("");
    setRequestInfo(null);
    setDataSourceLabel("OpenStreetMap via Overpass API");
    setSourceOsmBlob(null);
    setSourceOsmFilename("area_osm_extract.osm.xml");
    setSourceOsmIsUploaded(false);
    setModelName("");
    setCurrentModelId(null);
    setModelCreatedAt(null);
    setModelUpdatedAt(null);
    setSavedModelSignature(null);
    resetLoadProgress();
    setNewModelMode(true);
    navigateTo("/new-model");
  }, [hasUnsavedChanges, navigateTo, resetLoadedFeatures, resetLoadProgress]);

  const handleBoundaryChange = useCallback((feature) => {
    setBoundaryFeature(feature);
    setNewModelMode(true);
    resetLoadedFeatures();
    setSourceOsmBlob(null);
    setSourceOsmFilename("area_osm_extract.osm.xml");
    setSourceOsmIsUploaded(false);
    setCurrentModelId(null);
    setModelCreatedAt(null);
    setModelUpdatedAt(null);
    setError("");
    setRequestInfo(null);
    setDataSourceLabel("OpenStreetMap via Overpass API");
    setSavedModelSignature(null);
    resetLoadProgress();
    navigateTo("/new-model");
  }, [navigateTo, resetLoadedFeatures, resetLoadProgress]);

  const applyOsmPayload = useCallback((payload, sourceLabel, info) => {
    const converted = campusCollectionsFromPayload(payload);

    const buildingIds = converted.buildings.features.map(getFeatureId);
    const parkingIds = converted.parkingAreas.features.map(getFeatureId);
    const defaultParkingSpecs = buildParkingSpecs(converted.parkingAreas);
    const defaultBuildingClassifications = normalizeBuildingClassifications(
      converted.buildings,
      [],
    );

    setBuildings(converted.buildings);
    setParkingAreas(converted.parkingAreas);
    setSelectedBuildingIds(new Set(buildingIds));
    setSelectedParkingIds(new Set(parkingIds));
    setParkingSpecs(defaultParkingSpecs);
    setBuildingClassifications(defaultBuildingClassifications);
    setActiveBuildingClassificationId(defaultBuildingClassifications[0]?.id ?? null);
    setParkingClassifications([]);
    setActiveParkingClassificationId(null);
    setDetectors([]);
    setActiveDetectorId(null);
    setDetectorCandidates(emptyDetectorCandidates());
    setDetectorPlacementType(null);
    setE3EntryDraft(null);
    setDetectorMessage("");
    setPublicTransportOrigins([]);
    setPublicTransportPointPlacementActive(false);
    setVehicleGenerationPoints([]);
    setActiveVehicleGenerationPointId(null);
    setVehicleGenerationCandidates([]);
    setVehicleGenerationPointPlacementActive(false);
    setVehicleGenerationMessage("");
    setBuildingSpecMessage("");
    setActiveAccessFilters(new Set());
    setActiveCapacityFilters(new Set());
    setExpandedParkingSpecId(null);
    setParkingSpecMessage("");
    setSidebarMode("default");
    if (payload.boundary) {
      setBoundaryFeature(payload.boundary);
    }
    setDataSourceLabel(sourceLabel);
    setRequestInfo({ ...info, stats: payload.stats ?? null });

    if (!buildingIds.length && !parkingIds.length) {
      setError("No building or parking-area polygons were found in this data source.");
    }
  }, []);

  const loadFeatures = async () => {
    setError("");
    setRequestInfo(null);
    startLoadProgress();

    try {
      setLoading(true);
      await waitForNextFrame();

      const coordinates = extractOuterRing(boundaryFeature);
      activateLoadProgressStep("request-backend");
      await waitForNextFrame();

      activateLoadProgressStep("fetch-overpass");
      const payload = await extractCampusFeatures(coordinates);

      activateLoadProgressStep("receive-osm");
      await waitForNextFrame();

      activateLoadProgressStep("extract-buildings");
      await waitForNextFrame();

      activateLoadProgressStep("extract-parking");
      applyOsmPayload(payload, "OpenStreetMap via Overpass API", {
        source: "overpass",
        endpoint: payload.endpoint,
        cacheHit: payload.cache_hit,
      });

      activateLoadProgressStep("prepare-ui");
      await waitForNextFrame();

      setSourceOsmBlob(null);
      setSourceOsmFilename("area_osm_extract.osm.xml");
      setSourceOsmIsUploaded(false);
      setCurrentModelId(null);
      setModelCreatedAt(null);
      setModelUpdatedAt(null);
      setSavedModelSignature(null);
      setNewModelMode(true);
      navigateTo("/new-model");
      completeLoadProgress();
    } catch (caughtError) {
      const message = caughtError instanceof Error ? caughtError.message : "Unknown error.";
      resetLoadedFeatures();
      failLoadProgress(message);
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const uploadOsmFile = async (file) => {
    if (!file) {
      return;
    }

    setError("");
    setRequestInfo(null);
    resetLoadProgress();
    setUploading(true);

    try {
      const payload = await uploadOsmFileApi(file);
      applyOsmPayload(payload, `Uploaded OSM file: ${file.name}`, {
        source: "upload",
        filename: file.name,
        endpoint: payload.endpoint,
        cacheHit: false,
      });
      setBoundaryFeature(payload.boundary ?? null);
      setSourceOsmBlob(file);
      setSourceOsmFilename(file.name || "uploaded_area.osm.xml");
      setSourceOsmIsUploaded(true);
      setCurrentModelId(null);
      setModelCreatedAt(null);
      setModelUpdatedAt(null);
      setModelName(stripKnownOsmExtension(file.name) ?? "");
      setSavedModelSignature(null);
      setNewModelMode(true);
      navigateTo("/new-model");
    } catch (caughtError) {
      resetLoadedFeatures();
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error.");
    } finally {
      setUploading(false);
    }
  };

  const downloadSelectedAreaOsm = async () => {
    setError("");

    try {
      const coordinates = extractOuterRing(boundaryFeature);
      setDownloadingOsm(true);

      const blob = await downloadOsmExtract(coordinates);
      const exportName = `${resolveExportFolderName(modelName)}.osm.xml`;
      setSourceOsmBlob(blob);
      setSourceOsmFilename(exportName);
      setSourceOsmIsUploaded(false);
      downloadBlob(exportName, blob);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Unknown error.");
    } finally {
      setDownloadingOsm(false);
    }
  };

  const refreshOsmArea = async () => {
    if (!boundaryFeature || !currentModelId) {
      setError("Save a boundary-based model before refreshing its OSM area.");
      return;
    }
    if (!window.confirm(
      "Fetch the latest OpenStreetMap data for this exact boundary? Existing selections and specifications will be preserved for matching OSM IDs. New features will remain unselected until you review them.",
    )) {
      return;
    }

    setError("");
    setRefreshingOsm(true);
    try {
      const coordinates = extractOuterRing(boundaryFeature);
      const freshOsmBlob = await downloadOsmExtract(coordinates);
      const refreshedFilename = sourceOsmFilename || "area_osm_extract.osm.xml";
      const parseFile = new File(
        [freshOsmBlob],
        refreshedFilename,
        { type: freshOsmBlob.type || "application/xml" },
      );
      const payload = await uploadOsmFileApi(parseFile);
      const converted = campusCollectionsFromPayload(payload);

      const previousBuildingIds = new Set<string>(buildings.features.map(getFeatureId));
      const previousParkingIds = new Set<string>(parkingAreas.features.map(getFeatureId));
      const refreshedBuildingIds = new Set<string>(converted.buildings.features.map(getFeatureId));
      const refreshedParkingIds = new Set<string>(converted.parkingAreas.features.map(getFeatureId));
      const refreshedBuildingById = new Map(
        converted.buildings.features.map((feature) => [getFeatureId(feature), feature]),
      );

      const nextSelectedBuildingIds = new Set(
        [...selectedBuildingIds].filter((id) => refreshedBuildingIds.has(String(id))),
      );
      const nextSelectedParkingIds = new Set(
        [...selectedParkingIds].filter((id) => refreshedParkingIds.has(String(id))),
      );
      const nextBuildingClassifications = normalizeBuildingClassifications(
        converted.buildings,
        buildingClassifications,
      );
      const nextParkingClassifications = normalizeParkingClassifications(
        converted.parkingAreas,
        parkingClassifications,
      );
      const nextPublicTransportOrigins = publicTransportOrigins === undefined
        ? undefined
        : publicTransportOrigins.flatMap((origin) => {
            if (origin.sourceType !== "building" || !origin.buildingId) return [origin];
            const feature = refreshedBuildingById.get(String(origin.buildingId));
            if (!feature) return [];
            return [{ ...origin, location: featureLocation(feature) }];
          });

      const refreshSummary = {
        buildingsAdded: [...refreshedBuildingIds].filter((id) => !previousBuildingIds.has(id)).length,
        buildingsRemoved: [...previousBuildingIds].filter((id) => !refreshedBuildingIds.has(id)).length,
        parkingAdded: [...refreshedParkingIds].filter((id) => !previousParkingIds.has(id)).length,
        parkingRemoved: [...previousParkingIds].filter((id) => !refreshedParkingIds.has(id)).length,
        buildingSelectionsRemoved: selectedBuildingIds.size - nextSelectedBuildingIds.size,
        parkingSelectionsRemoved: selectedParkingIds.size - nextSelectedParkingIds.size,
        buildingOriginsRemoved:
          (publicTransportOrigins?.length ?? 0) - (nextPublicTransportOrigins?.length ?? 0),
      };

      setBuildings(converted.buildings);
      setParkingAreas(converted.parkingAreas);
      setSelectedBuildingIds(nextSelectedBuildingIds);
      setSelectedParkingIds(nextSelectedParkingIds);
      setParkingSpecs(buildParkingSpecs(converted.parkingAreas, parkingSpecs));
      setBuildingClassifications(nextBuildingClassifications);
      setParkingClassifications(nextParkingClassifications);
      setPublicTransportOrigins(nextPublicTransportOrigins);
      setDetectorCandidates(emptyDetectorCandidates());
      setVehicleGenerationCandidates([]);
      setSourceOsmBlob(freshOsmBlob);
      setSourceOsmFilename(refreshedFilename);
      setSourceOsmIsUploaded(false);
      setDataSourceLabel("OpenStreetMap via Overpass API (refreshed)");
      setRequestInfo({
        source: "osm-refresh",
        refreshedAt: new Date().toISOString(),
        stats: payload.stats ?? null,
        refreshSummary,
      });
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Could not refresh the OpenStreetMap area.",
      );
    } finally {
      setRefreshingOsm(false);
    }
  };

  const fetchCurrentOsmBlob = async () => {
    if (sourceOsmBlob) {
      return sourceOsmBlob;
    }

    if (isServerModelStorage() && currentModelId) {
      const blob = await getModelSourceOsm(currentModelId);
      setSourceOsmBlob(blob);
      setSourceOsmFilename(sourceOsmFilename || "area_osm_extract.osm.xml");
      setSourceOsmIsUploaded(false);
      return blob;
    }

    if (!boundaryFeature) {
      throw new Error(
        "No source OSM file is available. Upload an OSM file or draw a boundary first.",
      );
    }

    const coordinates = extractOuterRing(boundaryFeature);
    const blob = await downloadOsmExtract(coordinates);
    setSourceOsmBlob(blob);
    setSourceOsmFilename("area_osm_extract.osm.xml");
    setSourceOsmIsUploaded(false);
    return blob;
  };

  const currentCampusModelPayload = () =>
    buildAreaModelPayload({
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
    });

  const saveCurrentModel = async () => {
    setError("");
    setSavingModel(true);

    try {
      const model = currentCampusModelPayload();
      const previous = currentModelId ? await getModel(currentModelId) : null;
      const createdAt = previous?.createdAt ?? model.createdAt ?? model.updatedAt;
      const savedModel = {
        ...model,
        createdAt,
      };
      await saveModel(savedModel);
      setCurrentModelId(model.id);
      window.sessionStorage.setItem(SELECTED_MODEL_STORAGE_KEY, model.id);
      setModelName(model.name);
      setModelCreatedAt(createdAt);
      setModelUpdatedAt(model.updatedAt);
      navigateTo(routeForModel(model.id), { replace: !currentModelId });
      setSavedModelSignature(
        createModelSignature({
          modelName: model.name,
          boundaryFeature: model.boundaryFeature,
          buildings: model.buildings,
          parkingAreas: model.parkingAreas,
          selectedBuildingIds: model.selectedBuildingIds,
          selectedParkingIds: model.selectedParkingIds,
          sourceOsmFilename: model.sourceOsmFilename,
          requestInfo: model.requestInfo,
          parkingSpecs: model.parkingSpecs,
          buildingClassifications: model.buildingClassifications,
          parkingClassifications: model.parkingClassifications,
          detectors: model.detectors,
          publicTransportOrigins: model.publicTransportOrigins,
          vehicleGenerationPoints: model.vehicleGenerationPoints,
        }),
      );
      await refreshSavedModels();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not save model.");
    } finally {
      setSavingModel(false);
    }
  };

  const loadSavedModel = async (
    modelId,
    options: { skipUnsavedConfirm?: boolean; navigateAfterLoad?: boolean } = {},
  ) => {
    const { skipUnsavedConfirm = false, navigateAfterLoad = true } = options;

    if (
      !skipUnsavedConfirm &&
      hasUnsavedChanges &&
      modelId !== currentModelId &&
      !window.confirm(
        "The current model has unsaved changes. Load another model and discard those changes?",
      )
    ) {
      return;
    }

    setError("");
    setLoadingModel(true);

    try {
      const model = await getModel(modelId);
      if (!model) {
        throw new Error("The selected area model no longer exists.");
      }

      const loadedParkingAreas = model.parkingAreas ?? EMPTY_COLLECTION;
      const loadedBuildings = model.buildings ?? EMPTY_COLLECTION;
      const loadedParkingSpecs = buildParkingSpecs(loadedParkingAreas, model.parkingSpecs ?? {});
      const loadedBuildingClassifications = normalizeBuildingClassifications(
        loadedBuildings,
        model.buildingClassifications ?? [],
      );
      const loadedParkingClassifications = normalizeParkingClassifications(
        loadedParkingAreas,
        model.parkingClassifications ?? [],
      );

      setBoundaryFeature(model.boundaryFeature ?? null);
      setBuildings(loadedBuildings);
      setParkingAreas(loadedParkingAreas);
      setSelectedBuildingIds(new Set(model.selectedBuildingIds ?? []));
      setSelectedParkingIds(new Set(model.selectedParkingIds ?? []));
      setParkingSpecs(loadedParkingSpecs);
      setBuildingClassifications(loadedBuildingClassifications);
      setActiveBuildingClassificationId(loadedBuildingClassifications[0]?.id ?? null);
      setParkingClassifications(loadedParkingClassifications);
      setActiveParkingClassificationId(loadedParkingClassifications[0]?.id ?? null);
      setDetectors(model.detectors ?? []);
      setPublicTransportOrigins(model.publicTransportOrigins);
      setPublicTransportPointPlacementActive(false);
      setVehicleGenerationPoints(model.vehicleGenerationPoints);
      setActiveVehicleGenerationPointId(model.vehicleGenerationPoints?.[0]?.id ?? null);
      setVehicleGenerationCandidates([]);
      setVehicleGenerationPointPlacementActive(false);
      setVehicleGenerationMessage("");
      setActiveDetectorId(model.detectors?.[0]?.id ?? null);
      setDetectorCandidates(emptyDetectorCandidates());
      setDetectorPlacementType(null);
      setE3EntryDraft(null);
      setDetectorMessage("");
      setBuildingSpecMessage("");
      setActiveAccessFilters(new Set());
      setActiveCapacityFilters(new Set());
      setExpandedParkingSpecId(null);
      setBuildingSearch("");
      setParkingSearch("");
      setSidebarMode("default");
      setSourceOsmBlob(model.sourceOsmBlob ?? null);
      setSourceOsmFilename(model.sourceOsmFilename ?? "area_osm_extract.osm.xml");
      setSourceOsmIsUploaded(Boolean(model.sourceOsmIsUploaded));
      setDataSourceLabel(model.dataSourceLabel ?? "Saved area model");
      setRequestInfo({
        ...(model.requestInfo ?? {}),
        source: "saved-model",
        modelName: model.name,
      });
      setModelName(model.name ?? "");
      setCurrentModelId(model.id);
      setModelCreatedAt(model.createdAt ?? null);
      setModelUpdatedAt(model.updatedAt ?? null);
      setNewModelMode(false);
      if (navigateAfterLoad) {
        navigateTo(routeForModel(model.id));
      }
      setSavedModelSignature(
        createModelSignature({
          modelName: model.name ?? "",
          boundaryFeature: model.boundaryFeature ?? null,
          buildings: loadedBuildings,
          parkingAreas: loadedParkingAreas,
          selectedBuildingIds: model.selectedBuildingIds ?? [],
          selectedParkingIds: model.selectedParkingIds ?? [],
          sourceOsmFilename: model.sourceOsmFilename ?? "area_osm_extract.osm.xml",
          requestInfo: model.requestInfo,
          parkingSpecs: loadedParkingSpecs,
          buildingClassifications: loadedBuildingClassifications,
          parkingClassifications: loadedParkingClassifications,
          detectors: model.detectors ?? [],
          publicTransportOrigins: model.publicTransportOrigins,
          vehicleGenerationPoints: model.vehicleGenerationPoints,
        }),
      );
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not load model.");
    } finally {
      setLoadingModel(false);
    }
  };

  useEffect(() => {
    if (routePath === "/new-model") {
      setNewModelMode(true);
      return;
    }

    if (isSimulationRoute(routePath)) {
      const selectedModelId =
        simulationModelIdFromRoute(routePath) ??
        currentModelId ??
        window.sessionStorage.getItem(SELECTED_MODEL_STORAGE_KEY);
      const attemptKey = selectedModelId ? `${routePath}:${selectedModelId}` : null;
      if (
        selectedModelId &&
        selectedModelId !== currentModelId &&
        !loadingModel &&
        attemptedModelRouteRef.current !== attemptKey
      ) {
        attemptedModelRouteRef.current = attemptKey;
        void loadSavedModel(selectedModelId, {
          skipUnsavedConfirm: true,
          navigateAfterLoad: false,
        });
      }
      return;
    }

    const modelId = modelIdFromRoute(routePath);
    const attemptKey = modelId ? `${routePath}:${modelId}` : null;
    if (
      !modelId ||
      modelId === currentModelId ||
      loadingModel ||
      attemptedModelRouteRef.current === attemptKey
    ) {
      return;
    }

    attemptedModelRouteRef.current = attemptKey;
    void loadSavedModel(modelId, {
      skipUnsavedConfirm: true,
      navigateAfterLoad: false,
    });
  }, [currentModelId, loadingModel, routePath]);

  const deleteSavedModel = async (modelId) => {
    setError("");

    try {
      await deleteModel(modelId);
      if (currentModelId === modelId) {
        setCurrentModelId(null);
        setModelCreatedAt(null);
        setModelUpdatedAt(null);
        setSavedModelSignature(null);
      }
      await refreshSavedModels();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not delete model.");
    }
  };

  const requestDuplicateModel = (model) => {
    setModelActionDialog({
      action: "duplicate",
      model,
      defaultValue: `Copy of ${model.name}`,
    });
  };

  const requestRenameModel = (model) => {
    setModelActionDialog({
      action: "rename",
      model,
      defaultValue: model.name,
    });
  };

  const requestDeleteModel = (model) => {
    setModelActionDialog({
      action: "delete",
      model,
      defaultValue: "",
    });
  };

  const confirmModelAction = async (newName) => {
    if (!modelActionDialog) {
      return;
    }

    setError("");

    try {
      const { action, model } = modelActionDialog;

      if (action === "delete") {
        await deleteSavedModel(model.id);
        setModelActionDialog(null);
        return;
      }

      const trimmedName = String(newName ?? "").trim();
      if (!trimmedName) {
        return;
      }

      const fullModel = await getModel(model.id);
      if (!fullModel) {
        throw new Error("The selected area model no longer exists.");
      }

      const now = new Date().toISOString();

      if (action === "duplicate") {
        const newId = crypto.randomUUID();
        await saveModel({
          ...fullModel,
          id: newId,
          name: trimmedName,
          createdAt: now,
          updatedAt: now,
        });
        await refreshSavedModels();
        setModelActionDialog(null);
        return;
      }

      if (action === "rename") {
        const renamedModel = {
          ...fullModel,
          name: trimmedName,
          updatedAt: now,
        };
        await saveModel(renamedModel);

        if (currentModelId === model.id) {
          const loadedParkingSpecs = buildParkingSpecs(
            renamedModel.parkingAreas ?? EMPTY_COLLECTION,
            renamedModel.parkingSpecs ?? {},
          );
          setModelName(trimmedName);
          setModelUpdatedAt(now);
          setSavedModelSignature(
            createModelSignature({
              modelName: trimmedName,
              boundaryFeature: renamedModel.boundaryFeature ?? null,
              buildings: renamedModel.buildings ?? EMPTY_COLLECTION,
              parkingAreas: renamedModel.parkingAreas ?? EMPTY_COLLECTION,
              selectedBuildingIds: renamedModel.selectedBuildingIds ?? [],
              selectedParkingIds: renamedModel.selectedParkingIds ?? [],
              sourceOsmFilename:
                renamedModel.sourceOsmFilename ?? "area_osm_extract.osm.xml",
              requestInfo: renamedModel.requestInfo,
              parkingSpecs: loadedParkingSpecs,
              buildingClassifications: normalizeBuildingClassifications(
                renamedModel.buildings ?? EMPTY_COLLECTION,
                renamedModel.buildingClassifications ?? [],
              ),
              parkingClassifications: normalizeParkingClassifications(
                renamedModel.parkingAreas ?? EMPTY_COLLECTION,
                renamedModel.parkingClassifications ?? [],
              ),
              detectors: renamedModel.detectors ?? [],
              publicTransportOrigins: renamedModel.publicTransportOrigins,
              vehicleGenerationPoints: renamedModel.vehicleGenerationPoints,
            }),
          );
        }

        await refreshSavedModels();
        setModelActionDialog(null);
      }
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not update model.");
    }
  };


  const internalRoadsFromCapacityResult = (result) => {
    const ids = result?.relatedWayIds ?? [];
    return ids.length ? ids.map(String) : "not_found";
  };

  const calculateCapacityResultForFeature = (feature, osmData) => {
    const result = estimateParkingCapacityFromOsmData(feature, osmData);
    if (!result.capacity) {
      const error = new Error(result.error || "Could not estimate capacity for this parking area.");
      (error as Error & { capacityResult?: typeof result }).capacityResult = result;
      throw error;
    }
    return result;
  };

  const estimateCapacityForParking = async (parkingId) => {
    setError("");
    setParkingSpecMessage("");
    setEstimatingCapacity(true);

    try {
      if (isServerModelStorage() && currentModelId && !hasUnsavedChanges) {
        const { model, result } = await estimateModelParkingCapacity(currentModelId, parkingId);
        const loadedParkingSpecs = buildParkingSpecs(
          model.parkingAreas ?? EMPTY_COLLECTION,
          model.parkingSpecs ?? {},
        );
        setParkingSpecs(loadedParkingSpecs);
        setModelUpdatedAt(model.updatedAt ?? null);
        setSavedModelSignature(
          createModelSignature({
            modelName: model.name ?? modelName,
            boundaryFeature: model.boundaryFeature ?? boundaryFeature,
            buildings: model.buildings ?? buildings,
            parkingAreas: model.parkingAreas ?? parkingAreas,
            selectedBuildingIds: model.selectedBuildingIds ?? [...selectedBuildingIds],
            selectedParkingIds: model.selectedParkingIds ?? [...selectedParkingIds],
            sourceOsmFilename: model.sourceOsmFilename ?? sourceOsmFilename,
            requestInfo: model.requestInfo ?? requestInfo,
            parkingSpecs: loadedParkingSpecs,
            buildingClassifications,
            parkingClassifications,
            detectors,
            publicTransportOrigins,
            vehicleGenerationPoints,
          }),
        );
        if (!result.capacity) {
          throw new Error(result.error || "Could not estimate capacity for this parking area.");
        }
        setParkingSpecMessage(
          `Estimated ${result.capacity} spaces from ${(result.relatedWayIds ?? []).length} related OSM service ways.`,
        );
        return;
      }

      const feature = parkingAreas.features.find((item) => getFeatureId(item) === parkingId);
      if (!feature) {
        throw new Error("The selected parking area could not be found.");
      }

      const osmBlob = await fetchCurrentOsmBlob();
      const osmData = await parseOsmCapacitySource(osmBlob, sourceOsmFilename);
      const result = calculateCapacityResultForFeature(feature, osmData);

      setParkingSpecs((current) =>
        updateParkingSpec(current, parkingId, {
          capacity: result.capacity,
          capacitySource: result.capacitySource,
          capacityMethod: result.method,
          internalRoads: internalRoadsFromCapacityResult(result),
        }),
      );
      setParkingSpecMessage(
        `Estimated ${result.capacity} spaces from ${result.relatedWayIds.length} related OSM service ways.`,
      );
    } catch (caughtError) {
      const result =
        caughtError instanceof Error && "capacityResult" in caughtError
          ? caughtError.capacityResult
          : null;
      if (result) {
        setParkingSpecs((current) =>
          updateParkingSpec(current, parkingId, {
            internalRoads: internalRoadsFromCapacityResult(result),
          }),
        );
      }
      setError(
        caughtError instanceof Error ? caughtError.message : "Could not estimate parking capacity.",
      );
    } finally {
      setEstimatingCapacity(false);
    }
  };

  const estimateAllUnknownCapacities = async () => {
    setError("");
    setParkingSpecMessage("");
    setEstimatingCapacity(true);

    try {
      if (isServerModelStorage() && currentModelId && !hasUnsavedChanges) {
        const { model, summary } = await estimateModelUnknownParkingCapacities(currentModelId);
        const loadedParkingSpecs = buildParkingSpecs(
          model.parkingAreas ?? EMPTY_COLLECTION,
          model.parkingSpecs ?? {},
        );
        setParkingSpecs(loadedParkingSpecs);
        setModelUpdatedAt(model.updatedAt ?? null);
        setSavedModelSignature(
          createModelSignature({
            modelName: model.name ?? modelName,
            boundaryFeature: model.boundaryFeature ?? boundaryFeature,
            buildings: model.buildings ?? buildings,
            parkingAreas: model.parkingAreas ?? parkingAreas,
            selectedBuildingIds: model.selectedBuildingIds ?? [...selectedBuildingIds],
            selectedParkingIds: model.selectedParkingIds ?? [...selectedParkingIds],
            sourceOsmFilename: model.sourceOsmFilename ?? sourceOsmFilename,
            requestInfo: model.requestInfo ?? requestInfo,
            parkingSpecs: loadedParkingSpecs,
            buildingClassifications,
            parkingClassifications,
            detectors,
            publicTransportOrigins,
            vehicleGenerationPoints,
          }),
        );
        setParkingSpecMessage(
          `Filled ${summary.filled ?? 0} unknown capacities${summary.skipped ? `; skipped ${summary.skipped}.` : "."}`,
        );
        return;
      }

      const unknownFeatures = (parkingAreas.features ?? []).filter((feature) => {
        const id = getFeatureId(feature);
        const spec = parkingSpecs[id];
        return !spec?.capacity;
      });

      if (!unknownFeatures.length) {
        setParkingSpecMessage("There are no unknown parking capacities to fill.");
        return;
      }

      const osmBlob = await fetchCurrentOsmBlob();
      const osmData = await parseOsmCapacitySource(osmBlob, sourceOsmFilename);
      const now = new Date().toISOString();
      const updates: Record<string, Record<string, unknown>> = {};
      const skipped: Array<{ id: string; reason: string }> = [];

      for (const feature of unknownFeatures) {
        const id = getFeatureId(feature);
        const result = estimateParkingCapacityFromOsmData(feature, osmData);

        if (!result.capacity) {
          skipped.push({ id, reason: result.error || "No estimate available." });
          updates[id] = {
            internalRoads: internalRoadsFromCapacityResult(result),
            changeDate: now,
          };
          continue;
        }

        updates[id] = {
          capacity: result.capacity,
          capacitySource: result.capacitySource,
          capacityMethod: result.method,
          internalRoads: internalRoadsFromCapacityResult(result),
          changeDate: now,
        };
      }

      setParkingSpecs((current) => {
        const next = { ...current };
        for (const [id, patch] of Object.entries(updates)) {
          next[id] = {
            ...next[id],
            ...patch,
          };
        }
        return next;
      });

      setParkingSpecMessage(
        `Filled ${Object.keys(updates).length} unknown capacities${skipped.length ? `; skipped ${skipped.length}.` : "."}`,
      );
    } catch (caughtError) {
      setError(
        caughtError instanceof Error ? caughtError.message : "Could not estimate parking capacities.",
      );
    } finally {
      setEstimatingCapacity(false);
    }
  };

  const revertParkingCapacity = (parkingId) => {
    setParkingSpecs((current) => {
      const spec = current[parkingId];
      if (!spec) {
        return current;
      }

      return updateParkingSpec(current, parkingId, {
        capacity: spec.originalCapacity ?? null,
        capacitySource: spec.originalCapacitySource ?? "missing",
        capacityMethod: null,
      });
    });
    setParkingSpecMessage("Capacity reverted to the original value.");
  };

  const exportAllModelFiles = async (options: ModelExportOptions) => {
    setError("");
    setExportingAll(true);

    try {
      if (!Object.values(options).some(Boolean)) {
        throw new Error("Select at least one file to download.");
      }
      if (isServerModelStorage() && currentModelId && !hasUnsavedChanges) {
        const zipBlob = await downloadModelExport(currentModelId, options);
        downloadBlob(`${resolveExportFolderName(modelName)}.zip`, zipBlob);
        return;
      }

      const folderName = resolveExportFolderName(modelName);
      const isUploadedSource = sourceOsmIsUploaded;
      const osmFilename = isUploadedSource
        ? sourceOsmFilename || `${folderName}.osm.xml`
        : `${folderName}.osm.xml`;
      const includedFiles = [
        ...(options.osm ? [osmFilename] : []),
        ...(options.buildings ? ["buildings.geojson"] : []),
        ...(options.parkingAreas ? ["parking_areas.geojson"] : []),
        ...(options.modelConfig ? ["model_config.json"] : []),
      ];
      const entries: { path: string; content: Blob }[] = [];

      if (options.osm) {
        entries.push({
          path: `${folderName}/${osmFilename}`,
          content: await fetchCurrentOsmBlob(),
        });
      }
      if (options.buildings) {
        entries.push({
          path: `${folderName}/buildings.geojson`,
          content: jsonBlob(buildingExportGeoJson({
            modelName: folderName,
            buildings,
            selectedBuildingIds,
            boundaryFeature,
            dataSourceLabel,
            buildingClassifications,
          }), "application/geo+json"),
        });
      }
      if (options.parkingAreas) {
        entries.push({
          path: `${folderName}/parking_areas.geojson`,
          content: jsonBlob(parkingExportGeoJson({
            modelName: folderName,
            parkingAreas,
            selectedParkingIds,
            boundaryFeature,
            dataSourceLabel,
            parkingSpecs,
            parkingClassifications,
          }), "application/geo+json"),
        });
      }
      if (options.modelConfig) {
        entries.push({
          path: `${folderName}/model_config.json`,
          content: jsonBlob(modelConfigJson({
            id: currentModelId,
            name: modelName,
            createdAt: modelCreatedAt,
            updatedAt: modelUpdatedAt,
            dataSourceLabel,
            requestInfo,
            boundaryFeature,
            selectedBuildingIds,
            selectedParkingIds,
            sourceOsmFilename: osmFilename,
            sourceOsmIsUploaded,
            buildings,
            parkingAreas,
            includedFiles,
            detectors,
            publicTransportOrigins,
            vehicleGenerationPoints,
          })),
        });
      }

      const zipBlob = await createZipBlob(entries);

      downloadBlob(`${folderName}.zip`, zipBlob);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not export model ZIP.");
    } finally {
      setExportingAll(false);
    }
  };

  const busy =
    loading ||
    uploading ||
    downloadingOsm ||
    refreshingOsm ||
    savingModel ||
    loadingModel ||
    exportingAll ||
    estimatingCapacity;
  const workspaceMode =
    routePath === "/new-model" ? "new" : modelIdFromRoute(routePath) ? "model" : "unknown";

  const updateParkingSpecById = (parkingId, patch) => {
    setParkingSpecs((current) => updateParkingSpec(current, parkingId, patch));
  };

  const goHome = () => {
    if (
      hasUnsavedChanges &&
      !window.confirm(
        "The current model has unsaved changes. Go to the home page and keep those changes unsaved?",
      )
    ) {
      return;
    }
    navigateTo("/");
  };

  const openAnalytics = () => {
    if (currentModelId) {
      window.sessionStorage.setItem(ANALYTICS_RETURN_MODEL_STORAGE_KEY, currentModelId);
    } else {
      window.sessionStorage.removeItem(ANALYTICS_RETURN_MODEL_STORAGE_KEY);
    }
    navigateTo("/analytics");
  };

  const openDocumentation = () => navigateTo("/documentation");

  const confirmUnsavedNavigation = (action: () => void) => {
    if (hasUnsavedChanges && !window.confirm("The current model has unsaved changes. Leave this page anyway?")) return;
    action();
  };

  const openSimulation = () => {
    if (!currentModelId || hasUnsavedChanges || !selectedBuildingIds.size) return;
    window.sessionStorage.setItem(SELECTED_MODEL_STORAGE_KEY, currentModelId);
    navigateTo("/simulation");
  };

  const openParkingSpecs = () => {
    setSidebarMode("parkingSpecs");
  };

  const backFromParkingSpecs = () => {
    if (
      hasUnsavedChanges &&
      !window.confirm(
        "Parking spec changes are not saved yet. Return to the previous menu anyway?",
      )
    ) {
      return;
    }
    setExpandedParkingSpecId(null);
    setSidebarMode("default");
  };

  const openBuildingSpecs = () => {
    setSidebarMode("buildingSpecs");
  };

  const backFromBuildingSpecs = () => {
    if (
      hasUnsavedChanges &&
      !window.confirm(
        "Building spec changes are not saved yet. Return to the previous menu anyway?",
      )
    ) {
      return;
    }
    setSidebarMode("default");
  };

  const openPublicTransportOrigins = () => {
    setPublicTransportPointPlacementActive(false);
    setVehicleGenerationPointPlacementActive(false);
    setVehicleGenerationMessage("");
    setSidebarMode("publicTransportOrigins");
  };

  const backFromPublicTransportOrigins = () => {
    setPublicTransportPointPlacementActive(false);
    setVehicleGenerationPointPlacementActive(false);
    setVehicleGenerationCandidates([]);
    setVehicleGenerationMessage("");
    setSidebarMode("default");
  };

  const togglePublicTransportPointPlacement = () => {
    setVehicleGenerationPointPlacementActive(false);
    setPublicTransportPointPlacementActive((current) => !current);
  };

  const togglePublicTransportBuilding = (buildingId: string) => {
    const feature = buildings.features.find((item) => getFeatureId(item) === buildingId);
    if (!feature) return;
    try {
      const location = featureLocation(feature);
      setPublicTransportOrigins((current) => {
        const origins = current ?? [];
        const existing = origins.find(
          (origin) => origin.sourceType === "building" && origin.buildingId === buildingId,
        );
        if (existing) return origins.filter((origin) => origin.id !== existing.id);
        return [...origins, {
          id: crypto.randomUUID(),
          name: getBuildingDisplayName(feature),
          sourceType: "building",
          buildingId,
          location,
        }];
      });
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not use this building as a transit origin.");
    }
  };

  const placePublicTransportPoint = (location: { longitude: number; latitude: number }) => {
    if (!publicTransportPointPlacementActive) return;
    setPublicTransportOrigins((current) => {
      const origins = current ?? [];
      const pointNumber = origins.filter((origin) => origin.sourceType === "point").length + 1;
      return [...origins, {
        id: crypto.randomUUID(),
        name: `Transit point ${pointNumber}`,
        sourceType: "point",
        location,
      }];
    });
    setPublicTransportPointPlacementActive(false);
  };

  const changePublicTransportOrigin = (nextOrigin: PublicTransportOrigin) => {
    setPublicTransportOrigins((current) => (current ?? []).map(
      (origin) => origin.id === nextOrigin.id ? nextOrigin : origin,
    ));
  };

  const deletePublicTransportOrigin = (id: string) => {
    setPublicTransportOrigins((current) => (current ?? []).filter((origin) => origin.id !== id));
  };

  const resolveVehicleGenerationCandidatesAt = async (location: { longitude: number; latitude: number }) => {
    const candidates = await resolveDetectorCandidatesAt(location);
    return candidates.filter((candidate) => candidate.allows_passenger);
  };

  const loadVehicleGenerationCandidates = async (point: VehicleGenerationPoint) => {
    if (vehicleGenerationResolving) return;
    setVehicleGenerationResolving(true);
    setVehicleGenerationMessage("Loading nearby passenger lanes…");
    try {
      const candidates = await resolveVehicleGenerationCandidatesAt(point.location);
      setVehicleGenerationCandidates(candidates);
      setVehicleGenerationMessage(`${candidates.length} nearby passenger lane${candidates.length === 1 ? "" : "s"} found. Choose the direction that enters the modeled area.`);
    } catch (caughtError) {
      setVehicleGenerationCandidates([]);
      setVehicleGenerationMessage(caughtError instanceof Error ? caughtError.message : "Could not load vehicle-origin lanes.");
    } finally {
      setVehicleGenerationResolving(false);
    }
  };

  const toggleVehicleGenerationPointPlacement = () => {
    if (vehicleGenerationPointPlacementActive) {
      setVehicleGenerationPointPlacementActive(false);
      setVehicleGenerationMessage("");
      return;
    }
    if (!currentModelId) {
      setVehicleGenerationMessage("Save the model before adding a vehicle generation point so SUMO lanes can be resolved.");
      return;
    }
    setPublicTransportPointPlacementActive(false);
    setVehicleGenerationPointPlacementActive(true);
    setVehicleGenerationMessage("Click a passenger road on the map.");
  };

  const placeVehicleGenerationPoint = async (location: { longitude: number; latitude: number }) => {
    if (!vehicleGenerationPointPlacementActive || vehicleGenerationResolving) return;
    setVehicleGenerationResolving(true);
    setVehicleGenerationMessage("Resolving the nearest passenger lane and direction…");
    try {
      const candidates = await resolveVehicleGenerationCandidatesAt(location);
      const closest = candidates[0];
      if (!closest) throw new Error("No vehicle-accessible lane was found near this point.");
      const point: VehicleGenerationPoint = {
        id: crypto.randomUUID(),
        name: `Vehicle origin ${(vehicleGenerationPoints ?? []).length + 1}`,
        location,
        positionMetres: closest.position_metres,
        laneSelection: {
          mode: "lane",
          edgeId: closest.edge_id,
          laneId: closest.lane_id,
          laneIndex: closest.lane_index,
        },
      };
      setVehicleGenerationPoints((current) => [...(current ?? []), point]);
      setActiveVehicleGenerationPointId(point.id);
      setVehicleGenerationCandidates(candidates);
      setVehicleGenerationPointPlacementActive(false);
      setVehicleGenerationMessage(`Vehicle origin snapped to ${closest.lane_id}, ${closest.distance_metres.toFixed(1)} m from the click.`);
    } catch (caughtError) {
      setVehicleGenerationMessage(caughtError instanceof Error ? caughtError.message : "Could not place the vehicle generation point.");
    } finally {
      setVehicleGenerationResolving(false);
    }
  };

  const selectVehicleGenerationPoint = (id: string) => {
    setActiveVehicleGenerationPointId(id);
    setVehicleGenerationPointPlacementActive(false);
    const point = (vehicleGenerationPoints ?? []).find((candidate) => candidate.id === id);
    if (point) void loadVehicleGenerationCandidates(point);
  };

  const changeVehicleGenerationPoint = (nextPoint: VehicleGenerationPoint) => {
    setVehicleGenerationPoints((current) => (current ?? []).map(
      (point) => point.id === nextPoint.id ? nextPoint : point,
    ));
  };

  const deleteVehicleGenerationPoint = (id: string) => {
    setVehicleGenerationPoints((current) => {
      const next = (current ?? []).filter((point) => point.id !== id);
      if (activeVehicleGenerationPointId === id) {
        setActiveVehicleGenerationPointId(next[0]?.id ?? null);
        setVehicleGenerationCandidates([]);
      }
      return next;
    });
  };

  const refreshVehicleGenerationPointLanes = (id: string) => {
    const point = (vehicleGenerationPoints ?? []).find((candidate) => candidate.id === id);
    if (point) void loadVehicleGenerationCandidates(point);
  };

  const resolveDetectorCandidatesAt = async (location: { longitude: number; latitude: number }) => {
    if (!currentModelId) throw new Error("Save the model before placing a detector.");
    const result = await resolveDetectorLanes(currentModelId, location);
    return result.candidates as DetectorLaneCandidate[];
  };

  const previewDetectorLanes = async (detector: TrafficDetector) => {
    if (detectorResolving) return;
    setDetectorResolving(true);
    setDetectorMessage("Loading generated SUMO lane geometry…");
    try {
      if (detector.type === "e1") {
        const candidates = await resolveDetectorCandidatesAt(detector.location);
        setDetectorCandidates({ e1: candidates, entry: [], exit: [] });
        setDetectorMessage(`${candidates.filter((candidate) => candidate.allows_passenger).length} nearby vehicle lane${candidates.filter((candidate) => candidate.allows_passenger).length === 1 ? "" : "s"} shown on the map.`);
      } else {
        const [entryCandidates, exitCandidates] = await Promise.all([
          resolveDetectorCandidatesAt(detector.entry.location),
          resolveDetectorCandidatesAt(detector.exit.location),
        ]);
        setDetectorCandidates({ e1: [], entry: entryCandidates, exit: exitCandidates });
        const uniqueLaneCount = new Set([...entryCandidates, ...exitCandidates].map((candidate) => candidate.lane_id)).size;
        setDetectorMessage(`${uniqueLaneCount} nearby SUMO lane${uniqueLaneCount === 1 ? "" : "s"} shown. Hover an ID to locate it.`);
      }
    } catch (caughtError) {
      setDetectorCandidates(emptyDetectorCandidates());
      setDetectorMessage(caughtError instanceof Error ? caughtError.message : "Could not load detector lane geometry.");
    } finally {
      setDetectorResolving(false);
    }
  };

  const openDetectorSpecs = () => {
    setSidebarMode("detectorSpecs");
    setDetectorPlacementType(null);
    setE3EntryDraft(null);
    setDetectorMessage("");
    const active = detectors.find((detector) => detector.id === activeDetectorId) ?? detectors[0];
    if (active) void previewDetectorLanes(active);
  };

  const backFromDetectorSpecs = () => {
    setDetectorPlacementType(null);
    setE3EntryDraft(null);
    setSidebarMode("default");
  };

  const startDetectorPlacement = (type: "e1" | "e3") => {
    setDetectorPlacementType(type);
    setE3EntryDraft(null);
    setDetectorMessage(type === "e3"
      ? "Click the entry cross-section first, then the exit cross-section."
      : "Click a passenger road on the map.");
  };

  const cancelDetectorPlacement = () => {
    setDetectorPlacementType(null);
    setE3EntryDraft(null);
    setDetectorMessage("");
  };

  const placeDetectorAt = async (location: { longitude: number; latitude: number }) => {
    if (!detectorPlacementType || detectorResolving) return;
    setDetectorResolving(true);
    setDetectorMessage("Resolving nearby passenger lanes in the model network…");
    try {
      const candidates = await resolveDetectorCandidatesAt(location);
      const closest = detectorPlacementType === "e1"
        ? candidates.find((candidate) => candidate.allows_passenger)
        : candidates[0];
      if (!closest) throw new Error("No vehicle-accessible lane was found near this point.");
      const point: DetectorPoint = {
        location,
        laneSelection: detectorPlacementType === "e3" ? {
          mode: "lanes",
          edgeId: closest.edge_id,
          laneIds: candidates
            .filter((candidate) => candidate.distance_metres <= 8)
            .map((candidate) => candidate.lane_id),
        } : {
          mode: "lane",
          edgeId: closest.edge_id,
          laneId: closest.lane_id,
          laneIndex: closest.lane_index,
        },
      };
      if (detectorPlacementType === "e3" && !e3EntryDraft) {
        setE3EntryDraft(point);
        setDetectorCandidates((current) => ({ ...current, entry: candidates }));
        setDetectorMessage(`Entry snapped to ${closest.lane_id}. Now click the exit cross-section.`);
        return;
      }

      const detector: TrafficDetector = detectorPlacementType === "e1" ? {
        id: crypto.randomUUID(),
        name: `E1 Detector ${detectors.filter((item) => item.type === "e1").length + 1}`,
        type: "e1",
        periodSeconds: 900,
        ...point,
      } satisfies E1Detector : {
        id: crypto.randomUUID(),
        name: `E3 Detector ${detectors.filter((item) => item.type === "e3").length + 1}`,
        type: "e3",
        periodSeconds: 900,
        detects: ["vehicles", "pedestrians"],
        entry: e3EntryDraft as DetectorPoint,
        exit: point,
      } satisfies E3Detector;
      setDetectors((current) => [...current, detector]);
      setActiveDetectorId(detector.id);
      setDetectorCandidates((current) => detector.type === "e1"
        ? { ...current, e1: candidates }
        : { ...current, exit: candidates });
      setDetectorPlacementType(null);
      setE3EntryDraft(null);
      setDetectorMessage(detector.type === "e1"
        ? `Snapped to ${closest.lane_id}, ${closest.distance_metres.toFixed(1)} m from the click.`
        : `E3 entry and exit saved. Exit snapped to ${closest.lane_id}.`);
    } catch (caughtError) {
      setDetectorMessage(caughtError instanceof Error ? caughtError.message : "Could not place detector.");
    } finally {
      setDetectorResolving(false);
    }
  };

  const selectDetector = (id: string) => {
    setActiveDetectorId(id);
    setDetectorPlacementType(null);
    setE3EntryDraft(null);
    const detector = detectors.find((item) => item.id === id);
    if (detector) void previewDetectorLanes(detector);
  };

  const changeDetector = (nextDetector: TrafficDetector) => {
    setDetectors((current) => current.map((detector) => detector.id === nextDetector.id ? nextDetector : detector));
  };

  const deleteDetector = (id: string) => {
    if (!window.confirm("Delete this detector from the model?")) return;
    setDetectors((current) => {
      const next = current.filter((detector) => detector.id !== id);
      setActiveDetectorId(next[0]?.id ?? null);
      return next;
    });
    setDetectorCandidates(emptyDetectorCandidates());
  };

  const refreshDetectorLanes = async (id: string, endpoint: "e1" | "entry" | "exit") => {
    const detector = detectors.find((item) => item.id === id);
    if (!detector || detectorResolving) return;
    const point = detector.type === "e1"
      ? detector
      : endpoint === "entry" ? detector.entry : detector.exit;
    setDetectorResolving(true);
    setDetectorMessage("Refreshing nearby SUMO lanes…");
    try {
      const candidates = await resolveDetectorCandidatesAt(point.location);
      setDetectorCandidates((current) => ({ ...current, [endpoint]: candidates }));
      setDetectorMessage(`${candidates.length} nearby passenger lane${candidates.length === 1 ? "" : "s"} found.`);
    } catch (caughtError) {
      setDetectorMessage(caughtError instanceof Error ? caughtError.message : "Could not refresh detector lanes.");
    } finally {
      setDetectorResolving(false);
    }
  };

  const addBuildingClassificationHandler = (payload: { name?: string; types?: string[] } = {}) => {
    if ((buildingClassifications ?? []).length >= 10) {
      const message = "You can create up to 10 classifications.";
      window.alert(message);
      setBuildingSpecMessage(message);
      return;
    }

    const timestamp = new Date().toISOString();
    const classificationName = String(payload?.name ?? "").trim() || `Classification ${(buildingClassifications ?? []).length + 1}`;
    const typeNames = (payload?.types ?? [])
      .map((typeName) => String(typeName ?? "").trim())
      .filter(Boolean)
      .slice(0, 10);
    const nextClassification = {
      id: crypto.randomUUID(),
      name: classificationName,
      types: typeNames.map((typeName) => ({
        id: crypto.randomUUID(),
        name: typeName,
        createdAt: timestamp,
        updatedAt: timestamp,
      })),
      assignments: {},
      createdAt: timestamp,
      updatedAt: timestamp,
    };

    setBuildingClassifications((current) => [...(current ?? []), nextClassification]);
    setActiveBuildingClassificationId(nextClassification.id);
    setBuildingSpecMessage("");
  };

  const renameBuildingClassificationHandler = (classificationId, name) => {
    setBuildingClassifications((current) =>
      updateBuildingClassificationName(current, classificationId, name),
    );
    setBuildingSpecMessage("Classification renamed.");
  };

  const deleteBuildingClassificationHandler = (classificationId) => {
    setBuildingClassifications((current) => {
      const next = deleteBuildingClassification(current, classificationId);
      if (activeBuildingClassificationId === classificationId) {
        setActiveBuildingClassificationId(next[0]?.id ?? null);
      }
      return next;
    });
    setBuildingSpecMessage("Classification deleted.");
  };

  const addBuildingTypeHandler = (classificationId, name = "") => {
    const result = addBuildingType(buildingClassifications, classificationId, name);
    if (result.error) {
      window.alert(result.error);
      setBuildingSpecMessage(result.error);
      return;
    }
    setBuildingClassifications(result.classifications);
    setBuildingSpecMessage("Type added.");
  };

  const renameBuildingTypeHandler = (classificationId, typeId, name) => {
    setBuildingClassifications((current) =>
      updateBuildingTypeName(current, classificationId, typeId, name),
    );
    setBuildingSpecMessage("Type renamed.");
  };

  const deleteBuildingTypeHandler = (classificationId, typeId) => {
    setBuildingClassifications((current) =>
      deleteBuildingType(current, classificationId, typeId),
    );
    setBuildingSpecMessage("Type deleted. Assigned buildings were returned to Unknown / unspecified.");
  };

  const assignBuildingTypeHandler = (classificationId, buildingId, typeId) => {
    setBuildingClassifications((current) =>
      setBuildingAssignment(current, classificationId, buildingId, typeId),
    );
  };

  const updateBuildingTypeDemandDistributionHandler = (classificationId, typeId, mode, value) => {
    setBuildingClassifications((current) =>
      updateBuildingTypeDemandDistribution(current, classificationId, typeId, mode, value),
    );
  };

  const addParkingClassificationHandler = (payload: { name?: string; types?: string[] } = {}) => {
    if ((parkingClassifications ?? []).length >= 10) {
      const message = "You can create up to 10 parking classifications.";
      window.alert(message);
      setParkingSpecMessage(message);
      return;
    }
    const timestamp = new Date().toISOString();
    const nextClassification = {
      id: crypto.randomUUID(),
      name: String(payload.name ?? "").trim() || `Classification ${(parkingClassifications ?? []).length + 1}`,
      types: (payload.types ?? [])
        .map((name) => String(name ?? "").trim())
        .filter(Boolean)
        .slice(0, 10)
        .map((name) => ({ id: crypto.randomUUID(), name })),
      assignments: {},
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    setParkingClassifications((current) => [...(current ?? []), nextClassification]);
    setActiveParkingClassificationId(nextClassification.id);
    setParkingSpecMessage("");
  };

  const renameParkingClassificationHandler = (classificationId, name) => {
    setParkingClassifications((current) =>
      updateParkingClassificationName(current, classificationId, name),
    );
    setParkingSpecMessage("Parking classification renamed.");
  };

  const deleteParkingClassificationHandler = (classificationId) => {
    setParkingClassifications((current) => {
      const next = deleteParkingClassification(current, classificationId);
      if (activeParkingClassificationId === classificationId) {
        setActiveParkingClassificationId(next[0]?.id ?? null);
      }
      return next;
    });
    setParkingSpecMessage("Parking classification deleted.");
  };

  const addParkingTypeHandler = (classificationId, name = "") => {
    const result = addParkingType(parkingClassifications, classificationId, name);
    if (result.error) {
      window.alert(result.error);
      setParkingSpecMessage(result.error);
      return;
    }
    setParkingClassifications(result.classifications);
    setParkingSpecMessage("Parking type added.");
  };

  const renameParkingTypeHandler = (classificationId, typeId, name) => {
    setParkingClassifications((current) =>
      updateParkingTypeName(current, classificationId, typeId, name),
    );
    setParkingSpecMessage("Parking type renamed.");
  };

  const deleteParkingTypeHandler = (classificationId, typeId) => {
    setParkingClassifications((current) =>
      deleteParkingType(current, classificationId, typeId),
    );
    setParkingSpecMessage("Parking type deleted. Assigned parking areas were returned to Unknown / unspecified.");
  };

  const assignParkingTypeHandler = (classificationId, parkingId, typeId) => {
    setParkingClassifications((current) =>
      setParkingAssignment(current, classificationId, parkingId, typeId),
    );
  };

  if (isSimulationRoute(routePath)) {
    return (
      <SimulationPage
        modelId={currentModelId}
        modelName={modelName}
        parkingAreaCount={selectedParkingIds.size}
        selectedBuildingIds={[...selectedBuildingIds].map(String)}
        buildingClassifications={buildingClassifications}
        detectors={detectors}
        publicTransportOriginCount={publicTransportOrigins === undefined ? null : publicTransportOrigins.length}
        vehicleGenerationPoints={vehicleGenerationPoints ?? []}
        loadingModel={loadingModel}
        onBack={() => navigateTo(currentModelId ? routeForModel(currentModelId) : "/")}
        onHome={() => navigateTo("/")}
        onAnalytics={openAnalytics}
        onDocumentation={openDocumentation}
      />
    );
  }

  if (isAnalyticsRoute(routePath)) {
    return (
      <AnalyticsPage
        onHome={() => navigateTo("/")}
        onAnalytics={openAnalytics}
        onDocumentation={openDocumentation}
        returnModelId={window.sessionStorage.getItem(ANALYTICS_RETURN_MODEL_STORAGE_KEY)}
        onSimulation={(modelId) => {
          window.sessionStorage.removeItem(ANALYTICS_RETURN_MODEL_STORAGE_KEY);
          window.sessionStorage.setItem(SELECTED_MODEL_STORAGE_KEY, modelId);
          navigateTo(routeForSimulation(modelId));
        }}
      />
    );
  }

  if (isDocumentationRoute(routePath)) {
    return <DocumentationPage onHome={() => navigateTo("/")} onAnalytics={openAnalytics} onDocumentation={openDocumentation} />;
  }

  if (isHomeRoute(routePath)) {
    return (
      <HomeRoute
        savedModels={savedModels}
        loadingModel={loadingModel}
        busy={busy}
        modelActionDialog={modelActionDialog}
        onStartNewModel={startNewModel}
        onOpenAnalytics={() => {
          window.sessionStorage.removeItem(ANALYTICS_RETURN_MODEL_STORAGE_KEY);
          navigateTo("/analytics");
        }}
        onDocumentation={openDocumentation}
        onLoadSavedModel={loadSavedModel}
        onRequestDuplicateModel={requestDuplicateModel}
        onRequestRenameModel={requestRenameModel}
        onRequestDeleteModel={requestDeleteModel}
        onCancelModelAction={() => setModelActionDialog(null)}
        onConfirmModelAction={confirmModelAction}
      />
    );
  }

  return (
    <WorkspaceView
      boundaryFeature={boundaryFeature}
      buildings={buildings}
      parkingAreas={parkingAreas}
      filteredBuildings={filteredBuildings}
      filteredParkingAreas={filteredParkingAreas}
      selectedBuildingIds={selectedBuildingIds}
      selectedParkingIds={selectedParkingIds}
      buildingSearch={buildingSearch}
      parkingSearch={parkingSearch}
      parkingSpecs={parkingSpecs}
      buildingClassifications={buildingClassifications}
      activeBuildingClassificationId={activeBuildingClassificationId}
      activeBuildingClassification={activeBuildingClassification}
      buildingSpecMessage={buildingSpecMessage}
      parkingClassifications={parkingClassifications}
      activeParkingClassificationId={activeParkingClassificationId}
      activeParkingClassification={activeParkingClassification}
      detectors={detectors}
      activeDetectorId={activeDetectorId}
      detectorCandidates={detectorCandidates}
      detectorPlacementActive={detectorPlacementActive}
      detectorPlacementType={detectorPlacementType}
      detectorPlacementE3Exit={Boolean(e3EntryDraft)}
      detectorResolving={detectorResolving}
      detectorMessage={detectorMessage}
      publicTransportOrigins={publicTransportOrigins ?? []}
      publicTransportPointPlacementActive={publicTransportPointPlacementActive}
      vehicleGenerationPoints={vehicleGenerationPoints ?? []}
      activeVehicleGenerationPointId={activeVehicleGenerationPointId}
      vehicleGenerationCandidates={vehicleGenerationCandidates}
      vehicleGenerationPointPlacementActive={vehicleGenerationPointPlacementActive}
      vehicleGenerationResolving={vehicleGenerationResolving}
      vehicleGenerationMessage={vehicleGenerationMessage}
      activeAccessFilters={activeAccessFilters}
      activeCapacityFilters={activeCapacityFilters}
      expandedParkingSpecId={expandedParkingSpecId}
      highlightedParkingIds={highlightedParkingIds}
      expandedParkingIds={expandedParkingIds}
      sidebarMode={sidebarMode}
      loading={loading}
      uploading={uploading}
      downloadingOsm={downloadingOsm}
      refreshingOsm={refreshingOsm}
      loadProgress={loadProgress}
      busy={busy}
      error={error}
      requestInfo={requestInfo}
      modelName={modelName}
      currentModelId={currentModelId}
      modelCreatedAt={modelCreatedAt}
      modelUpdatedAt={modelUpdatedAt}
      savingModel={savingModel}
      exportingAll={exportingAll}
      estimatingCapacity={estimatingCapacity}
      parkingSpecMessage={parkingSpecMessage}
      hasUnsavedChanges={hasUnsavedChanges}
      currentModelHasContent={currentModelHasContent}
      workspaceMode={workspaceMode}
      sidebarCollapsed={sidebarCollapsed}
      routePath={routePath}
      modelActionDialog={modelActionDialog}
      unnamedBuildingCount={unnamedBuildingCount}
      unnamedParkingCount={unnamedParkingCount}
      selectedUnnamedBuildingCount={selectedUnnamedBuildingCount}
      selectedUnnamedParkingCount={selectedUnnamedParkingCount}
      setSidebarCollapsed={setSidebarCollapsed}
      goAnalytics={() => confirmUnsavedNavigation(openAnalytics)}
      goDocumentation={() => confirmUnsavedNavigation(openDocumentation)}
      goHome={goHome}
      setModelName={setModelName}
      saveCurrentModel={saveCurrentModel}
      openSimulation={openSimulation}
      exportAllModelFiles={exportAllModelFiles}
      openParkingSpecs={openParkingSpecs}
      backFromParkingSpecs={backFromParkingSpecs}
      openBuildingSpecs={openBuildingSpecs}
      backFromBuildingSpecs={backFromBuildingSpecs}
      openDetectorSpecs={openDetectorSpecs}
      backFromDetectorSpecs={backFromDetectorSpecs}
      openPublicTransportOrigins={openPublicTransportOrigins}
      backFromPublicTransportOrigins={backFromPublicTransportOrigins}
      togglePublicTransportPointPlacement={togglePublicTransportPointPlacement}
      changePublicTransportOrigin={changePublicTransportOrigin}
      deletePublicTransportOrigin={deletePublicTransportOrigin}
      togglePublicTransportBuilding={togglePublicTransportBuilding}
      placePublicTransportPoint={placePublicTransportPoint}
      toggleVehicleGenerationPointPlacement={toggleVehicleGenerationPointPlacement}
      placeVehicleGenerationPoint={placeVehicleGenerationPoint}
      selectVehicleGenerationPoint={selectVehicleGenerationPoint}
      changeVehicleGenerationPoint={changeVehicleGenerationPoint}
      deleteVehicleGenerationPoint={deleteVehicleGenerationPoint}
      refreshVehicleGenerationPointLanes={refreshVehicleGenerationPointLanes}
      startDetectorPlacement={startDetectorPlacement}
      cancelDetectorPlacement={cancelDetectorPlacement}
      selectDetector={selectDetector}
      changeDetector={changeDetector}
      deleteDetector={deleteDetector}
      refreshDetectorLanes={refreshDetectorLanes}
      placeDetectorAt={placeDetectorAt}
      addBuildingClassificationHandler={addBuildingClassificationHandler}
      setActiveBuildingClassificationId={setActiveBuildingClassificationId}
      renameBuildingClassificationHandler={renameBuildingClassificationHandler}
      deleteBuildingClassificationHandler={deleteBuildingClassificationHandler}
      addBuildingTypeHandler={addBuildingTypeHandler}
      renameBuildingTypeHandler={renameBuildingTypeHandler}
      deleteBuildingTypeHandler={deleteBuildingTypeHandler}
      assignBuildingTypeHandler={assignBuildingTypeHandler}
      updateBuildingTypeDemandDistributionHandler={updateBuildingTypeDemandDistributionHandler}
      addParkingClassificationHandler={addParkingClassificationHandler}
      setActiveParkingClassificationId={setActiveParkingClassificationId}
      renameParkingClassificationHandler={renameParkingClassificationHandler}
      deleteParkingClassificationHandler={deleteParkingClassificationHandler}
      addParkingTypeHandler={addParkingTypeHandler}
      renameParkingTypeHandler={renameParkingTypeHandler}
      deleteParkingTypeHandler={deleteParkingTypeHandler}
      assignParkingTypeHandler={assignParkingTypeHandler}
      updateParkingSpecById={updateParkingSpecById}
      estimateCapacityForParking={estimateCapacityForParking}
      estimateAllUnknownCapacities={estimateAllUnknownCapacities}
      revertParkingCapacity={revertParkingCapacity}
      setExpandedParkingSpecId={setExpandedParkingSpecId}
      toggleId={toggleId}
      setActiveAccessFilters={setActiveAccessFilters}
      setActiveCapacityFilters={setActiveCapacityFilters}
      setBuildingSearch={setBuildingSearch}
      setParkingSearch={setParkingSearch}
      loadFeatures={loadFeatures}
      uploadOsmFile={uploadOsmFile}
      downloadSelectedAreaOsm={downloadSelectedAreaOsm}
      refreshOsmArea={refreshOsmArea}
      setSelectedBuildingIds={setSelectedBuildingIds}
      setSelectedParkingIds={setSelectedParkingIds}
      selectFilteredIds={selectFilteredIds}
      deselectFilteredIds={deselectFilteredIds}
      deselectMatchingIds={deselectMatchingIds}
      handleBoundaryChange={handleBoundaryChange}
      confirmModelAction={confirmModelAction}
      setModelActionDialog={setModelActionDialog}
    />
  );
}
