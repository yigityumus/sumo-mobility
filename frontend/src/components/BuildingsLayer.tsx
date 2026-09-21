import { useMemo } from "react";
import L from "leaflet";
import { GeoJSON } from "react-leaflet";
import {
  getBuildingDisplayName,
  getFeatureId,
} from "../utils/osmFeatures.ts";
import { buildingTypeColor } from "../utils/buildingTypeColors.ts";

export default function BuildingsLayer({
  buildings,
  selectedIds,
  buildingClassification = null,
  onToggle,
  interactionDisabled = false,
  publicTransportEditing = false,
  publicTransportBuildingIds = new Set(),
  onTogglePublicTransportBuilding,
}) {
  const typeColorById = useMemo(() => {
    const entries = (buildingClassification?.types ?? []).map(
      (type, index): [string, string] => [type.id, buildingTypeColor(index)],
    );
    return new Map<string, string>(entries);
  }, [buildingClassification]);

  const style = useMemo(
    () => (feature) => {
      const id = getFeatureId(feature);
      const selected = selectedIds.has(id);
      const assignedTypeId = buildingClassification?.assignments?.[id];
      const assignedColor = assignedTypeId ? typeColorById.get(assignedTypeId) : null;

      if (publicTransportEditing) {
        const isOrigin = publicTransportBuildingIds.has(id);
        return {
          color: isOrigin ? "#047857" : "#64748b",
          fillColor: isOrigin ? "#34d399" : "#cbd5e1",
          fillOpacity: isOrigin ? 0.78 : 0.38,
          opacity: 1,
          weight: isOrigin ? 4 : 2,
          dashArray: isOrigin ? undefined : "5 4",
          className: interactionDisabled ? undefined : "campus-selectable-feature",
        };
      }

      if (!selected) {
        return {
          color: "#2563eb",
          fillColor: "#bfdbfe",
          fillOpacity: 0.68,
          opacity: 1,
          weight: 2.5,
          dashArray: "6 4",
          className: interactionDisabled ? undefined : "campus-selectable-feature",
        };
      }

      if (assignedColor) {
        return {
          color: assignedColor,
          fillColor: assignedColor,
          fillOpacity: 0.68,
          opacity: 1,
          weight: 3,
          className: interactionDisabled ? undefined : "campus-selectable-feature",
        };
      }

      if (buildingClassification) {
        return {
          color: "var(--foreground)",
          fillColor: "var(--muted)",
          fillOpacity: 0.36,
          opacity: 0.9,
          weight: 2,
          dashArray: "4 4",
          className: interactionDisabled ? undefined : "campus-selectable-feature",
        };
      }

      return {
        color: "#003e9c",
        fillColor: "#006cff",
        fillOpacity: 0.76,
        opacity: 1,
        weight: 3,
        className: interactionDisabled ? undefined : "campus-selectable-feature",
      };
    },
    [buildingClassification, interactionDisabled, publicTransportBuildingIds, publicTransportEditing, selectedIds, typeColorById],
  );

  const onEachFeature = (feature, layer) => {
    const id = getFeatureId(feature);
    const selected = selectedIds.has(id);
    const isPublicTransportOrigin = publicTransportBuildingIds.has(id);
    layer.bindTooltip(
      publicTransportEditing
        ? `${getBuildingDisplayName(feature)} · ${isPublicTransportOrigin ? "Transit origin — click to remove" : "Click to use as a transit origin"}`
        : `${getBuildingDisplayName(feature)} · ${selected ? "Selected — click to exclude" : "Unselected — click to include"}`,
      {
      sticky: true,
      direction: "top",
      opacity: 0.95,
      },
    );

    layer.on("mouseover", () => {
      if (interactionDisabled) return;
      const currentStyle = style(feature);
      const visiblySelected = publicTransportEditing ? isPublicTransportOrigin : selected;
      layer.setStyle({
        ...currentStyle,
        color: visiblySelected ? currentStyle.color : publicTransportEditing ? "#334155" : "#003e9c",
        fillOpacity: Math.min(Number(currentStyle.fillOpacity ?? 0.68) + 0.12, 0.88),
        weight: Math.max(Number(currentStyle.weight ?? 2.5), 3.5),
      });
      layer.bringToFront();
    });

    layer.on("mouseout", () => {
      if (!interactionDisabled) layer.setStyle(style(feature));
    });

    layer.on("click", (event) => {
      if (interactionDisabled) return;
      if (event.originalEvent) {
        L.DomEvent.stopPropagation(event.originalEvent);
      }
      if (publicTransportEditing) onTogglePublicTransportBuilding?.(getFeatureId(feature));
      else onToggle(getFeatureId(feature));
    });
  };

  if (!buildings.features.length) {
    return null;
  }

  return (
    <GeoJSON
      key={`${interactionDisabled}-${publicTransportEditing}-${buildings.features.map((feature) => feature.id).join("|")}-${[...selectedIds].sort().join("|")}-${[...publicTransportBuildingIds].sort().join("|")}`}
      data={buildings}
      style={style}
      onEachFeature={onEachFeature}
    />
  );
}
