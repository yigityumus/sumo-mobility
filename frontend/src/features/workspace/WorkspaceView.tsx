import { useEffect, useState } from "react";
import { LoaderCircle, MapPinned, MousePointerClick } from "lucide-react";
import { usePanelRef } from "react-resizable-panels";
import AppSidebar from "../../components/AppSidebar.tsx";
import AreaMap from "../../components/AreaMap.tsx";
import BuildingClassificationOverlay from "../../components/BuildingClassificationOverlay.tsx";
import DemandDistributionCard from "../../components/DemandDistributionCard.tsx";
import ModelActionDialog from "../../components/ModelActionDialog.tsx";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "../../components/ui/resizable.tsx";
import TopNavigation from "../../components/TopNavigation.tsx";
import {
  getFeatureId,
  isUnnamedBuilding,
  isUnnamedParkingArea,
} from "../../utils/osmFeatures.ts";

type WorkspaceViewProps = Record<string, any>;

export default function WorkspaceView(props: WorkspaceViewProps) {
  const {
    boundaryFeature,
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
    activeBuildingClassification,
    buildingSpecMessage,
    parkingClassifications,
    activeParkingClassificationId,
    activeParkingClassification,
    detectors,
    activeDetectorId,
    detectorCandidates,
    detectorPlacementActive,
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
    highlightedParkingIds,
    expandedParkingIds,
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
    routePath,
    modelActionDialog,
    unnamedBuildingCount,
    unnamedParkingCount,
    selectedUnnamedBuildingCount,
    selectedUnnamedParkingCount,
    setSidebarCollapsed,
    goHome,
    goAnalytics,
    goDocumentation,
    setModelName,
    saveCurrentModel,
    openSimulation,
    exportAllModelFiles,
    openParkingSpecs,
    backFromParkingSpecs,
    openBuildingSpecs,
    backFromBuildingSpecs,
    openDetectorSpecs,
    backFromDetectorSpecs,
    openPublicTransportOrigins,
    backFromPublicTransportOrigins,
    togglePublicTransportPointPlacement,
    changePublicTransportOrigin,
    deletePublicTransportOrigin,
    togglePublicTransportBuilding,
    placePublicTransportPoint,
    toggleVehicleGenerationPointPlacement,
    placeVehicleGenerationPoint,
    selectVehicleGenerationPoint,
    changeVehicleGenerationPoint,
    deleteVehicleGenerationPoint,
    refreshVehicleGenerationPointLanes,
    startDetectorPlacement,
    cancelDetectorPlacement,
    selectDetector,
    changeDetector,
    deleteDetector,
    refreshDetectorLanes,
    placeDetectorAt,
    addBuildingClassificationHandler,
    setActiveBuildingClassificationId,
    renameBuildingClassificationHandler,
    deleteBuildingClassificationHandler,
    addBuildingTypeHandler,
    renameBuildingTypeHandler,
    deleteBuildingTypeHandler,
    assignBuildingTypeHandler,
    updateBuildingTypeDemandDistributionHandler,
    addParkingClassificationHandler,
    setActiveParkingClassificationId,
    renameParkingClassificationHandler,
    deleteParkingClassificationHandler,
    addParkingTypeHandler,
    renameParkingTypeHandler,
    deleteParkingTypeHandler,
    assignParkingTypeHandler,
    updateParkingSpecById,
    estimateCapacityForParking,
    estimateAllUnknownCapacities,
    revertParkingCapacity,
    setExpandedParkingSpecId,
    toggleId,
    setActiveAccessFilters,
    setActiveCapacityFilters,
    setBuildingSearch,
    setParkingSearch,
    loadFeatures,
    uploadOsmFile,
    downloadSelectedAreaOsm,
    refreshOsmArea,
    setSelectedBuildingIds,
    setSelectedParkingIds,
    selectFilteredIds,
    deselectFilteredIds,
    deselectMatchingIds,
    handleBoundaryChange,
    confirmModelAction,
    setModelActionDialog,
  } = props;

  const [isCompact, setIsCompact] = useState(() => window.matchMedia("(max-width: 820px)").matches);
  const [sidebarLayoutSize, setSidebarLayoutSize] = useState(320);
  const [focusedDetectorLaneId, setFocusedDetectorLaneId] = useState<string | null>(null);
  const [focusedVehicleGenerationLaneId, setFocusedVehicleGenerationLaneId] = useState<string | null>(null);
  const [detectorWaitSeconds, setDetectorWaitSeconds] = useState(0);
  const sidebarPanelRef = usePanelRef();

  useEffect(() => {
    const query = window.matchMedia("(max-width: 820px)");
    const update = () => setIsCompact(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (sidebarCollapsed) sidebarPanelRef.current?.collapse();
    else sidebarPanelRef.current?.expand();
  }, [sidebarCollapsed, sidebarPanelRef]);

  useEffect(() => {
    setFocusedDetectorLaneId(null);
  }, [activeDetectorId, sidebarMode]);

  useEffect(() => {
    if (!detectorResolving) {
      setDetectorWaitSeconds(0);
      return;
    }
    const startedAt = Date.now();
    setDetectorWaitSeconds(0);
    const timer = window.setInterval(() => {
      setDetectorWaitSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [detectorResolving]);

  return (
    <>
      <ResizablePanelGroup
        orientation={isCompact ? "vertical" : "horizontal"}
        className={isCompact ? "!flex-col-reverse bg-background" : "bg-background"}
      >
        <ResizablePanel
          id="workspace-sidebar"
          panelRef={sidebarPanelRef}
          defaultSize={isCompact ? "48%" : "22%"}
          minSize={isCompact ? "220px" : "288px"}
          maxSize={isCompact ? "70%" : "576px"}
          collapsible
          collapsedSize="48px"
          onResize={(size) => {
            setSidebarLayoutSize(Math.round(size.inPixels));
            const panelIsCollapsed = sidebarPanelRef.current?.isCollapsed();
            if (typeof panelIsCollapsed === "boolean" && panelIsCollapsed !== sidebarCollapsed) {
              setSidebarCollapsed(panelIsCollapsed);
            }
          }}
        >
          <AppSidebar
          boundaryReady={Boolean(boundaryFeature)}
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
          buildingSpecMessage={buildingSpecMessage}
          parkingClassifications={parkingClassifications}
          activeParkingClassificationId={activeParkingClassificationId}
          detectors={detectors}
          activeDetectorId={activeDetectorId}
          detectorCandidates={detectorCandidates}
          detectorPlacementType={detectorPlacementType}
          detectorPlacementE3Exit={detectorPlacementE3Exit}
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
          onSidebarCollapsedChange={setSidebarCollapsed}
          onGoHome={goHome}
          onModelNameChange={setModelName}
          onSaveCurrentModel={saveCurrentModel}
          onOpenSimulation={openSimulation}
          onExportAllModelFiles={exportAllModelFiles}
          onOpenParkingSpecs={openParkingSpecs}
          onBackFromParkingSpecs={backFromParkingSpecs}
          onOpenBuildingSpecs={openBuildingSpecs}
          onBackFromBuildingSpecs={backFromBuildingSpecs}
          onOpenDetectorSpecs={openDetectorSpecs}
          onBackFromDetectorSpecs={backFromDetectorSpecs}
          onOpenPublicTransportOrigins={openPublicTransportOrigins}
          onBackFromPublicTransportOrigins={backFromPublicTransportOrigins}
          onTogglePublicTransportPointPlacement={togglePublicTransportPointPlacement}
          onChangePublicTransportOrigin={changePublicTransportOrigin}
          onDeletePublicTransportOrigin={deletePublicTransportOrigin}
          onToggleVehicleGenerationPointPlacement={toggleVehicleGenerationPointPlacement}
          onSelectVehicleGenerationPoint={selectVehicleGenerationPoint}
          onChangeVehicleGenerationPoint={changeVehicleGenerationPoint}
          onDeleteVehicleGenerationPoint={deleteVehicleGenerationPoint}
          onRefreshVehicleGenerationPointLanes={refreshVehicleGenerationPointLanes}
          onFocusVehicleGenerationLane={setFocusedVehicleGenerationLaneId}
          onStartDetectorPlacement={startDetectorPlacement}
          onCancelDetectorPlacement={cancelDetectorPlacement}
          onSelectDetector={selectDetector}
          onChangeDetector={changeDetector}
          onDeleteDetector={deleteDetector}
          onRefreshDetectorLanes={refreshDetectorLanes}
          onFocusDetectorLane={setFocusedDetectorLaneId}
          onAddBuildingClassification={addBuildingClassificationHandler}
          onSelectBuildingClassification={setActiveBuildingClassificationId}
          onRenameBuildingClassification={renameBuildingClassificationHandler}
          onDeleteBuildingClassification={deleteBuildingClassificationHandler}
          onAddBuildingType={addBuildingTypeHandler}
          onRenameBuildingType={renameBuildingTypeHandler}
          onDeleteBuildingType={deleteBuildingTypeHandler}
          onAssignBuildingType={assignBuildingTypeHandler}
          onUpdateParkingSpec={updateParkingSpecById}
          onAddParkingClassification={addParkingClassificationHandler}
          onSelectParkingClassification={setActiveParkingClassificationId}
          onRenameParkingClassification={renameParkingClassificationHandler}
          onDeleteParkingClassification={deleteParkingClassificationHandler}
          onAddParkingType={addParkingTypeHandler}
          onAssignParkingType={assignParkingTypeHandler}
          onEstimateParkingCapacity={estimateCapacityForParking}
          onEstimateAllUnknownCapacities={estimateAllUnknownCapacities}
          onRevertParkingCapacity={revertParkingCapacity}
          onExpandedParkingSpecChange={setExpandedParkingSpecId}
          onAccessFilterToggle={(id: string) => toggleId(setActiveAccessFilters, id)}
          onCapacityFilterToggle={(id: string) => toggleId(setActiveCapacityFilters, id)}
          onClearParkingSpecFilters={() => {
            setActiveAccessFilters(new Set());
            setActiveCapacityFilters(new Set());
          }}
          onBuildingSearchChange={setBuildingSearch}
          onParkingSearchChange={setParkingSearch}
          onLoadFeatures={loadFeatures}
          onUploadOsmFile={uploadOsmFile}
          onDownloadSelectedAreaOsm={downloadSelectedAreaOsm}
          onRefreshOsmArea={refreshOsmArea}
          onToggleBuilding={(id: string) => toggleId(setSelectedBuildingIds, id)}
          onToggleParking={(id: string) => toggleId(setSelectedParkingIds, id)}
          onSelectAllBuildings={() =>
            setSelectedBuildingIds(new Set(buildings.features.map(getFeatureId)))
          }
          onDeselectAllBuildings={() => setSelectedBuildingIds(new Set())}
          onSelectFilteredBuildings={() =>
            selectFilteredIds(setSelectedBuildingIds, filteredBuildings)
          }
          onDeselectFilteredBuildings={() =>
            deselectFilteredIds(setSelectedBuildingIds, filteredBuildings)
          }
          unnamedBuildingCount={unnamedBuildingCount}
          selectedUnnamedBuildingCount={selectedUnnamedBuildingCount}
          onDeselectUnnamedBuildings={() =>
            deselectMatchingIds(setSelectedBuildingIds, buildings.features, isUnnamedBuilding)
          }
          onSelectUnnamedBuildings={() =>
            setSelectedBuildingIds((current: Set<string>) => {
              const next = new Set(current);
              buildings.features.forEach((feature: any) => {
                if (isUnnamedBuilding(feature)) next.add(getFeatureId(feature));
              });
              return next;
            })
          }
          onSelectAllParking={() =>
            setSelectedParkingIds(new Set(parkingAreas.features.map(getFeatureId)))
          }
          onDeselectAllParking={() => setSelectedParkingIds(new Set())}
          onSelectFilteredParking={() =>
            selectFilteredIds(setSelectedParkingIds, filteredParkingAreas)
          }
          onDeselectFilteredParking={() =>
            deselectFilteredIds(setSelectedParkingIds, filteredParkingAreas)
          }
          unnamedParkingCount={unnamedParkingCount}
          selectedUnnamedParkingCount={selectedUnnamedParkingCount}
          onDeselectUnnamedParking={() =>
            deselectMatchingIds(setSelectedParkingIds, parkingAreas.features, isUnnamedParkingArea)
          }
          onSelectUnnamedParking={() =>
            setSelectedParkingIds((current: Set<string>) => {
              const next = new Set(current);
              parkingAreas.features.forEach((feature: any) => {
                if (isUnnamedParkingArea(feature)) next.add(getFeatureId(feature));
              });
              return next;
            })
          }
          />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id="workspace-map" minSize={isCompact ? "260px" : "380px"}>
        <section className="flex h-full min-w-0 flex-col overflow-y-auto bg-background p-8 max-[820px]:p-3.5">
          <TopNavigation onHome={goHome} onAnalytics={goAnalytics} onDocumentation={goDocumentation} className="mb-4 shrink-0" />
          <div className="mb-4 flex flex-col gap-3">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,380px)_minmax(0,380px)]">
              <div className="w-full max-w-[380px]">
                {activeBuildingClassification && (
                  <BuildingClassificationOverlay
                    classification={activeBuildingClassification}
                    buildings={buildings}
                    busy={busy}
                    onAddType={addBuildingTypeHandler}
                    onRenameType={renameBuildingTypeHandler}
                    onDeleteType={deleteBuildingTypeHandler}
                  />
                )}
                {activeParkingClassification && (
                  <BuildingClassificationOverlay
                    classification={activeParkingClassification}
                    features={parkingAreas}
                    subjectPlural="parking areas"
                    busy={busy}
                    onAddType={addParkingTypeHandler}
                    onRenameType={renameParkingTypeHandler}
                    onDeleteType={deleteParkingTypeHandler}
                  />
                )}
              </div>
              <div className="w-full max-w-[380px]">
                <DemandDistributionCard
                  classification={activeBuildingClassification}
                  busy={busy}
                  onChange={updateBuildingTypeDemandDistributionHandler}
                />
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-md border bg-card/90 px-3 py-2 text-xs leading-5 text-card-foreground shadow-sm">
              {workspaceMode === "new" && !currentModelHasContent ? (
                boundaryFeature ? <MapPinned className="mt-0.5 size-4 shrink-0 text-primary" /> : <MousePointerClick className="mt-0.5 size-4 shrink-0 text-primary" />
              ) : (
                <MousePointerClick className="mt-0.5 size-4 shrink-0 text-primary" />
              )}
              <span>
                {workspaceMode === "new" && !currentModelHasContent
                  ? boundaryFeature
                    ? <><strong>Area selected.</strong> Now click “Load buildings and parking areas” in the sidebar.</>
                    : <><strong>Select an area:</strong> use the square or polygon tool in the map's upper-left. For a rectangle, hold and drag; for a polygon, click each corner and then the first point.</>
                  : sidebarMode === "publicTransportOrigins"
                    ? vehicleGenerationPointPlacementActive
                      ? <><strong>Add a vehicle origin:</strong> click the road and direction where cars should enter the simulation.</>
                      : publicTransportPointPlacementActive
                      ? <><strong>Add a transit point:</strong> click the bus stop, station entrance, or other pedestrian origin on the map.</>
                      : <><strong>Select origins:</strong> add public-transport pedestrian origins or place one or more vehicle origins on passenger roads.</>
                    : <><strong>Refine the model:</strong> click any building or parking shape to select or deselect it. The sidebar shows the exact selected count.</>}
              </span>
            </div>
          </div>

          <div className="relative min-h-[640px] flex-1 overflow-hidden rounded-xl border bg-muted/20">
            <AreaMap
              buildings={buildings}
              parkingAreas={parkingAreas}
              boundaryFeature={boundaryFeature}
              selectedBuildingIds={selectedBuildingIds}
              selectedParkingIds={selectedParkingIds}
              highlightedParkingIds={highlightedParkingIds}
              expandedParkingIds={expandedParkingIds}
              buildingClassification={activeBuildingClassification}
              parkingClassification={activeParkingClassification}
              onToggleBuilding={(id: string) => toggleId(setSelectedBuildingIds, id)}
              onToggleParking={(id: string) => toggleId(setSelectedParkingIds, id)}
              onBoundaryChange={handleBoundaryChange}
              detectors={detectors}
              activeDetectorId={activeDetectorId}
              detectorPlacementActive={detectorPlacementActive}
              detectorLaneCandidates={detectorCandidates}
              focusedDetectorLaneId={focusedDetectorLaneId}
              onDetectorMapClick={placeDetectorAt}
              onDetectorClick={selectDetector}
              publicTransportOrigins={publicTransportOrigins ?? []}
              publicTransportEditing={sidebarMode === "publicTransportOrigins"}
              publicTransportPointPlacementActive={publicTransportPointPlacementActive}
              onPublicTransportMapClick={placePublicTransportPoint}
              onTogglePublicTransportBuilding={togglePublicTransportBuilding}
              vehicleGenerationPoints={vehicleGenerationPoints ?? []}
              activeVehicleGenerationPointId={activeVehicleGenerationPointId}
              vehicleGenerationEditing={sidebarMode === "publicTransportOrigins"}
              vehicleGenerationPointPlacementActive={vehicleGenerationPointPlacementActive}
              vehicleGenerationLaneCandidates={vehicleGenerationCandidates}
              focusedVehicleGenerationLaneId={focusedVehicleGenerationLaneId}
              onVehicleGenerationMapClick={placeVehicleGenerationPoint}
              onSelectVehicleGenerationPoint={selectVehicleGenerationPoint}
              layoutKey={`${sidebarCollapsed ? "collapsed" : sidebarLayoutSize}-${routePath}`}
            />
            {loading && (
              <div className="absolute inset-0 z-[1100] flex items-center justify-center bg-background/55 p-4 backdrop-blur-[2px]" role="status" aria-live="polite">
                <div className="w-full max-w-sm rounded-xl border bg-popover p-5 text-center text-popover-foreground shadow-xl">
                  <LoaderCircle className="mx-auto size-8 animate-spin text-primary" />
                  <h2 className="mt-3 text-base font-semibold">Loading your selected area</h2>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    The app is downloading and processing OpenStreetMap data. This can take a few minutes; keep this page open.
                  </p>
                  <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-xs font-medium">
                    {loadProgress.steps.find((step: any) => step.status === "active")?.label ?? "Preparing map data"}
                  </p>
                </div>
              </div>
            )}
            {!loading && detectorResolving && sidebarMode === "detectorSpecs" && (
              <div className="absolute inset-0 z-[1100] flex items-center justify-center bg-background/45 p-4 backdrop-blur-[1px]" role="status" aria-live="polite">
                <div className="w-full max-w-sm rounded-xl border border-blue-200 bg-popover p-5 text-center text-popover-foreground shadow-xl dark:border-blue-900">
                  <LoaderCircle className="mx-auto size-8 animate-spin text-blue-600" />
                  <h2 className="mt-3 text-base font-semibold">Preparing detector lanes</h2>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    SUMO is building or reading the lane-level network around the detector. The first load for a map can take longer; the program is not stuck.
                  </p>
                  <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-xs font-medium tabular-nums">
                    {detectorWaitSeconds < 1 ? "Starting lane lookup…" : `Still working · ${detectorWaitSeconds}s elapsed`}
                  </p>
                </div>
              </div>
            )}
            {(buildings.features.length > 0 || parkingAreas.features.length > 0) && (
              <div
                className="pointer-events-none absolute bottom-4 right-4 z-[1000] flex flex-col gap-1.5 rounded-md border bg-popover/95 px-3 py-2 text-xs text-popover-foreground shadow-md backdrop-blur-sm"
                aria-label="Map legend"
              >
                {buildings.features.length > 0 && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-[3px] border-2 border-blue-900 bg-blue-600/80" />Selected building</span>
                )}
                {selectedBuildingIds.size < buildings.features.length && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-[3px] border-2 border-dashed border-blue-600 bg-blue-200" />Unselected building</span>
                )}
                {parkingAreas.features.length > 0 && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-[3px] border-2 border-red-900 bg-red-600/80" />Selected parking area</span>
                )}
                {selectedParkingIds.size < parkingAreas.features.length && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-[3px] border-2 border-dashed border-red-500 bg-red-200" />Unselected parking area</span>
                )}
                {highlightedParkingIds.size > 0 && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-[3px] border-2 border-emerald-700 bg-emerald-500/70" />Highlighted parking</span>
                )}
                {expandedParkingIds.size > 0 && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-[3px] border-2 border-amber-700 bg-amber-400/80" />Expanded parking</span>
                )}
                {(publicTransportOrigins ?? []).length > 0 && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-full border-2 border-emerald-800 bg-emerald-400" />Public transportation origin</span>
                )}
                {(vehicleGenerationPoints ?? []).length > 0 && (
                  <span className="flex items-center gap-2"><i className="size-3 rounded-full border-2 border-blue-900 bg-blue-500" />Vehicle generation point</span>
                )}
                {sidebarMode === "detectorSpecs" && Object.values(detectorCandidates).some((items: any) => items.length > 0) && (
                  <>
                    <span className="flex items-center gap-2"><i className="h-1 w-4 rounded bg-blue-600" />Vehicle lane</span>
                    <span className="flex items-center gap-2"><i className="h-1 w-4 rounded bg-fuchsia-600" />Pedestrian lane</span>
                    <span className="flex items-center gap-2"><i className="h-1 w-4 rounded bg-violet-600" />Mixed lane</span>
                  </>
                )}
              </div>
            )}
          </div>
        </section>
        </ResizablePanel>
      </ResizablePanelGroup>
      <ModelActionDialog
        dialog={modelActionDialog}
        busy={busy}
        onCancel={() => setModelActionDialog(null)}
        onConfirm={confirmModelAction}
      />
    </>
  );
}
