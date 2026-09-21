import type { AnalyticsRun, AnalyticsData, RealWorldSeries, RealWorldSource } from "../types/campus";
import { requestJson } from "./client";

export function listAnalyticsRuns() {
  return requestJson<AnalyticsRun[]>(
    "/api/analytics",
    {},
    "Could not load analytics runs.",
  );
}

export function getAnalytics(runId: string) {
  return requestJson<AnalyticsData>(
    `/api/analytics/${encodeURIComponent(runId)}`,
    {},
    "Could not load analytics data.",
  );
}

export function listRealWorldSources() {
  return requestJson<RealWorldSource[]>(
    "/api/analytics/real-world/sources",
    {},
    "Could not load real-world sensor sources.",
  );
}

export function getRealWorldSeries(options: {
  sourceId: string;
  mode: "raw" | "weekly_average";
  subject: "vehicles" | "pedestrians";
  durationSeconds: number;
  startAt?: string;
  startWeekday?: number;
  startTimeSeconds?: number;
}) {
  const query = new URLSearchParams({
    source_id: options.sourceId,
    mode: options.mode,
    subject: options.subject,
    duration_seconds: String(options.durationSeconds),
  });
  if (options.startAt) query.set("start_at", options.startAt);
  if (options.startWeekday !== undefined) query.set("start_weekday", String(options.startWeekday));
  if (options.startTimeSeconds !== undefined) query.set("start_time_seconds", String(options.startTimeSeconds));
  return requestJson<RealWorldSeries>(
    `/api/analytics/real-world/series?${query.toString()}`,
    {},
    "Could not load real-world sensor data.",
  );
}
