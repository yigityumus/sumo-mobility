import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Label } from "./ui/label";
import { ScrollArea } from "./ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Separator } from "./ui/separator";
import { cn } from "../lib/utils";
import type { BuildingClassification, CampusFeatureCollection } from "../types/campus";
import {
  BUILDING_TYPE_UNKNOWN,
  MAX_BUILDING_CLASSIFICATIONS,
  MAX_BUILDING_TYPES_PER_CLASSIFICATION,
} from "../utils/buildingSpecs.ts";
import { buildingTypeColor } from "../utils/buildingTypeColors.ts";
import {
  getBuildingDescription,
  getBuildingDisplayName,
  getBuildingSearchText,
  getFeatureId,
} from "../utils/osmFeatures.ts";

type BuildingSpecsPanelProps = {
  buildings: CampusFeatureCollection;
  buildingClassifications: BuildingClassification[];
  activeBuildingClassificationId: string | null;
  selectedBuildingIds?: Set<string>;
  busy: boolean;
  buildingSpecMessage: string;
  onBack: () => void;
  onAddClassification: (payload: { name: string; types: string[] }) => void;
  onSelectClassification: (classificationId: string) => void;
  onRenameClassification: (classificationId: string, name: string) => void;
  onDeleteClassification: (classificationId: string) => void;
  onAddType: (classificationId: string, name: string) => void;
  onRenameType: (classificationId: string, typeId: string, name: string) => void;
  onDeleteType: (classificationId: string, typeId: string) => void;
  onAssignBuildingType: (classificationId: string, buildingId: string, typeId: string) => void;
};

function nextClassificationName(classifications: BuildingClassification[]) {
  const used = new Set((classifications ?? []).map((classification) => classification.name));
  for (let index = 1; index <= MAX_BUILDING_CLASSIFICATIONS + 1; index += 1) {
    const candidate = `Classification ${index}`;
    if (!used.has(candidate)) return candidate;
  }
  return `Classification ${(classifications ?? []).length + 1}`;
}

export default function BuildingSpecsPanel({
  buildings,
  buildingClassifications,
  activeBuildingClassificationId,
  selectedBuildingIds = new Set<string>(),
  busy,
  buildingSpecMessage,
  onBack,
  onAddClassification,
  onSelectClassification,
  onDeleteClassification,
  onAddType,
  onAssignBuildingType,
}: BuildingSpecsPanelProps) {
  const [buildingSearch, setBuildingSearch] = useState("");
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [draftClassificationName, setDraftClassificationName] = useState("");
  const [draftTypes, setDraftTypes] = useState<string[]>([""]);
  const [createTypeClassificationId, setCreateTypeClassificationId] = useState<string | null>(null);
  const [draftTypeName, setDraftTypeName] = useState("");
  const [expandedClassificationIds, setExpandedClassificationIds] = useState<Set<string>>(new Set());
  const [classificationPendingDeletion, setClassificationPendingDeletion] = useState<BuildingClassification | null>(null);

  const activeClassification = useMemo(
    () =>
      (buildingClassifications ?? []).find(
        (classification) => classification.id === activeBuildingClassificationId,
      ) ?? buildingClassifications?.[0] ?? null,
    [activeBuildingClassificationId, buildingClassifications],
  );

  const selectedBuildingIdSet = selectedBuildingIds ?? new Set<string>();

  const selectedBuildings = useMemo(() => {
    const selectedFeatures = (buildings.features ?? []).filter((feature) =>
      selectedBuildingIdSet.has(getFeatureId(feature)),
    );

    const normalizedSearch = buildingSearch.trim().toLocaleLowerCase();
    if (!normalizedSearch) {
      return selectedFeatures;
    }

    return selectedFeatures.filter((feature) => getBuildingSearchText(feature).includes(normalizedSearch));
  }, [buildings, buildingSearch, selectedBuildingIdSet]);

  const assignedCount = useMemo(() => {
    if (!activeClassification) {
      return 0;
    }

    return selectedBuildings.reduce((count, feature) => {
      const buildingId = getFeatureId(feature);
      const assignedTypeId = activeClassification.assignments?.[buildingId];
      return assignedTypeId && assignedTypeId !== BUILDING_TYPE_UNKNOWN ? count + 1 : count;
    }, 0);
  }, [activeClassification, selectedBuildings]);

  const unknownCount = Math.max(selectedBuildings.length - assignedCount, 0);
  const typeOptions = activeClassification?.types ?? [];

  const openCreateDialog = () => {
    setDraftClassificationName(nextClassificationName(buildingClassifications ?? []));
    setDraftTypes([""]);
    setCreateDialogOpen(true);
  };

  const openCreateTypeDialog = (classificationId: string) => {
    setCreateTypeClassificationId(classificationId);
    setDraftTypeName("");
  };

  const createType = () => {
    const name = draftTypeName.trim();
    if (!createTypeClassificationId || !name) return;
    onAddType(createTypeClassificationId, name);
    setCreateTypeClassificationId(null);
    setDraftTypeName("");
  };

  const createClassification = () => {
    onAddClassification({
      name: draftClassificationName,
      types: draftTypes.map((typeName) => typeName.trim()).filter(Boolean),
    });
    setCreateDialogOpen(false);
  };

  const toggleExpanded = (classificationId: string) => {
    setExpandedClassificationIds((current) => {
      const next = new Set(current);
      if (next.has(classificationId)) next.delete(classificationId);
      else next.add(classificationId);
      return next;
    });
  };

  return (
    <>
      <header className="mb-4 space-y-2">
        <Button type="button" variant="ghost" size="sm" className="-ml-2" disabled={busy} onClick={onBack}>
          ← Back
        </Button>
        <p className="text-xs font-bold uppercase tracking-[0.1em] text-muted-foreground">Building configuration</p>
        <h1 className="text-2xl font-semibold tracking-tight">Edit Building Specs</h1>
      </header>

      {buildingSpecMessage && (
        <p className="mb-3 rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300">
          {buildingSpecMessage}
        </p>
      )}

      <section className="mb-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Classifications</h2>
            <p className="text-xs text-muted-foreground">Optional type systems for destination capacity and pedestrian/vehicle weighting. Classification and type names are entirely up to you.</p>
          </div>
          <Badge variant="secondary" className="shrink-0 whitespace-nowrap bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
            {(buildingClassifications ?? []).length} / {MAX_BUILDING_CLASSIFICATIONS}
          </Badge>
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-full"
          disabled={busy || (buildingClassifications ?? []).length >= MAX_BUILDING_CLASSIFICATIONS}
          onClick={openCreateDialog}
        >
          <Plus className="size-4" />
          Create classification
        </Button>

        <div className="overflow-hidden rounded-lg border bg-background">
          {(buildingClassifications ?? []).map((classification) => {
            const isActive = classification.id === activeClassification?.id;
            const isExpanded = expandedClassificationIds.has(classification.id);

            return (
              <div className="border-b last:border-b-0" key={classification.id}>
                <div
                  className={cn(
                    "grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-1 px-1 py-1 transition-colors hover:bg-muted/70",
                    isActive && "bg-muted/80",
                  )}
                >
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-auto min-w-0 justify-start px-2 py-2 text-left font-normal"
                    disabled={busy}
                    onClick={() => onSelectClassification(classification.id)}
                  >
                    <span className="min-w-0">
                      <strong className="block truncate text-sm font-medium">{classification.name}</strong>
                      <small className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {(classification.types ?? []).length} type
                        {(classification.types ?? []).length === 1 ? "" : "s"} · {Object.keys(classification.assignments ?? {}).length} assigned
                      </small>
                    </span>
                  </Button>

                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    disabled={busy || (classification.types ?? []).length >= MAX_BUILDING_TYPES_PER_CLASSIFICATION}
                    onClick={() => openCreateTypeDialog(classification.id)}
                    title="Add type"
                    aria-label={`Add type to ${classification.name}`}
                  >
                    <Plus className="size-4" />
                  </Button>

                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    disabled={busy}
                    onClick={() => toggleExpanded(classification.id)}
                    aria-label={`${isExpanded ? "Collapse" : "Expand"} ${classification.name}`}
                  >
                    {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  </Button>

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        disabled={busy}
                        aria-label={`Actions for ${classification.name}`}
                      >
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onSelect={() => setClassificationPendingDeletion(classification)}
                      >
                        <Trash2 className="mr-2 size-4" />
                        Delete classification
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                {isExpanded && (
                  <div className="pb-1 pl-8 pr-2">
                    {(classification.types ?? []).map((type, index) => {
                      const assignedToTypeCount = Object.values(classification.assignments ?? {}).filter(
                        (assignedTypeId) => assignedTypeId === type.id,
                      ).length;
                      const color = buildingTypeColor(index);

                      return (
                        <div className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted/60" key={type.id}>
                          <span className="size-2.5 shrink-0 rounded-[3px] border" style={{ backgroundColor: color, borderColor: color }} />
                          <span className="min-w-0 flex-1 truncate">{type.name}</span>
                          <span className="shrink-0 tabular-nums">{assignedToTypeCount}</span>
                        </div>
                      );
                    })}
                    {!(classification.types ?? []).length && (
                      <p className="px-2 py-1.5 text-xs text-muted-foreground">No types yet.</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {!(buildingClassifications ?? []).length && (
            <p className="p-3 text-xs text-muted-foreground">No classifications yet. Create one to start labeling buildings.</p>
          )}
        </div>
      </section>

      {activeClassification && (
        <section className="mb-4 space-y-3">
          <Separator />
          <div className="flex flex-col gap-2">
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold">Buildings in {activeClassification.name}</h2>
              <p className="text-xs text-muted-foreground">Assign one type per building when needed. Unassigned buildings remain valid destinations with a capacity constant of 1 and a neutral 50/50 mode split.</p>
            </div>
            <Badge variant="secondary" className="w-fit shrink-0 whitespace-nowrap bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
              {assignedCount} assigned · {unknownCount} unknown
            </Badge>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="building-spec-search" className="text-xs text-muted-foreground">Search buildings</Label>
            <Input
              id="building-spec-search"
              type="search"
              placeholder="e.g. M1, teaching, way/…"
              value={buildingSearch}
              disabled={!buildings.features.length}
              onChange={(event) => setBuildingSearch(event.target.value)}
            />
          </div>

          <ScrollArea className="h-[420px] rounded-lg border bg-muted/20" onWheelCapture={(event) => event.stopPropagation()}>
            <div className="divide-y">
              {selectedBuildings.map((feature) => {
                const buildingId = getFeatureId(feature);
                const assignedTypeId = activeClassification.assignments?.[buildingId] ?? BUILDING_TYPE_UNKNOWN;
                const isUnknown = assignedTypeId === BUILDING_TYPE_UNKNOWN;

                return (
                  <article className={cn("grid gap-2 p-2.5 text-sm", !isUnknown && "bg-primary/10")} key={buildingId}>
                    <span className="min-w-0">
                      <strong className="block truncate text-foreground">{getBuildingDisplayName(feature)}</strong>
                      <small className="mt-0.5 block truncate text-xs text-muted-foreground">{getBuildingDescription(feature)}</small>
                    </span>
                    <Select
                      value={assignedTypeId}
                      disabled={busy || !typeOptions.length}
                      onValueChange={(value) => onAssignBuildingType(activeClassification.id, buildingId, value)}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Unknown / unspecified" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={BUILDING_TYPE_UNKNOWN}>Unknown / unspecified</SelectItem>
                        {typeOptions.map((type) => (
                          <SelectItem key={type.id} value={type.id}>{type.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </article>
                );
              })}

              {selectedBuildingIdSet.size > 0 && !selectedBuildings.length && (
                <p className="p-5 text-center text-xs text-muted-foreground">No selected buildings match this search.</p>
              )}

              {selectedBuildingIdSet.size === 0 && (
                <p className="p-5 text-center text-xs text-muted-foreground">Select buildings on the map to manage their types here.</p>
              )}
            </div>
          </ScrollArea>
        </section>
      )}

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create classification</DialogTitle>
            <DialogDescription>
              Add any classification name and optional starter types. No particular type name is required, and buildings may remain unassigned.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="new-classification-name">Classification name</Label>
              <Input
                id="new-classification-name"
                value={draftClassificationName}
                onChange={(event) => setDraftClassificationName(event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label>Types</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="group gap-2"
                  disabled={draftTypes.length >= MAX_BUILDING_TYPES_PER_CLASSIFICATION}
                  onClick={() => setDraftTypes((current) => [...current, ""])}
                  title="Add type"
                >
                  <Plus className="size-4" />
                  <span className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">Add type</span>
                </Button>
              </div>
              <div className="space-y-2">
                {draftTypes.map((typeName, index) => (
                  <Input
                    key={index}
                    value={typeName}
                    placeholder={`Type ${index + 1}`}
                    aria-label={`Type ${index + 1}`}
                    onChange={(event) => {
                      const value = event.target.value;
                      setDraftTypes((current) => current.map((item, itemIndex) => itemIndex === index ? value : item));
                    }}
                  />
                ))}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
            <Button type="button" onClick={createClassification}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={createTypeClassificationId !== null} onOpenChange={(open) => {
        if (!open) setCreateTypeClassificationId(null);
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create building type</DialogTitle>
            <DialogDescription>Enter a descriptive name for the new type.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="new-building-type-name">Type name</Label>
            <Input
              id="new-building-type-name"
              autoFocus
              value={draftTypeName}
              placeholder={`Type ${((buildingClassifications ?? []).find((item) => item.id === createTypeClassificationId)?.types ?? []).length + 1}`}
              onChange={(event) => setDraftTypeName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  createType();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateTypeClassificationId(null)}>Cancel</Button>
            <Button type="button" disabled={!draftTypeName.trim()} onClick={createType}>Create type</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={classificationPendingDeletion !== null}
        onOpenChange={(open) => {
          if (!open) setClassificationPendingDeletion(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete classification?</DialogTitle>
            <DialogDescription>
              {classificationPendingDeletion
                ? `“${classificationPendingDeletion.name}” and its building assignments will be removed. This cannot be undone after you save the model.`
                : "This classification will be removed."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setClassificationPendingDeletion(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                if (classificationPendingDeletion) {
                  onDeleteClassification(classificationPendingDeletion.id);
                }
                setClassificationPendingDeletion(null);
              }}
            >
              Delete classification
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
