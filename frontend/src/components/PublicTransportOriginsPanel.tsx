import { Building2, BusFront, CarFront, LoaderCircle, MapPin, Plus, Trash2 } from "lucide-react";
import type {
  CampusFeatureCollection,
  DetectorLaneCandidate,
  PublicTransportOrigin,
  VehicleGenerationPoint,
} from "../types/campus";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

type Props = {
  buildings: CampusFeatureCollection;
  origins: PublicTransportOrigin[];
  vehicleGenerationPoints: VehicleGenerationPoint[];
  activeVehicleGenerationPointId: string | null;
  vehicleLaneCandidates: DetectorLaneCandidate[];
  placingPoint: boolean;
  placingVehiclePoint: boolean;
  resolvingVehiclePoint: boolean;
  vehiclePointMessage: string;
  busy: boolean;
  onBack: () => void;
  onTogglePointPlacement: () => void;
  onChange: (origin: PublicTransportOrigin) => void;
  onDelete: (id: string) => void;
  onToggleVehiclePointPlacement: () => void;
  onSelectVehiclePoint: (id: string) => void;
  onChangeVehiclePoint: (point: VehicleGenerationPoint) => void;
  onDeleteVehiclePoint: (id: string) => void;
  onRefreshVehiclePointLanes: (id: string) => void;
  onFocusVehicleLane: (laneId: string | null) => void;
};

export default function PublicTransportOriginsPanel({
  buildings,
  origins,
  vehicleGenerationPoints,
  activeVehicleGenerationPointId,
  vehicleLaneCandidates,
  placingPoint,
  placingVehiclePoint,
  resolvingVehiclePoint,
  vehiclePointMessage,
  busy,
  onBack,
  onTogglePointPlacement,
  onChange,
  onDelete,
  onToggleVehiclePointPlacement,
  onSelectVehiclePoint,
  onChangeVehiclePoint,
  onDeleteVehiclePoint,
  onRefreshVehiclePointLanes,
  onFocusVehicleLane,
}: Props) {
  const buildingCount = origins.filter((origin) => origin.sourceType === "building").length;
  const pointCount = origins.length - buildingCount;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        <div>
          <h1 className="text-lg font-semibold">Transport origins</h1>
          <p className="text-xs text-muted-foreground">Choose where pedestrians and vehicles enter the model</p>
        </div>
      </div>

      <Alert className="border-blue-200 bg-blue-50 text-blue-950 dark:border-blue-900 dark:bg-blue-950/35 dark:text-blue-100">
        <BusFront className="size-4" />
        <AlertTitle className="text-sm">Independent from building classifications</AlertTitle>
        <AlertDescription className="text-xs leading-5">
          These origins represent metro entrances, stations, bus stops, or other arrival points. Building classifications only describe destinations and their demand weighting; they no longer need a Metro or Public Transportation type.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><MapPin className="size-4 text-primary" /> Select origins on the map</CardTitle>
          <CardDescription className="text-xs leading-5">
            Click a building to add or remove it. For a bus stop, metro entrance, or another location without a building polygon, add a custom point.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-2">
          <Button
            type="button"
            className="w-full"
            variant={placingPoint ? "secondary" : "default"}
            disabled={busy}
            onClick={onTogglePointPlacement}
          >
            {placingPoint ? <MapPin className="size-4" /> : <Plus className="size-4" />}
            {placingPoint ? "Cancel point placement" : "Add a custom transit point"}
          </Button>
          {placingPoint && (
            <p className="rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs leading-5 text-blue-900 dark:border-blue-900 dark:bg-blue-950/35 dark:text-blue-100">
              Click the exact bus stop, station entrance, or pedestrian arrival point on the map.
            </p>
          )}
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">{buildingCount} building{buildingCount === 1 ? "" : "s"}</Badge>
            <Badge variant="secondary">{pointCount} custom point{pointCount === 1 ? "" : "s"}</Badge>
            <span>{buildings.features.length} buildings available on the map</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">Selected origins</CardTitle>
          <CardDescription className="text-xs">Pedestrians are distributed across these origins and routed to reachable destination buildings.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 p-4 pt-2">
          {origins.length ? origins.map((origin) => (
            <div key={origin.id} className="space-y-2 rounded-md border p-2.5">
              <div className="flex items-center gap-2">
                {origin.sourceType === "building" ? <Building2 className="size-4 shrink-0 text-emerald-700" /> : <MapPin className="size-4 shrink-0 text-emerald-700" />}
                <Input
                  value={origin.name}
                  aria-label="Public transportation origin name"
                  disabled={busy}
                  onChange={(event) => onChange({ ...origin, name: event.target.value })}
                />
                <Button type="button" variant="ghost" size="icon" className="shrink-0 text-destructive hover:text-destructive" disabled={busy} onClick={() => onDelete(origin.id)} aria-label={`Delete ${origin.name}`}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <p className="pl-6 text-[11px] text-muted-foreground">
                {origin.sourceType === "building" ? "Building origin" : "Custom map point"} · {origin.location.latitude.toFixed(6)}, {origin.location.longitude.toFixed(6)}
              </p>
            </div>
          )) : (
            <p className="rounded-md border border-dashed p-4 text-center text-xs leading-5 text-muted-foreground">
              No public transportation origin is selected yet. Add one before running pedestrian demand.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="p-4 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><CarFront className="size-4 text-blue-700" /> Vehicle generation points</CardTitle>
          <CardDescription className="text-xs leading-5">
            Add one or more road origins. Each click snaps to a passenger lane; percentages or exact car counts are configured dynamically for each simulation.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-2">
          <Button
            type="button"
            className="w-full"
            variant={placingVehiclePoint ? "secondary" : "default"}
            disabled={busy || resolvingVehiclePoint}
            onClick={onToggleVehiclePointPlacement}
          >
            {resolvingVehiclePoint ? <LoaderCircle className="size-4 animate-spin" /> : placingVehiclePoint ? <MapPin className="size-4" /> : <Plus className="size-4" />}
            {resolvingVehiclePoint ? "Resolving passenger lanes…" : placingVehiclePoint ? "Cancel vehicle point placement" : "Add a vehicle generation point"}
          </Button>
          {placingVehiclePoint && (
            <p className="rounded-md border border-blue-200 bg-blue-50 p-2.5 text-xs leading-5 text-blue-900 dark:border-blue-900 dark:bg-blue-950/35 dark:text-blue-100">
              Click the road and direction where vehicles should enter the simulation.
            </p>
          )}
          {vehiclePointMessage && <p className="text-xs leading-5 text-muted-foreground">{vehiclePointMessage}</p>}
          <Badge variant="secondary">{vehicleGenerationPoints.length} vehicle point{vehicleGenerationPoints.length === 1 ? "" : "s"}</Badge>

          {vehicleGenerationPoints.length ? vehicleGenerationPoints.map((point) => {
            const active = point.id === activeVehicleGenerationPointId;
            const selectedLaneIsMissing = active && !vehicleLaneCandidates.some(
              (candidate) => candidate.lane_id === point.laneSelection.laneId,
            );
            return (
              <div key={point.id} className={`space-y-2 rounded-md border p-2.5 ${active ? "border-blue-500 bg-blue-50/60 dark:bg-blue-950/20" : ""}`}>
                <div className="flex items-center gap-2">
                  <button type="button" className="shrink-0" onClick={() => onSelectVehiclePoint(point.id)} aria-label={`Select ${point.name}`}>
                    <CarFront className="size-4 text-blue-700" />
                  </button>
                  <Input
                    value={point.name}
                    aria-label="Vehicle generation point name"
                    disabled={busy}
                    onFocus={() => onSelectVehiclePoint(point.id)}
                    onChange={(event) => onChangeVehiclePoint({ ...point, name: event.target.value })}
                  />
                  <Button type="button" variant="ghost" size="icon" className="shrink-0 text-destructive hover:text-destructive" disabled={busy} onClick={() => onDeleteVehiclePoint(point.id)} aria-label={`Delete ${point.name}`}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
                <button type="button" className="block w-full pl-6 text-left text-[11px] text-muted-foreground" onClick={() => onSelectVehiclePoint(point.id)}>
                  Lane <span className="font-mono">{point.laneSelection.laneId}</span> · edge <span className="font-mono">{point.laneSelection.edgeId}</span><br />
                  {point.location.latitude.toFixed(6)}, {point.location.longitude.toFixed(6)} · allocation configured on the Simulation page
                </button>
                {active && (
                  <div className="space-y-1.5 pl-6">
                    <div className="flex items-center justify-between gap-2">
                      <Label className="text-xs">Passenger lane and direction</Label>
                      <Button type="button" variant="ghost" size="sm" disabled={resolvingVehiclePoint} onClick={() => onRefreshVehiclePointLanes(point.id)}>Refresh lanes</Button>
                    </div>
                    <Select value={`lane:${point.laneSelection.laneId}`} onValueChange={(value) => {
                      const laneId = value.slice(5);
                      const candidate = vehicleLaneCandidates.find((item) => item.lane_id === laneId);
                      if (candidate) onChangeVehiclePoint({
                        ...point,
                        positionMetres: candidate.position_metres,
                        laneSelection: {
                          mode: "lane",
                          edgeId: candidate.edge_id,
                          laneId: candidate.lane_id,
                          laneIndex: candidate.lane_index,
                        },
                      });
                    }}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {selectedLaneIsMissing && <SelectItem value={`lane:${point.laneSelection.laneId}`}>Lane {point.laneSelection.laneId}</SelectItem>}
                        {vehicleLaneCandidates.filter((candidate) => candidate.allows_passenger).map((candidate) => (
                          <SelectItem
                            key={candidate.lane_id}
                            value={`lane:${candidate.lane_id}`}
                            onPointerMove={() => onFocusVehicleLane(candidate.lane_id)}
                            onPointerLeave={() => onFocusVehicleLane(null)}
                          >
                            Lane {candidate.lane_id} · edge {candidate.edge_id} · {candidate.distance_metres.toFixed(1)} m
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] leading-4 text-muted-foreground">Choose the lane whose direction points into the modeled area.</p>
                  </div>
                )}
              </div>
            );
          }) : (
            <p className="rounded-md border border-dashed p-4 text-center text-xs leading-5 text-muted-foreground">
              No vehicle generation point is saved. Simulations will continue using automatically selected fringe edges until you add one.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
