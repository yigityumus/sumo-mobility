import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Car,
  ChevronDown,
  ChevronRight,
  Clock3,
  Footprints,
  History,
  Info,
  ListOrdered,
  MonitorPlay,
  Play,
  RefreshCw,
  Square,
  Terminal,
  Trash2,
} from "lucide-react";
import { deleteSimulationRun, getSimulationQueueStatus, listSimulationRuns, startSimulationRun, stopSimulationRun } from "../../api/simulations";
import { listRealWorldSources } from "../../api/analytics";
import { listFlowCalibrations, startFlowCalibration } from "../../api/calibrations";
import type { BuildingClassification, CalibrationSubject, FlowCalibrationSession, FourierTrafficParameters, ParkingChoiceParameters, PedestrianModel, RealWorldSource, SimulationMode, SimulationQueueStatus, SimulationRun, SimulationRunRequest, TrafficDetector, TrafficModel, VehicleGenerationPoint, VehicleOriginAllocation } from "../../types/campus";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Alert, AlertDescription } from "../../components/ui/alert";
import { Progress } from "../../components/ui/progress";
import { RadioGroup, RadioGroupItem } from "../../components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Slider } from "../../components/ui/slider";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import TrafficProfileChart, { trafficModelLabel } from "./TrafficProfileChart";
import TopNavigation from "../../components/TopNavigation";

type Props = {
  modelId: string | null;
  modelName: string;
  parkingAreaCount: number;
  selectedBuildingIds: string[];
  buildingClassifications: BuildingClassification[];
  detectors: TrafficDetector[];
  publicTransportOriginCount: number | null;
  vehicleGenerationPoints: VehicleGenerationPoint[];
  loadingModel: boolean;
  onBack: () => void;
  onHome: () => void;
  onAnalytics: () => void;
  onDocumentation: () => void;
};

const ACTIVE_STATUSES = new Set(["queued", "running"]);
const SIMULATION_TIMEZONE = "Europe/Paris";
const NO_BUILDING_CLASSIFICATION = "__no_building_classification__";
const DEFAULT_FOURIER_PARAMETERS: FourierTrafficParameters = {
  peak_count: 2,
  peak_width_hours: 1.5,
  harmonics: 6,
  peak_heights: [1, 1],
};
const DEFAULT_PEDESTRIAN_FOURIER_PARAMETERS: FourierTrafficParameters = {
  peak_count: 16,
  peak_width_hours: 0.3,
  harmonics: 10,
  peak_heights: [0.2, 0.75, 0.1, 0.15, 1, 0.1, 0.4, 1, 0.1, 0.15, 0.75, 0.1, 0.65, 0.4, 0.15, 0.1],
};
const DEFAULT_PARKING_CHOICE: ParkingChoiceParameters = {
  knowledge_probability: 0.5,
  uninformed_occupancy_mean: 0.6,
  uninformed_occupancy_stddev: 0.15,
  frustration_step: 0.35,
  stochastic_scale: 0.0,
  weights: {
    drive_time: 0.8,
    walk_time: 1,
    capacity: 0.8,
    absolute_free_space: 1.3,
    relative_free_space: 1.5,
  },
};
const RUN_HISTORY_COLUMNS = [
  { id: "runType", label: "Run type / iteration group", defaultWidth: 205, minWidth: 130 },
  { id: "runId", label: "Run ID", defaultWidth: 180, minWidth: 100 },
  { id: "executed", label: "Executed", defaultWidth: 145, minWidth: 90 },
  { id: "simulatedWindow", label: "Simulated window", defaultWidth: 210, minWidth: 120 },
  { id: "status", label: "Status", defaultWidth: 170, minWidth: 100 },
  { id: "mode", label: "Mode", defaultWidth: 190, minWidth: 100 },
  { id: "byCar", label: "By car", defaultWidth: 80, minWidth: 60, align: "right" },
  { id: "carProfile", label: "Car-arrival profile", defaultWidth: 125, minWidth: 85 },
  { id: "walkers", label: "Independent walkers", defaultWidth: 115, minWidth: 80, align: "right" },
  { id: "walkingProfile", label: "Walking-arrival profile", defaultWidth: 140, minWidth: 90 },
  { id: "duration", label: "Simulation duration", defaultWidth: 110, minWidth: 75 },
  { id: "parkingAreas", label: "Parking areas", defaultWidth: 90, minWidth: 65, align: "right" },
  { id: "actions", label: "Actions", defaultWidth: 95, minWidth: 75, align: "right" },
] as const;
type RunHistoryColumnId = typeof RUN_HISTORY_COLUMNS[number]["id"];
type RunHistoryColumnWidths = Record<RunHistoryColumnId, number>;
const RUN_HISTORY_COLUMN_WIDTHS_KEY = "simulation-run-history-column-widths";

type RunHistoryBlock =
  | { kind: "standalone"; run: SimulationRun }
  | {
      kind: "calibration";
      id: string;
      name: string;
      totalIterations: number;
      runs: SimulationRun[];
    };

function groupRunHistory(runs: SimulationRun[]): RunHistoryBlock[] {
  const calibrationRuns = new Map<string, SimulationRun[]>();
  for (const run of runs) {
    const calibrationId = run.calibration?.id;
    if (!calibrationId) continue;
    calibrationRuns.set(calibrationId, [...(calibrationRuns.get(calibrationId) ?? []), run]);
  }

  const emittedCalibrationIds = new Set<string>();
  const blocks: RunHistoryBlock[] = [];
  for (const run of runs) {
    const calibration = run.calibration;
    if (!calibration) {
      blocks.push({ kind: "standalone", run });
      continue;
    }
    if (emittedCalibrationIds.has(calibration.id)) continue;
    emittedCalibrationIds.add(calibration.id);
    blocks.push({
      kind: "calibration",
      id: calibration.id,
      name: calibration.name,
      totalIterations: calibration.total_iterations,
      runs: [...(calibrationRuns.get(calibration.id) ?? [])].sort((left, right) => (
        (left.calibration?.iteration ?? 0) - (right.calibration?.iteration ?? 0)
        || left.created_at.localeCompare(right.created_at)
      )),
    });
  }
  return blocks;
}

function defaultRunHistoryColumnWidths(): RunHistoryColumnWidths {
  return Object.fromEntries(
    RUN_HISTORY_COLUMNS.map((column) => [column.id, column.defaultWidth]),
  ) as RunHistoryColumnWidths;
}

function initialRunHistoryColumnWidths(): RunHistoryColumnWidths {
  const defaults = defaultRunHistoryColumnWidths();
  if (typeof window === "undefined") return defaults;
  try {
    const saved = window.localStorage.getItem(RUN_HISTORY_COLUMN_WIDTHS_KEY);
    if (!saved) return defaults;
    const parsed = JSON.parse(saved) as Partial<Record<RunHistoryColumnId, unknown>>;
    return Object.fromEntries(RUN_HISTORY_COLUMNS.map((column) => {
      const savedWidth = Number(parsed[column.id]);
      const width = Number.isFinite(savedWidth)
        ? Math.min(Math.max(savedWidth, column.minWidth), 600)
        : column.defaultWidth;
      return [column.id, width];
    })) as RunHistoryColumnWidths;
  } catch {
    return defaults;
  }
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatDateInTimezone(value?: string | null, timezone = SIMULATION_TIMEZONE) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: timezone,
      }).format(date);
}

function dateTimeInputValue(date: Date, timezone = SIMULATION_TIMEZONE) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).formatToParts(date);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}`;
}

function defaultSimulationStart() {
  const nextHour = new Date(Math.ceil(Date.now() / 3_600_000) * 3_600_000);
  return dateTimeInputValue(nextHour);
}

function formatLocalWindow(start: string, durationHours: number) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(start);
  if (!match) return "Select a valid start date and time.";
  const [, year, month, day, hour, minute] = match;
  const startAsUtc = new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute));
  const endAsUtc = new Date(startAsUtc.getTime() + Math.max(durationHours, 0) * 3_600_000);
  const formatter = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
  return `${formatter.format(startAsUtc)} → ${formatter.format(endAsUtc)} (${SIMULATION_TIMEZONE})`;
}

function formatRunWindow(run: SimulationRun) {
  if (!run.simulation_start_at) return `${formatDuration(run.duration_hours)} relative window`;
  const timezone = run.simulation_timezone || SIMULATION_TIMEZONE;
  return `${formatDateInTimezone(run.simulation_start_at, timezone)} → ${formatDateInTimezone(run.simulation_end_at, timezone)}`;
}

function formatSimulationClock(run: SimulationRun, elapsed?: number | null) {
  if (!run.simulation_start_at) return formatSimulationTime(elapsed);
  const start = new Date(run.simulation_start_at);
  if (Number.isNaN(start.getTime())) return formatSimulationTime(elapsed);
  const current = new Date(start.getTime() + Math.max(elapsed ?? 0, 0) * 1000);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: run.simulation_timezone || SIMULATION_TIMEZONE,
  }).format(current);
}

function formatDuration(hours: number) {
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"}`;
  const days = hours / 24;
  return `${days} day${days === 1 ? "" : "s"}`;
}

function statusClass(status: SimulationRun["status"]) {
  if (status === "completed") return "border-green-200 bg-green-50 text-green-700 dark:border-green-900 dark:bg-green-950/40 dark:text-green-300";
  if (status === "failed") return "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300";
  if (status === "running") return "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300";
  return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300";
}

function formatRemaining(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "Calculating time remaining…";
  const seconds = Math.max(Math.round(value), 0);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  if (hours) return `${hours}h ${minutes}m remaining`;
  if (minutes) return `${minutes}m ${remainingSeconds}s remaining`;
  return `${remainingSeconds}s remaining`;
}

function formatSimulationTime(value?: number | null) {
  const seconds = Math.max(Math.round(value ?? 0), 0);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return `${seconds}s`;
}

function sourcePercentage(count: number, total: number) {
  return total > 0 ? count / total * 100 : 0;
}

function formatPercentage(value: number) {
  return `${Number(value.toFixed(value >= 10 ? 1 : 2))}%`;
}

type VehicleOriginAllocationMode = "percentage" | "count";

function equalOriginPercentages(points: VehicleGenerationPoint[]) {
  if (!points.length) return {};
  const equal = 100 / points.length;
  return Object.fromEntries(points.map((point) => [point.id, equal]));
}

function allocateVehicleCounts(
  points: VehicleGenerationPoint[],
  percentages: Record<string, number>,
  total: number,
): Record<string, number> {
  if (!points.length) return {};
  const raw = points.map((point, index) => {
    const exact = Math.max(percentages[point.id] ?? 0, 0) * total / 100;
    return { id: point.id, index, exact, count: Math.floor(exact) };
  });
  let remaining = total - raw.reduce((sum, item) => sum + item.count, 0);
  const remainderOrder = [...raw].sort((left, right) => (
    (right.exact - right.count) - (left.exact - left.count) || left.index - right.index
  ));
  for (let index = 0; index < remaining; index += 1) {
    remainderOrder[index % remainderOrder.length].count += 1;
  }
  return Object.fromEntries(raw.map((item) => [item.id, item.count]));
}

function FourierControls({
  idPrefix,
  value,
  durationHours,
  onChange,
}: {
  idPrefix: string;
  value: FourierTrafficParameters;
  durationHours: number;
  onChange: (value: FourierTrafficParameters) => void;
}) {
  const peakCount = Math.min(Math.max(Math.round(value.peak_count), 1), 16);
  const peakHeights = Array.from(
    { length: peakCount },
    (_, index) => value.peak_heights[index] ?? 1,
  );

  const setPeakHeight = (index: number, percentage: number) => {
    const nextHeights = [...peakHeights];
    nextHeights[index] = Math.min(Math.max(percentage / 100, 0), 3);
    onChange({ ...value, peak_heights: nextHeights });
  };

  return (
    <div className="grid gap-2 rounded-md bg-muted/45 p-2.5">
      <p className="text-xs leading-4 text-muted-foreground">
        Peaks become evenly spaced hills. Width is the Gaussian σ; amplitude controls each hill’s relative height.
      </p>
      <div className="grid grid-cols-3 gap-2">
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}-peaks`} className="text-[11px]">Hills</Label>
          <Input
            id={`${idPrefix}-peaks`}
            className="h-8 px-2 text-xs"
            type="number"
            min={1}
            max={16}
            value={value.peak_count}
            onChange={(event) => {
              const nextCount = Math.min(Math.max(Number(event.target.value), 1), 16);
              const nextHeights = Array.from(
                { length: nextCount },
                (_, index) => value.peak_heights[index] ?? 1,
              );
              onChange({ ...value, peak_count: nextCount, peak_heights: nextHeights });
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}-width`} className="text-[11px]">Width (h)</Label>
          <Input id={`${idPrefix}-width`} className="h-8 px-2 text-xs" type="number" min={0.01} max={Math.max(durationHours, 0.01)} step={0.01} value={value.peak_width_hours} onChange={(event) => onChange({ ...value, peak_width_hours: Number(event.target.value) })} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}-harmonics`} className="text-[11px]">Harmonics</Label>
          <Input id={`${idPrefix}-harmonics`} className="h-8 px-2 text-xs" type="number" min={1} max={16} value={value.harmonics} onChange={(event) => onChange({ ...value, harmonics: Number(event.target.value) })} />
        </div>
      </div>
      <div className="space-y-2 border-t pt-2">
        <div className="flex items-center justify-between gap-2">
          <Label className="text-[11px]">Peak amplitudes</Label>
          <span className="text-[10px] text-muted-foreground">0–300%</span>
        </div>
        {peakHeights.map((height, index) => {
          const percentage = Math.round(height * 100);
          return (
            <div key={index} className="grid grid-cols-[3.5rem_minmax(0,1fr)_3rem] items-center gap-2">
              <Label htmlFor={`${idPrefix}-height-${index}`} className="text-[11px] text-muted-foreground">
                Peak {index + 1}
              </Label>
              <Slider
                id={`${idPrefix}-height-${index}`}
                min={0}
                max={300}
                step={5}
                value={[percentage]}
                onValueChange={([nextValue]) => setPeakHeight(index, nextValue)}
                aria-label={`Peak ${index + 1} amplitude`}
              />
              <span className="text-right text-[11px] tabular-nums">{percentage}%</span>
            </div>
          );
        })}
      </div>
      {value.peak_width_hours < durationHours / (Math.max(value.harmonics, 1) * 4) && (
        <p className="text-[11px] leading-4 text-amber-700 dark:text-amber-300">
          This peak is narrower than the selected Fourier resolution. The value is retained to two decimal places, but the generated curve will be smoothed; increase harmonics or use a wider peak if the preview is too broad.
        </p>
      )}
    </div>
  );
}

function ParkingChoiceControls({
  value,
  onChange,
}: {
  value: ParkingChoiceParameters;
  onChange: (value: ParkingChoiceParameters) => void;
}) {
  const weightFields: Array<{
    key: keyof ParkingChoiceParameters["weights"];
    label: string;
    description: string;
  }> = [
    { key: "drive_time", label: "Driving time", description: "Avoid long vehicle reroutes." },
    { key: "walk_time", label: "Walking time", description: "Stay close to the destination building." },
    { key: "capacity", label: "Total capacity", description: "Prefer larger, safer-looking facilities." },
    { key: "absolute_free_space", label: "Free-space count", description: "Prefer more expected empty spaces." },
    { key: "relative_free_space", label: "Free-space ratio", description: "Prefer a lower occupancy percentage." },
  ];
  const behaviorFields: Array<{
    key: Exclude<keyof ParkingChoiceParameters, "weights">;
    label: string;
    description: string;
    max: number;
  }> = [
    { key: "knowledge_probability", label: "Occupancy knowledge", description: "Chance of knowing a remote lot’s true occupancy.", max: 1 },
    { key: "uninformed_occupancy_mean", label: "Expected occupancy", description: "Typical occupancy assumed when information is unavailable.", max: 1 },
    { key: "uninformed_occupancy_stddev", label: "Perception error", description: "Variation in guesses about unknown lots.", max: 1 },
    { key: "frustration_step", label: "Frustration response", description: "How strongly availability matters after each failed visit.", max: 2 },
    { key: "stochastic_scale", label: "Choice randomness", description: "Unobserved personal preference; 0 makes choices deterministic.", max: 5 },
  ];

  return (
    <fieldset className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {weightFields.map((field) => (
          <div key={field.key} className="space-y-1 rounded-md bg-muted/40 p-2.5">
            <Label htmlFor={`parking-weight-${field.key}`} className="text-xs">{field.label}</Label>
            <Input
              id={`parking-weight-${field.key}`}
              type="number"
              min={0}
              max={10}
              step={0.05}
              value={value.weights[field.key]}
              onChange={(event) => onChange({
                ...value,
                weights: { ...value.weights, [field.key]: Number(event.target.value) },
              })}
            />
            <p className="text-[10px] leading-4 text-muted-foreground">{field.description}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {behaviorFields.map((field) => (
          <div key={field.key} className="space-y-1 rounded-md bg-muted/20 p-2.5">
            <Label htmlFor={`parking-behavior-${field.key}`} className="text-xs">{field.label}</Label>
            <Input
              id={`parking-behavior-${field.key}`}
              type="number"
              min={0}
              max={field.max}
              step={0.05}
              value={value[field.key]}
              onChange={(event) => onChange({ ...value, [field.key]: Number(event.target.value) })}
            />
            <p className="text-[10px] leading-4 text-muted-foreground">{field.description}</p>
          </div>
        ))}
      </div>
      <Alert className="bg-muted/25">
        <Info className="size-4" />
        <AlertDescription className="text-xs leading-5">
          To reduce repeated searches, increase occupancy knowledge, frustration response, free-space count/ratio, or capacity. Very high knowledge assumes drivers have reliable signs, apps, or strong local familiarity. Compare the parking-attempt distribution between runs rather than treating any uncalibrated setting as ground truth.
        </AlertDescription>
      </Alert>
    </fieldset>
  );
}

function TableRun({
  run,
  deleting,
  stopping,
  onDelete,
  onStop,
}: {
  run: SimulationRun;
  deleting: boolean;
  stopping: boolean;
  onDelete: (run: SimulationRun) => void;
  onStop: (run: SimulationRun) => void;
}) {
  const rawProgress = Math.min(Math.max(run.progress_percent ?? 0, 0), 100);
  const progress = run.status === "running" ? Math.min(rawProgress, 99.9) : rawProgress;
  const progressText = progress >= 99 ? progress.toFixed(1) : Math.round(progress).toString();
  const finishing = run.progress_phase === "finishing";
  const simulating = run.progress_phase === "demand" || finishing;
  const stopRequested = Boolean(run.stop_requested_at);
  const statusText = run.status === "failed"
    ? run.failure_reason === "Removed from queue"
      ? "removed from queue"
      : `failed: ${run.failure_reason || run.message || "Unknown error"}`
    : stopRequested
      ? "stopping"
      : run.status === "queued" && run.queue_position
        ? `queued #${run.queue_position}`
        : run.status;
  const activityText = stopRequested
    ? "Stopping SUMO and saving partial analytics data…"
    : run.status === "queued"
      ? run.queue_position
        ? `Queue position ${run.queue_position}. ${run.queued_ahead || 0} run${run.queued_ahead === 1 ? "" : "s"} waiting ahead.`
        : run.message || "Waiting for an available simulation worker."
      : finishing
        ? `Demand window complete; finishing ${run.remaining_agents ?? 0} remaining agent${run.remaining_agents === 1 ? "" : "s"}.`
        : run.progress_phase === "demand"
          ? `${run.completed_agents ?? 0} / ${run.planned_agents ?? (run.vehicle_count + run.pedestrian_count)} agents completed`
          : run.message || "Preparing simulation inputs.";

  return (
    <>
      <TableRow className="hover:bg-muted/35">
        <TableCell className="px-3 py-2.5 text-xs">
          {run.calibration ? (
            <div className="space-y-1">
              <Badge variant="outline" className="border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300">
                Iteration {run.calibration.iteration} of {run.calibration.total_iterations}
              </Badge>
              <span className="block font-medium leading-4">{run.calibration.name}</span>
              <span className="block font-mono text-[10px] text-muted-foreground" title={run.calibration.id}>
                Group {run.calibration.id.slice(0, 8)}
              </span>
            </div>
          ) : (
            <div className="space-y-1">
              <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-300">
                Standalone run
              </Badge>
              <span className="block text-[10px] leading-4 text-muted-foreground">Started without iterations</span>
            </div>
          )}
        </TableCell>
        <TableCell className="px-3 py-2.5 font-mono text-[11px] leading-4">
          <span className="select-all break-all" title={`Run directory: simulations/${run.id}`}>{run.id}</span>
        </TableCell>
        <TableCell className="px-3 py-2.5">
          {formatDate(run.created_at)}
        </TableCell>
        <TableCell className="px-3 py-2.5 text-xs">
          {formatRunWindow(run)}
        </TableCell>
        <TableCell className="px-3 py-2.5">
          <Badge variant="outline" className={`h-auto max-w-full whitespace-normal px-2 py-0.5 text-left text-[11px] leading-4 ${statusClass(run.status)}`}>
            {statusText}
          </Badge>
        </TableCell>
        <TableCell className="px-3 py-2.5">
          <span className="flex items-center gap-1.5">
            {run.mode === "sumo-gui" ? <MonitorPlay className="size-3.5" /> : <Terminal className="size-3.5" />}
            {run.mode === "sumo-gui" ? "SUMO GUI" : "SUMO"}
          </span>
          <span className="mt-1 block text-[11px] text-muted-foreground">
            {run.pedestrian_model === "nonInteracting" ? "Fast pedestrians" : "Interactive pedestrians"}
            {run.diagnostic_tracing ? " · full trace" : ""}
            {run.random_seed ? ` · seed ${run.random_seed}` : ""}
          </span>
          {run.parking_choice && (
            <span
              className="mt-1 block text-[10px] leading-4 text-muted-foreground"
              title="Parking weights: driving time / walking time / capacity / absolute free spaces / relative free spaces"
            >
              Parking weights D/W/C/A/R: {run.parking_choice.weights.drive_time} / {run.parking_choice.weights.walk_time} / {run.parking_choice.weights.capacity} / {run.parking_choice.weights.absolute_free_space} / {run.parking_choice.weights.relative_free_space}
            </span>
          )}
        </TableCell>
        <TableCell className="px-3 py-2.5 text-right tabular-nums">{run.vehicle_count.toLocaleString()}</TableCell>
        <TableCell className="px-3 py-2.5">{trafficModelLabel(run.vehicle_traffic_model ?? "linear")}</TableCell>
        <TableCell className="px-3 py-2.5 text-right tabular-nums">{run.pedestrian_count.toLocaleString()}</TableCell>
        <TableCell className="px-3 py-2.5">{trafficModelLabel(run.pedestrian_traffic_model ?? "linear")}</TableCell>
        <TableCell className="px-3 py-2.5">{formatDuration(run.duration_hours)}</TableCell>
        <TableCell className="px-3 py-2.5 text-right tabular-nums">{run.parking_area_count ?? run.parking_areas?.length ?? 0}</TableCell>
        <TableCell className="px-3 py-2.5 text-right">
          {ACTIVE_STATUSES.has(run.status) && (run.status === "queued" || run.mode === "sumo") ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={stopping || stopRequested}
              onClick={() => onStop(run)}
              aria-label={run.status === "queued" ? `Remove queued simulation from ${formatDate(run.created_at)}` : `Stop simulation from ${formatDate(run.created_at)}`}
            >
              <Square className="size-3 fill-current" />
              {stopping || stopRequested ? "Stopping…" : run.status === "queued" ? "Remove" : "Stop"}
            </Button>
          ) : (
            <Button type="button" variant="ghost" size="icon" className="size-8 text-destructive hover:text-destructive" disabled={deleting || ACTIVE_STATUSES.has(run.status)} onClick={() => onDelete(run)} aria-label={`Delete simulation from ${formatDate(run.created_at)}`}>
              <Trash2 className="size-4" />
            </Button>
          )}
        </TableCell>
      </TableRow>
      {ACTIVE_STATUSES.has(run.status) && (
        <TableRow className="bg-blue-50/60 hover:bg-blue-50/60 dark:bg-blue-950/30 dark:hover:bg-blue-950/30">
          <TableCell colSpan={RUN_HISTORY_COLUMNS.length} className="px-3 py-2">
            <div className="flex min-w-[720px] items-center gap-3 text-xs text-blue-700 dark:text-blue-300">
              <strong className="w-24 shrink-0 text-right">{progressText}% complete</strong>
              <Progress value={progress} className="h-1.5 min-w-32 flex-1 bg-blue-100 [&>div]:bg-blue-600" />
              <span className="min-w-72 shrink-0">{activityText}</span>
              {stopRequested ? (
                <span className="shrink-0">Waiting for the process to exit…</span>
              ) : simulating ? (
                <>
                  <span className="shrink-0">{formatRemaining(run.estimated_remaining_seconds)}</span>
                  <span className="shrink-0 text-blue-600/80">Simulated clock: {formatSimulationClock(run, run.simulated_seconds)} · {formatSimulationTime(run.simulated_seconds)} elapsed</span>
                </>
              ) : null}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export default function SimulationPage({ modelId, modelName, parkingAreaCount, selectedBuildingIds, buildingClassifications, detectors, publicTransportOriginCount, vehicleGenerationPoints, loadingModel, onBack, onHome, onAnalytics, onDocumentation }: Props) {
  const [totalPeople, setTotalPeople] = useState(16_000);
  const [vehicleCount, setVehicleCount] = useState(3_000);
  const pedestrianCount = Math.max(totalPeople - vehicleCount, 0);
  const vehiclePercentage = totalPeople > 0 ? Math.round(vehicleCount / totalPeople * 100) : 0;
  const [buildingClassificationId, setBuildingClassificationId] = useState(NO_BUILDING_CLASSIFICATION);
  const [pedestrianSourceAllocation, setPedestrianSourceAllocation] = useState({
    residential: 0,
    publicTransport: 80,
  });
  const [durationHours, setDurationHours] = useState(12);
  const [simulationStartAt, setSimulationStartAt] = useState(defaultSimulationStart);
  const [mode, setMode] = useState<SimulationMode>("sumo");
  const [pedestrianModel, setPedestrianModel] = useState<PedestrianModel>("striping");
  const [diagnosticTracing, setDiagnosticTracing] = useState(false);
  const [vehicleTrafficModel, setVehicleTrafficModel] = useState<TrafficModel>("normal");
  const [pedestrianTrafficModel, setPedestrianTrafficModel] = useState<TrafficModel>("normal");
  const [vehicleFourierParameters, setVehicleFourierParameters] = useState<FourierTrafficParameters>(DEFAULT_FOURIER_PARAMETERS);
  const [pedestrianFourierParameters, setPedestrianFourierParameters] = useState<FourierTrafficParameters>(DEFAULT_PEDESTRIAN_FOURIER_PARAMETERS);
  const [parkingChoice, setParkingChoice] = useState<ParkingChoiceParameters>(DEFAULT_PARKING_CHOICE);
  const [runs, setRuns] = useState<SimulationRun[]>([]);
  const [queueStatus, setQueueStatus] = useState<SimulationQueueStatus | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [queueNotice, setQueueNotice] = useState("");
  const [simulationInfoOpen, setSimulationInfoOpen] = useState(false);
  const simulationInfoRef = useRef<HTMLDivElement>(null);
  const [runHistoryColumnWidths, setRunHistoryColumnWidths] = useState<RunHistoryColumnWidths>(initialRunHistoryColumnWidths);
  const [runPendingDeletion, setRunPendingDeletion] = useState<SimulationRun | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [runPendingStop, setRunPendingStop] = useState<SimulationRun | null>(null);
  const [stoppingRunId, setStoppingRunId] = useState<string | null>(null);
  const [calibrationName, setCalibrationName] = useState("Flow calibration");
  const [calibrationIterations, setCalibrationIterations] = useState(10);
  const [calibrationStepPercentage, setCalibrationStepPercentage] = useState(1);
  const [calibrationSubject, setCalibrationSubject] = useState<"vehicles" | "pedestrians" | "both">("vehicles");
  const [calibrationSourceId, setCalibrationSourceId] = useState("");
  const [calibrationDetectorId, setCalibrationDetectorId] = useState("");
  const [realWorldSources, setRealWorldSources] = useState<RealWorldSource[]>([]);
  const [calibrations, setCalibrations] = useState<FlowCalibrationSession[]>([]);
  const [startingCalibration, setStartingCalibration] = useState(false);
  const [collapsedCalibrationGroups, setCollapsedCalibrationGroups] = useState<Set<string>>(() => new Set());
  const [vehicleOriginAllocationMode, setVehicleOriginAllocationMode] = useState<VehicleOriginAllocationMode>("percentage");
  const [vehicleOriginAllocationValues, setVehicleOriginAllocationValues] = useState<Record<string, number>>({});

  const runHistoryBlocks = useMemo(() => groupRunHistory(runs), [runs]);
  const calibrationsById = useMemo(
    () => new Map(calibrations.map((calibration) => [calibration.id, calibration])),
    [calibrations],
  );

  const toggleCalibrationGroup = (calibrationId: string) => {
    setCollapsedCalibrationGroups((current) => {
      const next = new Set(current);
      if (next.has(calibrationId)) next.delete(calibrationId);
      else next.add(calibrationId);
      return next;
    });
  };

  const calibrationDetectors = useMemo(
    () => detectors.filter((detector) => detector.type === "e3"),
    [detectors],
  );

  useEffect(() => {
    let cancelled = false;
    void listRealWorldSources().then((sources) => {
      if (cancelled) return;
      setRealWorldSources(sources);
      setCalibrationSourceId((current) => current || sources[0]?.id || "");
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    setCalibrationDetectorId((current) => (
      calibrationDetectors.some((detector) => detector.id === current)
        ? current
        : calibrationDetectors[0]?.id || ""
    ));
  }, [calibrationDetectors]);

  const refreshCalibrations = useCallback(async () => {
    if (!modelId) return;
    try {
      setCalibrations(await listFlowCalibrations(modelId));
    } catch {
      // Simulation history remains usable if calibration metadata is unavailable.
    }
  }, [modelId]);

  useEffect(() => { void refreshCalibrations(); }, [refreshCalibrations]);

  const selectedDemandClassification = useMemo(
    () => buildingClassifications.find((classification) => classification.id === buildingClassificationId),
    [buildingClassificationId, buildingClassifications],
  );
  const classifiedSelectedBuildingCount = useMemo(() => {
    if (!selectedDemandClassification) return 0;
    const validTypeIds = new Set(selectedDemandClassification.types.map((type) => type.id));
    return selectedBuildingIds.filter((buildingId) => {
      const typeId = selectedDemandClassification.assignments[buildingId];
      return Boolean(typeId && validTypeIds.has(typeId));
    }).length;
  }, [selectedBuildingIds, selectedDemandClassification]);
  const unclassifiedSelectedBuildingCount = selectedBuildingIds.length - classifiedSelectedBuildingCount;
  const residentialTypeIds = useMemo(
    () => new Set(
      (selectedDemandClassification?.types ?? [])
        .filter((type) => type.name.trim().toLocaleLowerCase() === "residential")
        .map((type) => type.id),
    ),
    [selectedDemandClassification],
  );
  const hasResidentialType = residentialTypeIds.size > 0;
  const residentialOriginBuildingCount = useMemo(() => {
    if (!selectedDemandClassification || !hasResidentialType) return 0;
    return selectedBuildingIds.filter((buildingId) => (
      residentialTypeIds.has(selectedDemandClassification.assignments[buildingId] ?? "")
    )).length;
  }, [hasResidentialType, residentialTypeIds, selectedBuildingIds, selectedDemandClassification]);
  const residentialSourceAvailable = Boolean(
    selectedDemandClassification && hasResidentialType && residentialOriginBuildingCount > 0,
  );
  const publicTransportSourceAvailable = (publicTransportOriginCount ?? 0) > 0;

  useEffect(() => {
    setPedestrianSourceAllocation((current) => {
      if (!residentialSourceAvailable && !publicTransportSourceAvailable) {
        return { residential: 0, publicTransport: 0 };
      }
      if (!residentialSourceAvailable) {
        return { residential: 0, publicTransport: pedestrianCount };
      }
      if (!publicTransportSourceAvailable) {
        return { residential: pedestrianCount, publicTransport: 0 };
      }
      const previousTotal = current.residential + current.publicTransport;
      const residentialShare = previousTotal > 0
        ? current.residential / previousTotal
        : 0;
      const residential = Math.round(pedestrianCount * residentialShare);
      return {
        residential,
        publicTransport: pedestrianCount - residential,
      };
    });
  }, [pedestrianCount, publicTransportSourceAvailable, residentialSourceAvailable]);

  const residentialPedestrianCount = residentialSourceAvailable
    ? pedestrianSourceAllocation.residential
    : 0;
  const publicTransportPedestrianCount = publicTransportSourceAvailable
    ? pedestrianSourceAllocation.publicTransport
    : 0;
  const allocatedIndependentPedestrians = (
    residentialPedestrianCount + publicTransportPedestrianCount
  );
  const sourceAllocationValid = allocatedIndependentPedestrians === pedestrianCount;
  const vehicleGenerationPointIds = vehicleGenerationPoints.map((point) => point.id).join("|");

  useEffect(() => {
    setVehicleOriginAllocationMode("percentage");
    setVehicleOriginAllocationValues(equalOriginPercentages(vehicleGenerationPoints));
  }, [vehicleGenerationPointIds]);

  const vehicleOriginAllocationTotal = vehicleGenerationPoints.reduce(
    (sum, point) => sum + (vehicleOriginAllocationValues[point.id] ?? 0),
    0,
  );
  const vehicleOriginAllocationValid = vehicleGenerationPoints.length === 0 || (
    vehicleOriginAllocationMode === "percentage"
      ? Math.abs(vehicleOriginAllocationTotal - 100) < 0.01
        && vehicleGenerationPoints.every((point) => (
          Number.isFinite(vehicleOriginAllocationValues[point.id])
          && (vehicleOriginAllocationValues[point.id] ?? 0) >= 0
          && (vehicleOriginAllocationValues[point.id] ?? 0) <= 100
        ))
      : vehicleOriginAllocationTotal === vehicleCount
        && vehicleGenerationPoints.every((point) => (
          Number.isInteger(vehicleOriginAllocationValues[point.id])
          && (vehicleOriginAllocationValues[point.id] ?? 0) >= 0
        ))
  );
  const resolvedVehicleOriginCounts = vehicleOriginAllocationMode === "percentage"
    ? allocateVehicleCounts(vehicleGenerationPoints, vehicleOriginAllocationValues, vehicleCount)
    : Object.fromEntries(vehicleGenerationPoints.map((point) => [
        point.id,
        vehicleOriginAllocationValues[point.id] ?? 0,
      ]));
  const vehicleOriginAllocations: VehicleOriginAllocation[] | undefined = vehicleGenerationPoints.length
    ? vehicleGenerationPoints.map((point) => ({
        origin_id: point.id,
        vehicle_count: resolvedVehicleOriginCounts[point.id] ?? 0,
      }))
    : undefined;

  const changeVehicleOriginAllocationMode = (nextMode: VehicleOriginAllocationMode) => {
    if (nextMode === vehicleOriginAllocationMode) return;
    if (nextMode === "count") {
      const percentages = vehicleOriginAllocationValid
        ? vehicleOriginAllocationValues
        : equalOriginPercentages(vehicleGenerationPoints);
      setVehicleOriginAllocationValues(
        allocateVehicleCounts(vehicleGenerationPoints, percentages, vehicleCount),
      );
    } else {
      setVehicleOriginAllocationValues(
        vehicleCount > 0 && vehicleOriginAllocationValid
          ? Object.fromEntries(vehicleGenerationPoints.map((point) => [
              point.id,
              (vehicleOriginAllocationValues[point.id] ?? 0) * 100 / vehicleCount,
            ]))
          : equalOriginPercentages(vehicleGenerationPoints),
      );
    }
    setVehicleOriginAllocationMode(nextMode);
  };

  useEffect(() => {
    if (buildingClassificationId === NO_BUILDING_CLASSIFICATION) return;
    if (buildingClassifications.some((classification) => classification.id === buildingClassificationId)) return;
    setBuildingClassificationId(NO_BUILDING_CLASSIFICATION);
  }, [buildingClassificationId, buildingClassifications]);

  useEffect(() => {
    if (!simulationInfoOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!simulationInfoRef.current?.contains(event.target as Node)) {
        setSimulationInfoOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSimulationInfoOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [simulationInfoOpen]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        RUN_HISTORY_COLUMN_WIDTHS_KEY,
        JSON.stringify(runHistoryColumnWidths),
      );
    } catch {
      // Resizing still works for the current page if browser storage is unavailable.
    }
  }, [runHistoryColumnWidths]);

  const runHistoryTableWidth = RUN_HISTORY_COLUMNS.reduce(
    (total, column) => total + runHistoryColumnWidths[column.id],
    0,
  );

  const startRunHistoryColumnResize = (
    column: typeof RUN_HISTORY_COLUMNS[number],
    event: React.PointerEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = runHistoryColumnWidths[column.id];
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const resize = (pointerEvent: PointerEvent) => {
      const nextWidth = Math.min(
        Math.max(startWidth + pointerEvent.clientX - startX, column.minWidth),
        600,
      );
      setRunHistoryColumnWidths((current) => ({
        ...current,
        [column.id]: Math.round(nextWidth),
      }));
    };
    const finish = () => {
      document.removeEventListener("pointermove", resize);
      document.removeEventListener("pointerup", finish);
      document.removeEventListener("pointercancel", finish);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
    };
    document.addEventListener("pointermove", resize);
    document.addEventListener("pointerup", finish);
    document.addEventListener("pointercancel", finish);
  };

  const refreshHistory = useCallback(async (quiet = false) => {
    if (!modelId) return;
    if (!quiet) setLoadingHistory(true);
    try {
      const [history, status] = await Promise.all([
        listSimulationRuns(modelId),
        getSimulationQueueStatus(),
      ]);
      setRuns(history);
      setQueueStatus(status);
      if (!quiet) setError("");
    } catch (caughtError) {
      if (!quiet) {
        setError(caughtError instanceof Error ? caughtError.message : "Could not load history.");
      }
    } finally {
      if (!quiet) setLoadingHistory(false);
    }
  }, [modelId]);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const hasActiveRun = useMemo(
    () => runs.some((run) => ACTIVE_STATUSES.has(run.status)),
    [runs],
  );
  const hasRunningCalibration = useMemo(
    () => calibrations.some((item) => item.status === "running"),
    [calibrations],
  );
  const runningRuns = useMemo(
    () => runs.filter((run) => run.status === "running"),
    [runs],
  );
  const queuedRuns = useMemo(
    () => runs
      .filter((run) => run.status === "queued")
      .sort((left, right) => (left.queue_position ?? Number.MAX_SAFE_INTEGER) - (right.queue_position ?? Number.MAX_SAFE_INTEGER)),
    [runs],
  );

  useEffect(() => {
    if (!hasActiveRun && !hasRunningCalibration) return;
    const timer = window.setInterval(() => {
      void refreshHistory(true);
      void refreshCalibrations();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, hasRunningCalibration, refreshCalibrations, refreshHistory]);

  const currentSimulationRequest = (): SimulationRunRequest => ({
    vehicle_count: vehicleCount,
    pedestrian_count: pedestrianCount,
    total_people: totalPeople,
    vehicle_percentage: vehiclePercentage,
    building_classification_id: buildingClassificationId === NO_BUILDING_CLASSIFICATION
      ? null
      : buildingClassificationId,
    residential_pedestrian_count: residentialPedestrianCount,
    public_transport_pedestrian_count: publicTransportPedestrianCount,
    duration_hours: durationHours,
    simulation_start_at: simulationStartAt,
    simulation_timezone: SIMULATION_TIMEZONE,
    mode,
    pedestrian_model: pedestrianModel,
    diagnostic_tracing: diagnosticTracing,
    vehicle_traffic_model: vehicleTrafficModel,
    pedestrian_traffic_model: pedestrianTrafficModel,
    vehicle_fourier_parameters: vehicleFourierParameters,
    pedestrian_fourier_parameters: pedestrianFourierParameters,
    parking_choice: parkingChoice,
    vehicle_origin_allocations: vehicleOriginAllocations,
  });

  const startRun = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!modelId) return;
    setError("");
    setQueueNotice("");
    setStarting(true);
    try {
      const created = await startSimulationRun(modelId, currentSimulationRequest());
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      setQueueNotice(
        created.queue_position
          ? `Simulation added at global queue position ${created.queue_position}. You can change the setup and add another run now.`
          : "Simulation added to the queue. You can change the setup and add another run now.",
      );
      await refreshHistory(true);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not start simulation.");
    } finally {
      setStarting(false);
    }
  };

  const startCalibration = async () => {
    if (!modelId) return;
    setError("");
    setQueueNotice("");
    setStartingCalibration(true);
    try {
      const subjects: CalibrationSubject[] = calibrationSubject === "both"
        ? ["vehicles", "pedestrians"]
        : [calibrationSubject];
      const created = await startFlowCalibration(modelId, {
        name: calibrationName,
        real_world_source_id: calibrationSourceId,
        detector_logical_id: calibrationDetectorId,
        subjects,
        iterations: calibrationIterations,
        step_percentage: calibrationStepPercentage,
        simulation: currentSimulationRequest(),
      });
      setCalibrations((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setQueueNotice(
        `Calibration “${created.name}” started. All settings are locked; only the selected Fourier peak percentages will change.`,
      );
      await refreshHistory(true);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not start flow calibration.");
    } finally {
      setStartingCalibration(false);
    }
  };

  const confirmDeleteRun = async () => {
    if (!modelId || !runPendingDeletion) return;
    const runId = runPendingDeletion.id;
    setDeletingRunId(runId);
    setError("");
    try {
      await deleteSimulationRun(modelId, runId);
      setRuns((current) => current.filter((run) => run.id !== runId));
      setRunPendingDeletion(null);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not delete the simulation run.");
    } finally {
      setDeletingRunId(null);
    }
  };

  const confirmStopRun = async () => {
    if (!modelId || !runPendingStop) return;
    const runId = runPendingStop.id;
    setStoppingRunId(runId);
    setError("");
    try {
      const updated = await stopSimulationRun(modelId, runId);
      setRuns((current) => current.map((run) => run.id === runId ? updated : run));
      setRunPendingStop(null);
      await refreshHistory(true);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "Could not stop the simulation.");
    } finally {
      setStoppingRunId(null);
    }
  };

  if (!modelId) {
    return (
      <main className="grid min-h-full place-items-center bg-muted/30 p-6">
        <Card className="w-full max-w-lg">
          <CardHeader>
            <CardTitle>{loadingModel ? "Loading selected model…" : "No model selected"}</CardTitle>
            <CardDescription>Select and save a model before configuring a simulation.</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button variant="outline" onClick={onHome}>Go home</Button>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="min-h-full overflow-y-auto bg-muted/30">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-5 sm:px-6 sm:py-7">
        <header className="mb-7 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
              <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={onBack}>
                <ArrowLeft className="size-4" /> Model
              </button>
              <span>/</span><span>Simulation</span>
            </div>
            <h1 className="text-3xl font-semibold tracking-tight">Simulation</h1>
            <p className="mt-1 text-sm text-muted-foreground">{modelName}</p>
          </div>
          <div className="flex flex-col items-end gap-3">
            <TopNavigation onHome={onHome} onAnalytics={onAnalytics} onDocumentation={onDocumentation} />
            <div className="flex gap-2">
            <Button variant="outline" onClick={onAnalytics}>Open analytics</Button>
            <Button variant="outline" onClick={() => refreshHistory()} disabled={loadingHistory}>
              <RefreshCw className={loadingHistory ? "animate-spin" : ""} /> Refresh history
            </Button>
            </div>
          </div>
        </header>

        {error && <Alert variant="destructive" className="mb-5 bg-red-50 dark:bg-red-950/40"><AlertDescription>{error}</AlertDescription></Alert>}
        {queueNotice && <Alert className="mb-5 border-green-200 bg-green-50/80 text-green-950 dark:border-green-900 dark:bg-green-950/35 dark:text-green-100"><ListOrdered className="size-4" /><AlertDescription>{queueNotice}</AlertDescription></Alert>}

        <form onSubmit={startRun}>
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(600px,1fr)_minmax(0,1.4fr)]">
          <Card className="shadow-sm xl:sticky xl:top-5">
            <CardHeader className="p-5">
              <div className="flex items-start justify-between gap-3">
                <CardTitle className="flex items-center gap-2"><Play className="size-5 text-primary" /> New simulation</CardTitle>
                <div ref={simulationInfoRef} className="relative">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="-mr-2 -mt-2 size-8 rounded-full"
                    aria-label="Information about what happens after starting a simulation"
                    aria-expanded={simulationInfoOpen}
                    aria-controls="new-simulation-information"
                    onClick={() => setSimulationInfoOpen((open) => !open)}
                  >
                    <Info className="size-4" />
                  </Button>
                  {simulationInfoOpen && (
                    <div
                      id="new-simulation-information"
                      role="dialog"
                      aria-label="What happens after you start"
                      className="absolute right-0 top-9 z-50 w-[min(24rem,calc(100vw-2rem))] rounded-lg border bg-popover p-4 text-popover-foreground shadow-lg"
                    >
                      <p className="text-sm font-semibold">What happens after you start?</p>
                      <ol className="mt-2 list-decimal space-y-1.5 pl-4 text-xs leading-5 text-muted-foreground">
                        <li>The app builds the road and walking network, parking areas, detectors, routes, and travel demand.</li>
                        <li>SUMO advances the scenario second by second while vehicles park and pedestrians complete their trips.</li>
                        <li>Agents still travelling after the selected window finish, then analytics and output files are finalized.</li>
                      </ol>
                      <p className="mt-3 text-xs leading-5 text-muted-foreground"><strong className="text-foreground">For the fastest run:</strong> choose background SUMO. SUMO GUI adds live visualization and is slower. Smaller maps, shorter durations, and fewer people also finish sooner.</p>
                    </div>
                  )}
                </div>
              </div>
              <CardDescription>Create people who arrive by car, from residential buildings, or from saved public-transport origins and travel to a destination building. Queued runs are dispatched across the available simulation workers.</CardDescription>
            </CardHeader>
            <CardContent className="p-5 pt-0">
              <div className="space-y-5">
                <div className="space-y-3 rounded-lg border p-3">
                  <div className="space-y-2">
                    <Label htmlFor="total-people">Total people</Label>
                    <Input
                      id="total-people"
                      type="number"
                      min={1}
                      max={1000000}
                      required
                      value={totalPeople}
                      onChange={(event) => {
                        const nextTotal = Math.min(Math.max(Number(event.target.value), 0), 1000000);
                        setTotalPeople(nextTotal);
                        setVehicleCount(Math.min(Math.round(nextTotal * vehiclePercentage / 100), nextTotal));
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <Label htmlFor="arrival-mode-split">Arriving by car</Label>
                      <span className="tabular-nums text-muted-foreground">{vehiclePercentage}%</span>
                    </div>
                    <Slider
                      id="arrival-mode-split"
                      min={0}
                      max={100}
                      step={1}
                      value={[vehiclePercentage]}
                      onValueChange={([percentage]) => setVehicleCount(Math.round(totalPeople * percentage / 100))}
                      aria-label="Percentage of people arriving by car"
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="vehicle-count" className="flex items-center gap-2"><Car className="size-4 text-blue-600" /> By car</Label>
                      <Input id="vehicle-count" type="number" min={0} max={totalPeople} required value={vehicleCount} onChange={(event) => setVehicleCount(Math.min(Math.max(Number(event.target.value), 0), totalPeople))} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="pedestrian-count" className="flex items-center gap-2"><Footprints className="size-4 text-orange-500" /> Independent walking arrivals</Label>
                      <Input id="pedestrian-count" type="number" min={0} max={totalPeople} required value={pedestrianCount} onChange={(event) => setVehicleCount(totalPeople - Math.min(Math.max(Number(event.target.value), 0), totalPeople))} />
                    </div>
                  </div>
                  <p className="text-xs leading-5 text-muted-foreground">One car represents one person. After the car parks, that person is created at the parking area and walks to their assigned building.</p>
                </div>

                <div className="space-y-3 rounded-lg border p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="flex items-center gap-2 text-sm font-medium"><Car className="size-4 text-blue-600" /> Vehicle entry allocation</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">Choose how this run's {vehicleCount.toLocaleString()} cars are divided between the vehicle generation points saved in the model.</p>
                    </div>
                    {!!vehicleGenerationPoints.length && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const percentages = equalOriginPercentages(vehicleGenerationPoints);
                          setVehicleOriginAllocationValues(
                            vehicleOriginAllocationMode === "percentage"
                              ? percentages
                              : allocateVehicleCounts(vehicleGenerationPoints, percentages, vehicleCount),
                          );
                        }}
                      >
                        Divide equally
                      </Button>
                    )}
                  </div>

                  {vehicleGenerationPoints.length ? (
                    <>
                      <label className="block space-y-1.5 text-xs font-medium">
                        Input format
                        <Select value={vehicleOriginAllocationMode} onValueChange={(value) => changeVehicleOriginAllocationMode(value as VehicleOriginAllocationMode)}>
                          <SelectTrigger className="mt-1.5"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="percentage">Percentages</SelectItem>
                            <SelectItem value="count">Exact car counts</SelectItem>
                          </SelectContent>
                        </Select>
                      </label>
                      <div className="space-y-2">
                        {vehicleGenerationPoints.map((point) => {
                          const count = resolvedVehicleOriginCounts[point.id] ?? 0;
                          const percentage = vehicleCount > 0 ? count * 100 / vehicleCount : 0;
                          return (
                            <div key={point.id} className="grid gap-2 rounded-md border bg-background p-2.5 sm:grid-cols-[minmax(0,1fr)_8rem] sm:items-center">
                              <div className="min-w-0">
                                <p className="truncate text-xs font-medium" title={point.name}>{point.name}</p>
                                <p className="truncate font-mono text-[10px] text-muted-foreground" title={point.laneSelection.laneId}>Lane {point.laneSelection.laneId}</p>
                              </div>
                              <div>
                                <div className="relative">
                                  <Input
                                    type="number"
                                    min={0}
                                    max={vehicleOriginAllocationMode === "percentage" ? 100 : 1000000}
                                    step={vehicleOriginAllocationMode === "percentage" ? 0.1 : 1}
                                    value={vehicleOriginAllocationValues[point.id] ?? 0}
                                    onChange={(event) => setVehicleOriginAllocationValues((current) => ({
                                      ...current,
                                      [point.id]: vehicleOriginAllocationMode === "count"
                                        ? Math.max(Math.round(Number(event.target.value)), 0)
                                        : Math.min(Math.max(Number(event.target.value), 0), 100),
                                    }))}
                                    aria-label={`${point.name} vehicle allocation ${vehicleOriginAllocationMode}`}
                                    className="pr-9 text-right tabular-nums"
                                  />
                                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">{vehicleOriginAllocationMode === "percentage" ? "%" : "cars"}</span>
                                </div>
                                <p className="mt-1 text-right text-[10px] text-muted-foreground">
                                  {vehicleOriginAllocationMode === "percentage"
                                    ? `${count.toLocaleString()} cars`
                                    : formatPercentage(percentage)}
                                </p>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      <div className={`flex items-center justify-between gap-3 rounded-md px-3 py-2 text-xs ${vehicleOriginAllocationValid ? "bg-muted/60" : "bg-red-50 text-red-700 dark:bg-red-950/35 dark:text-red-300"}`}>
                        <span>Allocated across {vehicleGenerationPoints.length} entry point{vehicleGenerationPoints.length === 1 ? "" : "s"}</span>
                        <strong className="tabular-nums">
                          {vehicleOriginAllocationMode === "percentage"
                            ? `${Number(vehicleOriginAllocationTotal.toFixed(2))}% / 100%`
                            : `${vehicleOriginAllocationTotal.toLocaleString()} / ${vehicleCount.toLocaleString()} cars`}
                        </strong>
                      </div>
                      {!vehicleOriginAllocationValid && (
                        <p className="text-xs leading-5 text-red-600">{vehicleOriginAllocationMode === "percentage" ? "Vehicle entry percentages must add up to exactly 100%." : `Vehicle entry counts must add up to exactly ${vehicleCount.toLocaleString()} cars.`}</p>
                      )}
                    </>
                  ) : (
                    <p className="rounded-md border border-dashed p-3 text-xs leading-5 text-muted-foreground">No vehicle generation points are saved. This run will use the automatic fringe-road origins. Add points from <strong>Public &amp; Vehicle Origins</strong> in the model editor to configure an allocation.</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="building-classification">Building demand classification</Label>
                  <Select value={buildingClassificationId} onValueChange={setBuildingClassificationId}>
                    <SelectTrigger id="building-classification"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_BUILDING_CLASSIFICATION}>No classification</SelectItem>
                      {buildingClassifications.map((classification) => (
                        <SelectItem key={classification.id} value={classification.id}>{classification.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {selectedDemandClassification ? (
                    <Alert className="border-blue-200 bg-blue-50/70 text-blue-950 dark:border-blue-900 dark:bg-blue-950/35 dark:text-blue-100">
                      <Info className="size-4" />
                      <AlertDescription className="text-xs leading-5">
                        {classifiedSelectedBuildingCount} selected building{classifiedSelectedBuildingCount === 1 ? "" : "s"} use type-specific demand weights. {unclassifiedSelectedBuildingCount} unclassified building{unclassifiedSelectedBuildingCount === 1 ? "" : "s"} remain eligible and receive equal random treatment with neutral 50/50 weights.
                      </AlertDescription>
                    </Alert>
                  ) : (
                    <p className="text-xs leading-5 text-muted-foreground">All selected buildings are eligible destinations and receive equal random treatment. Choose an optional classification to apply its type-specific destination weights. Only the optional residential-origin source below reserves a type name: Residential.</p>
                  )}
                  <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
                    <div>
                      <p className="text-sm font-medium">Where pedestrians begin walking</p>
                      <p className="text-xs leading-5 text-muted-foreground">Residential and public-transport counts divide the <strong>{pedestrianCount.toLocaleString()}</strong> independently generated walkers. Parked drivers are derived from car arrivals. Together these sources can never exceed the {totalPeople.toLocaleString()} people in the run.</p>
                    </div>

                    <div className={`space-y-2 rounded-md border p-3 ${!residentialSourceAvailable ? "bg-muted/55 opacity-70" : "bg-background"}`}>
                      <div className="flex items-center justify-between gap-3">
                        <Label htmlFor="residential-pedestrian-count" className="flex items-center gap-2"><Footprints className="size-4 text-emerald-600" /> Residential areas</Label>
                        <Badge variant="outline">{formatPercentage(sourcePercentage(residentialPedestrianCount, totalPeople))}</Badge>
                      </div>
                      <Input
                        id="residential-pedestrian-count"
                        type="number"
                        min={0}
                        max={pedestrianCount}
                        disabled={!residentialSourceAvailable || pedestrianCount === 0}
                        value={residentialPedestrianCount}
                        onChange={(event) => {
                          const residential = Math.min(Math.max(Number(event.target.value), 0), pedestrianCount);
                          setPedestrianSourceAllocation({
                            residential,
                            publicTransport: publicTransportSourceAvailable
                              ? pedestrianCount - residential
                              : 0,
                          });
                        }}
                      />
                      {!selectedDemandClassification ? (
                        <p className="text-[11px] leading-4 text-muted-foreground">Select a building classification to use residential origins. Without one, this count is 0.</p>
                      ) : !hasResidentialType ? (
                        <p className="text-[11px] leading-4 text-muted-foreground">The selected classification has no type named <strong>Residential</strong>, so this count is 0.</p>
                      ) : residentialOriginBuildingCount === 0 ? (
                        <p className="text-[11px] leading-4 text-muted-foreground">The Residential type exists, but no selected building is assigned to it, so this count is 0.</p>
                      ) : (
                        <p className="text-[11px] leading-4 text-muted-foreground">Generated across {residentialOriginBuildingCount} selected Residential building{residentialOriginBuildingCount === 1 ? "" : "s"}. Matching is case-insensitive.</p>
                      )}
                    </div>

                    <div className={`space-y-2 rounded-md border p-3 ${!publicTransportSourceAvailable ? "bg-muted/55 opacity-70" : "bg-background"}`}>
                      <div className="flex items-center justify-between gap-3">
                        <Label htmlFor="public-transport-pedestrian-count" className="flex items-center gap-2"><Footprints className="size-4 text-fuchsia-600" /> Public transport origins</Label>
                        <Badge variant="outline">{formatPercentage(sourcePercentage(publicTransportPedestrianCount, totalPeople))}</Badge>
                      </div>
                      <Input
                        id="public-transport-pedestrian-count"
                        type="number"
                        min={0}
                        max={pedestrianCount}
                        disabled={!publicTransportSourceAvailable || pedestrianCount === 0}
                        value={publicTransportPedestrianCount}
                        onChange={(event) => {
                          const publicTransport = Math.min(Math.max(Number(event.target.value), 0), pedestrianCount);
                          setPedestrianSourceAllocation({
                            residential: residentialSourceAvailable
                              ? pedestrianCount - publicTransport
                              : 0,
                            publicTransport,
                          });
                        }}
                      />
                      {publicTransportOriginCount === null ? (
                        <p className="text-[11px] leading-4 text-muted-foreground">Checking the saved model for Public Transportation Origins…</p>
                      ) : publicTransportOriginCount === 0 ? (
                        <p className="text-[11px] leading-4 text-muted-foreground">The model has no saved Public Transportation Origin, so this count is 0.</p>
                      ) : (
                        <p className="text-[11px] leading-4 text-muted-foreground">Generated across {publicTransportOriginCount} saved transit point{publicTransportOriginCount === 1 ? "" : "s"}.</p>
                      )}
                    </div>

                    <div className="space-y-2 rounded-md border bg-background p-3">
                      <div className="flex items-center justify-between gap-3">
                        <Label htmlFor="parked-driver-pedestrian-count" className="flex items-center gap-2"><Car className="size-4 text-blue-600" /> Parked-car drivers</Label>
                        <Badge variant="outline">{formatPercentage(sourcePercentage(vehicleCount, totalPeople))}</Badge>
                      </div>
                      <Input id="parked-driver-pedestrian-count" type="number" disabled value={vehicleCount} />
                      <p className="text-[11px] leading-4 text-muted-foreground">Not editable. One driver is planned per car and becomes a pedestrian only after that car successfully begins parking. If a car cannot park, no driver is created from it.</p>
                    </div>

                    <div className="flex items-center justify-between gap-3 rounded-md bg-muted/60 px-3 py-2 text-xs">
                      <span>Allocated walking sources</span>
                      <strong className={sourceAllocationValid ? "text-foreground" : "text-red-600"}>
                        {(allocatedIndependentPedestrians + vehicleCount).toLocaleString()} / {totalPeople.toLocaleString()} · {formatPercentage(sourcePercentage(allocatedIndependentPedestrians + vehicleCount, totalPeople))}
                      </strong>
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="simulation-start" className="flex items-center gap-2"><Clock3 className="size-4" /> Simulated start date and time</Label>
                  <Input id="simulation-start" type="datetime-local" required value={simulationStartAt} onChange={(event) => setSimulationStartAt(event.target.value)} />
                  <p className="text-xs leading-5 text-muted-foreground">{formatLocalWindow(simulationStartAt, durationHours)}</p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="duration-hours" className="flex items-center gap-2"><Clock3 className="size-4" /> Duration in hours</Label>
                  <Input id="duration-hours" type="number" min={1} max={168} required value={durationHours} onChange={(event) => setDurationHours(Number(event.target.value))} />
                  <p className="text-xs text-muted-foreground">Minimum 1 hour, maximum 168 hours (1 week).</p>
                </div>

                <fieldset className="space-y-3">
                  <legend className="text-sm font-medium">Traffic models</legend>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2 rounded-lg border p-3">
                      <Label htmlFor="vehicle-traffic-model" className="flex items-center gap-2"><Car className="size-4 text-blue-600" /> Arriving-by-car profile</Label>
                      <Select value={vehicleTrafficModel} onValueChange={(value) => setVehicleTrafficModel(value as TrafficModel)}>
                        <SelectTrigger id="vehicle-traffic-model"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="constant">Constant distribution</SelectItem><SelectItem value="linear">Linear distribution</SelectItem><SelectItem value="normal">Normal distribution</SelectItem><SelectItem value="fourier">Fourier distribution</SelectItem></SelectContent>
                      </Select>
                      {vehicleTrafficModel === "fourier" && <FourierControls idPrefix="vehicle-fourier" value={vehicleFourierParameters} durationHours={durationHours} onChange={setVehicleFourierParameters} />}
                    </div>
                    <div className="space-y-2 rounded-lg border p-3">
                      <Label htmlFor="pedestrian-traffic-model" className="flex items-center gap-2"><Footprints className="size-4 text-orange-500" /> Pedestrian-departure profile</Label>
                      <Select value={pedestrianTrafficModel} onValueChange={(value) => setPedestrianTrafficModel(value as TrafficModel)}>
                        <SelectTrigger id="pedestrian-traffic-model"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="constant">Constant distribution</SelectItem><SelectItem value="linear">Linear distribution</SelectItem><SelectItem value="normal">Normal distribution</SelectItem><SelectItem value="fourier">Fourier distribution</SelectItem></SelectContent>
                      </Select>
                      {pedestrianTrafficModel === "fourier" && <FourierControls idPrefix="pedestrian-fourier" value={pedestrianFourierParameters} durationHours={durationHours} onChange={setPedestrianFourierParameters} />}
                    </div>
                  </div>
                </fieldset>

                <fieldset className="space-y-2">
                  <legend className="mb-2 text-sm font-medium">Pedestrian behavior</legend>
                  <RadioGroup value={pedestrianModel} onValueChange={(value) => setPedestrianModel(value as PedestrianModel)} className="grid gap-2 sm:grid-cols-2">
                    <Label htmlFor="pedestrian-model-striping" className={`cursor-pointer rounded-lg border p-3 text-left transition ${pedestrianModel === "striping" ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}>
                      <RadioGroupItem id="pedestrian-model-striping" value="striping" className="sr-only" />
                      <Footprints className="mb-2 size-5 text-orange-500" />
                      <span className="block text-sm font-medium">Interactive</span>
                      <span className="text-xs font-normal leading-4 text-muted-foreground">SUMO striping model. Pedestrians react to each other and vehicles; more realistic but slower in dense crowds.</span>
                    </Label>
                    <Label htmlFor="pedestrian-model-fast" className={`cursor-pointer rounded-lg border p-3 text-left transition ${pedestrianModel === "nonInteracting" ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}>
                      <RadioGroupItem id="pedestrian-model-fast" value="nonInteracting" className="sr-only" />
                      <Footprints className="mb-2 size-5 text-emerald-600" />
                      <span className="block text-sm font-medium">Fast</span>
                      <span className="text-xs font-normal leading-4 text-muted-foreground">Non-interacting pedestrians keep their routes but do not model crowd or vehicle conflicts. Detector crossings use the Fast-mode compatibility counter.</span>
                    </Label>
                  </RadioGroup>
                  {pedestrianModel === "nonInteracting" && (
                    <Alert className="border-amber-200 bg-amber-50/70 text-amber-950 dark:border-amber-900 dark:bg-amber-950/35 dark:text-amber-100">
                      <Info className="size-4" />
                      <AlertDescription className="text-xs leading-5">Fast mode changes simulation fidelity. Use Interactive mode when pedestrian congestion, avoidance, or collision behavior matters to the study.</AlertDescription>
                    </Alert>
                  )}
                </fieldset>

                <fieldset className="space-y-2">
                  <legend className="mb-2 text-sm font-medium">Execution mode</legend>
                  <RadioGroup value={mode} onValueChange={(value) => setMode(value as SimulationMode)} className="grid grid-cols-2 gap-2">
                    <Label htmlFor="mode-sumo" className={`cursor-pointer rounded-lg border p-3 text-left transition ${mode === "sumo" ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}><RadioGroupItem id="mode-sumo" value="sumo" className="sr-only" /><Terminal className="mb-2 size-5" /><span className="block text-sm font-medium">SUMO</span><span className="text-xs font-normal text-muted-foreground">Faster, runs in background</span></Label>
                    <Label htmlFor="mode-gui" className={`cursor-pointer rounded-lg border p-3 text-left transition ${mode === "sumo-gui" ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}><RadioGroupItem id="mode-gui" value="sumo-gui" className="sr-only" /><MonitorPlay className="mb-2 size-5" /><span className="block text-sm font-medium">SUMO GUI</span><span className="text-xs font-normal text-muted-foreground">Slower, opens visualization</span></Label>
                  </RadioGroup>
                </fieldset>

                <div className="flex items-start gap-3 rounded-lg border bg-muted/25 p-3">
                  <Checkbox id="diagnostic-tracing" checked={diagnosticTracing} onCheckedChange={(checked) => setDiagnosticTracing(checked === true)} />
                  <div className="space-y-1">
                    <Label htmlFor="diagnostic-tracing" className="cursor-pointer text-sm">Full TraCI diagnostic trace</Label>
                    <p className="text-xs leading-5 text-muted-foreground">Off by default. Enable only to reproduce a SUMO/TraCI failure; large runs can create several gigabytes of trace data and run considerably slower.</p>
                  </div>
                </div>

                <Button className="w-full" type="submit" disabled={starting || loadingModel || selectedBuildingIds.length === 0 || (vehicleCount > 0 && parkingAreaCount === 0) || !sourceAllocationValid || !vehicleOriginAllocationValid || totalPeople < 1 || durationHours < 1 || durationHours > 168}>
                  <ListOrdered /> {starting ? "Adding…" : "Add simulation to queue"}
                </Button>
                <p className="text-xs leading-5 text-muted-foreground">The current setup and saved model inputs are snapshotted when you add the run. You can immediately change these controls and add another setup without changing runs already waiting.</p>
                {selectedBuildingIds.length === 0 && <p className="text-xs text-red-600">Select and save at least one destination building before running a simulation.</p>}
                {vehicleCount > 0 && parkingAreaCount === 0 && <p className="text-xs text-red-600">Select and save at least one parking area for people arriving by car.</p>}
                {!sourceAllocationValid && pedestrianCount > 0 && <p className="text-xs text-red-600">Allocate all {pedestrianCount.toLocaleString()} independently generated pedestrians to available Residential buildings and/or Public Transportation Origins before starting.</p>}
                {!vehicleOriginAllocationValid && <p className="text-xs text-red-600">Complete the vehicle entry allocation before starting.</p>}
              </div>
            </CardContent>
          </Card>

          <div className="space-y-5">
          <Card className="shadow-sm">
            <CardHeader className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>Parking-search choice model</CardTitle>
                  <CardDescription className="mt-1 max-w-3xl">
                    Larger weights make that factor more important relative to the others. These values affect both the first parking choice and weighted rerouting after a failed visit.
                  </CardDescription>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={() => setParkingChoice({ ...DEFAULT_PARKING_CHOICE, weights: { ...DEFAULT_PARKING_CHOICE.weights } })}>
                  Reset defaults
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-5 pt-0">
              <ParkingChoiceControls
                value={parkingChoice}
                onChange={setParkingChoice}
              />
            </CardContent>
          </Card>

          <Card className="shadow-sm">
            <CardHeader className="p-5">
              <CardTitle className="flex items-center gap-2"><RefreshCw className="size-5 text-primary" /> Locked Fourier flow calibration</CardTitle>
              <CardDescription className="mt-1 max-w-3xl">
                Run sequential iterations against a weekly-average sensor. Agent totals, classification, source allocation, date, duration, behavior, random seed, peak count, peak width, and harmonics are frozen. Only peak percentages change.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 p-5 pt-0">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="space-y-1.5 text-sm font-medium">
                  Calibration name
                  <Input className="mt-1.5" value={calibrationName} maxLength={120} onChange={(event) => setCalibrationName(event.target.value)} />
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  Number of iterations
                  <Input className="mt-1.5" type="number" min={1} max={100} value={calibrationIterations} onChange={(event) => setCalibrationIterations(Number(event.target.value))} />
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  Minimum percentage step
                  <div className="relative mt-1.5">
                    <Input className="pr-8" type="number" min={0.1} max={100} step={0.1} value={calibrationStepPercentage} onChange={(event) => setCalibrationStepPercentage(Number(event.target.value))} />
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">%</span>
                  </div>
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  Physical sensor
                  <Select value={calibrationSourceId} onValueChange={setCalibrationSourceId}>
                    <SelectTrigger className="mt-1.5 font-normal"><SelectValue placeholder="Select a sensor" /></SelectTrigger>
                    <SelectContent>{realWorldSources.map((source) => <SelectItem key={source.id} value={source.id}>{source.name}</SelectItem>)}</SelectContent>
                  </Select>
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  Simulation detector
                  <Select value={calibrationDetectorId} onValueChange={setCalibrationDetectorId}>
                    <SelectTrigger className="mt-1.5 font-normal"><SelectValue placeholder="Select an E3 detector" /></SelectTrigger>
                    <SelectContent>{calibrationDetectors.map((detector) => <SelectItem key={detector.id} value={detector.id}>{detector.name}</SelectItem>)}</SelectContent>
                  </Select>
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  Percentages to update
                  <Select value={calibrationSubject} onValueChange={(value) => setCalibrationSubject(value as typeof calibrationSubject)}>
                    <SelectTrigger className="mt-1.5 font-normal"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="vehicles">Vehicle peaks</SelectItem><SelectItem value="pedestrians">Pedestrian peaks</SelectItem><SelectItem value="both">Vehicle and pedestrian peaks</SelectItem></SelectContent>
                  </Select>
                </label>
              </div>
              <Alert className="bg-muted/35">
                <Info className="size-4" />
                <AlertDescription className="text-xs leading-5">
                  Each peak uses its equal-width time cell. With {vehicleFourierParameters.peak_count} vehicle peaks over {durationHours} hours, cells are {Number((durationHours * 60 / vehicleFourierParameters.peak_count).toFixed(2))} minutes and the first peak center is {Number((durationHours * 30 / vehicleFourierParameters.peak_count).toFixed(2))} minutes after the simulation starts. Early iterations use the real/simulated ratio; later iterations learn a saturation response from earlier results and use a Hill fit when reliable. Every nonzero change is quantized to at least {calibrationStepPercentage || 1}%.
                </AlertDescription>
              </Alert>
              {(vehicleTrafficModel !== "fourier" || pedestrianTrafficModel !== "fourier") && <p className="text-xs text-red-600">Select Fourier for both traffic models before starting calibration.</p>}
              {mode !== "sumo" && <p className="text-xs text-red-600">Calibration requires background SUMO mode.</p>}
              {(calibrationSubject === "pedestrians" || calibrationSubject === "both") && <p className="text-xs leading-5 text-amber-700 dark:text-amber-300">Pedestrian calibration stops after an iteration if the selected detector records zero pedestrian crossings while the physical sensor is positive. A nonzero generated pedestrian population does not guarantee that routes cross this detector.</p>}
              <Button
                className="w-full"
                type="button"
                variant="secondary"
                onClick={() => void startCalibration()}
                disabled={startingCalibration || vehicleTrafficModel !== "fourier" || pedestrianTrafficModel !== "fourier" || mode !== "sumo" || !calibrationSourceId || !calibrationDetectorId || calibrationIterations < 1 || calibrationIterations > 100 || calibrationStepPercentage < 0.1 || calibrationStepPercentage > 100 || !sourceAllocationValid || !vehicleOriginAllocationValid}
              >
                <RefreshCw className={startingCalibration ? "animate-spin" : ""} /> {startingCalibration ? "Starting calibration…" : `Start ${calibrationIterations} locked iteration${calibrationIterations === 1 ? "" : "s"}`}
              </Button>
            </CardContent>
          </Card>

          <Card className="shadow-sm">
            <CardHeader className="p-5">
              <CardTitle className="flex items-center gap-2"><ListOrdered className="size-5 text-primary" /> Simulation queue</CardTitle>
              <CardDescription>Durable FIFO dispatch with multiple simulations running concurrently.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 p-5 pt-0">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-lg border bg-muted/25 p-3">
                  <p className="text-xs text-muted-foreground">Running for this model</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{runningRuns.length}</p>
                </div>
                <div className="rounded-lg border bg-muted/25 p-3">
                  <p className="text-xs text-muted-foreground">Waiting for this model</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{queuedRuns.length}</p>
                </div>
                <div className="rounded-lg border bg-muted/25 p-3">
                  <p className="text-xs text-muted-foreground">Running globally</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{queueStatus?.running_count ?? "—"}</p>
                </div>
                <div className="rounded-lg border bg-muted/25 p-3">
                  <p className="text-xs text-muted-foreground">Worker capacity</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{queueStatus?.concurrency ?? "—"}</p>
                </div>
              </div>
              {queuedRuns.length > 0 ? (
                <p className="text-sm leading-5 text-muted-foreground">
                  Next model run: global queue position <strong className="text-foreground">{queuedRuns[0].queue_position ?? "pending"}</strong>. Queue positions include simulations created from other models.
                </p>
              ) : runningRuns.length > 0 ? (
                <p className="text-sm leading-5 text-muted-foreground">This model has no additional runs waiting. Add another setup and it will start after the work ahead of it finishes.</p>
              ) : (
                <p className="text-sm leading-5 text-muted-foreground">Nothing from this model is running or waiting. The first setup you add can start as soon as the worker is available.</p>
              )}
              <Alert className="bg-muted/35">
                <Info className="size-4" />
                <AlertDescription className="text-xs leading-5">You may close the browser after adding runs. Keep Docker and the computer running; up to {queueStatus?.concurrency ?? 2} simulations run concurrently and RabbitMQ retains additional jobs across service restarts.</AlertDescription>
              </Alert>
            </CardContent>
          </Card>

          <Card className="shadow-sm">
            <CardHeader className="p-5">
              <CardTitle>Traffic profile preview</CardTitle>
              <CardDescription>Expected arrivals over the configured simulation clock.</CardDescription>
            </CardHeader>
            <CardContent className="p-5 pt-0">
              <TrafficProfileChart
                durationHours={durationHours}
                simulationStartAt={simulationStartAt}
                vehicleCount={vehicleCount}
                pedestrianCount={pedestrianCount}
                vehicleModel={vehicleTrafficModel}
                pedestrianModel={pedestrianTrafficModel}
                vehicleFourierParameters={vehicleFourierParameters}
                pedestrianFourierParameters={pedestrianFourierParameters}
              />
            </CardContent>
          </Card>

          </div>
        </div>
        </form>

          <Card className="mt-5 max-h-[640px] overflow-hidden shadow-sm">
            <CardHeader className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2"><History className="size-5 text-primary" /> Run history</CardTitle>
                  <CardDescription className="mt-1">Standalone runs are labeled explicitly. Calibration runs are collected into expandable iteration groups and ordered from the first iteration onward.</CardDescription>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={() => setRunHistoryColumnWidths(defaultRunHistoryColumnWidths())}>
                  Reset column widths
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-5 pt-0">
              {!runs.length && !loadingHistory ? (
                <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">No simulations have been run for this model yet.</div>
              ) : (
                <div className="overflow-hidden rounded-lg border bg-background">
                  <Table
                    className="table-fixed [&_td]:break-words [&_td]:whitespace-normal [&_td]:align-top"
                    containerClassName="max-h-[500px] overflow-auto"
                    style={{ width: `${runHistoryTableWidth}px`, minWidth: "100%" }}
                  >
                    <colgroup>
                      {RUN_HISTORY_COLUMNS.map((column) => (
                        <col key={column.id} style={{ width: `${runHistoryColumnWidths[column.id]}px` }} />
                      ))}
                    </colgroup>
                    <TableHeader className="sticky top-0 z-20 bg-muted text-xs uppercase tracking-wide text-muted-foreground shadow-sm">
                      <TableRow>
                        {RUN_HISTORY_COLUMNS.map((column) => (
                          <TableHead
                            key={column.id}
                            className={`relative h-auto px-3 py-2.5 align-top ${"align" in column && column.align === "right" ? "text-right" : ""}`}
                          >
                            <span className="block break-words pr-1 leading-4 whitespace-normal">{column.label}</span>
                            <button
                              type="button"
                              className="group absolute -right-1 top-0 z-10 h-full w-2 cursor-col-resize touch-none"
                              aria-label={`Resize ${column.label} column`}
                              title="Drag to resize; double-click to restore this column"
                              onPointerDown={(event) => startRunHistoryColumnResize(column, event)}
                              onDoubleClick={() => setRunHistoryColumnWidths((current) => ({
                                ...current,
                                [column.id]: column.defaultWidth,
                              }))}
                            >
                              <span className="mx-auto block h-full w-px bg-border transition-colors group-hover:bg-primary group-focus-visible:bg-primary" />
                            </button>
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {runHistoryBlocks.map((block) => {
                        if (block.kind === "standalone") {
                          const run = block.run;
                          return (
                            <TableRun
                              key={run.id}
                              run={run}
                              deleting={deletingRunId === run.id}
                              stopping={stoppingRunId === run.id}
                              onDelete={setRunPendingDeletion}
                              onStop={setRunPendingStop}
                            />
                          );
                        }

                        const collapsed = collapsedCalibrationGroups.has(block.id);
                        const session = calibrationsById.get(block.id);
                        const completedRuns = block.runs.filter((run) => run.status === "completed").length;
                        const groupStatus: FlowCalibrationSession["status"] | "incomplete" = session?.status
                          ?? (block.runs.some((run) => ACTIVE_STATUSES.has(run.status))
                            ? "running"
                            : block.runs.some((run) => run.status === "failed")
                              ? "failed"
                              : completedRuns >= block.totalIterations
                                ? "completed"
                                : "incomplete");
                        return (
                          <Fragment key={`calibration:${block.id}`}>
                            <TableRow className="border-y-2 border-violet-200 bg-violet-50/70 hover:bg-violet-50 dark:border-violet-900 dark:bg-violet-950/30 dark:hover:bg-violet-950/40">
                              <TableCell colSpan={RUN_HISTORY_COLUMNS.length} className="px-3 py-2">
                                <button
                                  type="button"
                                  className="flex w-full items-center gap-2 text-left"
                                  onClick={() => toggleCalibrationGroup(block.id)}
                                  aria-expanded={!collapsed}
                                  aria-label={`${collapsed ? "Expand" : "Collapse"} iteration group ${block.name}`}
                                >
                                  {collapsed ? <ChevronRight className="size-4 shrink-0" /> : <ChevronDown className="size-4 shrink-0" />}
                                  <ListOrdered className="size-4 shrink-0 text-violet-700 dark:text-violet-300" />
                                  <span className="min-w-0 flex-1">
                                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                      <strong className="text-sm">{block.name}</strong>
                                      <Badge variant="outline" className="border-violet-200 bg-background/70 text-[10px] text-violet-700 dark:border-violet-900 dark:text-violet-300">Iteration group</Badge>
                                      <Badge variant="outline" className={`text-[10px] ${groupStatus === "incomplete" ? "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-300" : statusClass(groupStatus)}`}>{groupStatus}</Badge>
                                    </span>
                                    <span className="mt-0.5 block text-[10px] leading-4 text-muted-foreground">
                                      Group <span className="font-mono" title={block.id}>{block.id.slice(0, 8)}</span> · started {formatDate(block.runs[0]?.created_at)} · {block.runs.length} run {block.runs.length === 1 ? "record" : "records"} · {completedRuns}/{block.totalIterations} completed · iteration 1 → {block.totalIterations}
                                    </span>
                                  </span>
                                  <span className="shrink-0 text-[10px] text-muted-foreground">{collapsed ? "Show runs" : "Hide runs"}</span>
                                </button>
                              </TableCell>
                            </TableRow>
                            {!collapsed && block.runs.map((run) => (
                              <TableRun
                                key={run.id}
                                run={run}
                                deleting={deletingRunId === run.id}
                                stopping={stoppingRunId === run.id}
                                onDelete={setRunPendingDeletion}
                                onStop={setRunPendingStop}
                              />
                            ))}
                          </Fragment>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
      </div>
      <Dialog open={runPendingDeletion !== null} onOpenChange={(open) => {
        if (!open && !deletingRunId) setRunPendingDeletion(null);
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete simulation run?</DialogTitle>
            <DialogDescription>
              This permanently deletes the selected run’s history record, snapshots, logs, and analytics files. The model itself will not be changed.
            </DialogDescription>
          </DialogHeader>
          {runPendingDeletion && (
            <div className="rounded-lg border bg-muted/40 p-3 text-sm">
              <p><strong>{formatDate(runPendingDeletion.created_at)}</strong></p>
              <p className="mt-1 text-muted-foreground">{runPendingDeletion.vehicle_count.toLocaleString()} vehicles · {runPendingDeletion.pedestrian_count.toLocaleString()} pedestrians · {formatDuration(runPendingDeletion.duration_hours)}</p>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={Boolean(deletingRunId)} onClick={() => setRunPendingDeletion(null)}>Cancel</Button>
            <Button type="button" variant="destructive" disabled={Boolean(deletingRunId)} onClick={() => void confirmDeleteRun()}>{deletingRunId ? "Deleting…" : "Delete run"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={runPendingStop !== null} onOpenChange={(open) => {
        if (!open && !stoppingRunId) setRunPendingStop(null);
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{runPendingStop?.status === "queued" ? "Remove this simulation from the queue?" : "Stop this simulation?"}</DialogTitle>
            <DialogDescription>
              {runPendingStop?.status === "queued"
                ? "This waiting setup will not start. Its snapshot remains in run history as removed, and later queue positions will move forward."
                : "SUMO will be interrupted and the run will be marked as failed with reason “User Interruption.” Partial logs and analytics files written so far will be preserved, but this run cannot be resumed."}
            </DialogDescription>
          </DialogHeader>
          {runPendingStop && (
            <div className="rounded-lg border bg-muted/40 p-3 text-sm">
              <p><strong>{formatDate(runPendingStop.created_at)}</strong></p>
              <p className="mt-1 text-muted-foreground">{runPendingStop.progress_percent?.toFixed(1) ?? 0}% complete · {formatSimulationTime(runPendingStop.simulated_seconds)} simulated</p>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={Boolean(stoppingRunId)} onClick={() => setRunPendingStop(null)}>{runPendingStop?.status === "queued" ? "Keep in queue" : "Keep running"}</Button>
            <Button type="button" variant="destructive" disabled={Boolean(stoppingRunId)} onClick={() => void confirmStopRun()}>
              <Square className="size-3 fill-current" />
              {stoppingRunId ? "Stopping…" : runPendingStop?.status === "queued" ? "Remove from queue" : "Stop simulation"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
