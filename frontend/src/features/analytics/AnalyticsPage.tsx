import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  Bug,
  Car,
  CircleX,
  Clock3,
  ChevronDown,
  Download,
  Footprints,
  GitCompareArrows,
  ListOrdered,
  RefreshCw,
  Route,
  Search,
  TriangleAlert,
  Activity,
  RadioTower,
} from "lucide-react";
import { getAnalytics, getRealWorldSeries, listAnalyticsRuns, listRealWorldSources } from "../../api/analytics";
import type {
  AnalyticsRun,
  AnalyticsData,
  FourierTrafficParameters,
  RealWorldSeries,
  RealWorldSource,
  TrafficModel,
  VehicleJourneySegmentType,
} from "../../types/campus";
import type { SimulationLogSection } from "../../types/campus";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import AnalyticsLineChart, { type AnalyticsChartSeries } from "./AnalyticsLineChart";
import ParkingAttemptChart from "./ParkingAttemptChart";
import ParkingDestinationAnalysis from "./ParkingDestinationAnalysis";
import FlowCalibrationPanel from "./FlowCalibrationPanel";
import { sampleRates } from "../simulation/TrafficProfileChart";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../../components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "../../components/ui/alert";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../components/ui/collapsible";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "../../components/ui/toggle-group";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../components/ui/dropdown-menu";
import TopNavigation from "../../components/TopNavigation";

type Props = {
  onHome: () => void;
  onSimulation: (modelId: string) => void;
  onAnalytics: () => void;
  onDocumentation: () => void;
  returnModelId?: string | null;
};

type ValidationSubject = "vehicles" | "pedestrians";
const COMPARISON_COLORS = ["#2563eb", "#f97316", "#16a34a", "#9333ea", "#dc2626"];
const MAX_COMPARISON_RUNS = 4;
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const JOURNEY_SEGMENT_LABELS: Record<VehicleJourneySegmentType, string> = {
  to_parking: "On the way to a parking lot",
  inside_parking: "Inside parking, not yet parked",
  between_parkings: "On the way to another parking lot",
  parked: "Parked",
};

function formatDate(value?: string | null) {
  if (!value) return "Unknown date";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatSimulationDate(value?: string | null, timezone = "Europe/Paris") {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(date);
}

function localDateTimeValue(value: string, timezone: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).formatToParts(date);
  const item = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${item.year}-${item.month}-${item.day}T${item.hour}:${item.minute}`;
}

function weeklyCalendarPosition(value: string, timezone: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).formatToParts(date);
  const item = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const weekday = WEEKDAYS.indexOf(item.weekday);
  return weekday < 0 ? null : { weekday, time: `${item.hour}:${item.minute}` };
}

function formatDuration(hours: number) {
  if (hours < 24) return `${hours}h`;
  return `${Number((hours / 24).toFixed(1))}d`;
}

function trafficModelLabel(model: TrafficModel) {
  if (model === "constant") return "Constant";
  if (model === "normal") return "Normal";
  if (model === "fourier") return "Fourier";
  return "Linear";
}

function compactNumber(value: number, decimalPlaces = 2) {
  return Number(value.toFixed(decimalPlaces)).toLocaleString();
}

function DemandDistributionSummary({
  subject,
  model,
  parameters,
}: {
  subject: ValidationSubject;
  model: TrafficModel;
  parameters: FourierTrafficParameters;
}) {
  const SubjectIcon = subject === "vehicles" ? Car : Footprints;
  const subjectLabel = subject === "vehicles" ? "Vehicles" : "Pedestrians";
  const isFourier = model === "fourier";
  const peakCount = Number.isFinite(parameters?.peak_count)
    ? Math.max(Math.round(parameters.peak_count), 0)
    : 0;
  const peakHeights = Array.isArray(parameters?.peak_heights)
    ? parameters.peak_heights.slice(0, peakCount)
    : [];

  return (
    <div className="min-w-0 rounded-md bg-muted/45 px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="flex items-center gap-1 font-medium">
          <SubjectIcon className="size-3.5 text-primary" />
          {subjectLabel}
        </span>
        <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{trafficModelLabel(model)}</Badge>
        {isFourier && peakCount > 0 && (
          <span className="text-muted-foreground">
            {peakCount} peaks · {compactNumber(parameters.peak_width_hours)}h width · {parameters.harmonics} harmonics
          </span>
        )}
      </div>
      {isFourier && (
        <div className="mt-1 text-[10px] leading-4 text-muted-foreground">
          {peakHeights.length === peakCount && peakCount > 0
            ? peakHeights.map((height, index) => `P${index + 1} ${compactNumber(height * 100)}%`).join(" · ")
            : "Peak percentages were not recorded for this run."}
        </div>
      )}
    </div>
  );
}

function csvCell(value: unknown) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function safeFilenamePart(value: string) {
  return value.trim().replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "data";
}

function formatRecordedDuration(seconds: number) {
  if (!seconds) return "0s";
  const minutes = seconds / 60;
  if (minutes < 1) return `${Math.round(seconds)}s`;
  if (minutes < 60) return `${Number(minutes.toFixed(1))}m`;
  return `${Number((minutes / 60).toFixed(1))}h`;
}

function runLabel(run: AnalyticsRun) {
  const date = run.simulation_start_at
    ? formatSimulationDate(run.simulation_start_at, run.simulation_timezone || "Europe/Paris")
    : formatDate(run.created_at);
  return `${run.model_name} · ${date} · ${run.vehicle_count.toLocaleString()} vehicles`;
}

type AnalyticsRunChoice =
  | { kind: "standalone"; key: string; run: AnalyticsRun }
  | {
      kind: "calibration";
      key: string;
      id: string;
      name: string;
      totalIterations: number;
      runs: AnalyticsRun[];
    };

function groupAnalyticsRuns(runs: AnalyticsRun[]): AnalyticsRunChoice[] {
  const grouped = new Map<string, AnalyticsRun[]>();
  for (const run of runs) {
    const calibrationId = run.calibration?.id;
    if (!calibrationId) continue;
    grouped.set(calibrationId, [...(grouped.get(calibrationId) ?? []), run]);
  }

  const emitted = new Set<string>();
  const choices: AnalyticsRunChoice[] = [];
  for (const run of runs) {
    const calibration = run.calibration;
    if (!calibration) {
      choices.push({ kind: "standalone", key: `run:${run.id}`, run });
      continue;
    }
    if (emitted.has(calibration.id)) continue;
    emitted.add(calibration.id);
    choices.push({
      kind: "calibration",
      key: `calibration:${calibration.id}`,
      id: calibration.id,
      name: calibration.name,
      totalIterations: calibration.total_iterations,
      runs: [...(grouped.get(calibration.id) ?? [])].sort((left, right) => (
        (left.calibration?.iteration ?? 0) - (right.calibration?.iteration ?? 0)
        || left.created_at.localeCompare(right.created_at)
      )),
    });
  }
  return choices;
}

function calibrationChoiceLabel(choice: Extract<AnalyticsRunChoice, { kind: "calibration" }>) {
  const first = choice.runs[0];
  return `${choice.name} · ${choice.runs.length}/${choice.totalIterations} iterations · ${first?.model_name ?? "Unknown model"} · ${formatDate(first?.created_at)}`;
}

function iterationRunLabel(run: AnalyticsRun) {
  const iteration = run.calibration?.iteration ?? 0;
  const total = run.calibration?.total_iterations ?? 0;
  return `Iteration ${iteration} of ${total} · ${run.status} · ${formatDate(run.created_at)}`;
}

function chartRunLabel(run: AnalyticsRun) {
  const date = run.simulation_start_at
    ? formatSimulationDate(run.simulation_start_at, run.simulation_timezone || "Europe/Paris")
    : formatDate(run.created_at);
  return `${run.model_name} · ${date}`;
}

function DebugLogSection({
  title,
  section,
  kind,
}: {
  title: string;
  section: SimulationLogSection;
  kind: "error" | "warning";
}) {
  const isError = kind === "error";
  return (
    <AccordionItem value={kind} className={`overflow-hidden rounded-lg border ${isError ? "border-red-200 dark:border-red-900" : "border-amber-200 dark:border-amber-900"}`}>
      <AccordionTrigger className={`px-3 py-2.5 hover:no-underline ${isError ? "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-300" : "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"}`}>
        <span className="flex items-center gap-2">
          {isError ? <CircleX className="size-4" /> : <TriangleAlert className="size-4" />}
          {title}
          <Badge variant="outline" className={isError ? "border-red-300 bg-background/70 text-red-800 dark:border-red-800 dark:text-red-300" : "border-amber-300 bg-background/70 text-amber-800 dark:border-amber-800 dark:text-amber-300"}>
            {section.total.toLocaleString()} total
          </Badge>
        </span>
        <span className="ml-auto mr-2 text-xs font-normal opacity-75">{section.unique.toLocaleString()} unique</span>
      </AccordionTrigger>
      <AccordionContent className="max-h-96 overflow-auto border-t bg-background pb-0">
        {section.entries.length ? (
          <ul className="divide-y">
            {section.entries.map((entry) => (
              <li key={`${kind}-${entry.first_line}-${entry.message}`} className="flex items-start gap-3 px-3 py-2.5 text-xs">
                <Badge variant="secondary" className="mt-0.5 shrink-0 tabular-nums">×{entry.count.toLocaleString()}</Badge>
                <div className="min-w-0">
                  <p className="whitespace-pre-wrap break-words font-mono leading-5 text-foreground">{entry.message}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">First occurrence: log line {entry.first_line.toLocaleString()}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-3 py-5 text-center text-xs text-muted-foreground">No {title.toLowerCase()} were recorded.</p>
        )}
      </AccordionContent>
    </AccordionItem>
  );
}

export default function AnalyticsPage({ onHome, onSimulation, onAnalytics, onDocumentation, returnModelId }: Props) {
  const [runs, setRuns] = useState<AnalyticsRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [results, setResults] = useState<AnalyticsData | null>(null);
  const [comparisonRunIds, setComparisonRunIds] = useState<string[]>([]);
  const [comparisonResults, setComparisonResults] = useState<Record<string, AnalyticsData>>({});
  const [selectedJourneySegment, setSelectedJourneySegment] = useState<VehicleJourneySegmentType>("inside_parking");
  const [selectedSegmentParkingId, setSelectedSegmentParkingId] = useState("all");
  const [selectedDetectorId, setSelectedDetectorId] = useState("");
  const [validationDetectorId, setValidationDetectorId] = useState("");
  const [realWorldSources, setRealWorldSources] = useState<RealWorldSource[]>([]);
  const [selectedRealWorldSourceId, setSelectedRealWorldSourceId] = useState("");
  const [realWorldMode, setRealWorldMode] = useState<"raw" | "weekly_average">("raw");
  const [realWorldStartAt, setRealWorldStartAt] = useState("");
  const [weeklyStartWeekday, setWeeklyStartWeekday] = useState(0);
  const [weeklyStartTime, setWeeklyStartTime] = useState("08:00");
  const [realWorldSeries, setRealWorldSeries] = useState<Record<ValidationSubject, RealWorldSeries | null>>({
    vehicles: null,
    pedestrians: null,
  });
  const [loadingRealWorld, setLoadingRealWorld] = useState(false);
  const [realWorldError, setRealWorldError] = useState("");
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingResults, setLoadingResults] = useState(false);
  const [loadingComparisons, setLoadingComparisons] = useState(false);
  const [error, setError] = useState("");

  const runChoices = useMemo(() => groupAnalyticsRuns(runs), [runs]);
  const selectedRun = runs.find((run) => run.id === selectedRunId);
  const selectedRunChoice = runChoices.find((choice) => (
    choice.kind === "standalone"
      ? choice.run.id === selectedRunId
      : choice.runs.some((run) => run.id === selectedRunId)
  ));
  const selectedRunChoiceKey = selectedRunChoice?.key ?? "";

  const selectRunChoice = (choiceKey: string) => {
    const choice = runChoices.find((candidate) => candidate.key === choiceKey);
    if (!choice) return;
    if (choice.kind === "standalone") {
      setSelectedRunId(choice.run.id);
      return;
    }
    const latestIteration = choice.runs[choice.runs.length - 1];
    if (latestIteration) setSelectedRunId(latestIteration.id);
  };

  const refreshRuns = useCallback(async (quiet = false) => {
    if (!quiet) setLoadingRuns(true);
    try {
      const availableRuns = await listAnalyticsRuns();
      setRuns(availableRuns);
      setSelectedRunId((current) =>
        availableRuns.some((run) => run.id === current) ? current : availableRuns[0]?.id ?? "",
      );
      setComparisonRunIds((current) => current.filter((id) => availableRuns.some((run) => run.id === id)));
      if (!quiet) setError("");
    } catch (caughtError) {
      if (!quiet) setError(caughtError instanceof Error ? caughtError.message : "Could not load simulations.");
    } finally {
      if (!quiet) setLoadingRuns(false);
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    let cancelled = false;
    void listRealWorldSources()
      .then((sources) => {
        if (cancelled) return;
        setRealWorldSources(sources);
        setSelectedRealWorldSourceId((current) =>
          sources.some((source) => source.id === current) ? current : sources[0]?.id ?? "",
        );
      })
      .catch((caughtError) => {
        if (!cancelled) setRealWorldError(caughtError instanceof Error ? caughtError.message : "Could not load real-world sensors.");
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedRunId) {
      setResults(null);
      return;
    }
    let cancelled = false;
    setLoadingResults(true);
    setError("");
    void getAnalytics(selectedRunId)
      .then((nextResults) => {
        if (cancelled) return;
        setResults(nextResults);
        setSelectedSegmentParkingId((current) =>
          nextResults.trip_segments.parkings.some((parking) => parking.id === current) ? current : "all",
        );
        setSelectedDetectorId((current) =>
          nextResults.detectors.definitions.some((detector) => detector.id === current)
            ? current
            : nextResults.detectors.definitions[0]?.id ?? "",
        );
        const comparableDetectorIds = [...new Set(
          nextResults.detectors.definitions
            .filter((detector) => detector.type === "e3")
            .map((detector) => detector.logical_id),
        )].filter((logicalId) => {
          const subjects = new Set(
            nextResults.detectors.definitions
              .filter((detector) => detector.logical_id === logicalId)
              .map((detector) => detector.subject),
          );
          return subjects.has("vehicles") && subjects.has("pedestrians");
        });
        setValidationDetectorId((current) =>
          comparableDetectorIds.includes(current) ? current : comparableDetectorIds[0] ?? "",
        );
      })
      .catch((caughtError) => {
        if (!cancelled) {
          setResults(null);
          setError(caughtError instanceof Error ? caughtError.message : "Could not load analytics data.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingResults(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  const selectedRealWorldSource = realWorldSources.find((source) => source.id === selectedRealWorldSourceId);
  useEffect(() => {
    if (!selectedRealWorldSource) return;
    const timezone = results?.run.simulation_timezone || "Europe/Paris";
    const scheduledStart = results?.run.simulation_start_at
      ? localDateTimeValue(results.run.simulation_start_at, timezone)
      : "";
    setRealWorldStartAt(
      scheduledStart >= selectedRealWorldSource.start_at && scheduledStart <= selectedRealWorldSource.end_at
        ? scheduledStart
        : selectedRealWorldSource.start_at,
    );
  }, [results?.run.simulation_start_at, results?.run.simulation_timezone, selectedRealWorldSource?.id]);

  useEffect(() => {
    if (!results?.run.simulation_start_at) return;
    const position = weeklyCalendarPosition(
      results.run.simulation_start_at,
      results.run.simulation_timezone || "Europe/Paris",
    );
    if (!position) return;
    setWeeklyStartWeekday(position.weekday);
    setWeeklyStartTime(position.time);
  }, [results?.run.simulation_start_at, results?.run.simulation_timezone]);

  const validationDetectorGroups = useMemo(() => {
    const grouped = new Map<string, {
      logicalId: string;
      label: string;
      vehicles: AnalyticsData["detectors"]["definitions"][number];
      pedestrians: AnalyticsData["detectors"]["definitions"][number];
    }>();
    for (const definition of results?.detectors.definitions ?? []) {
      if (definition.type !== "e3") continue;
      const siblings = (results?.detectors.definitions ?? []).filter(
        (candidate) => candidate.logical_id === definition.logical_id,
      );
      const vehicles = siblings.find((candidate) => candidate.subject === "vehicles");
      const pedestrians = siblings.find((candidate) => candidate.subject === "pedestrians");
      if (!vehicles || !pedestrians || grouped.has(definition.logical_id)) continue;
      grouped.set(definition.logical_id, {
        logicalId: definition.logical_id,
        label: definition.logical_name,
        vehicles,
        pedestrians,
      });
    }
    return [...grouped.values()];
  }, [results]);
  const validationDetectorGroup = validationDetectorGroups.find(
    (group) => group.logicalId === validationDetectorId,
  );

  useEffect(() => {
    if (!results || !validationDetectorGroup || !selectedRealWorldSourceId) {
      setRealWorldSeries({ vehicles: null, pedestrians: null });
      return;
    }
    const [hour, minute] = weeklyStartTime.split(":").map(Number);
    let cancelled = false;
    setLoadingRealWorld(true);
    setRealWorldError("");
    const loadSubject = (subject: ValidationSubject) => getRealWorldSeries({
        sourceId: selectedRealWorldSourceId,
        mode: realWorldMode,
        subject,
        durationSeconds: results.run.duration_seconds,
        startAt: realWorldMode === "raw" ? realWorldStartAt : undefined,
        startWeekday: realWorldMode === "weekly_average" ? weeklyStartWeekday : undefined,
        startTimeSeconds: realWorldMode === "weekly_average" ? (hour * 3600 + minute * 60) : undefined,
      });
    void Promise.all([loadSubject("vehicles"), loadSubject("pedestrians")])
      .then(([vehicles, pedestrians]) => {
        if (!cancelled) setRealWorldSeries({ vehicles, pedestrians });
      })
      .catch((caughtError) => {
        if (!cancelled) {
          setRealWorldSeries({ vehicles: null, pedestrians: null });
          setRealWorldError(caughtError instanceof Error ? caughtError.message : "Could not load real-world sensor data.");
        }
      })
      .finally(() => { if (!cancelled) setLoadingRealWorld(false); });
    return () => { cancelled = true; };
  }, [
    realWorldMode,
    realWorldStartAt,
    results?.run.duration_seconds,
    selectedRealWorldSourceId,
    validationDetectorGroup?.logicalId,
    weeklyStartTime,
    weeklyStartWeekday,
  ]);

  useEffect(() => {
    setComparisonRunIds((current) => current.filter((id) => id !== selectedRunId));
  }, [selectedRunId]);

  useEffect(() => {
    if (!comparisonRunIds.length) {
      setComparisonResults({});
      setLoadingComparisons(false);
      return;
    }
    let cancelled = false;
    setLoadingComparisons(true);
    void Promise.allSettled(comparisonRunIds.map((id) => getAnalytics(id)))
      .then((settled) => {
        if (cancelled) return;
        const loaded: Record<string, AnalyticsData> = {};
        settled.forEach((item, index) => {
          if (item.status === "fulfilled") loaded[comparisonRunIds[index]] = item.value;
        });
        setComparisonResults(loaded);
        const failed = settled.filter((item) => item.status === "rejected").length;
        if (failed) setError(`${failed} comparison dataset${failed === 1 ? "" : "s"} could not be loaded.`);
      })
      .finally(() => {
        if (!cancelled) setLoadingComparisons(false);
      });
    return () => {
      cancelled = true;
    };
  }, [comparisonRunIds]);

  const comparedResults = useMemo(
    () => results ? [results, ...comparisonRunIds.map((id) => comparisonResults[id]).filter((item): item is AnalyticsData => Boolean(item))] : [],
    [comparisonResults, comparisonRunIds, results],
  );
  const calendarChartProps = comparedResults.length === 1 && results?.run.simulation_start_at
    ? {
        calendarStartAt: results.run.simulation_start_at,
        calendarTimezone: results.run.simulation_timezone || "Europe/Paris",
      }
    : {};

  const searchPoints = results?.search_times.points.map((point) => ({
    x: point.time_seconds,
    y: point.average_search_seconds / 60,
    label: `${Number((point.average_search_seconds / 60).toFixed(1))} min average · ${point.vehicle_count} vehicle${point.vehicle_count === 1 ? "" : "s"}`,
  })) ?? [];
  const searchSeries = useMemo<AnalyticsChartSeries[]>(
    () => comparedResults.flatMap((item, index) => item.search_times.points.length ? [{
      id: `run_${index}`,
      label: chartRunLabel(item.run),
      color: COMPARISON_COLORS[index % COMPARISON_COLORS.length],
      points: item.search_times.points.map((point) => ({ x: point.time_seconds, y: point.average_search_seconds / 60 })),
    }] : []),
    [comparedResults],
  );
  const journeySegmentSeries = useMemo<AnalyticsChartSeries[]>(
    () => comparedResults.flatMap((item, index) => {
      const points = item.trip_segments.points.filter(
        (point) => point.segment_type === selectedJourneySegment
          && point.parking_id === selectedSegmentParkingId,
      );
      if (!points.length) return [];
      return [{
        id: `journey_run_${index}`,
        label: chartRunLabel(item.run),
        color: COMPARISON_COLORS[index % COMPARISON_COLORS.length],
        points: points.map((point) => ({
          x: point.time_seconds,
          y: point.average_duration_seconds / 60,
        })),
      }];
    }),
    [comparedResults, selectedJourneySegment, selectedSegmentParkingId],
  );
  const journeySegmentSummary = results?.trip_segments.summaries.find(
    (summary) => summary.segment_type === selectedJourneySegment
      && summary.parking_id === selectedSegmentParkingId,
  );
  const detectorDefinition = results?.detectors.definitions.find((detector) => detector.id === selectedDetectorId);
  const detectorPoints = results?.detectors.series[selectedDetectorId] ?? [];
  const detectorEntryTotal = detectorPoints.reduce(
    (total, point) => total + point.entry_count,
    0,
  );
  const detectorSeries = useMemo<AnalyticsChartSeries[]>(() => {
    if (!detectorPoints.length) return [];
    return [{
      id: selectedDetectorId,
      label: detectorDefinition?.label ?? selectedDetectorId,
      color: "#0f766e",
      points: detectorPoints.map((point) => ({
        x: point.end_seconds,
        y: point.entry_count,
      })),
    }];
  }, [detectorDefinition?.label, detectorPoints, selectedDetectorId]);
  const detectorSubjectLabel = detectorDefinition?.subject === "pedestrians" ? "Pedestrians" : "Vehicles";
  const detectorMetricLabel = `${detectorSubjectLabel} entering per interval`;
  const validationComparisonSeries = useMemo<Record<ValidationSubject, AnalyticsChartSeries[]>>(() => {
    const buildSeries = (subject: ValidationSubject) => {
      const definition = validationDetectorGroup?.[subject];
      const simulationPoints = definition
        ? results?.detectors.comparison_series[definition.id] ?? []
        : [];
      const physicalSeries = realWorldSeries[subject];
      const series: AnalyticsChartSeries[] = [];
      if (simulationPoints.length) {
        series.push({
          id: `simulation_detector_flow_${subject}`,
          label: `${validationDetectorGroup?.label ?? "Simulation detector"} · simulation`,
          color: "#2563eb",
          points: simulationPoints.map((point) => ({
            x: point.begin_seconds,
            y: point.flow_per_hour,
          })),
        });
      }
      if (physicalSeries?.points.length) {
        series.push({
          id: `real_world_flow_${subject}`,
          label: `${physicalSeries.source.name} · ${realWorldMode === "raw" ? "raw" : "weekly average"}`,
          color: "#f97316",
          points: physicalSeries.points.map((point) => ({
            x: point.time_seconds,
            y: point.flow_per_hour,
          })),
        });
      }
      return series;
    };
    return {
      vehicles: buildSeries("vehicles"),
      pedestrians: buildSeries("pedestrians"),
    };
  }, [realWorldMode, realWorldSeries, results, validationDetectorGroup]);
  const validationInputSeries = useMemo<Record<ValidationSubject, AnalyticsChartSeries[]>>(() => {
    if (!results) return { vehicles: [], pedestrians: [] };
    const sampleCount = Math.max(Math.ceil(results.run.duration_seconds / 900) + 1, 2);
    const hours = Array.from(
      { length: sampleCount },
      (_, index) => results.run.duration_hours * index / (sampleCount - 1),
    );
    const buildSeries = (subject: ValidationSubject): AnalyticsChartSeries[] => {
      const model = subject === "vehicles" ? results.run.vehicle_traffic_model : results.run.pedestrian_traffic_model;
      const total = subject === "vehicles" ? results.run.vehicle_count : results.run.pedestrian_count;
      const parameters = subject === "vehicles" ? results.run.vehicle_fourier_parameters : results.run.pedestrian_fourier_parameters;
      return [{
        id: `simulation_input_${subject}`,
        label: `${subject === "vehicles" ? "Vehicle" : "Pedestrian"} input demand`,
        color: "#7c3aed",
        strokeDasharray: "8 5",
        points: sampleRates(model, total, hours, results.run.duration_hours, parameters)
          .map((value, index) => ({ x: hours[index] * 3600, y: value })),
      }];
    };
    return { vehicles: buildSeries("vehicles"), pedestrians: buildSeries("pedestrians") };
  }, [results]);
  const validationDiagnostics = (['vehicles', 'pedestrians'] as const).reduce((diagnostics, subject) => {
    const definition = validationDetectorGroup?.[subject];
    const points = definition ? results?.detectors.series[definition.id] ?? [] : [];
    diagnostics[subject] = {
      points,
      entryCount: points.reduce((total, point) => total + point.entry_count, 0),
      completedCount: points.reduce((total, point) => total + point.vehicle_count, 0),
      peakWithin: points.reduce((maximum, point) => Math.max(maximum, point.vehicles_within ?? 0), 0),
    };
    return diagnostics;
  }, {} as Record<ValidationSubject, {
    points: AnalyticsData["detectors"]["series"][string];
    entryCount: number;
    completedCount: number;
    peakWithin: number;
  }>);
  const realWorldAverageSeries = realWorldSeries.vehicles ?? realWorldSeries.pedestrians;
  const realWorldAverageSampleCount = realWorldAverageSeries?.points.length
    ? realWorldAverageSeries.points.reduce((total, point) => total + point.sample_count, 0) / realWorldAverageSeries.points.length
    : 0;
  const validationExportAvailable = (["vehicles", "pedestrians"] as const).some(
    (subject) => validationComparisonSeries[subject].some((series) => series.points.length),
  );
  const downloadValidationComparison = () => {
    if (!results || !validationDetectorGroup || !validationExportAvailable) return;
    const intervalSeconds = results.detectors.comparison_interval_seconds || 900;
    const simulationStart = results.run.simulation_start_at
      ? new Date(results.run.simulation_start_at)
      : null;
    const timezone = results.run.simulation_timezone || "Europe/Paris";
    const rows = new Map<number, Record<string, unknown>>();
    const rowAt = (seconds: number) => {
      const existing = rows.get(seconds);
      if (existing) return existing;
      const validStart = simulationStart && !Number.isNaN(simulationStart.getTime())
        ? simulationStart
        : null;
      const row: Record<string, unknown> = {
        run_id: results.run.id,
        simulation_detector_id: validationDetectorGroup.logicalId,
        simulation_detector_name: validationDetectorGroup.label,
        real_world_source_id: selectedRealWorldSource?.id ?? "",
        real_world_source_name: selectedRealWorldSource?.name ?? "",
        real_world_mode: realWorldMode,
        interval_begin_seconds: seconds,
        interval_end_seconds: seconds + intervalSeconds,
        simulation_interval_begin_iso: validStart
          ? new Date(validStart.getTime() + seconds * 1000).toISOString()
          : "",
        simulation_interval_end_iso: validStart
          ? new Date(validStart.getTime() + (seconds + intervalSeconds) * 1000).toISOString()
          : "",
        simulation_timezone: timezone,
      };
      rows.set(seconds, row);
      return row;
    };

    (["vehicles", "pedestrians"] as const).forEach((subject) => {
      const definition = validationDetectorGroup[subject];
      const simulationPoints = results.detectors.comparison_series[definition.id] ?? [];
      simulationPoints.forEach((point) => {
        const row = rowAt(point.begin_seconds);
        row[`${subject}_simulation_flow_agents_per_hour`] = point.flow_per_hour;
        row[`${subject}_simulation_interval_count`] = point.interval_count;
      });
      realWorldSeries[subject]?.points.forEach((point) => {
        const row = rowAt(point.time_seconds);
        row[`${subject}_real_world_flow_agents_per_hour`] = point.flow_per_hour;
        row[`${subject}_real_world_interval_count`] = point.interval_count;
        row[`${subject}_real_world_sample_count`] = point.sample_count;
        row[`${subject}_real_world_observed_at`] = point.observed_at ?? "";
        row[`${subject}_real_world_weekday`] = point.weekday ?? "";
        row[`${subject}_real_world_time_of_day_seconds`] = point.time_of_day_seconds ?? "";
      });
    });

    const headers = [
      "run_id",
      "simulation_detector_id",
      "simulation_detector_name",
      "real_world_source_id",
      "real_world_source_name",
      "real_world_mode",
      "interval_begin_seconds",
      "interval_end_seconds",
      "simulation_interval_begin_iso",
      "simulation_interval_end_iso",
      "simulation_timezone",
      "vehicles_simulation_flow_agents_per_hour",
      "vehicles_simulation_interval_count",
      "vehicles_real_world_flow_agents_per_hour",
      "vehicles_real_world_interval_count",
      "vehicles_real_world_sample_count",
      "vehicles_real_world_observed_at",
      "vehicles_real_world_weekday",
      "vehicles_real_world_time_of_day_seconds",
      "pedestrians_simulation_flow_agents_per_hour",
      "pedestrians_simulation_interval_count",
      "pedestrians_real_world_flow_agents_per_hour",
      "pedestrians_real_world_interval_count",
      "pedestrians_real_world_sample_count",
      "pedestrians_real_world_observed_at",
      "pedestrians_real_world_weekday",
      "pedestrians_real_world_time_of_day_seconds",
    ];
    const csv = [
      headers.join(","),
      ...[...rows.entries()]
        .sort(([left], [right]) => left - right)
        .map(([, row]) => headers.map((header) => csvCell(row[header])).join(",")),
    ].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = [
      safeFilenamePart(results.run.model_name),
      safeFilenamePart(validationDetectorGroup.label),
      safeFilenamePart(selectedRealWorldSource?.name ?? "real-world-sensor"),
      realWorldMode,
      "comparison.csv",
    ].join("_");
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };
  const calibrationRuns = results?.run.calibration
    ? runs.filter((run) => run.calibration?.id === results.run.calibration?.id)
    : [];
  const calibrationIncomplete = Boolean(
    results?.run.calibration
    && calibrationRuns.length < results.run.calibration.total_iterations
  );

  useEffect(() => {
    if (!calibrationIncomplete) return;
    const timer = window.setInterval(() => void refreshRuns(true), 5000);
    return () => window.clearInterval(timer);
  }, [calibrationIncomplete, refreshRuns]);

  const simulationModelId = returnModelId || results?.run.model_id || selectedRun?.model_id;

  return (
    <main className="min-h-full overflow-y-auto bg-muted/30">
      <div className="mx-auto w-full max-w-[1680px] px-4 py-5 sm:px-6 sm:py-7">
        <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              {simulationModelId && (
                <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => onSimulation(simulationModelId)}>
                  <ArrowLeft className="size-4" /> Simulation settings
                </button>
              )}
              <button className="hover:text-foreground" onClick={onHome}>Home</button>
            </div>
            <h1 className="flex items-center gap-3 text-3xl font-semibold tracking-tight"><BarChart3 className="size-7 text-primary" /> Analytics</h1>
            <p className="mt-2 text-sm text-muted-foreground">Explore and compare simulation data independently from the model editor.</p>
          </div>
          <div className="flex flex-col items-end gap-3">
          <TopNavigation active="analytics" onHome={onHome} onAnalytics={onAnalytics} onDocumentation={onDocumentation} />
          <Button variant="outline" onClick={() => void refreshRuns()} disabled={loadingRuns || loadingResults}>
            <RefreshCw className={loadingRuns ? "animate-spin" : ""} /> Refresh analytics
          </Button>
          </div>
        </header>

        {error && <Alert variant="destructive" className="mb-5 bg-red-50 dark:bg-red-950/40"><AlertDescription>{error}</AlertDescription></Alert>}

        <Card className="mb-6 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Simulation or iteration group</CardTitle>
            <CardDescription>Select a standalone simulation or one calibration group. When a group is selected, choose its primary iteration separately.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(15rem,0.45fr)_auto] lg:items-end">
            {runs.length ? (
              <>
                <label className="min-w-0 flex-1 space-y-1.5 text-sm font-medium">
                  Primary simulation set
                  <Select value={selectedRunChoiceKey} onValueChange={selectRunChoice}>
                    <SelectTrigger className="mt-1.5 h-10"><SelectValue /></SelectTrigger>
                    <SelectContent>{runChoices.map((choice) => (
                      <SelectItem key={choice.key} value={choice.key}>
                        {choice.kind === "calibration"
                          ? calibrationChoiceLabel(choice)
                          : `Standalone · ${runLabel(choice.run)}`}
                      </SelectItem>
                    ))}</SelectContent>
                  </Select>
                </label>
                {selectedRunChoice?.kind === "calibration" && (
                  <label className="min-w-0 space-y-1.5 text-sm font-medium">
                    Primary iteration
                    <Select value={selectedRunId} onValueChange={setSelectedRunId}>
                      <SelectTrigger className="mt-1.5 h-10"><SelectValue /></SelectTrigger>
                      <SelectContent>{selectedRunChoice.runs.map((run) => (
                        <SelectItem key={run.id} value={run.id}>{iterationRunLabel(run)}</SelectItem>
                      ))}</SelectContent>
                    </Select>
                  </label>
                )}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" className="h-10 justify-between lg:min-w-56">
                      <span className="inline-flex items-center gap-2"><GitCompareArrows className="size-4" /> Compare simulations</span>
                      {!!comparisonRunIds.length && <Badge variant="secondary">{comparisonRunIds.length}</Badge>}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="max-h-80 w-[min(34rem,calc(100vw-2rem))] overflow-y-auto">
                    <DropdownMenuLabel>Overlay up to {MAX_COMPARISON_RUNS} other runs</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {runChoices.map((choice) => {
                      const choiceRuns = choice.kind === "calibration"
                        ? choice.runs.filter((run) => run.id !== selectedRunId)
                        : choice.run.id === selectedRunId ? [] : [choice.run];
                      if (!choiceRuns.length) return null;
                      return (
                        <div key={choice.key} className="py-0.5">
                          {choice.kind === "calibration" && (
                            <DropdownMenuLabel className="flex items-center gap-1.5 pb-1 text-[11px] text-violet-700 dark:text-violet-300">
                              <ListOrdered className="size-3.5" /> {choice.name} · group {choice.id.slice(0, 8)}
                            </DropdownMenuLabel>
                          )}
                          {choiceRuns.map((run) => {
                            const checked = comparisonRunIds.includes(run.id);
                            return (
                              <DropdownMenuCheckboxItem
                                key={run.id}
                                className={choice.kind === "calibration" ? "pl-6" : ""}
                                checked={checked}
                                disabled={!checked && comparisonRunIds.length >= MAX_COMPARISON_RUNS}
                                onSelect={(event) => event.preventDefault()}
                                onCheckedChange={(nextChecked) => setComparisonRunIds((current) => nextChecked ? [...current, run.id] : current.filter((id) => id !== run.id))}
                              >
                                <span className="truncate">
                                  {choice.kind === "calibration" ? iterationRunLabel(run) : `Standalone · ${runLabel(run)}`}
                                </span>
                              </DropdownMenuCheckboxItem>
                            );
                          })}
                        </div>
                      );
                    })}
                    {runs.length <= 1 && <p className="px-2 py-3 text-xs text-muted-foreground">No other simulation is available.</p>}
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">{loadingRuns ? "Loading simulations…" : "No analytics data or debug logs are available yet."}</p>
            )}
          </CardContent>
        </Card>

        {(loadingResults || loadingComparisons) && <div className="mb-6 rounded-lg border bg-background p-8 text-center text-sm text-muted-foreground">Loading and aggregating analytics data…</div>}

        {results && !loadingResults && (
          <div className="space-y-4">
            {results.run.status === "failed" && (
              <Alert variant="destructive" className="bg-red-50 dark:bg-red-950/40">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                <AlertTitle>This simulation did not complete successfully.</AlertTitle>
                <AlertDescription>
                  The partial analytics data generated before the failure is shown below.
                  {(results.run.failure_reason || results.run.message) && (
                    <> Reason: {results.run.failure_reason || results.run.message}</>
                  )}
                </AlertDescription>
              </Alert>
            )}
            {!!results.run.excluded_building_destination_count && (
              <Alert className="border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/35 dark:text-amber-100">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                <AlertTitle>Some selected buildings were not pedestrian-reachable.</AlertTitle>
                <AlertDescription>
                  This run used {results.run.building_destination_count?.toLocaleString() ?? 0} reachable building destinations and excluded {results.run.excluded_building_destination_count.toLocaleString()} destinations on disconnected pedestrian network components. Details are available in the debug warnings and the run’s person-access snapshot.
                </AlertDescription>
              </Alert>
            )}
            <Card className="shadow-sm">
              <CardContent className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-8">
                <div><span className="block text-xs text-muted-foreground">Model</span><strong className="text-sm">{results.run.model_name}</strong></div>
                <div><span className="block text-xs text-muted-foreground">Run date</span><strong className="text-sm">{formatDate(results.run.created_at)}</strong></div>
                <div><span className="block text-xs text-muted-foreground">Simulated window</span><strong className="text-sm">{formatSimulationDate(results.run.simulation_start_at, results.run.simulation_timezone || "Europe/Paris")} → {formatSimulationDate(results.run.simulation_end_at, results.run.simulation_timezone || "Europe/Paris")}</strong></div>
                <div><span className="block text-xs text-muted-foreground">Total people</span><strong>{(results.run.total_people ?? results.run.vehicle_count + results.run.pedestrian_count).toLocaleString()}</strong></div>
                <div><span className="flex items-center gap-1 text-xs text-muted-foreground"><Car className="size-3.5" /> By car</span><strong>{results.run.vehicle_count.toLocaleString()}</strong></div>
                <div><span className="flex items-center gap-1 text-xs text-muted-foreground"><Footprints className="size-3.5" /> Independent walkers</span><strong>{results.run.pedestrian_count.toLocaleString()}</strong></div>
                <div><span className="flex items-center gap-1 text-xs text-muted-foreground"><Clock3 className="size-3.5" /> Duration</span><strong>{formatDuration(results.run.duration_hours)}</strong></div>
                <div><span className="block text-xs text-muted-foreground">Parking areas</span><strong>{results.run.parking_area_count.toLocaleString()}</strong></div>
                <div className="space-y-1.5 border-t pt-3 sm:col-span-2 lg:col-span-8">
                  <span className="block text-xs font-medium text-muted-foreground">Demand distribution</span>
                  <div className="grid gap-2 lg:grid-cols-2">
                    <DemandDistributionSummary
                      subject="vehicles"
                      model={results.run.vehicle_traffic_model}
                      parameters={results.run.vehicle_fourier_parameters}
                    />
                    <DemandDistributionSummary
                      subject="pedestrians"
                      model={results.run.pedestrian_traffic_model}
                      parameters={results.run.pedestrian_fourier_parameters}
                    />
                  </div>
                </div>
                {!!results.run.vehicle_origin_allocations?.length && (
                  <div className="space-y-1.5 border-t pt-3 sm:col-span-2 lg:col-span-8">
                    <span className="block text-xs font-medium text-muted-foreground">Vehicle entry allocation</span>
                    <div className="flex flex-wrap gap-2">
                      {results.run.vehicle_origin_allocations.map((allocation) => (
                        <Badge key={allocation.origin_id} variant="outline" className="h-auto py-1 text-[11px]">
                          {allocation.origin_name || allocation.origin_id}: {allocation.vehicle_count.toLocaleString()} cars · {Number((allocation.percentage ?? 0).toFixed(2))}%
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {results.run.calibration && (
              <FlowCalibrationPanel runs={calibrationRuns} selected={results} />
            )}

            {!!results.run.parking_areas.length && (
              <Collapsible asChild>
              <Card className="group shadow-sm">
                  <CollapsibleTrigger className="flex w-full cursor-pointer items-center px-4 py-3 text-left text-sm font-medium [&[data-state=open]>svg]:rotate-180">
                    Parking areas used in this run ({results.run.parking_areas.length})
                    <span className="ml-2 text-xs font-normal text-muted-foreground">Names and capacities are preserved from run time</span>
                    <ChevronDown className="ml-auto size-4 shrink-0 transition-transform" />
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                  <CardContent className="max-h-72 overflow-auto border-t p-0">
                    <Table className="min-w-[620px]">
                      <TableHeader className="sticky top-0 bg-muted/95 text-xs uppercase text-muted-foreground">
                        <TableRow><TableHead className="px-4 py-2">Parking area</TableHead><TableHead className="px-4 py-2">OSM way</TableHead><TableHead className="px-4 py-2 text-right">Model capacity</TableHead><TableHead className="px-4 py-2 text-right">Generated capacity</TableHead></TableRow>
                      </TableHeader>
                      <TableBody>
                        {results.run.parking_areas.map((parking) => (
                          <TableRow key={parking.id}><TableCell className="px-4 py-2">{parking.name}</TableCell><TableCell className="px-4 py-2 font-mono text-xs">{parking.osm_way_id}</TableCell><TableCell className="px-4 py-2 text-right tabular-nums">{parking.configured_capacity?.toLocaleString() ?? "Calculated at run time"}</TableCell><TableCell className="px-4 py-2 text-right tabular-nums">{parking.generated_capacity?.toLocaleString() ?? "—"}</TableCell></TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                  </CollapsibleContent>
              </Card>
              </Collapsible>
            )}

            <ParkingDestinationAnalysis
              data={results.parking_destinations}
              parkingOptions={results.parkings}
              comparedResults={comparedResults}
              calendarStartAt={calendarChartProps.calendarStartAt}
              calendarTimezone={calendarChartProps.calendarTimezone}
            />

            <div className="grid items-start gap-4 lg:grid-cols-2">
            <Card className="min-w-0 shadow-sm">
              <CardHeader className="p-4 pb-3">
                <CardTitle className="flex items-center gap-2"><Car className="size-5 text-primary" /> Parking areas attempted</CardTitle>
                <CardDescription>Distribution of distinct logical parking areas checked by each vehicle before parking or exhausting its destination-specific choices.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                {results.parking_attempts?.available ? (
                  <>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Vehicles measured</span><strong>{results.parking_attempts.summary.vehicle_count.toLocaleString()}</strong></div>
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Average attempts</span><strong>{Number(results.parking_attempts.summary.average_attempts.toFixed(2))}</strong></div>
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Used a fallback</span><strong>{results.parking_attempts.summary.vehicles_using_fallback.toLocaleString()} ({Number(results.parking_attempts.summary.fallback_percentage.toFixed(1))}%)</strong></div>
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Unserved</span><strong>{results.parking_attempts.summary.unserved_vehicle_count.toLocaleString()}</strong></div>
                    </div>
                    <ParkingAttemptChart points={results.parking_attempts.distribution} />
                  </>
                ) : (
                  <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">Parking-attempt data was not recorded for this run. Run a new simulation to populate this chart.</div>
                )}
              </CardContent>
            </Card>

            <Card className="min-w-0 shadow-sm">
              <CardHeader className="p-4 pb-3">
                <CardTitle className="flex items-center gap-2"><Search className="size-5 text-primary" /> Recorded parking search duration</CardTitle>
                <CardDescription>The line shows averages within time bins. Summary cards describe individual vehicles across the full run, so an individual percentile may be higher than every bin average.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Vehicles measured</span><strong>{results.search_times.summary.vehicle_count.toLocaleString()}</strong></div>
                  <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Overall average</span><strong>{formatRecordedDuration(results.search_times.summary.average_seconds)}</strong></div>
                  <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Individual median</span><strong>{formatRecordedDuration(results.search_times.summary.median_seconds)}</strong></div>
                  <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Individual 95th percentile</span><strong>{formatRecordedDuration(results.search_times.summary.p95_seconds)}</strong></div>
                </div>
                <AnalyticsLineChart points={searchPoints} series={searchSeries} xLabel={calendarChartProps.calendarStartAt ? "Simulated date and time" : "Simulation time"} yLabel="Average recorded duration (minutes)" color="#9333ea" {...calendarChartProps} />
              </CardContent>
            </Card>

            <Card className="min-w-0 shadow-sm">
              <CardHeader className="p-4 pb-3">
                <CardTitle className="flex items-center gap-2">
                  <Route className="size-5 text-primary" /> Vehicle journey segment duration
                </CardTitle>
                <CardDescription>
                  The line shows average segment duration within time bins. Summary cards describe individual segments across the full run; repeated parking visits remain separate segments.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                {results.trip_segments.available ? (
                  <>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <label className="space-y-1.5 text-sm font-medium">
                        Journey stage
                        <Select value={selectedJourneySegment} onValueChange={(value) => setSelectedJourneySegment(value as VehicleJourneySegmentType)}>
                          <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {results.trip_segments.segment_types.map((segmentType) => (
                              <SelectItem key={segmentType} value={segmentType}>{JOURNEY_SEGMENT_LABELS[segmentType]}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </label>
                      <label className="space-y-1.5 text-sm font-medium">
                        Parking area
                        <Select value={selectedSegmentParkingId} onValueChange={setSelectedSegmentParkingId}>
                          <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {results.trip_segments.parkings.map((parking) => (
                              <SelectItem key={parking.id} value={parking.id}>{parking.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </label>
                    </div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Segments</span><strong>{journeySegmentSummary?.segment_count.toLocaleString() ?? 0}</strong></div>
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Vehicles</span><strong>{journeySegmentSummary?.vehicle_count.toLocaleString() ?? 0}</strong></div>
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Overall average</span><strong>{formatRecordedDuration(journeySegmentSummary?.average_seconds ?? 0)}</strong></div>
                      <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Individual 95th percentile</span><strong>{formatRecordedDuration(journeySegmentSummary?.p95_seconds ?? 0)}</strong></div>
                    </div>
                    <AnalyticsLineChart
                      series={journeySegmentSeries}
                      xLabel={calendarChartProps.calendarStartAt ? "Simulated date and time" : "Segment start time"}
                      yLabel="Average segment duration (minutes)"
                      color="#0891b2"
                      {...calendarChartProps}
                    />
                    {selectedJourneySegment === "between_parkings" && !journeySegmentSeries.length && (
                      <p className="rounded-lg border border-dashed p-3 text-xs leading-5 text-muted-foreground">
                        No cross-parking fallback occurred in this run.
                      </p>
                    )}
                  </>
                ) : (
                  <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                    This is an older run without vehicle journey segment output. Run a new simulation to generate it.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="min-w-0 shadow-sm">
              <CardHeader className="p-4 pb-3">
                <CardTitle className="flex items-center gap-2"><Activity className="size-5 text-primary" /> Traffic detector measurements</CardTitle>
                <CardDescription>Count of vehicles or pedestrians that entered the selected detection zone during each interval.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                {results.detectors.definitions.length ? <>
                  <div>
                    <label className="space-y-1.5 text-sm font-medium">Detector
                      <Select value={selectedDetectorId} onValueChange={setSelectedDetectorId}><SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger><SelectContent>{results.detectors.definitions.map((detector) => <SelectItem key={detector.id} value={detector.id}>{detector.label}</SelectItem>)}</SelectContent></Select>
                    </label>
                  </div>
                  <div className="rounded-lg bg-muted/60 p-2.5">
                    <span className="block text-xs text-muted-foreground">Total {detectorSubjectLabel.toLowerCase()} entered</span>
                    <strong>{detectorEntryTotal.toLocaleString()}</strong>
                  </div>
                  <AnalyticsLineChart series={detectorSeries} xLabel={results.run.simulation_start_at ? "Simulated date and time" : "Simulation time"} yLabel={detectorMetricLabel} color="#0f766e" calendarStartAt={results.run.simulation_start_at} calendarTimezone={results.run.simulation_timezone} />
                  {detectorDefinition && <p className="text-xs text-muted-foreground">{detectorDefinition.type === "e1" ? <>SUMO lane <span className="font-mono">{detectorDefinition.lane_id}</span> · edge <span className="font-mono">{detectorDefinition.edge_id}</span></> : detectorDefinition.type === "e2" ? <>{detectorDefinition.physical_detectors?.length ?? 0} bidirectional pedestrian zone{(detectorDefinition.physical_detectors?.length ?? 0) === 1 ? "" : "s"}; each pedestrian is counted when entering a zone from either direction</> : <>{detectorDefinition.entries?.length ?? 0} entry and {detectorDefinition.exits?.length ?? 0} exit cross-sections</>} · {detectorDefinition.period_seconds}s intervals</p>}
                </> : <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">This run has no detector measurements. Add E1 or E3 detectors to the model and run a new simulation.</div>}
              </CardContent>
            </Card>
            </div>

            <Card className="min-w-0 shadow-sm">
              <CardHeader className="p-4 pb-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2"><RadioTower className="size-5 text-primary" /> Simulation detector vs real-world sensor</CardTitle>
                    <CardDescription className="mt-1">Compare vehicle and pedestrian flow together. Simulation entries are rebinned to the physical sensor's 15-minute intervals.</CardDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button type="button" variant="outline" size="sm" disabled={loadingRealWorld || !validationExportAvailable} onClick={downloadValidationComparison}>
                      <Download className="size-4" /> Download graph CSV
                    </Button>
                    <ToggleGroup type="single" value={realWorldMode} onValueChange={(value) => value && setRealWorldMode(value as "raw" | "weekly_average")} className="rounded-lg border bg-muted/40 p-1">
                      <ToggleGroupItem value="raw">Raw observations</ToggleGroupItem>
                      <ToggleGroupItem value="weekly_average">Weekly average</ToggleGroupItem>
                    </ToggleGroup>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 p-4 pt-0">
                {validationDetectorGroups.length && realWorldSources.length ? <>
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                    <label className="space-y-1.5 text-sm font-medium">
                      Simulation E3 detector
                      <Select value={validationDetectorId} onValueChange={setValidationDetectorId}>
                        <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                        <SelectContent>{validationDetectorGroups.map((group) => <SelectItem key={group.logicalId} value={group.logicalId}>{group.label}</SelectItem>)}</SelectContent>
                      </Select>
                    </label>
                    <label className="space-y-1.5 text-sm font-medium">
                      Real-world sensor location
                      <Select value={selectedRealWorldSourceId} onValueChange={setSelectedRealWorldSourceId}>
                        <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                        <SelectContent>{realWorldSources.map((source) => <SelectItem key={source.id} value={source.id}>{source.name}</SelectItem>)}</SelectContent>
                      </Select>
                    </label>
                    {realWorldMode === "raw" ? <label className="space-y-1.5 text-sm font-medium md:col-span-2">
                      Real-world window starts
                      <Input
                        className="mt-1.5 h-10 font-normal"
                        type="datetime-local"
                        value={realWorldStartAt}
                        min={selectedRealWorldSource?.start_at}
                        max={selectedRealWorldSource?.end_at}
                        onChange={(event) => setRealWorldStartAt(event.target.value)}
                      />
                    </label> : <>
                      <label className="space-y-1.5 text-sm font-medium">
                        Average profile starts on
                        <Select value={String(weeklyStartWeekday)} onValueChange={(value) => setWeeklyStartWeekday(Number(value))}>
                          <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                          <SelectContent>{WEEKDAYS.map((weekday, index) => <SelectItem key={weekday} value={String(index)}>{weekday}</SelectItem>)}</SelectContent>
                        </Select>
                      </label>
                      <label className="space-y-1.5 text-sm font-medium">
                        Start time
                        <Input className="mt-1.5 h-10 font-normal" type="time" step={900} value={weeklyStartTime} onChange={(event) => setWeeklyStartTime(event.target.value)} />
                      </label>
                    </>}
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="outline">Vehicles + pedestrians</Badge>
                    <Badge variant="outline">{formatDuration(results.run.duration_hours)} window</Badge>
                    <Badge variant="outline">900-second comparison intervals</Badge>
                    {selectedRealWorldSource && <Badge variant="outline">{selectedRealWorldSource.observation_count.toLocaleString()} physical observations</Badge>}
                    {realWorldMode === "weekly_average" && realWorldAverageSampleCount > 0 && <Badge variant="outline">~{Math.round(realWorldAverageSampleCount)} samples per average point</Badge>}
                  </div>
                  {realWorldError && <Alert variant="destructive"><AlertDescription>{realWorldError}</AlertDescription></Alert>}
                  {loadingRealWorld ? <div className="grid min-h-52 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground">Loading and aggregating vehicle and pedestrian observations…</div> : <div className="grid min-w-0 gap-3 lg:grid-cols-2">
                    {(["vehicles", "pedestrians"] as const).map((subject) => {
                      const diagnostics = validationDiagnostics[subject];
                      const physicalSeries = realWorldSeries[subject];
                      const title = subject === "vehicles" ? "Vehicle flow" : "Pedestrian flow";
                      const SubjectIcon = subject === "vehicles" ? Car : Footprints;
                      return <section key={subject} className="min-w-0 space-y-3 rounded-lg border bg-background p-3">
                        <div className="flex items-center justify-between gap-2">
                          <h3 className="flex items-center gap-2 text-sm font-semibold"><SubjectIcon className="size-4 text-primary" /> {title}</h3>
                          <Badge variant="secondary">15 min</Badge>
                        </div>
                        {diagnostics.points.length > 0 && diagnostics.entryCount === 0 && <Alert className="border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/35 dark:text-amber-100"><TriangleAlert className="size-4" /><AlertTitle>No simulated {subject} entered this detector area.</AlertTitle><AlertDescription>This is a genuine zero. The selected routes do not enter the measured area.</AlertDescription></Alert>}
                        {diagnostics.entryCount > 0 && diagnostics.completedCount === 0 && <Alert className="border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/35 dark:text-amber-100"><TriangleAlert className="size-4" /><AlertTitle>Entries recorded, but no completed traversal.</AlertTitle><AlertDescription>{diagnostics.entryCount.toLocaleString()} entry events were reconstructed and as many as {diagnostics.peakWithin.toLocaleString()} agents were tracked inside. This comparison uses entry flow.</AlertDescription></Alert>}
                        {physicalSeries && !physicalSeries.points.length && <Alert className="border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/35 dark:text-amber-100"><AlertDescription>No physical {subject} observations exist in this comparison window.</AlertDescription></Alert>}
                        <div className="space-y-1.5">
                          <p className="text-xs font-medium">Dashed simulation input · solid detector output and physical sensor</p>
                          <AnalyticsLineChart
                            series={[...validationInputSeries[subject], ...validationComparisonSeries[subject]]}
                            xLabel={results.run.simulation_start_at ? "Simulated date and time" : "Time from comparison start"}
                            calendarStartAt={results.run.simulation_start_at}
                            calendarTimezone={results.run.simulation_timezone}
                            yLabel={`${subject === "vehicles" ? "Vehicle" : "Pedestrian"} input and output (agents/hour)`}
                          />
                        </div>
                      </section>;
                    })}
                  </div>}
                  <p className="text-xs leading-5 text-muted-foreground">
                    Simulation values are entry counts summed into 900-second buckets and converted to agents/hour. Vehicles in the workbook are <strong>Car Total + Large vehicle Total</strong>. Weekly-average points are means for the same weekday and 15-minute time slot across all available weeks. Raw mode uses the selected real date/time and a window equal to this simulation's duration.
                  </p>
                </> : <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                  {!validationDetectorGroups.length ? "This simulation has no E3 detector that measures both vehicles and pedestrians." : "No ingested real-world sensor datasets are available."}
                </div>}
              </CardContent>
            </Card>

            <Collapsible asChild>
            <Card className="shadow-sm">
                <CollapsibleTrigger className="flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left">
                  <span className="flex items-center gap-2 font-medium"><Bug className="size-4 text-primary" /> Debug menu</span>
                  <span className="text-xs text-muted-foreground">
                    {(results.debug.errors.total + results.debug.warnings.total).toLocaleString()} recorded messages
                  </span>
                  <ChevronDown className="size-4 shrink-0 transition-transform [[data-state=open]>&]:rotate-180" />
                </CollapsibleTrigger>
                <CollapsibleContent>
                <CardContent className="space-y-3 border-t p-4">
                  {results.debug.log_available ? (
                    <Accordion type="multiple" className="space-y-3">
                      <DebugLogSection title="Errors" section={results.debug.errors} kind="error" />
                      <DebugLogSection title="Warnings" section={results.debug.warnings} kind="warning" />
                    </Accordion>
                  ) : (
                    <p className="text-sm text-muted-foreground">No simulation log is available for this run.</p>
                  )}
                </CardContent>
                </CollapsibleContent>
            </Card>
            </Collapsible>
          </div>
        )}
      </div>
    </main>
  );
}
