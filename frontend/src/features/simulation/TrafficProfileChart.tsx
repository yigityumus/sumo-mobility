import type { FourierTrafficParameters, TrafficModel } from "../../types/campus";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "../../components/ui/chart";

type Props = {
  durationHours: number;
  simulationStartAt: string;
  vehicleCount: number;
  pedestrianCount: number;
  vehicleModel: TrafficModel;
  pedestrianModel: TrafficModel;
  vehicleFourierParameters: FourierTrafficParameters;
  pedestrianFourierParameters: FourierTrafficParameters;
};

const NORMAL_RANGE_MASS = 0.9973002039;
const SAMPLE_COUNT = 65;

function baseArrivalRate(model: Exclude<TrafficModel, "fourier">, total: number, hour: number, durationHours: number) {
  if (total <= 0 || durationHours <= 0) return 0;
  if (model === "constant") return total / durationHours;
  if (model === "linear") return (2 * total * hour) / (durationHours * durationHours);

  const mean = durationHours / 2;
  const standardDeviation = durationHours / 6;
  const exponent = -0.5 * ((hour - mean) / standardDeviation) ** 2;
  return (total / (standardDeviation * Math.sqrt(2 * Math.PI) * NORMAL_RANGE_MASS)) * Math.exp(exponent);
}

function fourierProfile(hours: number[], durationHours: number, parameters: FourierTrafficParameters) {
  const referenceCount = 512;
  const peakCount = Math.min(Math.max(Math.round(parameters.peak_count), 1), 16);
  const harmonics = Math.min(Math.max(Math.round(parameters.harmonics), 1), 16);
  const width = Math.min(Math.max(parameters.peak_width_hours, 0.01), durationHours);
  const peakHeights = Array.from(
    { length: peakCount },
    (_, index) => Math.min(Math.max(parameters.peak_heights?.[index] ?? 1, 0), 3),
  );
  const logTargets = Array.from({ length: referenceCount }, (_, index) => {
    const hour = (durationHours * index) / referenceCount;
    let target = 0.05;
    for (let peak = 0; peak < peakCount; peak += 1) {
      const center = (durationHours * (peak + 0.5)) / peakCount;
      target += peakHeights[peak] * Math.exp(-0.5 * ((hour - center) / width) ** 2);
    }
    return Math.log(target);
  });

  const intercept = logTargets.reduce((sum, value) => sum + value, 0) / referenceCount;
  const coefficients = Array.from({ length: harmonics }, (_, harmonicIndex) => {
    const harmonic = harmonicIndex + 1;
    let sine = 0;
    let cosine = 0;
    for (let index = 0; index < referenceCount; index += 1) {
      const angle = (2 * Math.PI * harmonic * index) / referenceCount;
      sine += logTargets[index] * Math.sin(angle);
      cosine += logTargets[index] * Math.cos(angle);
    }
    return { sine: (2 * sine) / referenceCount, cosine: (2 * cosine) / referenceCount };
  });

  return hours.map((hour) => {
    let logRate = intercept;
    coefficients.forEach((coefficient, index) => {
      const angle = (2 * Math.PI * (index + 1) * hour) / durationHours;
      logRate += coefficient.sine * Math.sin(angle) + coefficient.cosine * Math.cos(angle);
    });
    return Math.exp(logRate);
  });
}

export function sampleRates(
  model: TrafficModel,
  total: number,
  hours: number[],
  durationHours: number,
  fourierParameters: FourierTrafficParameters,
) {
  if (model !== "fourier") {
    return hours.map((hour) => baseArrivalRate(model, total, hour, durationHours));
  }
  if (total <= 0) return hours.map(() => 0);
  const raw = fourierProfile(hours, durationHours, fourierParameters);
  const step = durationHours / (hours.length - 1);
  const area = raw.slice(0, -1).reduce((sum, value, index) => sum + ((value + raw[index + 1]) * step) / 2, 0);
  return raw.map((value) => value * total / area);
}

function formatAxisTime(hours: number) {
  if (hours < 48) return `${Number(hours.toFixed(1))}h`;
  return `${Number((hours / 24).toFixed(1))}d`;
}

function formatCalendarTime(start: string, hours: number) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(start);
  if (!match) return formatAxisTime(hours);
  const [, year, month, day, hour, minute] = match;
  const value = new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute) + hours * 3_600_000);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(value);
}

function formatRate(value: number) {
  if (value >= 100) return Math.round(value).toLocaleString();
  if (value >= 10) return value.toFixed(1);
  return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

export function trafficModelLabel(model: TrafficModel) {
  if (model === "constant") return "Constant distribution";
  if (model === "normal") return "Normal distribution";
  if (model === "fourier") return "Fourier distribution";
  return "Linear distribution";
}

export default function TrafficProfileChart({
  durationHours,
  simulationStartAt,
  vehicleCount,
  pedestrianCount,
  vehicleModel,
  pedestrianModel,
  vehicleFourierParameters,
  pedestrianFourierParameters,
}: Props) {
  const safeDuration = Math.min(Math.max(durationHours || 1, 1), 168);
  const hours = Array.from({ length: SAMPLE_COUNT }, (_, index) => (safeDuration * index) / (SAMPLE_COUNT - 1));
  const vehicleRates = sampleRates(vehicleModel, vehicleCount, hours, safeDuration, vehicleFourierParameters);
  const pedestrianRates = sampleRates(pedestrianModel, pedestrianCount, hours, safeDuration, pedestrianFourierParameters);
  const samples = hours.map((hour, index) => ({ hour, vehicles: vehicleRates[index], pedestrians: pedestrianRates[index] }));
  const config = {
    vehicles: { label: `Arriving by car · ${trafficModelLabel(vehicleModel)}`, color: "#2563eb" },
    pedestrians: { label: `Independent pedestrian departures · ${trafficModelLabel(pedestrianModel)}`, color: "#f97316" },
  } satisfies ChartConfig;
  const formatTime = (hour: number) => formatCalendarTime(simulationStartAt, hour);

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-x-5 gap-y-2 text-xs">
        <span className="inline-flex items-center gap-2"><span className="h-0.5 w-6 bg-blue-600" />Arriving by car · {trafficModelLabel(vehicleModel)}</span>
        <span className="inline-flex items-center gap-2"><span className="h-0.5 w-6 bg-orange-500" />Independent pedestrian departures · {trafficModelLabel(pedestrianModel)}</span>
      </div>
      <div className="rounded-lg border bg-background p-2">
        <ChartContainer config={config} className="h-[300px] w-full min-w-0 aspect-auto" aria-label={`Traffic arrival rates over ${safeDuration} simulation hours`}>
          <LineChart accessibilityLayer data={samples} margin={{ top: 12, right: 18, bottom: 18, left: 12 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="hour" type="number" domain={[0, safeDuration]} tickFormatter={formatTime} label={{ value: "Simulated date and time", position: "insideBottom", offset: -12 }} />
            <YAxis tickFormatter={formatRate} width={54} label={{ value: "Agents per hour", angle: -90, position: "insideLeft" }} />
            <ChartTooltip content={<ChartTooltipContent labelFormatter={(hour) => formatTime(Number(hour))} formatter={(value) => formatRate(Number(value))} />} />
            <Line type="monotone" dataKey="vehicles" stroke="var(--color-vehicles, #2563eb)" strokeWidth={3} dot={false} />
            <Line type="monotone" dataKey="pedestrians" stroke="var(--color-pedestrians, #f97316)" strokeWidth={3} dot={false} />
          </LineChart>
        </ChartContainer>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        The area under each curve equals its requested agent total. Fourier profiles use editable peaks and a periodic harmonic approximation; the same profile drives the generated SUMO departures.
      </p>
    </div>
  );
}
