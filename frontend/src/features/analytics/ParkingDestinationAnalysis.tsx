import { useEffect, useMemo, useState } from "react";
import { Building2, Car, TriangleAlert } from "lucide-react";
import type {
  AnalyticsData,
  ParkingDestinationAnalysis as ParkingDestinationAnalysisData,
  ParkingResultOption,
} from "../../types/campus";
import { Alert, AlertDescription, AlertTitle } from "../../components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "../../components/ui/toggle-group";
import AnalyticsLineChart, { type AnalyticsChartSeries } from "./AnalyticsLineChart";

type CapacityMetric = "occupied" | "unoccupied";
type ViewMode = "parking" | "building";

type Props = {
  data?: ParkingDestinationAnalysisData;
  parkingOptions: ParkingResultOption[];
  comparedResults: AnalyticsData[];
  calendarStartAt?: string;
  calendarTimezone?: string;
};

const COMPARISON_COLORS = ["#2563eb", "#f97316", "#16a34a", "#9333ea", "#dc2626"];

function runLabel(item: AnalyticsData) {
  if (item.run.calibration) {
    return `Iteration ${item.run.calibration.iteration} of ${item.run.calibration.total_iterations}`;
  }
  return `${item.run.model_name} · ${item.run.id.slice(0, 8)}`;
}

export default function ParkingDestinationAnalysis({
  data,
  parkingOptions,
  comparedResults,
  calendarStartAt,
  calendarTimezone,
}: Props) {
  const [mode, setMode] = useState<ViewMode>("parking");
  const [parkingId, setParkingId] = useState("");
  const [buildingId, setBuildingId] = useState("");
  const [capacityMetric, setCapacityMetric] = useState<CapacityMetric>("occupied");

  useEffect(() => {
    if (!data) return;
    setParkingId((current) => data.parkings.some((parking) => parking.id === current)
      ? current
      : data.parkings.find((parking) => parking.parked_people === 0)?.id ?? data.parkings[0]?.id ?? "");
    setBuildingId((current) => data.buildings.some((building) => building.id === current)
      ? current
      : data.buildings[0]?.id ?? "");
  }, [data]);

  const selectedParking = data?.parkings.find((parking) => parking.id === parkingId);
  const selectedParkingOption = parkingOptions.find((parking) => parking.id === parkingId);
  const selectedBuilding = data?.buildings.find((building) => building.id === buildingId);

  const distribution = useMemo(() => {
    if (!data) return [];
    if (mode === "parking") {
      return data.parking_building_flows
        .filter((flow) => flow.parking_id === parkingId)
        .map((flow) => ({ id: flow.building_id, name: flow.building_name, count: flow.parked_people }))
        .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
    }
    const outcomes = data.parking_building_flows
      .filter((flow) => flow.building_id === buildingId)
      .map((flow) => ({ id: flow.parking_id, name: flow.parking_name, count: flow.parked_people }));
    const didNotPark = Math.max(
      (selectedBuilding?.planned_vehicle_people ?? 0) - (selectedBuilding?.parked_people ?? 0),
      0,
    );
    if (didNotPark) outcomes.push({ id: "__no_parking__", name: "Did not park", count: didNotPark });
    return outcomes.sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
  }, [buildingId, data, mode, parkingId, selectedBuilding]);

  const occupancySeries = useMemo<AnalyticsChartSeries[]>(
    () => comparedResults.flatMap((item, index) => {
      const occupancy = item.occupancy[parkingId];
      if (!occupancy?.length) return [];
      return [{
        id: `parking_occupancy_${item.run.id}`,
        label: runLabel(item),
        color: COMPARISON_COLORS[index % COMPARISON_COLORS.length],
        points: occupancy.map((point) => ({
          x: point.time_seconds,
          y: capacityMetric === "occupied" ? point.occupied_percent : point.unoccupied_percent,
        })),
      }];
    }),
    [capacityMetric, comparedResults, parkingId],
  );

  if (!data?.available) {
    return (
      <Card className="shadow-sm">
        <CardHeader className="p-4">
          <CardTitle className="flex items-center gap-2"><Building2 className="size-5 text-primary" /> Parking and destination buildings</CardTitle>
          <CardDescription>This older run has no vehicle-to-building plan to join with its parking outcomes. New simulations record this automatically.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const maximumDistribution = Math.max(...distribution.map((item) => item.count), 1);
  const distributionTotal = distribution.reduce((total, item) => total + item.count, 0);
  const distributionPanel = (
    <div className="min-w-0 rounded-lg border">
      <div className="border-b px-3 py-2.5">
        <h3 className="text-sm font-semibold">{mode === "parking" ? "Actual destination buildings" : "Actual parking outcomes"}</h3>
        <p className="text-xs text-muted-foreground">Aggregated statistics from recorded final parking starts.</p>
      </div>
      <div className="max-h-[28rem] space-y-2 overflow-auto p-3">
        {distribution.length ? distribution.map((item) => (
          <div key={item.id} className="space-y-1">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate" title={item.name}>{item.name}</span>
              <span className="shrink-0 tabular-nums">
                <strong>{item.count.toLocaleString()}</strong>
                <span className="ml-1 text-muted-foreground">({distributionTotal ? Number((item.count / distributionTotal * 100).toFixed(1)) : 0}%)</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${item.count / maximumDistribution * 100}%` }} />
            </div>
          </div>
        )) : (
          <p className="p-4 text-center text-xs text-muted-foreground">No completed parking outcome exists for this selection.</p>
        )}
      </div>
    </div>
  );

  return (
    <Card className="min-w-0 shadow-sm">
      <CardHeader className="p-4 pb-3">
        <CardTitle className="flex items-center gap-2"><Building2 className="size-5 text-primary" /> Parking ↔ destination buildings</CardTitle>
        <CardDescription className="mt-1">Aggregated relationships between intended buildings, initial parking choices, and parking areas actually used.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-4 pt-0">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Drivers planned</span><strong>{data.summary.planned_vehicle_people.toLocaleString()}</strong></div>
          <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Actually parked</span><strong>{data.summary.parked_people.toLocaleString()}</strong></div>
          <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Unserved</span><strong>{data.summary.unserved_people.toLocaleString()}</strong></div>
          <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Selected destinations</span><strong>{data.summary.destination_buildings.toLocaleString()}</strong></div>
          <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Received drivers</span><strong>{data.summary.buildings_receiving_drivers.toLocaleString()}</strong></div>
          <div className="rounded-lg bg-muted/60 p-2.5"><span className="block text-xs text-muted-foreground">Unused parking areas</span><strong>{data.summary.unused_parking_areas.toLocaleString()}</strong></div>
        </div>

        <Tabs value={mode} onValueChange={(value) => setMode(value as ViewMode)}>
          <TabsList className="grid h-auto w-full grid-cols-2 sm:w-[430px]">
            <TabsTrigger value="parking"><Car className="mr-2 size-4" /> Parking → buildings</TabsTrigger>
            <TabsTrigger value="building"><Building2 className="mr-2 size-4" /> Building → parkings</TabsTrigger>
          </TabsList>

          <TabsContent value="parking" className="mt-4 space-y-4">
            <label className="block max-w-xl space-y-1.5 text-sm font-medium">
              Parking area
              <Select value={parkingId} onValueChange={setParkingId}>
                <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                <SelectContent>{data.parkings.map((parking) => (
                  <SelectItem key={parking.id} value={parking.id}>{parking.name} · {parking.parked_people.toLocaleString()} parked</SelectItem>
                ))}</SelectContent>
              </Select>
            </label>
            {selectedParking && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Had as candidate</span><strong>{selectedParking.candidate_people.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Initially chose it</span><strong>{selectedParking.initial_choice_people.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Actually parked here</span><strong>{selectedParking.parked_people.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Rerouted away</span><strong>{selectedParking.rerouted_out_people.toLocaleString()}</strong></div>
                <div className="col-span-2 rounded-lg border p-2.5 sm:col-span-1"><span className="block text-xs text-muted-foreground">Capacity</span><strong>{selectedParkingOption?.capacity.toLocaleString() ?? "—"}</strong></div>
              </div>
            )}
            {selectedParking?.unused_reason && (
              <Alert className="border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/35">
                <TriangleAlert className="size-4" />
                <AlertTitle>Why this parking area was unused</AlertTitle>
                <AlertDescription>{selectedParking.unused_reason}</AlertDescription>
              </Alert>
            )}
            <div className="grid items-start gap-4 lg:grid-cols-2">
              {distributionPanel}
              <div className="min-w-0 rounded-lg border p-3">
                <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold">Parking capacity over time</h3>
                    <p className="text-xs text-muted-foreground">Parked vehicles only; moving and queued cars are excluded.</p>
                  </div>
                  <ToggleGroup type="single" value={capacityMetric} onValueChange={(value) => value && setCapacityMetric(value as CapacityMetric)} className="rounded-lg border bg-muted/40 p-1">
                    <ToggleGroupItem value="occupied">Occupied</ToggleGroupItem>
                    <ToggleGroupItem value="unoccupied">Empty slots</ToggleGroupItem>
                  </ToggleGroup>
                </div>
                {occupancySeries.length ? (
                  <AnalyticsLineChart
                    series={occupancySeries}
                    xLabel={calendarStartAt ? "Simulated date and time" : "Simulation time"}
                    yLabel={capacityMetric === "occupied" ? "Occupied capacity (%)" : "Empty capacity (%)"}
                    fixedMaximumY={100}
                    formatY={(value) => `${Math.round(value)}%`}
                    calendarStartAt={calendarStartAt}
                    calendarTimezone={calendarTimezone}
                  />
                ) : (
                  <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">No occupancy output exists for this parking area.</div>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="building" className="mt-4 space-y-4">
            <label className="block max-w-xl space-y-1.5 text-sm font-medium">
              Destination building
              <Select value={buildingId} onValueChange={setBuildingId}>
                <SelectTrigger className="mt-1.5 h-10 font-normal"><SelectValue /></SelectTrigger>
                <SelectContent>{data.buildings.map((building) => (
                  <SelectItem key={building.id} value={building.id}>{building.name} · {building.planned_vehicle_people.toLocaleString()} drivers</SelectItem>
                ))}</SelectContent>
              </Select>
            </label>
            {selectedBuilding && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Drivers destined here</span><strong>{selectedBuilding.planned_vehicle_people.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Actually parked</span><strong>{selectedBuilding.parked_people.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Parking areas used</span><strong>{selectedBuilding.parking_area_count.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Unserved</span><strong>{selectedBuilding.unserved_people.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Eligible parking areas</span><strong>{selectedBuilding.eligible_parking_area_count.toLocaleString()}</strong></div>
                <div className="rounded-lg border p-2.5"><span className="block text-xs text-muted-foreground">Vehicle demand weight</span><strong>{Number(selectedBuilding.vehicle_weight.toFixed(2))}</strong></div>
              </div>
            )}
            {selectedBuilding?.zero_driver_reason && (
              <Alert className="border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/35">
                <TriangleAlert className="size-4" />
                <AlertTitle>Why this building received no drivers</AlertTitle>
                <AlertDescription>{selectedBuilding.zero_driver_reason}</AlertDescription>
              </Alert>
            )}
            {distributionPanel}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
