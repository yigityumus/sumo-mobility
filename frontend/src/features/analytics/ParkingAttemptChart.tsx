import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "../../components/ui/chart";
import type { ParkingAttemptPoint } from "../../types/campus";

const config = {
  vehicle_count: { label: "Vehicles", color: "#ea580c" },
} satisfies ChartConfig;

export default function ParkingAttemptChart({ points }: { points: ParkingAttemptPoint[] }) {
  if (!points.length) {
    return <div className="grid min-h-52 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground">No vehicle reached a parking decision in this run.</div>;
  }

  return (
    <div className="rounded-lg border bg-background p-1.5">
      <div className="grid grid-cols-[2rem_minmax(0,1fr)] items-stretch">
        <div className="flex h-[250px] items-center justify-center" aria-hidden="true">
          <span className="rotate-180 whitespace-nowrap text-xs text-muted-foreground [writing-mode:vertical-rl]">Number of vehicles</span>
        </div>
        <ChartContainer config={config} className="h-[250px] w-full min-w-0 aspect-auto" aria-label="Distribution of parking areas attempted per vehicle">
          <BarChart accessibilityLayer data={points} margin={{ top: 12, right: 14, bottom: 18, left: 4 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="attempt_count" allowDecimals={false} label={{ value: "Distinct parking areas attempted", position: "insideBottom", offset: -12 }} />
            <YAxis allowDecimals={false} width={64} tickMargin={8} tick={{ fontSize: 11 }} />
            <ChartTooltip
              content={<ChartTooltipContent
                labelFormatter={(value) => `${value} parking area${Number(value) === 1 ? "" : "s"} attempted`}
                formatter={(value) => `${value.toLocaleString()} vehicle${value === 1 ? "" : "s"}`}
              />}
            />
            <Bar dataKey="vehicle_count" fill="var(--color-vehicle_count)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </div>
    </div>
  );
}
