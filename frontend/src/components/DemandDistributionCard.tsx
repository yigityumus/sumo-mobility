import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Slider } from "./ui/slider";
import type { BuildingClassification } from "../types/campus";

type DemandDistributionCardProps = {
  classification: BuildingClassification | null;
  busy: boolean;
  onChange: (classificationId: string, typeId: string, mode: "pedestrian" | "vehicle", value: number) => void;
};

export default function DemandDistributionCard({
  classification,
  busy,
  onChange,
}: DemandDistributionCardProps) {
  if (!classification) {
    return null;
  }

  return (
    <Card className="flex h-[420px] w-full max-w-[380px] flex-col bg-card/95 shadow-lg backdrop-blur-sm">
      <CardHeader className="shrink-0 p-4 pb-2">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-[0.1em] text-muted-foreground">Demand Distribution</p>
          <CardTitle className="mt-1 truncate text-lg">{classification.name}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-4 pt-2">
        <div className="space-y-2">
          <p className="rounded-md bg-muted/50 p-2 text-[11px] leading-4 text-muted-foreground">
            These values weight destination building types for people arriving on foot or by car. Names are unrestricted. Unassigned buildings use neutral 50/50 weights and remain eligible through equal random treatment.
          </p>
          {(classification.types ?? []).length === 0 && (
            <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
              Add types in the classification card to define demand distribution.
            </p>
          )}

          {(classification.types ?? []).map((type) => {
            const distribution = classification.demandDistribution?.[type.id] ?? { pedestrian: 50, vehicle: 50 };

            return (
              <div key={type.id} className="rounded-lg border px-2.5 py-2">
                <div className="mb-2 flex min-w-0 items-center gap-3">
                  <strong className="min-w-0 flex-1 truncate text-sm font-medium">{type.name}</strong>
                  <span className="shrink-0 text-xs text-muted-foreground">Pedestrian <b className="text-foreground">{distribution.pedestrian}%</b></span>
                  <span className="shrink-0 text-xs text-muted-foreground">Vehicle <b className="text-foreground">{distribution.vehicle}%</b></span>
                </div>
                <div>
                  <Slider
                    min={0}
                    max={100}
                    step={1}
                    value={[distribution.pedestrian]}
                    disabled={busy}
                    aria-label={`${type.name} pedestrian percentage`}
                    onValueChange={([nextValue]) => {
                      onChange(classification.id, type.id, "pedestrian", nextValue);
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
