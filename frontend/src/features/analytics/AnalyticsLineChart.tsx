import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "../../components/ui/chart";

export type ChartPoint = {
  x: number;
  y: number;
  label?: string;
};

export type AnalyticsChartSeries = {
  id: string;
  label: string;
  color: string;
  points: ChartPoint[];
  strokeDasharray?: string;
  strokeWidth?: number;
  showDots?: boolean;
};

type Props = {
  points?: ChartPoint[];
  series?: AnalyticsChartSeries[];
  xLabel: string;
  yLabel: string;
  color?: string;
  fixedMaximumY?: number;
  formatY?: (value: number) => string;
  formatX?: (value: number) => string;
  calendarStartAt?: string | null;
  calendarTimezone?: string | null;
};

function formatSimulationTime(seconds: number) {
  const hours = seconds / 3600;
  if (hours < 1) return `${Math.round(seconds / 60)}m`;
  if (hours < 48) return `${Number(hours.toFixed(1))}h`;
  return `${Number((hours / 24).toFixed(1))}d`;
}

function formatCalendarTime(startAt: string, timezone: string, seconds: number) {
  const start = new Date(startAt);
  if (Number.isNaN(start.getTime())) return formatSimulationTime(seconds);
  const value = new Date(start.getTime() + seconds * 1000);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(value);
}

function defaultFormatY(value: number) {
  if (value >= 100) return Math.round(value).toLocaleString();
  return Number(value.toFixed(1)).toLocaleString();
}

export default function AnalyticsLineChart({
  points = [],
  series,
  xLabel,
  yLabel,
  color = "#2563eb",
  fixedMaximumY,
  formatY = defaultFormatY,
  formatX: customFormatX,
  calendarStartAt,
  calendarTimezone = "Europe/Paris",
}: Props) {
  const visibleSeries = series?.length ? series.filter((item) => item.points.length) : [{ id: "value", label: yLabel, color, points }];
  const allPoints = visibleSeries.flatMap((item) => item.points);
  if (!allPoints.length) {
    return <div className="grid min-h-52 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground">No chart data is available for this dataset.</div>;
  }

  const maximumX = Math.max(...allPoints.map((point) => point.x), 1);
  const maximumY = fixedMaximumY ?? Math.max(...allPoints.map((point) => point.y), 1) * 1.08;
  const config = Object.fromEntries(visibleSeries.map((item) => [item.id, { label: item.label, color: item.color }])) satisfies ChartConfig;
  const merged = new Map<number, Record<string, number>>();
  visibleSeries.forEach((item) => {
    item.points.forEach((point) => {
      const row = merged.get(point.x) ?? { x: point.x };
      row[item.id] = point.y;
      merged.set(point.x, row);
    });
  });
  const data = [...merged.values()].sort((left, right) => left.x - right.x);
  const formatX = (seconds: number) => customFormatX
    ? customFormatX(seconds)
    : calendarStartAt
      ? formatCalendarTime(calendarStartAt, calendarTimezone || "Europe/Paris", seconds)
      : formatSimulationTime(seconds);

  return (
    <div className="rounded-lg border bg-background p-1.5">
      {visibleSeries.length > 1 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-2 pb-1.5 pt-1 text-[11px]">
          {visibleSeries.map((item) => (
            <span key={item.id} className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className="h-0.5 w-4" style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      )}
      <div className="grid grid-cols-[2rem_minmax(0,1fr)] items-stretch">
        <div className="flex h-[250px] items-center justify-center overflow-visible" aria-hidden="true">
          <span className="rotate-180 whitespace-nowrap text-xs text-muted-foreground [writing-mode:vertical-rl]">
            {yLabel}
          </span>
        </div>
        <ChartContainer config={config} className="h-[250px] w-full min-w-0 aspect-auto" aria-label={`${yLabel} over ${xLabel}`}>
          <LineChart accessibilityLayer data={data} margin={{ top: 12, right: 14, bottom: 18, left: 4 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="x" type="number" domain={[0, maximumX]} tickFormatter={formatX} label={{ value: xLabel, position: "insideBottom", offset: -12 }} />
            <YAxis
              domain={[0, maximumY]}
              tickFormatter={formatY}
              width={64}
              tickMargin={8}
              tick={{ fontSize: 11 }}
            />
            <ChartTooltip content={<ChartTooltipContent labelFormatter={(value) => formatX(Number(value))} formatter={(value) => formatY(Number(value))} />} />
            {visibleSeries.map((item) => (
              <Line
                key={item.id}
                type="monotone"
                dataKey={item.id}
                stroke={item.color}
                strokeWidth={item.strokeWidth ?? (visibleSeries.length > 1 ? 2.25 : 3)}
                strokeDasharray={item.strokeDasharray}
                dot={item.showDots ?? (visibleSeries.length === 1 && item.points.length <= 60)}
                connectNulls
              />
            ))}
          </LineChart>
        </ChartContainer>
      </div>
    </div>
  );
}
