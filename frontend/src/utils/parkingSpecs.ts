import { getFeatureId, getParkingDisplayName, getTags } from "./osmFeatures.ts";

export const ACCESS_UNKNOWN = "__unknown__";
export const CAPACITY_UNKNOWN = "unknown";
export const CALCULATED_CAPACITY_SOURCE = "calculated_related_lane_length_2_3m";
export const INTERNAL_ROADS_NOT_CHECKED = "not_checked";
export const INTERNAL_ROADS_NOT_FOUND = "not_found";


export const COMMON_ACCESS_OPTIONS = [
  "yes",
  "public",
  "private",
  "customers",
  "permissive",
  "destination",
  "employees",
  "students",
  "no",
];

export const CAPACITY_BUCKETS = [
  { id: "0-10", label: "0–10", min: 0, max: 10 },
  { id: "10-30", label: "10–30", min: 10, max: 30 },
  { id: "30-50", label: "30–50", min: 30, max: 50 },
  { id: "50-100", label: "50–100", min: 50, max: 100 },
  { id: "100-200", label: "100–200", min: 100, max: 200 },
  { id: "200+", label: "200+", min: 200, max: Infinity },
  { id: CAPACITY_UNKNOWN, label: "Unknown / unspecified", min: null, max: null },
];

function normalizeAccess(value) {
  const trimmed = String(value ?? "").trim();
  return trimmed || null;
}

function parsePositiveInteger(value) {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) {
    return null;
  }

  if (!/^[1-9]\d*$/.test(trimmed)) {
    return null;
  }

  return Number(trimmed);
}

export function getOsmAccess(feature) {
  const tags = getTags(feature);
  return normalizeAccess(tags.access ?? tags.vehicle ?? tags.motor_vehicle);
}

export function getOsmCapacity(feature) {
  const tags = getTags(feature);
  return parsePositiveInteger(
    tags["capacity:motorcar"] ?? tags.capacity ?? tags["capacity:cars"],
  );
}

export function createDefaultParkingSpec(feature) {
  const access = getOsmAccess(feature);
  const capacity = getOsmCapacity(feature);

  const accessSource = access ? "osm" : "missing";
  const capacitySource = capacity ? "osm" : "missing";

  return {
    id: getFeatureId(feature),
    name: getParkingDisplayName(feature),
    wayId: getFeatureId(feature),
    access,
    accessSource,
    originalAccess: access,
    originalAccessSource: accessSource,
    capacity,
    capacitySource,
    originalCapacity: capacity,
    originalCapacitySource: capacitySource,
    capacityMethod: null,
    internalRoads: INTERNAL_ROADS_NOT_CHECKED,
    changeDate: null,
  };
}

function normalizeInternalRoads(value) {
  if (Array.isArray(value)) {
    const roadIds = value
      .map((item) => String(item ?? "").trim())
      .filter(Boolean);
    return roadIds.length ? roadIds : INTERNAL_ROADS_NOT_FOUND;
  }

  if (value === INTERNAL_ROADS_NOT_FOUND) {
    return INTERNAL_ROADS_NOT_FOUND;
  }

  return INTERNAL_ROADS_NOT_CHECKED;
}

export function normalizeParkingSpec(feature, existingSpec) {
  const base = createDefaultParkingSpec(feature);
  if (!existingSpec) {
    return base;
  }

  return {
    ...base,
    ...existingSpec,
    id: base.id,
    name: getParkingDisplayName(feature),
    wayId: existingSpec.wayId ?? base.wayId,
    access: normalizeAccess(existingSpec.access),
    accessSource: existingSpec.accessSource ?? base.accessSource,
    originalAccess:
      existingSpec.originalAccess === undefined
        ? base.originalAccess
        : normalizeAccess(existingSpec.originalAccess),
    originalAccessSource: existingSpec.originalAccessSource ?? base.originalAccessSource,
    capacity:
      existingSpec.capacity === null || existingSpec.capacity === undefined
        ? null
        : parsePositiveInteger(existingSpec.capacity),
    capacitySource: existingSpec.capacitySource ?? base.capacitySource,
    originalCapacity:
      existingSpec.originalCapacity === undefined
        ? base.originalCapacity
        : parsePositiveInteger(existingSpec.originalCapacity),
    originalCapacitySource: existingSpec.originalCapacitySource ?? base.originalCapacitySource,
    capacityMethod: existingSpec.capacityMethod ?? null,
    internalRoads: normalizeInternalRoads(existingSpec.internalRoads ?? existingSpec.internal_roads),
    changeDate: existingSpec.changeDate ?? null,
  };
}

export function buildParkingSpecs(parkingAreas, existingSpecs = {}) {
  const next = {};

  for (const feature of parkingAreas.features ?? []) {
    const id = getFeatureId(feature);
    next[id] = normalizeParkingSpec(feature, existingSpecs[id]);
  }

  return next;
}

export function updateParkingSpec(parkingSpecs, parkingId, patch) {
  const current = parkingSpecs[parkingId];
  if (!current) {
    return parkingSpecs;
  }

  return {
    ...parkingSpecs,
    [parkingId]: {
      ...current,
      ...patch,
      changeDate: new Date().toISOString(),
    },
  };
}

export function accessValueForFilter(spec) {
  return normalizeAccess(spec?.access) ?? ACCESS_UNKNOWN;
}

export function capacityBucketForValue(value) {
  const numeric = Number(value);
  if (!Number.isInteger(numeric) || numeric <= 0) {
    return CAPACITY_UNKNOWN;
  }

  for (const bucket of CAPACITY_BUCKETS) {
    if (bucket.id === CAPACITY_UNKNOWN) {
      continue;
    }

    const lowerOk = numeric > bucket.min || (bucket.min === 0 && numeric >= 0);
    const upperOk = numeric <= bucket.max;
    if (lowerOk && upperOk) {
      return bucket.id;
    }
  }

  return CAPACITY_UNKNOWN;
}

export function capacityBucketForSpec(spec) {
  return capacityBucketForValue(spec?.capacity);
}

export function accessFilterOptions(parkingAreas, parkingSpecs) {
  const counts = new Map();

  for (const feature of parkingAreas.features ?? []) {
    const id = getFeatureId(feature);
    const value = accessValueForFilter(parkingSpecs[id]);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }

  return [...counts.entries()]
    .map(([value, count]) => ({
      id: value,
      label: value === ACCESS_UNKNOWN ? "Unknown / unspecified" : value,
      count,
    }))
    .sort((left, right) => {
      if (left.id === ACCESS_UNKNOWN) return 1;
      if (right.id === ACCESS_UNKNOWN) return -1;
      return left.label.localeCompare(right.label, undefined, {
        numeric: true,
        sensitivity: "base",
      });
    });
}

export function capacityFilterOptions(parkingAreas, parkingSpecs) {
  const counts = new Map(CAPACITY_BUCKETS.map((bucket) => [bucket.id, 0]));

  for (const feature of parkingAreas.features ?? []) {
    const id = getFeatureId(feature);
    const bucketId = capacityBucketForSpec(parkingSpecs[id]);
    counts.set(bucketId, (counts.get(bucketId) ?? 0) + 1);
  }

  return CAPACITY_BUCKETS.map((bucket) => ({
    ...bucket,
    count: counts.get(bucket.id) ?? 0,
  }));
}

export function highlightedParkingIdsFromFilters({
  parkingAreas,
  parkingSpecs,
  activeAccessFilters,
  activeCapacityFilters,
}) {
  const accessFilters = activeAccessFilters ?? new Set();
  const capacityFilters = activeCapacityFilters ?? new Set();
  const hasAccessFilters = accessFilters.size > 0;
  const hasCapacityFilters = capacityFilters.size > 0;

  if (!hasAccessFilters && !hasCapacityFilters) {
    return new Set();
  }

  const ids = new Set();

  for (const feature of parkingAreas.features ?? []) {
    const id = getFeatureId(feature);
    const spec = parkingSpecs[id];
    const matchesAccess = hasAccessFilters && accessFilters.has(accessValueForFilter(spec));
    const matchesCapacity = hasCapacityFilters && capacityFilters.has(capacityBucketForSpec(spec));

    if (matchesAccess || matchesCapacity) {
      ids.add(id);
    }
  }

  return ids;
}

export function parkingSpecAccessOptions(parkingSpecs) {
  const currentValues = Object.values(
    (parkingSpecs ?? {}) as Record<string, { access?: unknown }>,
  )
    .map((spec) => normalizeAccess(spec.access))
    .filter(Boolean);

  return [...new Set([...COMMON_ACCESS_OPTIONS, ...currentValues])].sort((left, right) =>
    left.localeCompare(right, undefined, { sensitivity: "base" }),
  );
}

export function parkingConfigJson({
  modelName,
  parkingAreas,
  parkingSpecs,
}) {
  const parkingAreasOutput = (parkingAreas.features ?? []).map((feature) => {
    const id = getFeatureId(feature);
    const spec = normalizeParkingSpec(feature, parkingSpecs[id]);

    return {
      name: spec.name,
      way_id: spec.wayId,
      access: spec.access,
      access_source: spec.accessSource,
      capacity: spec.capacity,
      capacity_source: spec.capacitySource,
      capacity_method: spec.capacityMethod ?? null,
      internal_roads: normalizeInternalRoads(spec.internalRoads),
      change_date: spec.changeDate,
    };
  });

  return {
    schema_version: 1,
    model_name: modelName || null,
    exported_at: new Date().toISOString(),
    parking_area_count: parkingAreasOutput.length,
    parking_areas: parkingAreasOutput,
  };
}


export function sourceLabel(source) {
  if (source === "manual") return "manual";
  if (source === "osm") return "OSM";
  if (source === CALCULATED_CAPACITY_SOURCE) return "calculated from related lanes / 2.3 m";
  return "missing";
}

export function isCapacityChangedFromOriginal(spec) {
  if (!spec) return false;
  return (spec.capacity ?? null) !== (spec.originalCapacity ?? null);
}
