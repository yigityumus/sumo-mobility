import osm2geojson from "osm2geojson-lite";

export function getTags(feature) {
  const properties = feature?.properties ?? {};

  if (properties.tags && typeof properties.tags === "object") {
    return properties.tags;
  }

  const metadataKeys = new Set([
    "id",
    "version",
    "timestamp",
    "changeset",
    "user",
    "uid",
    "visible",
    "bounds",
    "nodes",
    "members",
  ]);

  return Object.fromEntries(
    Object.entries(properties).filter(([key]) => !metadataKeys.has(key)),
  );
}

export function getFeatureId(feature) {
  if (feature?.id) {
    return String(feature.id);
  }

  const type = feature?.properties?.type ?? "unknown";
  const id = feature?.properties?.id ?? crypto.randomUUID();
  return `${type}/${id}`;
}

function normalizeFeature(feature) {
  const featureId = getFeatureId(feature);
  const [osmType, rawOsmId] = featureId.split("/");

  return {
    ...feature,
    id: featureId,
    properties: {
      type: osmType,
      id: Number(rawOsmId),
      tags: getTags(feature),
      source_properties: feature.properties ?? {},
    },
  };
}

export function getBuildingDisplayName(feature) {
  const tags = getTags(feature);
  return (
    tags.name ||
    tags.ref ||
    tags["addr:housename"] ||
    tags.official_name ||
    `Unnamed building ${getFeatureId(feature)}`
  );
}

export function getParkingDisplayName(feature) {
  const tags = getTags(feature);
  return (
    tags.name ||
    tags.ref ||
    tags["addr:housename"] ||
    `Parking area ${getFeatureId(feature)}`
  );
}


function hasMeaningfulName(feature) {
  const tags = getTags(feature);

  const directNameFields = [
    tags.name,
    tags.official_name,
    tags.short_name,
    tags.ref,
    tags.local_ref,
    tags["addr:housename"],
  ];

  if (directNameFields.some((value) => String(value ?? "").trim())) {
    return true;
  }

  return Object.entries(tags).some(
    ([key, value]) => key.startsWith("name:") && String(value ?? "").trim(),
  );
}

export function isUnnamedBuilding(feature) {
  return !hasMeaningfulName(feature);
}

export function isUnnamedParkingArea(feature) {
  return !hasMeaningfulName(feature);
}

export function getBuildingSearchText(feature) {
  const tags = getTags(feature);
  return [
    getBuildingDisplayName(feature),
    getFeatureId(feature),
    tags.ref,
    tags.building,
    tags.amenity,
    tags.operator,
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
}

export function getParkingSearchText(feature) {
  const tags = getTags(feature);
  return [
    getParkingDisplayName(feature),
    getFeatureId(feature),
    tags.ref,
    tags.parking,
    tags.capacity,
    tags["capacity:motorcar"],
    tags.access,
    tags.operator,
    tags.surface,
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase();
}

export function getBuildingDescription(feature) {
  const tags = getTags(feature);
  return [getFeatureId(feature), tags.building].filter(Boolean).join(" · ");
}

export function getParkingDescription(feature) {
  const tags = getTags(feature);
  const capacity = tags["capacity:motorcar"] ?? tags.capacity;

  return [
    getFeatureId(feature),
    tags.parking,
    capacity ? `capacity ${capacity}` : null,
    tags.access,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function convertOsmCampusFeatures(osmPayload) {
  const converted = osm2geojson(osmPayload, {
    completeFeature: true,
    renderTagged: true,
    excludeWay: true,
  });

  const buildingIds = new Set();
  const parkingIds = new Set();
  const buildings = [];
  const parkingAreas = [];

  for (const rawFeature of converted.features) {
    const geometryType = rawFeature.geometry?.type;
    if (geometryType !== "Polygon" && geometryType !== "MultiPolygon") {
      continue;
    }

    const feature = normalizeFeature(rawFeature);
    const tags = getTags(feature);

    // A parking garage can carry both building=* and amenity=parking. Treat it
    // as a parking facility so the same polygon is not rendered twice.
    if (tags.amenity === "parking") {
      if (!parkingIds.has(feature.id)) {
        parkingIds.add(feature.id);
        parkingAreas.push(feature);
      }
      continue;
    }

    if (tags.building && !buildingIds.has(feature.id)) {
      buildingIds.add(feature.id);
      buildings.push(feature);
    }
  }

  buildings.sort((left, right) =>
    getBuildingDisplayName(left).localeCompare(
      getBuildingDisplayName(right),
      undefined,
      { numeric: true, sensitivity: "base" },
    ),
  );

  parkingAreas.sort((left, right) =>
    getParkingDisplayName(left).localeCompare(
      getParkingDisplayName(right),
      undefined,
      { numeric: true, sensitivity: "base" },
    ),
  );

  return {
    buildings: {
      type: "FeatureCollection",
      features: buildings,
    },
    parkingAreas: {
      type: "FeatureCollection",
      features: parkingAreas,
    },
  };
}

export function extractOuterRing(boundaryFeature) {
  if (!boundaryFeature || boundaryFeature.geometry?.type !== "Polygon") {
    throw new Error("Draw a polygon or rectangle before loading area features.");
  }

  const ring = boundaryFeature.geometry.coordinates?.[0];
  if (!Array.isArray(ring) || ring.length < 4) {
    throw new Error("The drawn area boundary is invalid.");
  }

  return ring;
}

export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function downloadJson(filename, value, mimeType = "application/json") {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: mimeType });
  downloadBlob(filename, blob);
}

export function selectedFeatureCollection(
  collection,
  selectedIds,
  boundaryFeature,
  featureType,
  source = "OpenStreetMap via Overpass API",
) {
  const selectedFeatures = collection.features.filter((feature) =>
    selectedIds.has(feature.id),
  );

  return {
    type: "FeatureCollection",
    metadata: {
      source,
      exported_at: new Date().toISOString(),
      feature_type: featureType,
      selected_feature_count: selectedFeatures.length,
      area_boundary: boundaryFeature?.geometry ?? null,
    },
    features: selectedFeatures,
  };
}

export function campusBuildingConfiguration(
  buildings,
  selectedIds,
  boundaryFeature,
  source = "OpenStreetMap via Overpass API",
) {
  const selectedBuildings = buildings.features
    .filter((feature) => selectedIds.has(feature.id))
    .map((feature) => {
      const tags = getTags(feature);

      return {
        id: feature.id,
        osm_type: feature.properties?.type ?? feature.id.split("/")[0],
        osm_id: feature.properties?.id ?? Number(feature.id.split("/")[1]),
        name: getBuildingDisplayName(feature),
        ref: tags.ref ?? null,
        building: tags.building ?? null,
        tags,
        geometry: feature.geometry,
        entrance: null,
        pedestrian_edge: null,
        pedestrian_position: null,
      };
    });

  return {
    schema_version: 1,
    source,
    exported_at: new Date().toISOString(),
    area_boundary: boundaryFeature?.geometry ?? null,
    building_count: selectedBuildings.length,
    buildings: selectedBuildings,
  };
}

export function campusParkingConfiguration(
  parkingAreas,
  selectedIds,
  boundaryFeature,
  source = "OpenStreetMap via Overpass API",
  parkingSpecs = {},
) {
  const selectedParkingAreas = parkingAreas.features
    .filter((feature) => selectedIds.has(feature.id))
    .map((feature) => {
      const tags = getTags(feature);
      const spec = parkingSpecs[feature.id] ?? {};

      return {
        id: feature.id,
        osm_type: feature.properties?.type ?? feature.id.split("/")[0],
        osm_id: feature.properties?.id ?? Number(feature.id.split("/")[1]),
        name: getParkingDisplayName(feature),
        amenity: tags.amenity ?? null,
        parking: tags.parking ?? null,
        capacity: spec.capacity ?? tags["capacity:motorcar"] ?? tags.capacity ?? null,
        capacity_source: spec.capacitySource ?? null,
        access: spec.access ?? tags.access ?? null,
        access_source: spec.accessSource ?? null,
        tags,
        geometry: feature.geometry,
        capacity_override: null,
        vehicle_entrance: null,
        vehicle_edge: null,
        vehicle_position: null,
        pedestrian_exit: null,
        pedestrian_edge: null,
        pedestrian_position: null,
      };
    });

  return {
    schema_version: 1,
    source,
    exported_at: new Date().toISOString(),
    area_boundary: boundaryFeature?.geometry ?? null,
    parking_area_count: selectedParkingAreas.length,
    parking_areas: selectedParkingAreas,
  };
}
