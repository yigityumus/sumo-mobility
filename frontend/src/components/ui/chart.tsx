import * as React from "react";
import { ResponsiveContainer, Tooltip as RechartsTooltip, type TooltipContentProps } from "recharts";
import { cn } from "../../lib/utils";

export type ChartConfig = Record<string, { label?: React.ReactNode; color?: string }>;

const ChartContext = React.createContext<ChartConfig>({});

function ChartContainer({ config, className, children, ...props }: React.HTMLAttributes<HTMLDivElement> & { config: ChartConfig; children: React.ComponentProps<typeof ResponsiveContainer>["children"] }) {
  const colorVariables = Object.fromEntries(Object.entries(config).filter(([, item]) => item.color).map(([key, item]) => [`--color-${key}`, item.color])) as React.CSSProperties;
  return (
    <ChartContext.Provider value={config}>
      <div data-chart className={cn("flex aspect-video justify-center text-xs [&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-grid_line]:stroke-border/70 [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border", className)} {...props} style={{ ...colorVariables, ...props.style }}>
        <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
}

const ChartTooltip = RechartsTooltip;

type ChartTooltipContentProps = Omit<Partial<TooltipContentProps<number, string>>, "formatter" | "labelFormatter"> & {
  formatter?: (value: number) => React.ReactNode;
  labelFormatter?: (label: unknown) => React.ReactNode;
};

function ChartTooltipContent({ active, payload, label, labelFormatter, formatter }: ChartTooltipContentProps) {
  const config = React.useContext(ChartContext);
  if (!active || !payload?.length) return null;
  const formattedLabel = labelFormatter ? labelFormatter(label) : label;
  return (
    <div className="grid min-w-36 gap-1.5 rounded-lg border bg-background px-2.5 py-2 text-xs shadow-xl">
      {formattedLabel != null && <div className="font-medium">{formattedLabel}</div>}
      {payload.map((item, index) => {
        const key = String(item.dataKey ?? item.name ?? index);
        const color = item.color ?? config[key]?.color ?? "currentColor";
        return (
          <div key={key} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-2 text-muted-foreground"><span className="size-2.5 rounded-sm" style={{ backgroundColor: color }} />{config[key]?.label ?? item.name ?? key}</span>
            <span className="font-mono font-medium tabular-nums">{formatter ? formatter(Number(item.value)) : String(item.value ?? "")}</span>
          </div>
        );
      })}
    </div>
  );
}

export { ChartContainer, ChartTooltip, ChartTooltipContent };
