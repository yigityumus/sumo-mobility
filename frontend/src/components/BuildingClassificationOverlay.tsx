import { useEffect, useState } from "react";
import { Check, Ellipsis, Plus, X } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import type { BuildingClassification, CampusFeatureCollection, ParkingClassification } from "../types/campus";
import { buildingTypeColor } from "../utils/buildingTypeColors.ts";

type BuildingClassificationOverlayProps = {
  classification: BuildingClassification | ParkingClassification;
  buildings?: CampusFeatureCollection;
  features?: CampusFeatureCollection;
  subjectPlural?: string;
  busy: boolean;
  onAddType: (classificationId: string, name: string) => void;
  onRenameType: (classificationId: string, typeId: string, name: string) => void;
  onDeleteType: (classificationId: string, typeId: string) => void;
};

export default function BuildingClassificationOverlay({
  classification,
  buildings,
  features,
  subjectPlural = "buildings",
  busy,
  onAddType,
  onRenameType,
  onDeleteType,
}: BuildingClassificationOverlayProps) {
  const [draftTypeName, setDraftTypeName] = useState<string | null>(null);
  const assignedCount = Object.keys(classification.assignments ?? {}).length;
  const featureCount = (features ?? buildings)?.features?.length ?? 0;
  const suggestedTypeName = `Type ${(classification.types ?? []).length + 1}`;

  useEffect(() => setDraftTypeName(null), [classification.id]);

  const createType = () => {
    const name = draftTypeName?.trim() ?? "";
    if (!name) return;
    onAddType(classification.id, name);
    setDraftTypeName(null);
  };

  return (
    <Card className="flex h-[420px] w-full max-w-[380px] flex-col bg-card/95 shadow-lg backdrop-blur-sm">
      <CardHeader className="shrink-0 p-4 pb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.1em] text-muted-foreground">Classification</p>
            <CardTitle className="mt-1 truncate text-lg">{classification.name}</CardTitle>
          </div>
          <Badge variant="secondary" className="shrink-0 whitespace-nowrap">
            {assignedCount} / {featureCount}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-2 overflow-y-auto p-4 pt-2">
        <div className="space-y-1">
          {(classification.types ?? []).map((type, index) => {
            const assignedToTypeCount = Object.values(classification.assignments ?? {}).filter(
              (assignedTypeId) => assignedTypeId === type.id,
            ).length;
            const color = buildingTypeColor(index);

            return (
              <div
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground"
                key={type.id}
              >
                <span
                  className="size-3 shrink-0 rounded-[4px] border"
                  style={{ backgroundColor: color, borderColor: color }}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate">{type.name}</span>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {assignedToTypeCount}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="ghost" size="icon" className="size-7 cursor-pointer">
                      <Ellipsis className="size-4" />
                      <span className="sr-only">Type actions</span>
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onSelect={() => {
                        const nextName = window.prompt("Rename type", type.name);
                        if (nextName !== null) onRenameType(classification.id, type.id, nextName);
                      }}
                    >
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onSelect={() => {
                        if (window.confirm(`Delete type “${type.name}”? Assigned ${subjectPlural} become Unknown / unspecified.`)) {
                          onDeleteType(classification.id, type.id);
                        }
                      }}
                    >
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            );
          })}
        </div>

        {!(classification.types ?? []).length && (
          <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
            No types yet. Add one to start coloring {subjectPlural} by this classification.
          </p>
        )}

        {draftTypeName !== null && (
          <div className="flex items-center gap-1.5 px-2 py-1">
            <Input
              autoFocus
              value={draftTypeName}
              placeholder={suggestedTypeName}
              aria-label="New building type name"
              className="h-8"
              onChange={(event) => setDraftTypeName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  createType();
                } else if (event.key === "Escape") {
                  setDraftTypeName(null);
                }
              }}
            />
            <Button type="button" variant="ghost" size="icon" className="size-8" disabled={!draftTypeName.trim()} onClick={createType} aria-label="Create type">
              <Check className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" className="size-8" onClick={() => setDraftTypeName(null)} aria-label="Cancel type creation">
              <X className="size-4" />
            </Button>
          </div>
        )}

        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="group h-auto w-full justify-start gap-2 px-2 py-1.5 text-muted-foreground hover:text-foreground"
          disabled={busy || draftTypeName !== null || (classification.types ?? []).length >= 10}
          onClick={() => setDraftTypeName("")}
          title="Add Type"
        >
          <Plus className="size-4" />
          <span className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            Add Type
          </span>
        </Button>
      </CardContent>
    </Card>
  );
}
