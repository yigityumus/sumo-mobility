import { useState } from "react";
import { ChevronDown, ChevronRight, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import type { ParkingClassification } from "../types/campus.ts";
import { buildingTypeColor } from "../utils/buildingTypeColors.ts";
import {
  MAX_PARKING_CLASSIFICATIONS,
  MAX_PARKING_TYPES_PER_CLASSIFICATION,
} from "../utils/parkingClassifications.ts";
import { cn } from "../lib/utils.ts";
import { Badge } from "./ui/badge.tsx";
import { Button } from "./ui/button.tsx";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu.tsx";
import { Input } from "./ui/input.tsx";
import { Label } from "./ui/label.tsx";

type Props = {
  classifications: ParkingClassification[];
  activeClassificationId: string | null;
  busy: boolean;
  onAddClassification: (payload: { name: string; types: string[] }) => void;
  onSelectClassification: (classificationId: string) => void;
  onRenameClassification: (classificationId: string, name: string) => void;
  onDeleteClassification: (classificationId: string) => void;
  onAddType: (classificationId: string, name: string) => void;
};

function nextClassificationName(classifications: ParkingClassification[]) {
  const used = new Set((classifications ?? []).map((classification) => classification.name));
  for (let index = 1; index <= MAX_PARKING_CLASSIFICATIONS + 1; index += 1) {
    const candidate = `Classification ${index}`;
    if (!used.has(candidate)) return candidate;
  }
  return `Classification ${(classifications ?? []).length + 1}`;
}

export default function ParkingClassificationManager({
  classifications,
  activeClassificationId,
  busy,
  onAddClassification,
  onSelectClassification,
  onRenameClassification,
  onDeleteClassification,
  onAddType,
}: Props) {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [draftClassificationName, setDraftClassificationName] = useState("");
  const [draftTypes, setDraftTypes] = useState<string[]>([""]);
  const [createTypeClassificationId, setCreateTypeClassificationId] = useState<string | null>(null);
  const [draftTypeName, setDraftTypeName] = useState("");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [pendingDeletion, setPendingDeletion] = useState<ParkingClassification | null>(null);

  const activeClassification = (classifications ?? []).find(
    (classification) => classification.id === activeClassificationId,
  ) ?? classifications?.[0] ?? null;

  const toggleExpanded = (classificationId: string) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(classificationId)) next.delete(classificationId);
      else next.add(classificationId);
      return next;
    });
  };

  const openCreateDialog = () => {
    setDraftClassificationName(nextClassificationName(classifications ?? []));
    setDraftTypes([""]);
    setCreateDialogOpen(true);
  };

  const createType = () => {
    const name = draftTypeName.trim();
    if (!createTypeClassificationId || !name) return;
    onAddType(createTypeClassificationId, name);
    setCreateTypeClassificationId(null);
    setDraftTypeName("");
  };

  return (
    <>
      <section className="mb-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Classifications</h2>
            <p className="text-xs text-muted-foreground">Independent labeling systems for the same parking-area set.</p>
          </div>
          <Badge variant="secondary" className="shrink-0 whitespace-nowrap bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
            {(classifications ?? []).length} / {MAX_PARKING_CLASSIFICATIONS}
          </Badge>
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-full"
          disabled={busy || (classifications ?? []).length >= MAX_PARKING_CLASSIFICATIONS}
          onClick={openCreateDialog}
        >
          <Plus className="size-4" /> Create classification
        </Button>

        <div className="overflow-hidden rounded-lg border bg-background">
          {(classifications ?? []).map((classification) => {
            const isActive = classification.id === activeClassification?.id;
            const isExpanded = expandedIds.has(classification.id);
            return (
              <div className="border-b last:border-b-0" key={classification.id}>
                <div className={cn("grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-1 px-1 py-1 transition-colors hover:bg-muted/70", isActive && "bg-muted/80")}>
                  <Button type="button" variant="ghost" className="h-auto min-w-0 justify-start px-2 py-2 text-left font-normal" disabled={busy} onClick={() => onSelectClassification(classification.id)}>
                    <span className="min-w-0">
                      <strong className="block truncate text-sm font-medium">{classification.name}</strong>
                      <small className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {(classification.types ?? []).length} type{classification.types?.length === 1 ? "" : "s"} · {Object.keys(classification.assignments ?? {}).length} assigned
                      </small>
                    </span>
                  </Button>
                  <Button type="button" variant="ghost" size="icon" className="size-8" disabled={busy || classification.types.length >= MAX_PARKING_TYPES_PER_CLASSIFICATION} onClick={() => { setCreateTypeClassificationId(classification.id); setDraftTypeName(""); }} title="Add type" aria-label={`Add type to ${classification.name}`}>
                    <Plus className="size-4" />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" className="size-8" disabled={busy} onClick={() => toggleExpanded(classification.id)} aria-label={`${isExpanded ? "Collapse" : "Expand"} ${classification.name}`}>
                    {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild><Button type="button" variant="ghost" size="icon" className="size-8" disabled={busy} aria-label={`Actions for ${classification.name}`}><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => { const name = window.prompt("Rename classification", classification.name); if (name !== null) onRenameClassification(classification.id, name); }}>Rename classification</DropdownMenuItem>
                      <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={() => setPendingDeletion(classification)}><Trash2 className="mr-2 size-4" />Delete classification</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                {isExpanded && (
                  <div className="pb-1 pl-8 pr-2">
                    {(classification.types ?? []).map((type, index) => {
                      const assigned = Object.values(classification.assignments ?? {}).filter((id) => id === type.id).length;
                      const color = buildingTypeColor(index);
                      return <div className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted/60" key={type.id}><span className="size-2.5 shrink-0 rounded-[3px] border" style={{ backgroundColor: color, borderColor: color }} /><span className="min-w-0 flex-1 truncate">{type.name}</span><span className="shrink-0 tabular-nums">{assigned}</span></div>;
                    })}
                    {!classification.types.length && <p className="px-2 py-1.5 text-xs text-muted-foreground">No types yet.</p>}
                  </div>
                )}
              </div>
            );
          })}
          {!classifications.length && <p className="p-3 text-xs text-muted-foreground">No classifications yet. Create one to start labeling parking areas.</p>}
        </div>
      </section>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create classification</DialogTitle><DialogDescription>Add a classification name and optional starter types. You can add more types later.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5"><Label htmlFor="new-parking-classification-name">Classification name</Label><Input id="new-parking-classification-name" value={draftClassificationName} onChange={(event) => setDraftClassificationName(event.target.value)} /></div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2"><Label>Types</Label><Button type="button" variant="ghost" size="sm" className="group gap-2" disabled={draftTypes.length >= MAX_PARKING_TYPES_PER_CLASSIFICATION} onClick={() => setDraftTypes((current) => [...current, ""])}><Plus className="size-4" /><span className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">Add type</span></Button></div>
              <div className="space-y-2">{draftTypes.map((name, index) => <Input key={index} value={name} placeholder={`Type ${index + 1}`} aria-label={`Type ${index + 1}`} onChange={(event) => setDraftTypes((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} />)}</div>
            </div>
          </div>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setCreateDialogOpen(false)}>Cancel</Button><Button type="button" onClick={() => { onAddClassification({ name: draftClassificationName, types: draftTypes.map((name) => name.trim()).filter(Boolean) }); setCreateDialogOpen(false); }}>Create</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={createTypeClassificationId !== null} onOpenChange={(open) => { if (!open) setCreateTypeClassificationId(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create parking type</DialogTitle><DialogDescription>Enter a descriptive name for the new type.</DialogDescription></DialogHeader>
          <div className="space-y-1.5"><Label htmlFor="new-parking-type-name">Type name</Label><Input id="new-parking-type-name" autoFocus value={draftTypeName} placeholder={`Type ${((classifications ?? []).find((item) => item.id === createTypeClassificationId)?.types ?? []).length + 1}`} onChange={(event) => setDraftTypeName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); createType(); } }} /></div>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setCreateTypeClassificationId(null)}>Cancel</Button><Button type="button" disabled={!draftTypeName.trim()} onClick={createType}>Create type</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingDeletion !== null} onOpenChange={(open) => { if (!open) setPendingDeletion(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete classification?</DialogTitle><DialogDescription>This permanently deletes “{pendingDeletion?.name}” and its parking-area assignments.</DialogDescription></DialogHeader>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setPendingDeletion(null)}>Cancel</Button><Button type="button" variant="destructive" onClick={() => { if (pendingDeletion) onDeleteClassification(pendingDeletion.id); setPendingDeletion(null); }}>Delete classification</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
