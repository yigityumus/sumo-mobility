import { Crosshair, LoaderCircle, MapPin, Plus, Radar, Trash2 } from "lucide-react";
import type {
  DetectorLaneCandidate,
  DetectorLaneSelection,
  DetectorPoint,
  TrafficDetector,
} from "../types/campus";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import DetectorGuideCard from "./DetectorGuideCard.tsx";

type DetectorEndpoint = "e1" | "entry" | "exit";
type CandidateSets = Record<DetectorEndpoint, DetectorLaneCandidate[]>;

type Props = {
  detectors: TrafficDetector[];
  activeDetectorId: string | null;
  candidates: CandidateSets;
  placingType: "e1" | "e3" | null;
  placingE3Exit: boolean;
  resolving: boolean;
  message: string;
  busy: boolean;
  onBack: () => void;
  onStartPlacement: (type: "e1" | "e3") => void;
  onCancelPlacement: () => void;
  onSelect: (id: string) => void;
  onChange: (detector: TrafficDetector) => void;
  onDelete: (id: string) => void;
  onRefreshLanes: (id: string, endpoint: DetectorEndpoint) => void;
  onFocusLane: (laneId: string | null) => void;
};

function LaneSelector({
  label,
  point,
  candidates,
  resolving,
  onRefresh,
  onChange,
  onFocusLane,
  multiple = false,
}: {
  label: string;
  point: DetectorPoint;
  candidates: DetectorLaneCandidate[];
  resolving: boolean;
  onRefresh: () => void;
  onChange: (selection: DetectorLaneSelection) => void;
  onFocusLane: (laneId: string | null) => void;
  multiple?: boolean;
}) {
  const edges = [...new Map(candidates.map((candidate) => [candidate.edge_id, candidate])).values()];
  const selectionValue = point.laneSelection.mode === "edge_all"
    ? `edge:${point.laneSelection.edgeId}`
    : point.laneSelection.laneId ? `lane:${point.laneSelection.laneId}` : "";
  const selectedLaneIsMissing = point.laneSelection.mode === "lane"
    && point.laneSelection.laneId
    && !candidates.some((candidate) => candidate.lane_id === point.laneSelection.laneId);
  const selectedEdgeIsMissing = point.laneSelection.mode === "edge_all"
    && !edges.some((candidate) => candidate.edge_id === point.laneSelection.edgeId);
  const selectedLaneIds = new Set(
    point.laneSelection.mode === "lanes"
      ? point.laneSelection.laneIds ?? []
      : point.laneSelection.laneId ? [point.laneSelection.laneId] : [],
  );
  const setSelectedLanes = (laneIds: string[]) => {
    const first = candidates.find((candidate) => laneIds.includes(candidate.lane_id));
    onChange({ mode: "lanes", edgeId: first?.edge_id ?? point.laneSelection.edgeId, laneIds });
  };

  return (
    <div className="space-y-1.5 rounded-md border p-2.5">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-xs">{label}</Label>
        <Button variant="ghost" size="sm" disabled={resolving} onClick={onRefresh}>Refresh lanes</Button>
      </div>
      {multiple ? <>
        <div className="flex flex-wrap gap-1.5">
          <Button type="button" variant="outline" size="sm" disabled={!candidates.length} onClick={() => setSelectedLanes(candidates.map((candidate) => candidate.lane_id))}>All nearby</Button>
          <Button type="button" variant="outline" size="sm" disabled={!candidates.some((candidate) => candidate.allows_passenger)} onClick={() => setSelectedLanes(candidates.filter((candidate) => candidate.allows_passenger).map((candidate) => candidate.lane_id))}>Vehicle lanes</Button>
          <Button type="button" variant="outline" size="sm" disabled={!candidates.some((candidate) => candidate.allows_pedestrian)} onClick={() => setSelectedLanes(candidates.filter((candidate) => candidate.allows_pedestrian).map((candidate) => candidate.lane_id))}>Pedestrian lanes</Button>
        </div>
        {candidates.length ? <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-1.5">
          {candidates.map((candidate) => {
            const checked = selectedLaneIds.has(candidate.lane_id);
            return <label
              key={candidate.lane_id}
              className={`flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-xs ${checked ? "bg-primary/10" : "hover:bg-muted"}`}
              onMouseEnter={() => onFocusLane(candidate.lane_id)}
              onMouseLeave={() => onFocusLane(null)}
              onFocus={() => onFocusLane(candidate.lane_id)}
              onBlur={() => onFocusLane(null)}
            >
              <Checkbox checked={checked} onCheckedChange={(nextChecked) => {
                const next = new Set(selectedLaneIds);
                if (nextChecked) next.add(candidate.lane_id);
                else next.delete(candidate.lane_id);
                setSelectedLanes([...next]);
              }} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono">{candidate.lane_id}</span>
                <span className="flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
                  {candidate.allows_passenger && <Badge variant="outline" className="h-4 border-blue-300 px-1 text-[9px] text-blue-700 dark:text-blue-300">vehicle</Badge>}
                  {candidate.allows_pedestrian && <Badge variant="outline" className="h-4 border-fuchsia-300 px-1 text-[9px] text-fuchsia-700 dark:text-fuchsia-300">pedestrian</Badge>}
                  {candidate.distance_metres.toFixed(1)} m away
                </span>
              </span>
            </label>;
          })}
        </div> : <p className="rounded-md border border-dashed p-2 text-center text-[11px] text-muted-foreground">Refresh lanes to view and select nearby lane geometry.</p>}
        <p className="text-[11px] text-muted-foreground">{selectedLaneIds.size} lane{selectedLaneIds.size === 1 ? "" : "s"} selected · Hover a lane ID to locate it on the map.</p>
      </> : <Select value={selectionValue} onValueChange={(value) => {
        const isEdge = value.startsWith("edge:");
        const id = value.slice(5);
        if (isEdge) onChange({ mode: "edge_all", edgeId: id });
        else {
          const lane = candidates.find((candidate) => candidate.lane_id === id);
          if (lane) onChange({ mode: "lane", edgeId: lane.edge_id, laneId: lane.lane_id, laneIndex: lane.lane_index });
        }
      }}>
        <SelectTrigger><SelectValue placeholder="Refresh nearby lanes" /></SelectTrigger>
        <SelectContent>
          {selectedLaneIsMissing && <SelectItem value={`lane:${point.laneSelection.laneId}`}>Lane {point.laneSelection.laneId}</SelectItem>}
          {selectedEdgeIsMissing && <SelectItem value={`edge:${point.laneSelection.edgeId}`}>All passenger lanes on edge {point.laneSelection.edgeId}</SelectItem>}
          {candidates.map((candidate) => <SelectItem key={`lane:${candidate.lane_id}`} value={`lane:${candidate.lane_id}`}>Lane {candidate.lane_id} · {candidate.distance_metres.toFixed(1)} m away</SelectItem>)}
          {edges.map((candidate) => <SelectItem key={`edge:${candidate.edge_id}`} value={`edge:${candidate.edge_id}`}>All passenger lanes on edge {candidate.edge_id}</SelectItem>)}
        </SelectContent>
      </Select>}
      <p className="text-[11px] leading-4 text-muted-foreground">
        {point.location.latitude.toFixed(6)}, {point.location.longitude.toFixed(6)}
      </p>
    </div>
  );
}

export default function DetectorSpecsPanel({
  detectors, activeDetectorId, candidates, placingType, placingE3Exit, resolving, message, busy,
  onBack, onStartPlacement, onCancelPlacement, onSelect, onChange, onDelete, onRefreshLanes, onFocusLane,
}: Props) {
  const active = detectors.find((detector) => detector.id === activeDetectorId) ?? null;
  const placing = placingType !== null;
  const selectedLaneCount = (selection: DetectorLaneSelection) =>
    selection.mode === "lanes" ? selection.laneIds?.length ?? 0 : selection.mode === "lane" ? 1 : null;
  const e3EntryLaneCount = active?.type === "e3" ? selectedLaneCount(active.entry.laneSelection) : null;
  const e3ExitLaneCount = active?.type === "e3" ? selectedLaneCount(active.exit.laneSelection) : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        <div><h1 className="text-lg font-semibold">Edit Detectors</h1><p className="text-xs text-muted-foreground">E1 point and E3 entry/exit detectors</p></div>
      </div>

      <DetectorGuideCard />

      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><Radar className="size-4 text-primary" /> Traffic detectors</CardTitle>
          <CardDescription className="text-xs">E1 measures a road cross-section. E3 measures traffic between an entry and an exit cross-section.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-2">
          {resolving && (
            <Alert
              className="border-blue-300 bg-blue-50 text-blue-950 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-100"
              role="status"
              aria-live="polite"
            >
              <LoaderCircle className="size-4 animate-spin text-blue-600 dark:text-blue-400" />
              <AlertTitle className="text-sm">Preparing SUMO detector lanes…</AlertTitle>
              <AlertDescription className="text-xs leading-5">
                The app is still working. The first detector lookup must build and cache a lane-level SUMO network from the saved OSM map, which can take a minute for a large area. Keep this page open.
              </AlertDescription>
            </Alert>
          )}
          {placing ? (
            <Button className="w-full" variant="secondary" disabled={busy || resolving} onClick={onCancelPlacement}>
              {resolving ? <LoaderCircle className="size-4 animate-spin" /> : <Crosshair className="size-4" />}
              {resolving ? "Resolving SUMO lanes…" : "Cancel map placement"}
            </Button>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <Button disabled={busy || resolving} onClick={() => onStartPlacement("e1")}><Plus className="size-4" /> Add E1</Button>
              <Button disabled={busy || resolving} variant="outline" onClick={() => onStartPlacement("e3")}><Plus className="size-4" /> Add E3</Button>
            </div>
          )}
          {placing && <Alert className="border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/40"><MapPin className="size-4" /><AlertDescription className="text-xs">{placingType === "e3" ? (placingE3Exit ? "Entry saved. Click the E3 exit cross-section on the map." : "Click the E3 entry cross-section on the map first.") : "Click the E1 cross-section on a road."}</AlertDescription></Alert>}
          {message && <p className="text-xs leading-5 text-muted-foreground">{message}</p>}
          {detectors.length ? (
            <div className="max-h-52 space-y-1 overflow-y-auto pr-1">
              {detectors.map((detector) => (
                <button key={detector.id} type="button" onClick={() => onSelect(detector.id)} className={`w-full rounded-md border px-2.5 py-2 text-left text-xs ${detector.id === activeDetectorId ? "border-primary bg-primary/10" : "hover:bg-muted"}`}>
                  <span className="flex items-center gap-2"><strong className="min-w-0 flex-1 truncate">{detector.name}</strong><Badge variant="outline" className="h-5 px-1.5 uppercase">{detector.type}</Badge></span>
                  <span className="block truncate text-muted-foreground">{detector.type === "e1"
                    ? detector.laneSelection.mode === "edge_all" ? `All lanes · ${detector.laneSelection.edgeId}` : detector.laneSelection.laneId
                    : `${detector.entry.laneSelection.edgeId} → ${detector.exit.laneSelection.edgeId}`}</span>
                </button>
              ))}
            </div>
          ) : <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">No detector has been added.</p>}
        </CardContent>
      </Card>

      {active && (
        <Card>
          <CardHeader className="p-4 pb-2"><CardTitle className="flex items-center gap-2 text-sm">Detector settings <Badge variant="secondary" className="uppercase">{active.type}</Badge></CardTitle></CardHeader>
          <CardContent className="space-y-3 p-4 pt-2">
            <div className="space-y-1"><Label className="text-xs">Name</Label><Input value={active.name} onChange={(event) => onChange({ ...active, name: event.target.value })} /></div>
            <div className="space-y-1">
              <Label className="text-xs">Native SUMO interval (seconds)</Label>
              <Input type="number" min={1} max={86400} value={active.periodSeconds} onChange={(event) => onChange({ ...active, periodSeconds: Math.max(1, Number(event.target.value) || 1) })} />
              <p className="text-[11px] leading-4 text-muted-foreground">New detectors default to 900 seconds. Analytics always rebins real-world comparisons to 900 seconds.</p>
            </div>
            {active.type === "e1" ? (
              <LaneSelector
                label="SUMO lane selection"
                point={active}
                candidates={candidates.e1.filter((candidate) => candidate.allows_passenger)}
                resolving={resolving}
                onRefresh={() => onRefreshLanes(active.id, "e1")}
                onChange={(laneSelection) => onChange({ ...active, laneSelection })}
                onFocusLane={onFocusLane}
              />
            ) : (
              <>
                <div className="space-y-1.5 rounded-md border p-2.5">
                  <Label className="text-xs">Measure</Label>
                  <div className="flex flex-wrap gap-4 text-xs">
                    {(["vehicles", "pedestrians"] as const).map((target) => {
                      const detects = active.detects ?? ["vehicles"];
                      const checked = detects.includes(target);
                      return <label key={target} className="flex cursor-pointer items-center gap-2 capitalize">
                        <Checkbox checked={checked} onCheckedChange={(nextChecked) => {
                          const next = new Set(detects);
                          if (nextChecked) next.add(target);
                          else next.delete(target);
                          if (next.size) onChange({ ...active, detects: [...next] });
                        }} />
                        {target}
                      </label>;
                    })}
                  </div>
                  <p className="text-[11px] leading-4 text-muted-foreground">Selecting both keeps one website group. Vehicles use entry-to-exit E3 traversal measurements; pedestrians use a bidirectional lane zone and are counted once when they enter it from either direction.</p>
                </div>
                <LaneSelector
                  label="Entry cross-section"
                  point={active.entry}
                  candidates={candidates.entry}
                  resolving={resolving}
                  onRefresh={() => onRefreshLanes(active.id, "entry")}
                  onChange={(laneSelection) => onChange({ ...active, entry: { ...active.entry, laneSelection } })}
                  onFocusLane={onFocusLane}
                  multiple
                />
                <LaneSelector
                  label="Exit cross-section"
                  point={active.exit}
                  candidates={candidates.exit}
                  resolving={resolving}
                  onRefresh={() => onRefreshLanes(active.id, "exit")}
                  onChange={(laneSelection) => onChange({ ...active, exit: { ...active.exit, laneSelection } })}
                  onFocusLane={onFocusLane}
                  multiple
                />
                {e3EntryLaneCount !== null && e3ExitLaneCount !== null && e3EntryLaneCount !== e3ExitLaneCount && <Alert className="border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/35 dark:text-amber-100"><AlertDescription className="text-xs">This E3 has {e3EntryLaneCount} selected entry lane{e3EntryLaneCount === 1 ? "" : "s"} but {e3ExitLaneCount} exit lane{e3ExitLaneCount === 1 ? "" : "s"}. Vehicle traversal may remain incomplete. Pedestrian measurement also requires the same sidewalk lane at both markers so a bidirectional zone can be formed.</AlertDescription></Alert>}
                <p className="text-[11px] leading-4 text-muted-foreground">For pedestrians, select each sidewalk lane at both markers. Direction does not matter: entering the area from either end adds one count.</p>
              </>
            )}
            <p className="text-[11px] leading-4 text-muted-foreground">The exact SUMO lane positions are resolved again and snapshotted for every run.</p>
            <Button variant="destructive" className="w-full" onClick={() => onDelete(active.id)}><Trash2 className="size-4" /> Delete detector</Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
