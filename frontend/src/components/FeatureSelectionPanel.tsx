import { CheckCircle2, CircleHelp } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { ScrollArea } from "./ui/scroll-area";
import { cn } from "../lib/utils";
import type { CampusFeature, CampusFeatureCollection } from "../types/campus";

type FeatureSelectionPanelProps = {
  title: string;
  kind: "building" | "parking";
  features: CampusFeatureCollection;
  filteredFeatures: CampusFeature[];
  selectedIds: Set<string>;
  search: string;
  searchPlaceholder: string;
  getFeatureId: (feature: CampusFeature) => string;
  getDisplayName: (feature: CampusFeature) => string;
  getDescription: (feature: CampusFeature) => string;
  onSearchChange: (value: string) => void;
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onSelectFiltered: () => void;
  onDeselectFiltered: () => void;
  unnamedCount?: number;
  selectedUnnamedCount?: number;
  onDeselectUnnamed?: () => void;
  onSelectUnnamed?: () => void;
  onShowHelp?: () => void;
};

export default function FeatureSelectionPanel({
  title,
  kind,
  features,
  filteredFeatures,
  selectedIds,
  search,
  searchPlaceholder,
  getFeatureId,
  getDisplayName,
  getDescription,
  onSearchChange,
  onToggle,
  onSelectAll,
  onDeselectAll,
  onSelectFiltered,
  onDeselectFiltered,
  unnamedCount = 0,
  selectedUnnamedCount = 0,
  onDeselectUnnamed,
  onSelectUnnamed,
  onShowHelp,
}: FeatureSelectionPanelProps) {
  const featureCount = features.features.length;

  return (
    <Card className="mb-3.5 shadow-sm">
      <CardHeader className="space-y-2 p-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-sm">{title}</CardTitle>
            <CardDescription className="mt-1 text-xs">
              {kind === "building"
                ? "Selected buildings become simulation destinations and can receive demand settings."
                : "Selected parking areas are the facilities included in the model and simulation."}
            </CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {onShowHelp && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                onClick={onShowHelp}
                aria-label={`Why select ${kind === "building" ? "buildings" : "parking areas"}?`}
                title="Why select or deselect these?"
              >
                <CircleHelp className="size-4" />
              </Button>
            )}
            <Badge
              variant="secondary"
              className={cn(
                "shrink-0",
                kind === "building" && "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300",
                kind === "parking" && "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300",
              )}
            >
              {selectedIds.size} / {featureCount}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-0">
        <div className="space-y-1.5">
          <Label htmlFor={`${kind}-search`} className="text-xs text-muted-foreground">
            Search by name, tags or OSM ID
          </Label>
          <Input
            id={`${kind}-search`}
            type="search"
            placeholder={searchPlaceholder}
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            disabled={!featureCount}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onSelectAll} disabled={!featureCount}>
            Select all
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onDeselectAll} disabled={!featureCount}>
            Deselect all
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onSelectFiltered} disabled={!filteredFeatures.length}>
            Select filtered
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onDeselectFiltered} disabled={!filteredFeatures.length}>
            Deselect filtered
          </Button>
          {onDeselectUnnamed && (
            <Button
              type="button"
              variant={unnamedCount > 0 && selectedUnnamedCount === 0 ? "secondary" : "outline"}
              size="sm"
              className="col-span-2 gap-2"
              onClick={selectedUnnamedCount > 0 ? onDeselectUnnamed : onSelectUnnamed}
              disabled={!unnamedCount || (selectedUnnamedCount === 0 && !onSelectUnnamed)}
              title={
                !unnamedCount
                  ? "No unnamed items loaded"
                  : selectedUnnamedCount
                    ? `Deselect ${selectedUnnamedCount} selected unnamed item${selectedUnnamedCount === 1 ? "" : "s"}`
                    : `All unnamed items are deselected. Select all ${unnamedCount} again.`
              }
            >
              {unnamedCount > 0 && selectedUnnamedCount === 0 && <CheckCircle2 className="size-4" />}
              {!unnamedCount
                ? "No unnamed items"
                : selectedUnnamedCount
                  ? `Deselect unnamed (${selectedUnnamedCount})`
                  : `Unnamed deselected · Select again (${unnamedCount})`}
            </Button>
          )}
        </div>

        {onDeselectUnnamed && unnamedCount > 0 && (
          <p className="rounded-lg border bg-muted/30 p-2.5 text-xs leading-5 text-muted-foreground">
            <strong className="text-foreground">Why unnamed?</strong> OSM includes useful shapes that have no name tag,
            but many are minor or incomplete entries. “Deselect unnamed” is a quick cleanup; review the shapes on the
            map first because some may still belong in your model. You can select all unnamed items again at any time.
          </p>
        )}

        <ScrollArea className="h-[330px] rounded-lg border bg-muted/25" onWheelCapture={(event) => event.stopPropagation()}>
          <div className="divide-y">
            {filteredFeatures.map((feature) => {
              const id = getFeatureId(feature);
              const isSelected = selectedIds.has(id);

              return (
                <label
                  className={cn(
                    "grid cursor-pointer grid-cols-[auto_auto_minmax(0,1fr)_auto] items-start gap-2.5 p-2.5 text-sm transition-colors",
                    isSelected ? "bg-primary/10 hover:bg-primary/20" : "bg-background text-muted-foreground hover:bg-muted/70",
                  )}
                  key={id}
                >
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => onToggle(id)}
                    aria-label={`${isSelected ? "Deselect" : "Select"} ${getDisplayName(feature)}`}
                    className="mt-0.5"
                  />
                  <span
                    className={cn(
                      "mt-1 block h-3 w-3 rounded-[4px] border",
                      kind === "building" && "border-blue-700 bg-blue-500",
                      kind === "parking" && "border-red-700 bg-red-500",
                    )}
                    aria-hidden="true"
                  />
                  <span className="min-w-0">
                    <strong className="block truncate text-[0.83rem] text-foreground">
                      {getDisplayName(feature)}
                    </strong>
                    <small className="mt-0.5 block truncate text-[0.7rem] text-muted-foreground">
                      {getDescription(feature)}
                    </small>
                  </span>
                  <Badge variant={isSelected ? "default" : "outline"} className="shrink-0 text-[0.65rem]">
                    {isSelected ? "Selected" : "Unselected"}
                  </Badge>
                </label>
              );
            })}

            {Boolean(featureCount) && !filteredFeatures.length && (
              <p className="p-5 text-center text-xs text-muted-foreground">No items match this filter.</p>
            )}

            {!featureCount && (
              <p className="p-5 text-center text-xs text-muted-foreground">No data loaded yet.</p>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
