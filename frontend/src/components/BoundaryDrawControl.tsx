import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet-draw";
import { useMap } from "react-leaflet";
import { patchLeafletDrawReadableArea } from "../utils/patchLeafletDraw.ts";

const BOUNDARY_STYLE = {
  color: "#7c3aed",
  fillOpacity: 0.08,
  weight: 3,
};

export default function BoundaryDrawControl({ onBoundaryChange }) {
  const map = useMap();
  const callbackRef = useRef(onBoundaryChange);

  useEffect(() => {
    callbackRef.current = onBoundaryChange;
  }, [onBoundaryChange]);

  useEffect(() => {
    patchLeafletDrawReadableArea();

    // Make the built-in Leaflet Draw instructions clearer for this app.
    L.drawLocal.draw.toolbar.buttons.rectangle =
      "Draw a rectangular area boundary";
    L.drawLocal.draw.toolbar.buttons.polygon =
      "Draw a custom area boundary";

    L.drawLocal.draw.handlers.rectangle.tooltip.start =
      "Press and hold, drag diagonally, then release.";
    L.drawLocal.draw.handlers.polygon.tooltip.start =
      "Click the first boundary point.";
    L.drawLocal.draw.handlers.polygon.tooltip.cont =
      "Keep clicking to add more points.";
    L.drawLocal.draw.handlers.polygon.tooltip.end =
      "Click the first point to close the polygon.";

    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    const drawControl = new L.Control.Draw({
      position: "topleft",
      draw: {
        polyline: false,
        circle: false,
        circlemarker: false,
        marker: false,
        polygon: {
          allowIntersection: false,
          showArea: true,
          showLength: true,
          metric: true,
          repeatMode: false,
          guidelineDistance: 12,
          shapeOptions: BOUNDARY_STYLE,
        },
        rectangle: {
          repeatMode: false,
          shapeOptions: BOUNDARY_STYLE,
        },
      },
      edit: {
        featureGroup: drawnItems,
        edit: {},
        remove: true,
      },
    });

    map.addControl(drawControl);

    const replaceBoundary = (layer) => {
      drawnItems.clearLayers();
      drawnItems.addLayer(layer);
      callbackRef.current(layer.toGeoJSON());
    };

    const handleCreated = (event) => {
      replaceBoundary(event.layer);
    };

    const handleEdited = () => {
      let feature = null;
      drawnItems.eachLayer((layer) => {
        feature = (layer as L.Layer & { toGeoJSON: () => GeoJSON.Feature }).toGeoJSON();
      });
      callbackRef.current(feature);
    };

    const handleDeleted = () => {
      callbackRef.current(null);
    };

    map.on(L.Draw.Event.CREATED, handleCreated);
    map.on(L.Draw.Event.EDITED, handleEdited);
    map.on(L.Draw.Event.DELETED, handleDeleted);

    return () => {
      map.off(L.Draw.Event.CREATED, handleCreated);
      map.off(L.Draw.Event.EDITED, handleEdited);
      map.off(L.Draw.Event.DELETED, handleDeleted);
      map.removeControl(drawControl);
      map.removeLayer(drawnItems);
    };
  }, [map]);

  return null;
}
