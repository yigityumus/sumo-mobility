import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Car, Footprints, RefreshCw, TrendingUp } from "lucide-react";
import { getAnalytics, getRealWorldSeries } from "../../api/analytics";
import type {
  AnalyticsData,
  AnalyticsRun,
  CalibrationSubject,
  FlowCalibrationMetrics,
  FlowCalibrationPeakResult,
  RealWorldSeries,
} from "../../types/campus";
import { Alert, AlertDescription } from "../../components/ui/alert";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { sampleRates } from "../simulation/TrafficProfileChart";
import AnalyticsLineChart, { type AnalyticsChartSeries } from "./AnalyticsLineChart";


const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SUBJECTS: CalibrationSubject[] = ["vehicles", "pedestrians"];

type ComputedPeak = {
  peak_index: number;
  center_seconds: number;
  real_flow_per_hour: number;
  simulation_flow_per_hour: number;
  residual_flow_per_hour: number;
  percentage_error: number | null;
};

type ComputedResult = {
  metrics: FlowCalibrationMetrics;
  peaks: ComputedPeak[];
};

function weeklyPosition(value: string, timezone: string) {
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).formatToParts(date);
  const item = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    weekday: Math.max(WEEKDAYS.indexOf(item.weekday), 0),
    seconds: Number(item.hour) * 3600 + Number(item.minute) * 60 + Number(item.second),
  };
}

function colorForIteration(iteration: number) {
  return `hsl(${(iteration * 137.508) % 360} 68% 43%)`;
}

function colorForPeak(peak: number) {
  return `hsl(${(peak * 97.31) % 360} 66% 44%)`;
}

function percent(value: number) {
  return `${Number((value * 100).toFixed(2))}%`;
}

function signedPercent(value: number | null) {
  if (value == null) return "—";
  const amount = Number((value * 100).toFixed(2));
  return `${amount > 0 ? "+" : ""}${amount}%`;
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function correlation(left: number[], right: number[]) {
  if (left.length < 2) return left[0] === right[0] ? 1 : 0;
  const leftMean = mean(left);
  const rightMean = mean(right);
  const numerator = left.reduce((sum, value, index) => sum + (value - leftMean) * (right[index] - rightMean), 0);
  const leftScale = Math.sqrt(left.reduce((sum, value) => sum + (value - leftMean) ** 2, 0));
  const rightScale = Math.sqrt(right.reduce((sum, value) => sum + (value - rightMean) ** 2, 0));
  return leftScale && rightScale ? Math.min(Math.max(numerator / (leftScale * rightScale), -1), 1) : 0;
}

function averageWindow(points: Array<{ x: number; y: number }>, start: number, end: number) {
  return mean(points.filter((point) => point.x >= start && point.x < end).map((point) => point.y));
}

function computedResult(
  analytics: AnalyticsData,
  real: RealWorldSeries | null,
  subject: CalibrationSubject,
): ComputedResult | null {
  if (!real) return null;
  const metadata = analytics.run.calibration;
  const definition = analytics.detectors.definitions.find((candidate) => (
    candidate.logical_id === metadata?.detector_logical_id && candidate.subject === subject
  ));
  if (!definition) return null;
  const output = (analytics.detectors.comparison_series[definition.id] ?? []).map((point) => ({
    x: point.begin_seconds,
    y: point.flow_per_hour,
  }));
  const physical = real.points.map((point) => ({ x: point.time_seconds, y: point.flow_per_hour }));
  const profile = subject === "vehicles"
    ? analytics.run.vehicle_fourier_parameters
    : analytics.run.pedestrian_fourier_parameters;
  const peakCount = Math.max(profile.peak_count || 1, 1);
  const spacing = analytics.run.duration_seconds / peakCount;
  const peaks = Array.from({ length: peakCount }, (_, index) => {
    const start = index * spacing;
    const end = (index + 1) * spacing;
    const realFlow = averageWindow(physical, start, end);
    const simulationFlow = averageWindow(output, start, end);
    return {
      peak_index: index + 1,
      center_seconds: start + spacing / 2,
      real_flow_per_hour: realFlow,
      simulation_flow_per_hour: simulationFlow,
      residual_flow_per_hour: simulationFlow - realFlow,
      percentage_error: realFlow > 0 ? (simulationFlow - realFlow) / realFlow : null,
    };
  });
  const realValues = peaks.map((peak) => peak.real_flow_per_hour);
  const simulatedValues = peaks.map((peak) => peak.simulation_flow_per_hour);
  const errors = peaks.map((peak) => peak.residual_flow_per_hour);
  const meanReal = Math.max(mean(realValues), 1);
  const mae = mean(errors.map(Math.abs));
  const rmse = Math.sqrt(mean(errors.map((value) => value ** 2)));
  const curveCorrelation = correlation(realValues, simulatedValues);
  const totalVariation = realValues.reduce((sum, value) => sum + (value - mean(realValues)) ** 2, 0);
  const sumSquaredError = errors.reduce((sum, value) => sum + value ** 2, 0);
  const percentageErrors = peaks.filter((peak) => peak.real_flow_per_hour > 0).map((peak) => Math.abs(peak.percentage_error ?? 0));
  const symmetricErrors = peaks
    .filter((peak) => Math.abs(peak.real_flow_per_hour) + Math.abs(peak.simulation_flow_per_hour) > 0)
    .map((peak) => 2 * Math.abs(peak.residual_flow_per_hour) / (Math.abs(peak.real_flow_per_hour) + Math.abs(peak.simulation_flow_per_hour)));
  return {
    peaks,
    metrics: {
      mae_flow_per_hour: mae,
      rmse_flow_per_hour: rmse,
      normalized_mae: mae / meanReal,
      normalized_rmse: rmse / meanReal,
      volume_error: Math.abs(mean(simulatedValues) - mean(realValues)) / meanReal,
      correlation: curveCorrelation,
      shape_error: (1 - curveCorrelation) / 2,
      mean_bias_flow_per_hour: mean(errors),
      normalized_bias: mean(errors) / meanReal,
      mean_absolute_percentage_error: mean(percentageErrors),
      symmetric_mean_absolute_percentage_error: mean(symmetricErrors),
      nash_sutcliffe_efficiency: totalVariation > 0 ? 1 - sumSquaredError / totalVariation : 0,
      real_mean_flow_per_hour: mean(realValues),
      simulation_mean_flow_per_hour: mean(simulatedValues),
      peak_count: peakCount,
      peak_spacing_seconds: spacing,
    },
  };
}

function profileFor(analytics: AnalyticsData, subject: CalibrationSubject) {
  return subject === "vehicles"
    ? analytics.run.vehicle_fourier_parameters
    : analytics.run.pedestrian_fourier_parameters;
}

function inputSeries(analytics: AnalyticsData, subject: CalibrationSubject): AnalyticsChartSeries {
  const durationHours = analytics.run.duration_hours;
  const sampleCount = Math.max(Math.ceil(analytics.run.duration_seconds / 900) + 1, 2);
  const hours = Array.from({ length: sampleCount }, (_, index) => durationHours * index / (sampleCount - 1));
  const total = subject === "vehicles" ? analytics.run.vehicle_count : analytics.run.pedestrian_count;
  const iteration = analytics.run.calibration?.iteration ?? 0;
  return {
    id: `input_${analytics.run.id}`,
    label: `Iteration ${iteration} input`,
    color: colorForIteration(iteration),
    strokeDasharray: "8 5",
    points: sampleRates("fourier", total, hours, durationHours, profileFor(analytics, subject))
      .map((value, index) => ({ x: hours[index] * 3600, y: value })),
  };
}

function outputSeries(
  analytics: AnalyticsData,
  subject: CalibrationSubject,
): AnalyticsChartSeries | null {
  const detectorId = analytics.run.calibration?.detector_logical_id;
  const definition = analytics.detectors.definitions.find((candidate) => (
    candidate.logical_id === detectorId && candidate.subject === subject
  ));
  if (!definition) return null;
  const iteration = analytics.run.calibration?.iteration ?? 0;
  return {
    id: `output_${analytics.run.id}`,
    label: `Iteration ${iteration} detector output`,
    color: colorForIteration(iteration),
    points: (analytics.detectors.comparison_series[definition.id] ?? []).map((point) => ({
      x: point.begin_seconds,
      y: point.flow_per_hour,
    })),
  };
}

function methodLabel(value: FlowCalibrationPeakResult["update_method"] | undefined) {
  if (value === "hill") return "Hill saturation fit";
  if (value === "local_elasticity") return "Local elasticity";
  if (value === "undefined_zero_flow") return "Undefined: zero output";
  if (!value) return "Legacy proportional update";
  return "Proportional ratio";
}

export default function FlowCalibrationPanel({ runs, selected }: { runs: AnalyticsRun[]; selected: AnalyticsData }) {
  const metadata = selected.run.calibration;
  const [enabledIds, setEnabledIds] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<Record<string, AnalyticsData>>({});
  const [real, setReal] = useState<Record<CalibrationSubject, RealWorldSeries | null>>({ vehicles: null, pedestrians: null });
  const [detailSubject, setDetailSubject] = useState<CalibrationSubject>("vehicles");
  const [selectedPeak, setSelectedPeak] = useState("1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const calibrationIdRef = useRef<string | null>(null);
  const knownRunIdsRef = useRef<Set<string>>(new Set());

  const orderedRuns = useMemo(() => [...runs].sort((left, right) => (
    (left.calibration?.iteration ?? 0) - (right.calibration?.iteration ?? 0)
  )), [runs]);
  const orderedRunIds = orderedRuns.map((run) => run.id).join("|");

  useEffect(() => {
    const currentIds = new Set(orderedRuns.map((run) => run.id));
    if (calibrationIdRef.current !== metadata?.id) {
      calibrationIdRef.current = metadata?.id ?? null;
      knownRunIdsRef.current = currentIds;
      setEnabledIds(currentIds);
      return;
    }
    const newIds = [...currentIds].filter((id) => !knownRunIdsRef.current.has(id));
    knownRunIdsRef.current = currentIds;
    if (newIds.length) {
      setEnabledIds((current) => new Set([...current, ...newIds]));
    }
  }, [metadata?.id, orderedRunIds]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void Promise.allSettled(orderedRuns.map((run) => getAnalytics(run.id))).then((settled) => {
      if (cancelled) return;
      const loaded: Record<string, AnalyticsData> = {};
      settled.forEach((item, index) => {
        if (item.status === "fulfilled") loaded[orderedRuns[index].id] = item.value;
      });
      setResults(loaded);
      const failed = settled.length - Object.keys(loaded).length;
      setError(failed ? `${failed} calibration iteration${failed === 1 ? "" : "s"} could not be loaded.` : "");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [orderedRunIds]);

  useEffect(() => {
    if (!metadata || !selected.run.simulation_start_at) return;
    const position = weeklyPosition(selected.run.simulation_start_at, selected.run.simulation_timezone || "Europe/Paris");
    let cancelled = false;
    void Promise.all(SUBJECTS.map((subject) => getRealWorldSeries({
      sourceId: metadata.source_id,
      mode: "weekly_average",
      subject,
      durationSeconds: selected.run.duration_seconds,
      startWeekday: position.weekday,
      startTimeSeconds: position.seconds,
    }))).then(([vehicles, pedestrians]) => {
      if (!cancelled) setReal({ vehicles, pedestrians });
    }).catch((caughtError) => {
      if (!cancelled) setError(caughtError instanceof Error ? caughtError.message : "Could not load the physical sensor.");
    });
    return () => { cancelled = true; };
  }, [metadata?.id, selected.run.duration_seconds, selected.run.simulation_start_at, selected.run.simulation_timezone]);

  if (!metadata) return null;

  const loaded = orderedRuns.map((run) => results[run.id]).filter((item): item is AnalyticsData => Boolean(item));
  const enabled = loaded.filter((item) => enabledIds.has(item.run.id));
  const calculations = new Map<string, ComputedResult | null>();
  for (const item of loaded) {
    for (const subject of SUBJECTS) calculations.set(`${item.run.id}:${subject}`, computedResult(item, real[subject], subject));
  }
  const summaryRows = loaded.flatMap((item) => SUBJECTS.map((subject) => ({
    item,
    subject,
    metrics: calculations.get(`${item.run.id}:${subject}`)?.metrics ?? null,
  })));
  const peakCount = Math.max(profileFor(selected, detailSubject).peak_count || 1, 1);
  const selectedPeakIndex = Math.min(Math.max(Number(selectedPeak) || 1, 1), peakCount) - 1;
  const iterationFormat = (value: number) => `${Math.round(value)}`;
  const errorSeries: AnalyticsChartSeries[] = [
    ["normalized_rmse", "NRMSE", "#dc2626"],
    ["normalized_mae", "NMAE", "#f97316"],
    ["shape_error", "Shape error", "#7c3aed"],
    ["volume_error", "Volume error", "#0891b2"],
  ].map(([key, label, color]) => ({
    id: key,
    label,
    color,
    points: loaded.flatMap((item) => {
      const metrics = calculations.get(`${item.run.id}:${detailSubject}`)?.metrics;
      return metrics ? [{ x: item.run.calibration?.iteration ?? 0, y: metrics[key as keyof FlowCalibrationMetrics] as number * 100 }] : [];
    }),
  }));
  const percentageSeries: AnalyticsChartSeries[] = [{
    id: "input_percentage",
    label: `Peak ${selectedPeakIndex + 1} input percentage`,
    color: colorForPeak(selectedPeakIndex + 1),
    points: loaded.map((item) => ({
      x: item.run.calibration?.iteration ?? 0,
      y: (profileFor(item, detailSubject).peak_heights[selectedPeakIndex] ?? 0) * 100,
    })),
  }];
  const peakResponseSeries: AnalyticsChartSeries[] = [{
    id: "physical_target",
    label: "Physical target",
    color: "#111827",
    points: loaded.flatMap((item) => {
      const peak = calculations.get(`${item.run.id}:${detailSubject}`)?.peaks[selectedPeakIndex];
      return peak ? [{ x: item.run.calibration?.iteration ?? 0, y: peak.real_flow_per_hour }] : [];
    }),
  }, {
    id: "simulated_output",
    label: "Simulated detector output",
    color: "#2563eb",
    points: loaded.flatMap((item) => {
      const peak = calculations.get(`${item.run.id}:${detailSubject}`)?.peaks[selectedPeakIndex];
      return peak ? [{ x: item.run.calibration?.iteration ?? 0, y: peak.simulation_flow_per_hour }] : [];
    }),
  }];
  const detailRows = loaded.flatMap((item) => {
    const computed = calculations.get(`${item.run.id}:${detailSubject}`);
    const stored = item.run.calibration?.result?.subjects[detailSubject]?.peaks ?? [];
    return (computed?.peaks ?? []).map((peak, index) => ({ item, peak, stored: stored[index] }));
  });

  const toggleRun = (id: string, checked: boolean) => setEnabledIds((current) => {
    const next = new Set(current);
    if (checked) next.add(id); else next.delete(id);
    return next;
  });

  return <Card className="shadow-sm">
    <CardHeader className="p-4 pb-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2"><RefreshCw className="size-5 text-primary" /> {metadata.name}</CardTitle>
          <CardDescription className="mt-1">Locked calibration group · {orderedRuns.length}/{metadata.total_iterations} iterations available · {metadata.step_percentage ?? 1}% minimum step.</CardDescription>
        </div>
        <div className="flex gap-2"><Badge variant="outline">Adaptive Hill response</Badge><Badge variant="outline">Both subjects shown</Badge></div>
      </div>
    </CardHeader>
    <CardContent className="space-y-4 p-4 pt-0">
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => setEnabledIds(new Set(orderedRuns.map((run) => run.id)))}>Select all</Button>
        <Button type="button" size="sm" variant="outline" onClick={() => setEnabledIds(new Set())}>Clear</Button>
        {orderedRuns.map((run) => <label key={run.id} className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs" style={{ borderColor: colorForIteration(run.calibration?.iteration ?? 0) }}>
          <Checkbox checked={enabledIds.has(run.id)} onCheckedChange={(checked) => toggleRun(run.id, checked === true)} />
          Iteration {run.calibration?.iteration}
        </label>)}
      </div>
      {loading ? <div className="grid min-h-48 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground">Loading calibration iterations…</div> : <Tabs defaultValue="profiles">
        <TabsList className="grid h-auto w-full grid-cols-3">
          <TabsTrigger value="profiles">Input vs output</TabsTrigger>
          <TabsTrigger value="progress">Iteration progress</TabsTrigger>
          <TabsTrigger value="statistics">Statistics</TabsTrigger>
        </TabsList>

        <TabsContent value="profiles" className="space-y-5 pt-2">
          {SUBJECTS.map((subject) => {
            const SubjectIcon = subject === "vehicles" ? Car : Footprints;
            const physical = real[subject];
            const inputs = enabled.map((item) => inputSeries(item, subject));
            const outputs = enabled.map((item) => outputSeries(item, subject)).filter((item): item is AnalyticsChartSeries => Boolean(item));
            const outputWithPhysical: AnalyticsChartSeries[] = physical ? [{
              id: `physical_${subject}`,
              label: `${physical.source.name} weekly average`,
              color: "#111827",
              strokeWidth: 3,
              points: physical.points.map((point) => ({ x: point.time_seconds, y: point.flow_per_hour })),
            }, ...outputs] : outputs;
            const combinedSeries = [...inputs, ...outputWithPhysical];
            return <section key={subject} className="space-y-3 rounded-lg border p-3">
              <h3 className="flex items-center gap-2 font-semibold"><SubjectIcon className="size-4 text-primary" /> {subject === "vehicles" ? "Vehicles" : "Pedestrians"}</h3>
              <div className="min-w-0 space-y-1.5"><p className="text-xs font-medium">Dashed input demand · solid detector output · black physical target</p><AnalyticsLineChart series={combinedSeries} xLabel="Simulation time" yLabel="Flow (agents/hour)" calendarStartAt={selected.run.simulation_start_at} calendarTimezone={selected.run.simulation_timezone} /></div>
            </section>;
          })}
          <Alert><Activity className="size-4" /><AlertDescription className="text-xs">Input is total network-wide generated demand; output is flow through one detector. Their levels need not match. Compare how changes in the input shape move the detector output shape.</AlertDescription></Alert>
        </TabsContent>

        <TabsContent value="progress" className="space-y-4 pt-2">
          <div className="flex flex-wrap gap-3">
            <Select value={detailSubject} onValueChange={(value) => { setDetailSubject(value as CalibrationSubject); setSelectedPeak("1"); }}><SelectTrigger className="w-48"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="vehicles">Vehicles</SelectItem><SelectItem value="pedestrians">Pedestrians</SelectItem></SelectContent></Select>
            <Select value={String(selectedPeakIndex + 1)} onValueChange={setSelectedPeak}><SelectTrigger className="w-40"><SelectValue /></SelectTrigger><SelectContent>{Array.from({ length: peakCount }, (_, index) => <SelectItem key={index} value={String(index + 1)}>Peak {index + 1}</SelectItem>)}</SelectContent></Select>
          </div>
          <div className="grid min-w-0 gap-3 xl:grid-cols-2">
            <AnalyticsLineChart series={percentageSeries} xLabel="Iteration" yLabel="Input percentage" formatX={iterationFormat} formatY={(value) => `${Number(value.toFixed(1))}%`} />
            <AnalyticsLineChart series={peakResponseSeries} xLabel="Iteration" yLabel="Peak-window flow (agents/hour)" formatX={iterationFormat} />
          </div>
          <AnalyticsLineChart series={errorSeries} xLabel="Iteration" yLabel="Error (%)" formatX={iterationFormat} formatY={(value) => `${Number(value.toFixed(1))}%`} />
          <p className="flex items-center gap-2 text-xs text-muted-foreground"><TrendingUp className="size-3.5" /> Select a peak to see whether its input change produced the expected detector response. Error curves use every peak window for the selected subject.</p>
        </TabsContent>

        <TabsContent value="statistics" className="space-y-4 pt-2">
          <div className="overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Iteration</TableHead><TableHead>Subject</TableHead><TableHead className="text-right">NRMSE</TableHead><TableHead className="text-right">NMAE</TableHead><TableHead className="text-right">MAPE</TableHead><TableHead className="text-right">Bias</TableHead><TableHead className="text-right">Shape</TableHead><TableHead className="text-right">Volume</TableHead><TableHead className="text-right">Correlation</TableHead><TableHead className="text-right">NSE</TableHead></TableRow></TableHeader><TableBody>{summaryRows.map(({ item, subject, metrics }) => <TableRow key={`${item.run.id}:${subject}`}><TableCell>{item.run.calibration?.iteration}</TableCell><TableCell>{subject}</TableCell><TableCell className="text-right">{metrics ? percent(metrics.normalized_rmse) : "—"}</TableCell><TableCell className="text-right">{metrics ? percent(metrics.normalized_mae) : "—"}</TableCell><TableCell className="text-right">{metrics ? percent(metrics.mean_absolute_percentage_error) : "—"}</TableCell><TableCell className="text-right">{metrics ? signedPercent(metrics.normalized_bias) : "—"}</TableCell><TableCell className="text-right">{metrics ? percent(metrics.shape_error) : "—"}</TableCell><TableCell className="text-right">{metrics ? percent(metrics.volume_error) : "—"}</TableCell><TableCell className="text-right">{metrics ? metrics.correlation.toFixed(3) : "—"}</TableCell><TableCell className="text-right">{metrics ? metrics.nash_sutcliffe_efficiency.toFixed(3) : "—"}</TableCell></TableRow>)}</TableBody></Table></div>
          <div className="flex flex-wrap items-end gap-3"><label className="space-y-1 text-sm font-medium">Detailed peak statistics<Select value={detailSubject} onValueChange={(value) => setDetailSubject(value as CalibrationSubject)}><SelectTrigger className="mt-1 w-48"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="vehicles">Vehicles</SelectItem><SelectItem value="pedestrians">Pedestrians</SelectItem></SelectContent></Select></label></div>
          <div className="max-h-[32rem] overflow-auto rounded-lg border"><Table><TableHeader className="sticky top-0 bg-background"><TableRow><TableHead>Iteration</TableHead><TableHead>Peak</TableHead><TableHead className="text-right">Input</TableHead><TableHead className="text-right">Real</TableHead><TableHead className="text-right">Output</TableHead><TableHead className="text-right">Residual</TableHead><TableHead className="text-right">Error</TableHead><TableHead>Update model</TableHead><TableHead className="text-right">Proposed</TableHead><TableHead className="text-right">Next</TableHead><TableHead className="text-right">Predicted output</TableHead></TableRow></TableHeader><TableBody>{detailRows.map(({ item, peak, stored }) => <TableRow key={`${item.run.id}:${peak.peak_index}`}><TableCell>{item.run.calibration?.iteration}</TableCell><TableCell>{peak.peak_index}</TableCell><TableCell className="text-right">{((profileFor(item, detailSubject).peak_heights[peak.peak_index - 1] ?? 0) * 100).toFixed(1)}%</TableCell><TableCell className="text-right">{peak.real_flow_per_hour.toFixed(1)}</TableCell><TableCell className="text-right">{peak.simulation_flow_per_hour.toFixed(1)}</TableCell><TableCell className="text-right">{peak.residual_flow_per_hour > 0 ? "+" : ""}{peak.residual_flow_per_hour.toFixed(1)}</TableCell><TableCell className="text-right">{signedPercent(peak.percentage_error)}</TableCell><TableCell>{stored ? methodLabel(stored.update_method) : "Not calibrated"}{stored?.hill_model ? ` (R² ${stored.hill_model.r_squared.toFixed(2)})` : stored?.estimated_elasticity != null ? ` (e ${stored.estimated_elasticity.toFixed(2)})` : ""}</TableCell><TableCell className="text-right">{stored?.proposed_percentage != null ? `${stored.proposed_percentage.toFixed(1)}%` : "—"}</TableCell><TableCell className="text-right">{stored ? `${stored.new_percentage.toFixed(1)}%` : "—"}</TableCell><TableCell className="text-right">{stored?.predicted_next_flow_per_hour != null ? stored.predicted_next_flow_per_hour.toFixed(1) : "—"}</TableCell></TableRow>)}</TableBody></Table></div>
          <Alert><Activity className="size-4" /><AlertDescription className="space-y-1 text-xs"><p><strong>NRMSE/NMAE/MAPE</strong> measure overall size of the error; lower is better. <strong>Bias</strong> shows consistent overproduction (+) or underproduction (−).</p><p><strong>Shape error</strong> is derived from correlation; lower is better. <strong>Volume error</strong> compares total flow. <strong>NSE</strong> is 1 for a perfect match, 0 when no better than the physical mean, and negative when worse.</p></AlertDescription></Alert>
        </TabsContent>
      </Tabs>}
    </CardContent>
  </Card>;
}
