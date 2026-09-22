import { useEffect, useState, type DragEvent, type ReactNode } from "react";
import { BusFront, ChevronDown, CircleHelp, Download, FileUp, Home, MapPinned, PanelLeftClose, PanelLeftOpen, Play, RefreshCw, Save } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Alert, AlertDescription } from "./ui/alert";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";
import { cn } from "../lib/utils";
import FeatureSelectionPanel from "./FeatureSelectionPanel.tsx";
import ParkingSpecsPanel from "./ParkingSpecsPanel.tsx";
import BuildingSpecsPanel from "./BuildingSpecsPanel.tsx";
import DetectorSpecsPanel from "./DetectorSpecsPanel.tsx";
import PublicTransportOriginsPanel from "./PublicTransportOriginsPanel.tsx";
import LoadProgressStatus from "./LoadProgressStatus.tsx";
import NewModelGuideDialog from "./NewModelGuideDialog.tsx";
import type { CampusFeature, CampusFeatureCollection, DetectorLaneCandidate, LoadProgressState, ModelExportOptions, PublicTransportOrigin, RequestInfo, TrafficDetector, VehicleGenerationPoint } from "../types/campus";
import {
  getBuildingDescription,
  getBuildingDisplayName,
  getFeatureId,
  getParkingDescription,
  getParkingDisplayName,
} from "../utils/osmFeatures.ts";

const NEW_MODEL_GUIDE_SEEN_KEY = "sumo-campus-builder:new-model-guide-v2";

function formatDateTime(value?: string | null) {
  if (!value) return "Not saved yet";
  return new Date(value).toLocaleString();
}

function InfoMessage({ children }: { children: ReactNode }) {
  return <Alert className="mb-3 border-blue-200 bg-blue-50 p-2.5 text-blue-700"><AlertDescription className="text-xs">{children}</AlertDescription></Alert>;
}

function ErrorMessage({ children }: { children: ReactNode }) {
  return <Alert variant="destructive" className="mb-3 bg-red-50 p-2.5"><AlertDescription className="text-xs">{children}</AlertDescription></Alert>;
}

type AppSidebarProps = {
  boundaryReady: boolean;
  buildings: CampusFeatureCollection;
  parkingAreas: CampusFeatureCollection;
  filteredBuildings: CampusFeature[];
  filteredParkingAreas: CampusFeature[];
  selectedBuildingIds: Set<string>;
  selectedParkingIds: Set<string>;
  buildingSearch: string;
  parkingSearch: string;
  parkingSpecs: any;
  buildingClassifications: any[];
  activeBuildingClassificationId: string | null;
  buildingSpecMessage: string;
  parkingClassifications: any[];
  activeParkingClassificationId: string | null;
  detectors: TrafficDetector[];
  activeDetectorId: string | null;
  detectorCandidates: Record<"e1" | "entry" | "exit", DetectorLaneCandidate[]>;
  detectorPlacementType: "e1" | "e3" | null;
  detectorPlacementE3Exit: boolean;
  detectorResolving: boolean;
  detectorMessage: string;
  publicTransportOrigins: PublicTransportOrigin[];
  publicTransportPointPlacementActive: boolean;
  vehicleGenerationPoints: VehicleGenerationPoint[];
  activeVehicleGenerationPointId: string | null;
  vehicleGenerationCandidates: DetectorLaneCandidate[];
  vehicleGenerationPointPlacementActive: boolean;
  vehicleGenerationResolving: boolean;
  vehicleGenerationMessage: string;
  activeAccessFilters: Set<string>;
  activeCapacityFilters: Set<string>;
  expandedParkingSpecId: string | null;
  sidebarMode: string;
  loading: boolean;
  uploading: boolean;
  downloadingOsm: boolean;
  refreshingOsm: boolean;
  loadProgress: LoadProgressState;
  busy: boolean;
  error: string;
  requestInfo: RequestInfo | null;
  modelName: string;
  currentModelId: string | null;
  modelCreatedAt: string | null;
  modelUpdatedAt: string | null;
  savingModel: boolean;
  exportingAll: boolean;
  estimatingCapacity: boolean;
  parkingSpecMessage: string;
  hasUnsavedChanges: boolean;
  currentModelHasContent: boolean;
  workspaceMode: "new" | "model" | "unknown";
  sidebarCollapsed: boolean;
  onSidebarCollapsedChange: (collapsed: boolean) => void;
  onGoHome: () => void;
  onModelNameChange: (value: string) => void;
  onSaveCurrentModel: () => void;
  onOpenSimulation: () => void;
  onExportAllModelFiles: (options: ModelExportOptions) => void;
  onOpenParkingSpecs: () => void;
  onBackFromParkingSpecs: () => void;
  onOpenBuildingSpecs: () => void;
  onBackFromBuildingSpecs: () => void;
  onOpenDetectorSpecs: () => void;
  onBackFromDetectorSpecs: () => void;
  onOpenPublicTransportOrigins: () => void;
  onBackFromPublicTransportOrigins: () => void;
  onTogglePublicTransportPointPlacement: () => void;
  onChangePublicTransportOrigin: (origin: PublicTransportOrigin) => void;
  onDeletePublicTransportOrigin: (id: string) => void;
  onToggleVehicleGenerationPointPlacement: () => void;
  onSelectVehicleGenerationPoint: (id: string) => void;
  onChangeVehicleGenerationPoint: (point: VehicleGenerationPoint) => void;
  onDeleteVehicleGenerationPoint: (id: string) => void;
  onRefreshVehicleGenerationPointLanes: (id: string) => void;
  onFocusVehicleGenerationLane: (laneId: string | null) => void;
  onStartDetectorPlacement: (type: "e1" | "e3") => void;
  onCancelDetectorPlacement: () => void;
  onSelectDetector: (id: string) => void;
  onChangeDetector: (detector: TrafficDetector) => void;
  onDeleteDetector: (id: string) => void;
  onRefreshDetectorLanes: (id: string, endpoint: "e1" | "entry" | "exit") => void;
  onFocusDetectorLane: (laneId: string | null) => void;
  onAddBuildingClassification: (payload: { name: string; types: string[] }) => void;
  onSelectBuildingClassification: (classificationId: string) => void;
  onRenameBuildingClassification: (classificationId: string, name: string) => void;
  onDeleteBuildingClassification: (classificationId: string) => void;
  onAddBuildingType: (classificationId: string) => void;
  onRenameBuildingType: (classificationId: string, typeId: string, name: string) => void;
  onDeleteBuildingType: (classificationId: string, typeId: string) => void;
  onAssignBuildingType: (classificationId: string, buildingId: string, typeId: string) => void;
  onUpdateParkingSpec: (parkingId: string, patch: Record<string, unknown>) => void;
  onAddParkingClassification: (payload: { name: string; types: string[] }) => void;
  onSelectParkingClassification: (classificationId: string) => void;
  onRenameParkingClassification: (classificationId: string, name: string) => void;
  onDeleteParkingClassification: (classificationId: string) => void;
  onAddParkingType: (classificationId: string, name: string) => void;
  onAssignParkingType: (classificationId: string, parkingId: string, typeId: string) => void;
  onEstimateParkingCapacity: (parkingId: string) => void;
  onEstimateAllUnknownCapacities: () => void;
  onRevertParkingCapacity: (parkingId: string) => void;
  onExpandedParkingSpecChange: (parkingId: string | null) => void;
  onAccessFilterToggle: (id: string) => void;
  onCapacityFilterToggle: (id: string) => void;
  onClearParkingSpecFilters: () => void;
  onBuildingSearchChange: (value: string) => void;
  onParkingSearchChange: (value: string) => void;
  onLoadFeatures: () => void;
  onUploadOsmFile: (file: File) => void;
  onDownloadSelectedAreaOsm: () => void;
  onRefreshOsmArea: () => void;
  onToggleBuilding: (id: string) => void;
  onToggleParking: (id: string) => void;
  onSelectAllBuildings: () => void;
  onDeselectAllBuildings: () => void;
  onSelectFilteredBuildings: () => void;
  onDeselectFilteredBuildings: () => void;
  unnamedBuildingCount: number;
  selectedUnnamedBuildingCount: number;
  onDeselectUnnamedBuildings: () => void;
  onSelectUnnamedBuildings: () => void;
  onSelectAllParking: () => void;
  onDeselectAllParking: () => void;
  onSelectFilteredParking: () => void;
  onDeselectFilteredParking: () => void;
  unnamedParkingCount: number;
  selectedUnnamedParkingCount: number;
  onDeselectUnnamedParking: () => void;
  onSelectUnnamedParking: () => void;
};

export default function AppSidebar({
  boundaryReady,
  buildings,
  parkingAreas,
  filteredBuildings,
  filteredParkingAreas,
  selectedBuildingIds,
  selectedParkingIds,
  buildingSearch,
  parkingSearch,
  parkingSpecs,
  buildingClassifications,
  activeBuildingClassificationId,
  buildingSpecMessage,
  parkingClassifications,
  activeParkingClassificationId,
  detectors,
  activeDetectorId,
  detectorCandidates,
  detectorPlacementType,
  detectorPlacementE3Exit,
  detectorResolving,
  detectorMessage,
  publicTransportOrigins,
  publicTransportPointPlacementActive,
  vehicleGenerationPoints,
  activeVehicleGenerationPointId,
  vehicleGenerationCandidates,
  vehicleGenerationPointPlacementActive,
  vehicleGenerationResolving,
  vehicleGenerationMessage,
  activeAccessFilters,
  activeCapacityFilters,
  expandedParkingSpecId,
  sidebarMode,
  loading,
  uploading,
  downloadingOsm,
  refreshingOsm,
  loadProgress,
  busy,
  error,
  requestInfo,
  modelName,
  currentModelId,
  modelCreatedAt,
  modelUpdatedAt,
  savingModel,
  exportingAll,
  estimatingCapacity,
  parkingSpecMessage,
  hasUnsavedChanges,
  currentModelHasContent,
  workspaceMode,
  sidebarCollapsed,
  onSidebarCollapsedChange,
  onGoHome,
  onModelNameChange,
  onSaveCurrentModel,
  onOpenSimulation,
  onExportAllModelFiles,
  onOpenParkingSpecs,
  onBackFromParkingSpecs,
  onOpenBuildingSpecs,
  onBackFromBuildingSpecs,
  onOpenDetectorSpecs,
  onBackFromDetectorSpecs,
  onOpenPublicTransportOrigins,
  onBackFromPublicTransportOrigins,
  onTogglePublicTransportPointPlacement,
  onChangePublicTransportOrigin,
  onDeletePublicTransportOrigin,
  onToggleVehicleGenerationPointPlacement,
  onSelectVehicleGenerationPoint,
  onChangeVehicleGenerationPoint,
  onDeleteVehicleGenerationPoint,
  onRefreshVehicleGenerationPointLanes,
  onFocusVehicleGenerationLane,
  onStartDetectorPlacement,
  onCancelDetectorPlacement,
  onSelectDetector,
  onChangeDetector,
  onDeleteDetector,
  onRefreshDetectorLanes,
  onFocusDetectorLane,
  onAddBuildingClassification,
  onSelectBuildingClassification,
  onRenameBuildingClassification,
  onDeleteBuildingClassification,
  onAddBuildingType,
  onRenameBuildingType,
  onDeleteBuildingType,
  onAssignBuildingType,
  onUpdateParkingSpec,
  onAddParkingClassification,
  onSelectParkingClassification,
  onRenameParkingClassification,
  onDeleteParkingClassification,
  onAddParkingType,
  onAssignParkingType,
  onEstimateParkingCapacity,
  onEstimateAllUnknownCapacities,
  onRevertParkingCapacity,
  onExpandedParkingSpecChange,
  onAccessFilterToggle,
  onCapacityFilterToggle,
  onClearParkingSpecFilters,
  onBuildingSearchChange,
  onParkingSearchChange,
  onLoadFeatures,
  onUploadOsmFile,
  onDownloadSelectedAreaOsm,
  onRefreshOsmArea,
  onToggleBuilding,
  onToggleParking,
  onSelectAllBuildings,
  onDeselectAllBuildings,
  onSelectFilteredBuildings,
  onDeselectFilteredBuildings,
  unnamedBuildingCount,
  selectedUnnamedBuildingCount,
  onDeselectUnnamedBuildings,
  onSelectUnnamedBuildings,
  onSelectAllParking,
  onDeselectAllParking,
  onSelectFilteredParking,
  onDeselectFilteredParking,
  unnamedParkingCount,
  selectedUnnamedParkingCount,
  onDeselectUnnamedParking,
  onSelectUnnamedParking,
}: AppSidebarProps) {
  const [dragActive, setDragActive] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideInitialStep, setGuideInitialStep] = useState(0);
  const [exportOptions, setExportOptions] = useState<ModelExportOptions>({
    osm: true,
    buildings: false,
    parkingAreas: false,
    modelConfig: false,
  });

  useEffect(() => {
    setExportOptions((current) => ({
      ...current,
      buildings: selectedBuildingIds.size ? current.buildings : false,
      parkingAreas: selectedParkingIds.size ? current.parkingAreas : false,
    }));
  }, [selectedBuildingIds.size, selectedParkingIds.size]);

  const isNewModelRoute = workspaceMode === "new";
  const isSavedModelRoute = workspaceMode === "model";
  const showSourceControls = isNewModelRoute;
  const showWorkingPanels = currentModelHasContent;

  useEffect(() => {
    if (!isNewModelRoute) return;

    try {
      if (!window.localStorage.getItem(NEW_MODEL_GUIDE_SEEN_KEY)) {
        setGuideInitialStep(0);
        setGuideOpen(true);
      }
    } catch {
      setGuideInitialStep(0);
      setGuideOpen(true);
    }
  }, [isNewModelRoute]);

  const setGuideVisibility = (open: boolean) => {
    setGuideOpen(open);
    if (!open) {
      try {
        window.localStorage.setItem(NEW_MODEL_GUIDE_SEEN_KEY, "seen");
      } catch {
        // Storage can be unavailable in privacy-restricted browsers; the guide still works for this visit.
      }
    }
  };

  const showGuideStep = (step: number) => {
    setGuideInitialStep(step);
    setGuideOpen(true);
  };

  const uploadFile = (file?: File) => {
    if (file && !busy) {
      onUploadOsmFile(file);
    }
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!busy) setDragActive(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    uploadFile(event.dataTransfer.files?.[0]);
  };
  const saveStatus = currentModelHasContent ? (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-disabled={!hasUnsavedChanges || busy}
      tabIndex={!hasUnsavedChanges || busy ? -1 : 0}
      onClick={() => {
        if (hasUnsavedChanges && !busy) onSaveCurrentModel();
      }}
      title={
        savingModel
          ? "Saving the current model"
          : hasUnsavedChanges
            ? "Save all model changes"
            : "All model changes are saved"
      }
      className={cn(
        "shrink-0 gap-2",
        hasUnsavedChanges && !savingModel && "text-red-600 hover:text-red-600",
        savingModel && "cursor-default text-muted-foreground",
        !hasUnsavedChanges && currentModelId && "cursor-default text-green-600 hover:text-green-600",
        !hasUnsavedChanges && !currentModelId && "cursor-default text-muted-foreground",
      )}
    >
      <Save className="size-4" />
      {savingModel ? "Saving…" : hasUnsavedChanges ? "Unsaved Changes" : currentModelId ? "Saved" : "Not saved"}
    </Button>
  ) : null;

  const topBar = (
    <div className="mb-3 flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onGoHome} className="shrink-0 gap-2">
          <Home className="size-4" />
          Home
        </Button>
        {saveStatus}
      </div>
      <Tooltip><TooltipTrigger asChild><Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={busy}
        onClick={() => onSidebarCollapsedChange(true)}
        aria-label="Collapse sidebar"
      >
        <PanelLeftClose className="size-4" />
      </Button></TooltipTrigger><TooltipContent>Collapse sidebar</TooltipContent></Tooltip>
    </div>
  );

  const loadedMessage = !error && requestInfo?.source && requestInfo.source !== "saved-model" && (
    <InfoMessage>
      {requestInfo.source === "overpass" && (
        <>Loaded {buildings.features.length} buildings and {parkingAreas.features.length} parking areas{requestInfo.cacheHit ? " from the local cache." : "."}</>
      )}
      {requestInfo.source === "upload" && (
        <>Loaded {buildings.features.length} buildings and {parkingAreas.features.length} parking areas from {requestInfo.filename}.</>
      )}
      {requestInfo.source === "osm-refresh" && (() => {
        const summary = requestInfo.refreshSummary as Record<string, number> | undefined;
        return (
          <>Updated this boundary from OpenStreetMap: {buildings.features.length} buildings and {parkingAreas.features.length} parking areas. Added {summary?.buildingsAdded ?? 0} building(s) and {summary?.parkingAdded ?? 0} parking area(s); removed {summary?.buildingsRemoved ?? 0} building(s) and {summary?.parkingRemoved ?? 0} parking area(s). Review and save the model.</>
        );
      })()}
    </InfoMessage>
  );

  const asideClass = "relative z-10 h-full overflow-hidden border-r bg-background shadow-sm max-[820px]:border-r-0 max-[820px]:border-t";
  const sidebarContentClass = "h-full overflow-y-auto overscroll-contain p-4";

  if (sidebarCollapsed) {
    return (
      <>
        <aside className="relative z-10 flex h-full items-start justify-center overflow-hidden border-r bg-background p-1.5 shadow-sm transition-[width] duration-300 ease-in-out max-[820px]:row-start-2 max-[820px]:border-r-0 max-[820px]:border-t">
          <Tooltip><TooltipTrigger asChild><Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onSidebarCollapsedChange(false)}
            aria-label="Expand sidebar"
          >
            <PanelLeftOpen className="size-4" />
          </Button></TooltipTrigger><TooltipContent side="right">Expand sidebar</TooltipContent></Tooltip>
        </aside>
        <NewModelGuideDialog
          open={guideOpen}
          initialStep={guideInitialStep}
          onOpenChange={setGuideVisibility}
        />
      </>
    );
  }

  if (sidebarMode === "parkingSpecs") {
    return (
      <aside className={asideClass}>
        <div className={sidebarContentClass}>
          {topBar}
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <ParkingSpecsPanel
            parkingAreas={parkingAreas}
            selectedParkingIds={selectedParkingIds}
            parkingSpecs={parkingSpecs}
            parkingClassifications={parkingClassifications}
            activeParkingClassificationId={activeParkingClassificationId}
            activeAccessFilters={activeAccessFilters}
            activeCapacityFilters={activeCapacityFilters}
            expandedParkingSpecId={expandedParkingSpecId}
            busy={busy}
            estimatingCapacity={estimatingCapacity}
            parkingSpecMessage={parkingSpecMessage}
            onBack={onBackFromParkingSpecs}
            onAccessFilterToggle={onAccessFilterToggle}
            onCapacityFilterToggle={onCapacityFilterToggle}
            onClearFilters={onClearParkingSpecFilters}
            onUpdateParkingSpec={onUpdateParkingSpec}
            onAddClassification={onAddParkingClassification}
            onSelectClassification={onSelectParkingClassification}
            onRenameClassification={onRenameParkingClassification}
            onDeleteClassification={onDeleteParkingClassification}
            onAddType={onAddParkingType}
            onAssignType={onAssignParkingType}
            onEstimateParkingCapacity={onEstimateParkingCapacity}
            onEstimateAllUnknownCapacities={onEstimateAllUnknownCapacities}
            onRevertParkingCapacity={onRevertParkingCapacity}
            onExpandedParkingSpecChange={onExpandedParkingSpecChange}
          />
        </div>
      </aside>
    );
  }

  if (sidebarMode === "detectorSpecs") {
    return (
      <aside className={asideClass}>
        <div className={sidebarContentClass}>
          {topBar}
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <DetectorSpecsPanel
            detectors={detectors}
            activeDetectorId={activeDetectorId}
            candidates={detectorCandidates}
            placingType={detectorPlacementType}
            placingE3Exit={detectorPlacementE3Exit}
            resolving={detectorResolving}
            message={detectorMessage}
            busy={busy}
            onBack={onBackFromDetectorSpecs}
            onStartPlacement={onStartDetectorPlacement}
            onCancelPlacement={onCancelDetectorPlacement}
            onSelect={onSelectDetector}
            onChange={onChangeDetector}
            onDelete={onDeleteDetector}
            onRefreshLanes={onRefreshDetectorLanes}
            onFocusLane={onFocusDetectorLane}
          />
        </div>
      </aside>
    );
  }

  if (sidebarMode === "buildingSpecs") {
    return (
      <aside className={asideClass}>
        <div className={sidebarContentClass}>
          {topBar}
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <BuildingSpecsPanel
            buildings={buildings}
            buildingClassifications={buildingClassifications}
            activeBuildingClassificationId={activeBuildingClassificationId}
            selectedBuildingIds={selectedBuildingIds}
            busy={busy}
            buildingSpecMessage={buildingSpecMessage}
            onBack={onBackFromBuildingSpecs}
            onAddClassification={onAddBuildingClassification}
            onSelectClassification={onSelectBuildingClassification}
            onRenameClassification={onRenameBuildingClassification}
            onDeleteClassification={onDeleteBuildingClassification}
            onAddType={onAddBuildingType}
            onRenameType={onRenameBuildingType}
            onDeleteType={onDeleteBuildingType}
            onAssignBuildingType={onAssignBuildingType}
          />
        </div>
      </aside>
    );
  }

  if (sidebarMode === "publicTransportOrigins") {
    return (
      <aside className={asideClass}>
        <div className={sidebarContentClass}>
          {topBar}
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <PublicTransportOriginsPanel
            buildings={buildings}
            origins={publicTransportOrigins}
            vehicleGenerationPoints={vehicleGenerationPoints}
            activeVehicleGenerationPointId={activeVehicleGenerationPointId}
            vehicleLaneCandidates={vehicleGenerationCandidates}
            placingPoint={publicTransportPointPlacementActive}
            placingVehiclePoint={vehicleGenerationPointPlacementActive}
            resolvingVehiclePoint={vehicleGenerationResolving}
            vehiclePointMessage={vehicleGenerationMessage}
            busy={busy}
            onBack={onBackFromPublicTransportOrigins}
            onTogglePointPlacement={onTogglePublicTransportPointPlacement}
            onChange={onChangePublicTransportOrigin}
            onDelete={onDeletePublicTransportOrigin}
            onToggleVehiclePointPlacement={onToggleVehicleGenerationPointPlacement}
            onSelectVehiclePoint={onSelectVehicleGenerationPoint}
            onChangeVehiclePoint={onChangeVehicleGenerationPoint}
            onDeleteVehiclePoint={onDeleteVehicleGenerationPoint}
            onRefreshVehiclePointLanes={onRefreshVehicleGenerationPointLanes}
            onFocusVehicleLane={onFocusVehicleGenerationLane}
          />
        </div>
      </aside>
    );
  }

  return (
    <aside className={asideClass}>
      <div className={sidebarContentClass}>
      {topBar}

      {error && <ErrorMessage>{error}</ErrorMessage>}
      {loadedMessage}

      {showSourceControls && (
        <Card className="mb-3.5 shadow-sm">
          <CardHeader className="p-4 pb-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-sm">Choose source data</CardTitle>
              <Button type="button" variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs" onClick={() => showGuideStep(0)}>
                <CircleHelp className="size-3.5" /> How it works
              </Button>
            </div>
            <CardDescription className="text-xs">
              Choose one path below. You do not need to upload a file if you select an area on the map.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 p-4 pt-0">
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-800 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200">
              <strong>Start here:</strong> upload an existing OSM extract, or draw a boundary and let the app download the data for you.
            </div>
            <div className="rounded-lg border bg-muted/20 p-3">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-full bg-muted text-xs font-semibold">A</span>
                <FileUp className="size-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Upload a .osm file</h3>
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Use an existing .osm, .osm.xml, or compressed OSM extract. The app reads its buildings and parking areas, so no map boundary is required.
              </p>
              <div
                className={`mt-3 grid gap-1 rounded-xl border border-dashed p-4 text-center transition-colors ${dragActive ? "border-primary bg-primary/10" : "bg-muted/50"}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <strong className="text-sm">Drag and drop an OSM file here</strong>
                <span className="text-xs text-muted-foreground">or choose a file from your computer</span>
                <Input
                  id="osm-file-upload"
                  type="file"
                  accept=".osm,.xml,.gz,.osm.xml,.osm.xml.gz,application/xml,text/xml"
                  disabled={busy}
                  className="mt-2"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) {
                      uploadFile(file);
                      event.target.value = "";
                    }
                  }}
                />
              </div>
              {uploading && (
                <div className="mt-3 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 p-2.5 text-xs text-blue-800 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-200" role="status">
                  <span className="size-2 animate-pulse rounded-full bg-blue-600" />
                  Reading the OSM file and extracting map features…
                </div>
              )}
            </div>

            <div className="rounded-lg border bg-muted/20 p-3">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-full bg-muted text-xs font-semibold">B</span>
                <MapPinned className="size-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Select an area on the map</h3>
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Use the square or polygon tool in the map's upper-left corner. After the purple boundary appears, load its buildings and parking areas.
              </p>

              {loadProgress.status !== "idle" && (
                <LoadProgressStatus progress={loadProgress} />
              )}

              <div className="mt-3 grid gap-2">
                <div className="w-full" title={!boundaryReady ? "Select an area on the map first" : undefined}>
                  <Button
                    type="button"
                    className="min-h-9 h-auto w-full px-3 py-2"
                    disabled={!boundaryReady || busy}
                    onClick={onLoadFeatures}
                  >
                    {loading ? "Still loading — keep this page open…" : "Load buildings and parking areas"}
                  </Button>
                </div>
                <div className="w-full" title={!boundaryReady ? "Select an area on the map first" : undefined}>
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-9 h-auto w-full px-3 py-2"
                    disabled={!boundaryReady || busy}
                    onClick={onDownloadSelectedAreaOsm}
                  >
                    {downloadingOsm ? "Preparing .osm…" : "Download selected area as .osm"}
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {isSavedModelRoute && !showWorkingPanels && !error && (
        <Card className="mb-3.5 shadow-sm">
          <CardHeader className="p-4">
            <CardTitle className="text-sm">Loading model</CardTitle>
            <CardDescription className="text-xs">The selected model is being restored.</CardDescription>
          </CardHeader>
        </Card>
      )}

      {showWorkingPanels && (
        <Card className="mb-3.5 shadow-sm">
          <CardHeader className="p-4 pb-3">
            <CardTitle className="text-sm">Current Model</CardTitle>
            <CardDescription className="text-xs">Name the current model so it can be identified and loaded again later.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 p-4 pt-0">
            <div className="space-y-1 rounded-lg bg-muted/40 p-2.5 text-xs text-muted-foreground">
              <p>Created at: {formatDateTime(modelCreatedAt)}</p>
              <p>Last modified at: {formatDateTime(modelUpdatedAt)}</p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="area-model-name" className="text-xs text-muted-foreground">Model name</Label>
              <Input
                id="area-model-name"
                type="text"
                value={modelName}
                placeholder="e.g. Cité Scientifique baseline"
                disabled={busy}
                onChange={(event) => onModelNameChange(event.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy || !currentModelId || !boundaryReady}
                onClick={onRefreshOsmArea}
              >
                <RefreshCw className={cn("size-4", refreshingOsm && "animate-spin")} />
                {refreshingOsm ? "Updating OSM area…" : "Update OSM area"}
              </Button>
              <p className="text-xs leading-5 text-muted-foreground">
                Fetch the latest OSM data for the same boundary. Matching selections and specifications are preserved; new features remain unselected.
              </p>
              {hasUnsavedChanges ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="block w-full" tabIndex={0}>
                      <Button type="button" className="w-full" disabled>
                        <Play className="size-4" /> Run simulation
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>Save your changes before running the simulation.</TooltipContent>
                </Tooltip>
              ) : (
                <Button
                  type="button"
                  disabled={busy || !currentModelId || !selectedBuildingIds.size}
                  onClick={onOpenSimulation}
                >
                  <Play className="size-4" /> Run simulation
                </Button>
              )}
              <Button type="button" variant="outline" disabled={busy || !buildings.features.length} onClick={onOpenBuildingSpecs}>
                Edit Building Specs
              </Button>
              <Button type="button" variant="outline" disabled={busy || !parkingAreas.features.length} onClick={onOpenParkingSpecs}>
                Edit Parking Specs
              </Button>
              <Button type="button" variant="outline" disabled={busy} onClick={onOpenPublicTransportOrigins}>
                <BusFront className="size-4" /> Public & Vehicle Origins
              </Button>
              <Button type="button" variant="outline" disabled={busy || !currentModelId} onClick={onOpenDetectorSpecs}>
                Edit Detectors
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {showWorkingPanels && (
        <>
          <FeatureSelectionPanel
            title="Select buildings"
            kind="building"
            features={buildings}
            filteredFeatures={filteredBuildings}
            selectedIds={selectedBuildingIds}
            search={buildingSearch}
            searchPlaceholder="e.g. engineering, M1, way/…"
            getFeatureId={getFeatureId}
            getDisplayName={getBuildingDisplayName}
            getDescription={getBuildingDescription}
            onSearchChange={onBuildingSearchChange}
            onToggle={onToggleBuilding}
            onSelectAll={onSelectAllBuildings}
            onDeselectAll={onDeselectAllBuildings}
            onSelectFiltered={onSelectFilteredBuildings}
            onDeselectFiltered={onDeselectFilteredBuildings}
            unnamedCount={unnamedBuildingCount}
            selectedUnnamedCount={selectedUnnamedBuildingCount}
            onDeselectUnnamed={onDeselectUnnamedBuildings}
            onSelectUnnamed={onSelectUnnamedBuildings}
            onShowHelp={() => showGuideStep(3)}
          />

          <FeatureSelectionPanel
            title="Select parking areas"
            kind="parking"
            features={parkingAreas}
            filteredFeatures={filteredParkingAreas}
            selectedIds={selectedParkingIds}
            search={parkingSearch}
            searchPlaceholder="e.g. C6, surface, public, way/…"
            getFeatureId={getFeatureId}
            getDisplayName={getParkingDisplayName}
            getDescription={getParkingDescription}
            onSearchChange={onParkingSearchChange}
            onToggle={onToggleParking}
            onSelectAll={onSelectAllParking}
            onDeselectAll={onDeselectAllParking}
            onSelectFiltered={onSelectFilteredParking}
            onDeselectFiltered={onDeselectFilteredParking}
            unnamedCount={unnamedParkingCount}
            selectedUnnamedCount={selectedUnnamedParkingCount}
            onDeselectUnnamed={onDeselectUnnamedParking}
            onSelectUnnamed={onSelectUnnamedParking}
            onShowHelp={() => showGuideStep(3)}
          />

          <Collapsible className="group mb-3.5 overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm">
            <CollapsibleTrigger className="flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-sm font-medium hover:bg-muted/50 [&[data-state=open]>svg]:rotate-180">
              <span className="flex items-center gap-2"><Download className="size-4" /> Download model</span>
              <ChevronDown className="size-4 transition-transform" />
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-3 border-t p-4">
              <p className="text-xs leading-5 text-muted-foreground">Choose which files to include in the ZIP.</p>
              <div className="space-y-2.5">
                {([
                  ["osm", "OSM file", false],
                  ["buildings", `Buildings (${selectedBuildingIds.size} selected)`, !selectedBuildingIds.size],
                  ["parkingAreas", `Parking areas (${selectedParkingIds.size} selected)`, !selectedParkingIds.size],
                  ["modelConfig", "Model config", false],
                ] as const).map(([key, label, disabled]) => (
                  <label key={key} className={cn("flex items-center gap-2.5 text-sm", disabled && "text-muted-foreground")}>
                    <Checkbox
                      checked={exportOptions[key]}
                      disabled={disabled || exportingAll}
                      onCheckedChange={(checked) => setExportOptions((current) => ({
                        ...current,
                        [key]: checked === true,
                      }))}
                    />
                    {label}
                  </label>
                ))}
              </div>
              <Button
                type="button"
                className="w-full"
                disabled={busy || !Object.values(exportOptions).some(Boolean)}
                onClick={() => onExportAllModelFiles(exportOptions)}
              >
                <Download className="size-4" />
                {exportingAll ? "Preparing ZIP…" : "Download ZIP"}
              </Button>
            </CollapsibleContent>
          </Collapsible>
        </>
      )}
      </div>
      <NewModelGuideDialog
        open={guideOpen}
        initialStep={guideInitialStep}
        onOpenChange={setGuideVisibility}
      />
    </aside>
  );
}
