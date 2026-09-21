import L from "leaflet";
import { GeoJSON } from "react-leaflet";
import { getFeatureId, getParkingDisplayName } from "../utils/osmFeatures.ts";
import { buildingTypeColor } from "../utils/buildingTypeColors.ts";

function parkingStyle(feature, selectedIds, highlightedIds, expandedIds, parkingClassification, typeColorById, interactionDisabled = false) {
  const id = getFeatureId(feature);
  const selected = selectedIds.has(id);
  const highlighted = highlightedIds?.has(id);
  const expanded = expandedIds?.has(id);

  if (expanded) {
    return {
      color: "#b45309",
      fillColor: "#facc15",
      weight: 4,
      fillOpacity: 0.72,
      className: interactionDisabled ? undefined : "campus-selectable-feature",
    };
  }

  if (highlighted) {
    return {
      color: "#15803d",
      fillColor: "#22c55e",
      weight: 3,
      fillOpacity: 0.62,
      className: interactionDisabled ? undefined : "campus-selectable-feature",
    };
  }

  if (!selected) {
    return {
      color: "#ef4444",
      fillColor: "#fecaca",
      weight: 2.5,
      fillOpacity: 0.68,
      opacity: 1,
      dashArray: "6 4",
      className: interactionDisabled ? undefined : "campus-selectable-feature",
    };
  }

  const assignedTypeId = parkingClassification?.assignments?.[id];
  const assignedColor = assignedTypeId ? typeColorById.get(assignedTypeId) : null;
  if (assignedColor) {
    return {
      color: assignedColor,
      fillColor: assignedColor,
      weight: 3,
      fillOpacity: 0.68,
      className: interactionDisabled ? undefined : "campus-selectable-feature",
    };
  }

  if (parkingClassification) {
    return {
      color: "var(--foreground)",
      fillColor: "var(--muted)",
      weight: 2,
      fillOpacity: 0.32,
      dashArray: "4 4",
      className: interactionDisabled ? undefined : "campus-selectable-feature",
    };
  }

  return {
    color: "#991b1b",
    fillColor: "#f20d2f",
    weight: 3,
    fillOpacity: 0.76,
    className: interactionDisabled ? undefined : "campus-selectable-feature",
  };
}

export default function ParkingAreasLayer({
  parkingAreas,
  selectedIds,
  highlightedIds = new Set(),
  expandedIds = new Set(),
  parkingClassification = null,
  onToggle,
  interactionDisabled = false,
}) {
  if (!parkingAreas.features.length) {
    return null;
  }

  const typeColorById = new Map(
    (parkingClassification?.types ?? []).map((type, index) => [type.id, buildingTypeColor(index)]),
  );
  const classificationKey = parkingClassification
    ? `${parkingClassification.id}-${JSON.stringify(parkingClassification.assignments ?? {})}-${(parkingClassification.types ?? []).map((type) => type.id).join("|")}`
    : "none";

  return (
    <GeoJSON
      key={`${interactionDisabled}-${parkingAreas.features.length}-${classificationKey}-${[...selectedIds].sort().join("|")}-${[
        ...highlightedIds,
      ]
        .sort()
        .join("|")}-${[...expandedIds].sort().join("|")}`}
      data={parkingAreas}
      style={(feature) => parkingStyle(feature, selectedIds, highlightedIds, expandedIds, parkingClassification, typeColorById, interactionDisabled)}
      onEachFeature={(feature, layer) => {
        const pathLayer = layer as L.Path;
        const id = getFeatureId(feature);
        const selected = selectedIds.has(id);
        pathLayer.bindTooltip(
          `${getParkingDisplayName(feature)} · ${selected ? "Selected — click to exclude" : "Unselected — click to include"}`,
          { sticky: true, direction: "top", opacity: 0.95 },
        );
        pathLayer.on({
          mouseover: () => {
            if (interactionDisabled) return;
            const currentStyle = parkingStyle(feature, selectedIds, highlightedIds, expandedIds, parkingClassification, typeColorById, interactionDisabled);
            pathLayer.setStyle({
              ...currentStyle,
              color: selected ? currentStyle.color : "#991b1b",
              fillOpacity: Math.min(Number(currentStyle.fillOpacity ?? 0.68) + 0.12, 0.88),
              weight: Math.max(Number(currentStyle.weight ?? 2.5), 3.5),
            });
            pathLayer.bringToFront();
          },
          mouseout: () => {
            if (!interactionDisabled) {
              pathLayer.setStyle(parkingStyle(feature, selectedIds, highlightedIds, expandedIds, parkingClassification, typeColorById, interactionDisabled));
            }
          },
          click: () => {
            if (!interactionDisabled) onToggle(id);
          },
        });
      }}
    />
  );
}
