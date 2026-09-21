import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { ScrollArea } from "./ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Separator } from "./ui/separator";
import { cn } from "../lib/utils";
import type { CampusFeature, CampusFeatureCollection, ParkingClassification, ParkingSpecsById } from "../types/campus";
import { PARKING_TYPE_UNKNOWN } from "../utils/parkingClassifications.ts";
import ParkingClassificationManager from "./ParkingClassificationManager.tsx";
import {
  CAPACITY_UNKNOWN,
  accessFilterOptions,
  capacityFilterOptions,
  capacityBucketForSpec,
  getOsmCapacity,
  isCapacityChangedFromOriginal,
  parkingSpecAccessOptions,
  sourceLabel,
} from "../utils/parkingSpecs.ts";
import {
  getFeatureId,
  getParkingDescription,
  getParkingDisplayName,
} from "../utils/osmFeatures.ts";

const UNKNOWN_SELECT_VALUE = "__unknown__";

type ParkingSpecsPanelProps = {
  parkingAreas: CampusFeatureCollection;
  selectedParkingIds: Set<string>;
  parkingSpecs: ParkingSpecsById;
  parkingClassifications: ParkingClassification[];
  activeParkingClassificationId: string | null;
  activeAccessFilters: Set<string>;
  activeCapacityFilters: Set<string>;
  expandedParkingSpecId: string | null;
  busy: boolean;
  estimatingCapacity: boolean;
  parkingSpecMessage: string;
  onBack: () => void;
  onAccessFilterToggle: (id: string) => void;
  onCapacityFilterToggle: (id: string) => void;
  onClearFilters: () => void;
  onUpdateParkingSpec: (id: string, patch: Record<string, unknown>) => void;
  onAddClassification: (payload: { name: string; types: string[] }) => void;
  onSelectClassification: (classificationId: string) => void;
  onRenameClassification: (classificationId: string, name: string) => void;
  onDeleteClassification: (classificationId: string) => void;
  onAddType: (classificationId: string, name: string) => void;
  onAssignType: (classificationId: string, parkingId: string, typeId: string) => void;
  onEstimateParkingCapacity: (id: string) => void;
  onEstimateAllUnknownCapacities: () => void;
  onRevertParkingCapacity: (id: string) => void;
  onExpandedParkingSpecChange: (id: string | null) => void;
};

export default function ParkingSpecsPanel({
  parkingAreas,
  selectedParkingIds,
  parkingSpecs,
  parkingClassifications,
  activeParkingClassificationId,
  activeAccessFilters,
  activeCapacityFilters,
  expandedParkingSpecId,
  busy,
  estimatingCapacity,
  parkingSpecMessage,
  onBack,
  onAccessFilterToggle,
  onCapacityFilterToggle,
  onClearFilters,
  onUpdateParkingSpec,
  onAddClassification,
  onSelectClassification,
  onRenameClassification,
  onDeleteClassification,
  onAddType,
  onAssignType,
  onEstimateParkingCapacity,
  onEstimateAllUnknownCapacities,
  onRevertParkingCapacity,
  onExpandedParkingSpecChange,
}: ParkingSpecsPanelProps) {
  const [capacityDrafts, setCapacityDrafts] = useState<Record<string, string>>({});
  const [capacityErrors, setCapacityErrors] = useState<Record<string, string>>({});
  const [selectedListOpen, setSelectedListOpen] = useState(true);
  const [unselectedListOpen, setUnselectedListOpen] = useState(false);

  const activeParkingClassification = useMemo(
    () => (parkingClassifications ?? []).find(
      (classification) => classification.id === activeParkingClassificationId,
    ) ?? parkingClassifications?.[0] ?? null,
    [activeParkingClassificationId, parkingClassifications],
  );

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const feature of parkingAreas.features ?? []) {
      const id = getFeatureId(feature);
      const spec = parkingSpecs[id];
      next[id] = spec?.capacity ? String(spec.capacity) : "";
    }
    setCapacityDrafts(next);
  }, [parkingAreas, parkingSpecs]);

  const accessOptions = useMemo(
    () => accessFilterOptions(parkingAreas, parkingSpecs),
    [parkingAreas, parkingSpecs],
  );

  const capacityOptions = useMemo(
    () => capacityFilterOptions(parkingAreas, parkingSpecs),
    [parkingAreas, parkingSpecs],
  );

  const accessSelectOptions = useMemo(
    () => parkingSpecAccessOptions(parkingSpecs),
    [parkingSpecs],
  );

  const unknownCapacityCount = useMemo(
    () =>
      (parkingAreas.features ?? []).filter((feature) => {
        const id = getFeatureId(feature);
        return !parkingSpecs[id]?.capacity;
      }).length,
    [parkingAreas, parkingSpecs],
  );

  const [selectedParkingAreas, unselectedParkingAreas] = useMemo(() => {
    const selected: CampusFeature[] = [];
    const unselected: CampusFeature[] = [];

    for (const feature of parkingAreas.features ?? []) {
      (selectedParkingIds.has(getFeatureId(feature)) ? selected : unselected).push(feature);
    }

    return [selected, unselected];
  }, [parkingAreas, selectedParkingIds]);

  useEffect(() => {
    if (!expandedParkingSpecId) return;
    if (selectedParkingIds.has(expandedParkingSpecId)) setSelectedListOpen(true);
    else setUnselectedListOpen(true);
  }, [expandedParkingSpecId, selectedParkingIds]);

  const highlightedCount = new Set([
    ...activeAccessFilters,
    ...activeCapacityFilters,
  ]).size;

  function toggleExpanded(id: string) {
    onExpandedParkingSpecChange(expandedParkingSpecId === id ? null : id);
  }

  function handleCapacityDraftChange(id: string, value: string) {
    setCapacityDrafts((current) => ({ ...current, [id]: value }));

    if (!value.trim()) {
      setCapacityErrors((current) => ({ ...current, [id]: "" }));
      onUpdateParkingSpec(id, {
        capacity: null,
        capacitySource: "manual",
        capacityMethod: null,
      });
      return;
    }

    if (!/^[1-9]\d*$/.test(value.trim())) {
      setCapacityErrors((current) => ({
        ...current,
        [id]: "Capacity must be a whole number greater than 0.",
      }));
      return;
    }

    setCapacityErrors((current) => ({ ...current, [id]: "" }));
    onUpdateParkingSpec(id, {
      capacity: Number(value.trim()),
      capacitySource: "manual",
      capacityMethod: null,
    });
  }

  function parkingRows(features: CampusFeature[], selected: boolean) {
    return (
      <div className="divide-y">
        {features.map((feature) => {
          const id = getFeatureId(feature);
          const spec = parkingSpecs[id];
          const isExpanded = expandedParkingSpecId === id;
          const accessValue = spec?.access || UNKNOWN_SELECT_VALUE;
          const capacityValue = capacityDrafts[id] ?? "";
          const error = capacityErrors[id];
          const capacityBucket = capacityBucketForSpec(spec);
          const osmCapacity = getOsmCapacity(feature);
          const capacityChanged = isCapacityChangedFromOriginal(spec);
          const hasCapacity = Boolean(spec?.capacity);
          const assignedTypeId = activeParkingClassification?.assignments?.[id] ?? PARKING_TYPE_UNKNOWN;

          return (
            <article
              className={cn(
                "border-l-2",
                selected
                  ? "border-l-primary/60 bg-background"
                  : "border-l-amber-400/70 bg-amber-50/40 dark:bg-amber-950/10",
                isExpanded && (selected ? "bg-primary/[0.04]" : "bg-amber-50/80 dark:bg-amber-950/20"),
              )}
              key={id}
            >
              <Button
                type="button"
                variant="ghost"
                className="h-auto w-full justify-start rounded-none px-3 py-2 text-left text-sm font-normal hover:bg-muted/60"
                onClick={() => toggleExpanded(id)}
                aria-expanded={isExpanded}
              >
                <span className="grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
                  <span className="mt-0.5 text-muted-foreground" aria-hidden="true">
                    {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  </span>
                  <span className="min-w-0">
                    <strong className="block truncate text-[0.8rem] leading-4 text-foreground">{getParkingDisplayName(feature)}</strong>
                    <small className="block truncate text-[0.67rem] leading-4 text-muted-foreground">{getParkingDescription(feature)}</small>
                  </span>
                </span>
                {!selected && (
                  <Badge
                    variant="outline"
                    className="shrink-0 border-amber-300 bg-amber-100/80 px-1.5 py-0 text-[0.58rem] font-semibold text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
                  >
                    Not selected
                  </Badge>
                )}
              </Button>

              {isExpanded && (
                <div className="ml-6 space-y-2 px-3 pb-3 pt-0.5">
                  {activeParkingClassification && selected && (
                    <div className="grid grid-cols-[68px_minmax(0,1fr)] items-start gap-2">
                      <Label className="pt-2 text-[0.7rem] text-muted-foreground">Type</Label>
                      <Select
                        value={assignedTypeId}
                        disabled={busy || !activeParkingClassification.types.length}
                        onValueChange={(value) => onAssignType(activeParkingClassification.id, id, value)}
                      >
                        <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Unknown / unspecified" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value={PARKING_TYPE_UNKNOWN}>Unknown / unspecified</SelectItem>
                          {activeParkingClassification.types.map((type) => <SelectItem key={type.id} value={type.id}>{type.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <div className="grid grid-cols-[68px_minmax(0,1fr)] items-start gap-2">
                    <Label htmlFor={`access-${id}`} className="pt-2 text-[0.7rem] text-muted-foreground">Access</Label>
                    <div className="min-w-0 space-y-0.5">
                      <Select
                        value={accessValue}
                        disabled={busy}
                        onValueChange={(value) =>
                          onUpdateParkingSpec(id, {
                            access: value === UNKNOWN_SELECT_VALUE ? null : value,
                            accessSource: "manual",
                          })
                        }
                      >
                        <SelectTrigger id={`access-${id}`} className="h-8 text-xs">
                          <SelectValue placeholder="Unknown / unspecified" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={UNKNOWN_SELECT_VALUE}>Unknown / unspecified</SelectItem>
                          {accessSelectOptions.map((option) => (
                            <SelectItem key={option} value={option}>{option}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className="truncate text-[0.62rem] leading-4 text-muted-foreground">Source: {sourceLabel(spec?.accessSource)}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-[68px_minmax(0,1fr)] items-start gap-2">
                    <Label htmlFor={`capacity-${id}`} className="pt-2 text-[0.7rem] text-muted-foreground">Capacity</Label>
                    <div className="min-w-0 space-y-0.5">
                      <Input
                        id={`capacity-${id}`}
                        type="number"
                        min="1"
                        step="1"
                        inputMode="numeric"
                        value={capacityValue}
                        placeholder={osmCapacity ? String(osmCapacity) : "Unknown"}
                        disabled={busy}
                        onChange={(event) => handleCapacityDraftChange(id, event.target.value)}
                        className="h-8 text-xs"
                      />
                      <p className="truncate text-[0.62rem] leading-4 text-muted-foreground">
                        Source: {sourceLabel(spec?.capacitySource)} · {capacityBucket === CAPACITY_UNKNOWN ? "Unknown" : capacityBucket}
                      </p>
                    </div>
                  </div>

                  {spec?.capacityMethod?.total_inside_length_m && (
                    <p className="pl-[76px] text-[0.62rem] leading-4 text-muted-foreground">
                      Estimated from {spec.capacityMethod.total_inside_length_m} m of related ways.
                    </p>
                  )}
                  {error && <p className="rounded-md border border-red-200 bg-red-50 p-1.5 text-[0.68rem] text-red-700">{error}</p>}

                  <div className="grid grid-cols-2 gap-1.5 pl-[76px]">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-[0.68rem]"
                      disabled={busy || hasCapacity}
                      onClick={() => onEstimateParkingCapacity(id)}
                    >
                      {estimatingCapacity ? "Calculating…" : "Fill unknown"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-[0.68rem]"
                      disabled={busy || !capacityChanged}
                      onClick={() => onRevertParkingCapacity(id)}
                    >
                      Revert capacity
                    </Button>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    );
  }

  return (
    <>
      <header className="mb-4 space-y-2">
        <Button type="button" variant="ghost" size="sm" className="-ml-2" disabled={busy} onClick={onBack}>
          ← Back
        </Button>
        <p className="text-xs font-bold uppercase tracking-[0.1em] text-muted-foreground">Parking configuration</p>
        <h1 className="text-2xl font-semibold tracking-tight">Edit Parking Specs</h1>
        <p className="text-sm leading-6 text-muted-foreground">
          Filter parking areas by access and capacity, then expand a parking item to edit its
          saved simulation configuration.
        </p>
      </header>

      {parkingSpecMessage && (
        <p className="mb-3 rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300">
          {parkingSpecMessage}
        </p>
      )}

      <ParkingClassificationManager
        classifications={parkingClassifications}
        activeClassificationId={activeParkingClassification?.id ?? null}
        busy={busy}
        onAddClassification={onAddClassification}
        onSelectClassification={onSelectClassification}
        onRenameClassification={onRenameClassification}
        onDeleteClassification={onDeleteClassification}
        onAddType={onAddType}
      />

      <Card className="mb-3.5 shadow-sm">
        <CardHeader className="p-4 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm">Highlight filters</CardTitle>
              <CardDescription className="mt-1 text-xs">
                Checked filters highlight matching parking areas in green on the map. They do not
                change whether a parking area is selected for export.
              </CardDescription>
            </div>
            <Badge variant={highlightedCount ? "default" : "secondary"}>{highlightedCount ? "Active" : "None"}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 p-4 pt-0">
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Access</h3>
            <div className="space-y-1.5">
              {accessOptions.map((option) => (
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/70" key={option.id}>
                  <Checkbox
                    checked={activeAccessFilters.has(option.id)}
                    disabled={!option.count}
                    onCheckedChange={() => onAccessFilterToggle(option.id)}
                  />
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  <Badge variant="outline" className="text-[0.65rem]">{option.count}</Badge>
                </label>
              ))}
            </div>
          </div>

          <Separator />

          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Capacity</h3>
            <div className="space-y-1.5">
              {capacityOptions.map((option) => (
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/70" key={option.id}>
                  <Checkbox
                    checked={activeCapacityFilters.has(option.id)}
                    disabled={!option.count}
                    onCheckedChange={() => onCapacityFilterToggle(option.id)}
                  />
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  <Badge variant="outline" className="text-[0.65rem]">{option.count}</Badge>
                </label>
              ))}
            </div>
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            disabled={!activeAccessFilters.size && !activeCapacityFilters.size}
            onClick={onClearFilters}
          >
            Clear highlight filters
          </Button>
        </CardContent>
      </Card>

      <Card className="mb-3.5 shadow-sm">
        <CardHeader className="p-4 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm">Capacity estimation</CardTitle>
              <CardDescription className="mt-1 text-xs">
                Estimate unknown capacities from related OSM parking-aisle/service-way length using
                one slot every 2.3 metres.
              </CardDescription>
            </div>
            <Badge variant="secondary" className="bg-red-50 text-red-700">{unknownCapacityCount} unknown</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            disabled={busy || !unknownCapacityCount || !parkingAreas.features.length}
            onClick={onEstimateAllUnknownCapacities}
          >
            {estimatingCapacity ? "Calculating capacities…" : "Fill all unknown capacities"}
          </Button>
        </CardContent>
      </Card>

      <Card className="mb-3.5 shadow-sm">
        <CardHeader className="p-4 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm">Parking areas</CardTitle>
              <CardDescription className="mt-1 text-xs">
                Click a parking row to edit access and capacity. Capacity must be a whole number greater
                than 0 when specified.
              </CardDescription>
            </div>
            <Badge variant="secondary" className="bg-red-50 text-red-700">{parkingAreas.features.length}</Badge>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea
            className="h-[clamp(260px,48vh,520px)] overscroll-contain"
            onWheelCapture={(event) => event.stopPropagation()}
          >
            {parkingAreas.features.length ? (
              <div className="divide-y">
                <Collapsible open={selectedListOpen} onOpenChange={setSelectedListOpen}>
                  <CollapsibleTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      className="group h-10 w-full justify-between rounded-none bg-primary/[0.06] px-3 hover:bg-primary/10"
                    >
                      <span className="flex min-w-0 items-center gap-2 text-xs font-semibold">
                        <span className="size-2 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                        Selected
                        <Badge variant="secondary" className="h-5 px-1.5 text-[0.62rem]">{selectedParkingAreas.length}</Badge>
                      </span>
                      <ChevronDown className="size-4 transition-transform group-data-[state=closed]:-rotate-90" />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    {selectedParkingAreas.length ? parkingRows(selectedParkingAreas, true) : (
                      <p className="border-l-2 border-l-primary/60 p-4 text-center text-xs text-muted-foreground">No parking areas are selected.</p>
                    )}
                  </CollapsibleContent>
                </Collapsible>

                <Collapsible open={unselectedListOpen} onOpenChange={setUnselectedListOpen}>
                  <CollapsibleTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      className="group h-10 w-full justify-between rounded-none bg-amber-50 px-3 text-amber-900 hover:bg-amber-100 dark:bg-amber-950/30 dark:text-amber-100 dark:hover:bg-amber-950/50"
                    >
                      <span className="flex min-w-0 items-center gap-2 text-xs font-semibold">
                        <span className="size-2 shrink-0 rounded-full bg-amber-500" aria-hidden="true" />
                        Not selected
                        <Badge variant="outline" className="h-5 border-amber-300 bg-amber-100/80 px-1.5 text-[0.62rem] text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                          {unselectedParkingAreas.length}
                        </Badge>
                      </span>
                      <ChevronDown className="size-4 transition-transform group-data-[state=closed]:-rotate-90" />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    {unselectedParkingAreas.length ? parkingRows(unselectedParkingAreas, false) : (
                      <p className="border-l-2 border-l-amber-400/70 bg-amber-50/30 p-4 text-center text-xs text-muted-foreground dark:bg-amber-950/10">Every parking area is selected.</p>
                    )}
                  </CollapsibleContent>
                </Collapsible>
              </div>
            ) : (
              <p className="p-5 text-center text-xs text-muted-foreground">No parking areas loaded yet.</p>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

    </>
  );
}
