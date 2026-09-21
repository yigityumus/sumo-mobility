import { Fragment, useEffect } from "react";
import L from "leaflet";
import type { LatLngExpression, LeafletMouseEvent } from "leaflet";
import type { FeatureCollection, Geometry } from "geojson";
import { CircleMarker, GeoJSON, MapContainer, Pane, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { DetectorLaneCandidate, PublicTransportOrigin, TrafficDetector, VehicleGenerationPoint } from "../types/campus";
import BoundaryDrawControl from "./BoundaryDrawControl.tsx";
import BuildingsLayer from "./BuildingsLayer.tsx";
import ParkingAreasLayer from "./ParkingAreasLayer.tsx";

function FitToFeatures({ buildings, parkingAreas, boundaryFeature }) {
  const map = useMap();

  useEffect(() => {
    const features = [...buildings.features, ...parkingAreas.features];
    if (boundaryFeature) {
      features.push(boundaryFeature);
    }

    if (!features.length) {
      return;
    }

    const collection: FeatureCollection<Geometry> = {
      type: "FeatureCollection",
      features,
    };
    const temporaryLayer = L.geoJSON(collection);
    const bounds = temporaryLayer.getBounds();

    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.08), { maxZoom: 18 });
    }
  }, [buildings, parkingAreas, boundaryFeature, map]);

  return null;
}

function InvalidateSizeOnResize({ layoutKey }: { layoutKey?: string | number }) {
  const map = useMap();

  useEffect(() => {
    const invalidate = () => map.invalidateSize({ animate: false });
    const frame = window.requestAnimationFrame(invalidate);
    return () => window.cancelAnimationFrame(frame);
  }, [layoutKey, map]);

  useEffect(() => {
    const container = map.getContainer();
    const observer = new ResizeObserver(() => {
      window.requestAnimationFrame(() => map.invalidateSize({ animate: false }));
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);

  return null;
}

function BoundaryPreviewLayer({ boundaryFeature }) {
  if (!boundaryFeature) {
    return null;
  }

  return (
    <Pane name="area-boundary-preview" style={{ zIndex: 405 }}>
      <GeoJSON
        key={JSON.stringify(boundaryFeature.geometry)}
        data={boundaryFeature}
        style={{
          color: "#7c3aed",
          fillOpacity: 0.05,
          weight: 3,
          dashArray: "7 5",
        }}
      />
    </Pane>
  );
}

function DetectorLayer({ detectors, activeDetectorId, placing, onMapClick, onDetectorClick }: {
  detectors: TrafficDetector[];
  activeDetectorId: string | null;
  placing: boolean;
  onMapClick?: (location: { latitude: number; longitude: number }) => void;
  onDetectorClick?: (id: string) => void;
}) {
  useMapEvents({
    click(event) {
      if (placing) onMapClick?.({ latitude: event.latlng.lat, longitude: event.latlng.lng });
    },
  });
  const clickHandler = (id: string) => (event: LeafletMouseEvent) => {
    if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
    onDetectorClick?.(id);
  };
  return <Pane name="traffic-detectors" style={{ zIndex: 650 }}>
    {detectors.map((detector) => detector.type === "e1" ? <CircleMarker
      key={detector.id}
      center={[detector.location.latitude, detector.location.longitude]}
      radius={detector.id === activeDetectorId ? 9 : 7}
      pathOptions={{ color: detector.id === activeDetectorId ? "#7c3aed" : "#0f766e", fillColor: detector.id === activeDetectorId ? "#a78bfa" : "#14b8a6", fillOpacity: 0.9, weight: 3 }}
      eventHandlers={{ click: clickHandler(detector.id) }}
    ><Tooltip>{detector.name} · E1</Tooltip></CircleMarker> : <Fragment key={detector.id}>
      <Polyline
        positions={[
          [detector.entry.location.latitude, detector.entry.location.longitude],
          [detector.exit.location.latitude, detector.exit.location.longitude],
        ]}
        pathOptions={{ color: detector.id === activeDetectorId ? "#7c3aed" : "#ea580c", dashArray: "6 5", weight: 3 }}
        eventHandlers={{ click: clickHandler(detector.id) }}
      />
      <CircleMarker
        center={[detector.entry.location.latitude, detector.entry.location.longitude]}
        radius={detector.id === activeDetectorId ? 9 : 7}
        pathOptions={{ color: "#166534", fillColor: "#22c55e", fillOpacity: 0.9, weight: 3 }}
        eventHandlers={{ click: clickHandler(detector.id) }}
      ><Tooltip>{detector.name} · E3 entry</Tooltip></CircleMarker>
      <CircleMarker
        center={[detector.exit.location.latitude, detector.exit.location.longitude]}
        radius={detector.id === activeDetectorId ? 9 : 7}
        pathOptions={{ color: "#9a3412", fillColor: "#f97316", fillOpacity: 0.9, weight: 3 }}
        eventHandlers={{ click: clickHandler(detector.id) }}
      ><Tooltip>{detector.name} · E3 exit</Tooltip></CircleMarker>
    </Fragment>)}
  </Pane>;
}

function PublicTransportOriginLayer({ origins, editing, placingPoint, onMapClick, onToggleBuilding }: {
  origins: PublicTransportOrigin[];
  editing: boolean;
  placingPoint: boolean;
  onMapClick?: (location: { latitude: number; longitude: number }) => void;
  onToggleBuilding?: (buildingId: string) => void;
}) {
  useMapEvents({
    click(event) {
      if (editing && placingPoint) onMapClick?.({ latitude: event.latlng.lat, longitude: event.latlng.lng });
    },
  });

  if (!origins.length) return null;
  return (
    <Pane name="public-transport-origins" style={{ zIndex: 625 }}>
      {origins.map((origin) => (
        <CircleMarker
          key={origin.id}
          center={[origin.location.latitude, origin.location.longitude]}
          radius={origin.sourceType === "building" ? 6 : 8}
          pathOptions={{
            color: "#065f46",
            fillColor: origin.sourceType === "building" ? "#34d399" : "#fbbf24",
            fillOpacity: 0.95,
            weight: 3,
          }}
          eventHandlers={editing && origin.sourceType === "building" && origin.buildingId ? {
            click(event) {
              if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
              onToggleBuilding?.(origin.buildingId as string);
            },
          } : undefined}
        >
          <Tooltip>{origin.name} · {origin.sourceType === "building" ? "building transit origin" : "custom transit point"}</Tooltip>
        </CircleMarker>
      ))}
    </Pane>
  );
}

function VehicleGenerationPointLayer({ points, editing, placingPoint, onMapClick, onSelect }: {
  points: VehicleGenerationPoint[];
  editing: boolean;
  placingPoint: boolean;
  onMapClick?: (location: { latitude: number; longitude: number }) => void;
  onSelect?: (id: string) => void;
}) {
  useMapEvents({
    click(event) {
      if (editing && placingPoint) onMapClick?.({ latitude: event.latlng.lat, longitude: event.latlng.lng });
    },
  });

  if (!points.length) return null;
  return (
    <Pane name="vehicle-generation-points" style={{ zIndex: 630 }}>
      {points.map((point) => (
        <CircleMarker
          key={point.id}
          center={[point.location.latitude, point.location.longitude]}
          radius={8}
          pathOptions={{ color: "#1e3a8a", fillColor: "#3b82f6", fillOpacity: 0.95, weight: 3 }}
          eventHandlers={{
            click(event) {
              if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
              onSelect?.(point.id);
            },
          }}
        >
          <Tooltip>{point.name} · vehicle origin · lane {point.laneSelection.laneId}</Tooltip>
        </CircleMarker>
      ))}
    </Pane>
  );
}

function VehicleGenerationLanePreview({ candidates, point, focusedLaneId }: {
  candidates: DetectorLaneCandidate[];
  point: VehicleGenerationPoint | null;
  focusedLaneId: string | null;
}) {
  if (!candidates.length) return null;
  return (
    <Pane name="vehicle-generation-lane-preview" style={{ zIndex: 642 }}>
      {candidates.filter((candidate) => candidate.allows_passenger && candidate.shape.length >= 2).map((candidate) => {
        const selected = candidate.lane_id === point?.laneSelection.laneId;
        const focused = candidate.lane_id === focusedLaneId;
        return (
          <Polyline
            key={candidate.lane_id}
            positions={candidate.shape.map((location) => [location.latitude, location.longitude])}
            pathOptions={{
              color: focused ? "#f59e0b" : "#2563eb",
              weight: focused ? 12 : selected ? 8 : 3,
              opacity: focused ? 1 : selected ? 0.95 : 0.28,
            }}
          >
            <Tooltip sticky={!focused} permanent={focused} direction="top" opacity={1}>
              {candidate.lane_id} · edge {candidate.edge_id} · vehicle lane
            </Tooltip>
          </Polyline>
        );
      })}
    </Pane>
  );
}

function DetectorLanePreview({ candidates, detectors, activeDetectorId, focusedLaneId }: {
  candidates: Record<"e1" | "entry" | "exit", DetectorLaneCandidate[]>;
  detectors: TrafficDetector[];
  activeDetectorId: string | null;
  focusedLaneId: string | null;
}) {
  const active = detectors.find((detector) => detector.id === activeDetectorId);
  const selectedLaneIds = new Set<string>();
  const addSelection = (selection) => {
    if (selection.mode === "lanes") selection.laneIds?.forEach((laneId) => selectedLaneIds.add(laneId));
    else if (selection.laneId) selectedLaneIds.add(selection.laneId);
  };
  if (active?.type === "e1") addSelection(active.laneSelection);
  if (active?.type === "e3") {
    addSelection(active.entry.laneSelection);
    addSelection(active.exit.laneSelection);
  }
  const uniqueCandidates = [...new Map(
    Object.values(candidates).flat().map((candidate) => [candidate.lane_id, candidate]),
  ).values()];
  if (!uniqueCandidates.length) return null;

  return <Pane name="detector-lane-preview" style={{ zIndex: 640 }}>
    {uniqueCandidates.map((candidate) => {
      if (candidate.shape.length < 2) return null;
      const selected = selectedLaneIds.has(candidate.lane_id);
      const focused = candidate.lane_id === focusedLaneId;
      const laneColor = candidate.allows_passenger && candidate.allows_pedestrian
        ? "#7c3aed"
        : candidate.allows_pedestrian ? "#c026d3" : "#2563eb";
      const color = focused ? "#f59e0b" : laneColor;
      return <Polyline
        key={candidate.lane_id}
        positions={candidate.shape.map((point) => [point.latitude, point.longitude])}
        pathOptions={{
          color,
          weight: focused ? 12 : selected ? 8 : 3,
          opacity: focused ? 1 : selected ? 0.95 : 0.3,
        }}
      >
        <Tooltip sticky={!focused} permanent={focused} direction="top" opacity={1}>
          {candidate.lane_id} · edge {candidate.edge_id} · {candidate.allows_passenger ? "vehicle" : ""}{candidate.allows_passenger && candidate.allows_pedestrian ? " + " : ""}{candidate.allows_pedestrian ? "pedestrian" : ""}
        </Tooltip>
      </Polyline>;
    })}
  </Pane>;
}

export default function AreaMap({
  buildings,
  parkingAreas,
  boundaryFeature,
  selectedBuildingIds,
  selectedParkingIds,
  highlightedParkingIds = new Set(),
  expandedParkingIds = new Set(),
  buildingClassification = null,
  parkingClassification = null,
  onToggleBuilding,
  onToggleParking,
  onBoundaryChange,
  layoutKey,
  detectors = [],
  activeDetectorId = null,
  detectorPlacementActive = false,
  detectorLaneCandidates = { e1: [], entry: [], exit: [] },
  focusedDetectorLaneId = null,
  onDetectorMapClick,
  onDetectorClick,
  publicTransportOrigins = [],
  publicTransportEditing = false,
  publicTransportPointPlacementActive = false,
  onPublicTransportMapClick,
  onTogglePublicTransportBuilding,
  vehicleGenerationPoints = [],
  activeVehicleGenerationPointId = null,
  vehicleGenerationEditing = false,
  vehicleGenerationPointPlacementActive = false,
  vehicleGenerationLaneCandidates = [],
  focusedVehicleGenerationLaneId = null,
  onVehicleGenerationMapClick,
  onSelectVehicleGenerationPoint,
}) {
  const center: LatLngExpression = [
    Number(import.meta.env.VITE_DEFAULT_LAT ?? 50.611),
    Number(import.meta.env.VITE_DEFAULT_LNG ?? 3.142),
  ];
  const zoom = Number(import.meta.env.VITE_DEFAULT_ZOOM ?? 15);

  return (
    <MapContainer
      center={center}
      zoom={zoom}
      minZoom={3}
      maxZoom={20}
      className="area-map"
      doubleClickZoom={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />
      <InvalidateSizeOnResize layoutKey={layoutKey} />
      <BoundaryDrawControl onBoundaryChange={onBoundaryChange} />
      <BoundaryPreviewLayer boundaryFeature={boundaryFeature} />

      <Pane name="parking-areas" style={{ zIndex: 410 }}>
        <ParkingAreasLayer
          parkingAreas={parkingAreas}
          selectedIds={selectedParkingIds}
          highlightedIds={highlightedParkingIds}
          expandedIds={expandedParkingIds}
          parkingClassification={parkingClassification}
          onToggle={onToggleParking}
          interactionDisabled={detectorPlacementActive || publicTransportEditing || vehicleGenerationEditing}
        />
      </Pane>

      <Pane name="area-buildings" style={{ zIndex: 420 }}>
        <BuildingsLayer
          buildings={buildings}
          selectedIds={selectedBuildingIds}
          buildingClassification={buildingClassification}
          onToggle={onToggleBuilding}
          interactionDisabled={detectorPlacementActive || publicTransportPointPlacementActive || vehicleGenerationEditing}
          publicTransportEditing={publicTransportEditing && !vehicleGenerationPointPlacementActive}
          publicTransportBuildingIds={new Set(publicTransportOrigins.filter((origin) => origin.sourceType === "building" && origin.buildingId).map((origin) => origin.buildingId as string))}
          onTogglePublicTransportBuilding={onTogglePublicTransportBuilding}
        />
      </Pane>

      <PublicTransportOriginLayer
        origins={publicTransportOrigins}
        editing={publicTransportEditing}
        placingPoint={publicTransportPointPlacementActive}
        onMapClick={onPublicTransportMapClick}
        onToggleBuilding={onTogglePublicTransportBuilding}
      />

      <VehicleGenerationPointLayer
        points={vehicleGenerationPoints}
        editing={vehicleGenerationEditing}
        placingPoint={vehicleGenerationPointPlacementActive}
        onMapClick={onVehicleGenerationMapClick}
        onSelect={onSelectVehicleGenerationPoint}
      />
      <VehicleGenerationLanePreview
        candidates={vehicleGenerationLaneCandidates}
        point={vehicleGenerationPoints.find((point) => point.id === activeVehicleGenerationPointId) ?? null}
        focusedLaneId={focusedVehicleGenerationLaneId}
      />

      <DetectorLayer
        detectors={detectors}
        activeDetectorId={activeDetectorId}
        placing={detectorPlacementActive}
        onMapClick={onDetectorMapClick}
        onDetectorClick={onDetectorClick}
      />
      <DetectorLanePreview
        candidates={detectorLaneCandidates}
        detectors={detectors}
        activeDetectorId={activeDetectorId}
        focusedLaneId={focusedDetectorLaneId}
      />

      <FitToFeatures
        buildings={buildings}
        parkingAreas={parkingAreas}
        boundaryFeature={boundaryFeature}
      />
    </MapContainer>
  );
}
