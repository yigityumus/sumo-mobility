import { getBuildingDisplayName, getFeatureId } from "./osmFeatures.ts";

export const MAX_BUILDING_CLASSIFICATIONS = 10;
export const MAX_BUILDING_TYPES_PER_CLASSIFICATION = 10;
export const BUILDING_TYPE_UNKNOWN = "__unknown__";

function nowIso() {
  return new Date().toISOString();
}

function trimName(value) {
  return String(value ?? "").trim();
}

function defaultClassificationName(existingClassifications = []) {
  const used = new Set(
    existingClassifications.map((classification) => trimName(classification.name)),
  );

  for (let index = 1; index <= MAX_BUILDING_CLASSIFICATIONS + 1; index += 1) {
    const candidate = `Classification ${index}`;
    if (!used.has(candidate)) {
      return candidate;
    }
  }

  return `Classification ${existingClassifications.length + 1}`;
}

function normalizeType(type, fallbackIndex = 1) {
  const id = trimName(type?.id) || crypto.randomUUID();
  const name = trimName(type?.name) || `Type ${fallbackIndex}`;
  return { id, name };
}

function normalizeDemandPercentage(value, fallback = 50) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.max(0, Math.min(100, parsed));
}

function normalizeCapacityConstant(value, fallback = 1) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.max(0, parsed);
}

function normalizeDemandDistributionEntry(value, fallback = 50) {
  const pedestrian = normalizeDemandPercentage(value?.pedestrian, fallback);
  return {
    pedestrian,
    vehicle: 100 - pedestrian,
    capacityConstant: normalizeCapacityConstant(value?.capacityConstant, 1),
  };
}

function normalizeDemandDistributionMap(distribution, types = []) {
  return Object.fromEntries(
    (types ?? []).map((type) => [
      type.id,
      normalizeDemandDistributionEntry(distribution?.[type.id], 50),
    ]),
  );
}

function normalizeAssignments(assignments, validBuildingIds, validTypeIds) {
  const next = {};

  for (const [buildingId, typeId] of Object.entries(assignments ?? {})) {
    const normalizedBuildingId = String(buildingId ?? "");
    const normalizedTypeId = String(typeId ?? "");
    if (validBuildingIds.has(normalizedBuildingId) && validTypeIds.has(normalizedTypeId)) {
      next[normalizedBuildingId] = normalizedTypeId;
    }
  }

  return next;
}

export function normalizeBuildingClassifications(buildings, existingClassifications = []) {
  const validBuildingIds = new Set((buildings?.features ?? []).map(getFeatureId));

  return (existingClassifications ?? [])
    .slice(0, MAX_BUILDING_CLASSIFICATIONS)
    .map((classification, classificationIndex) => {
      const types = (classification?.types ?? [])
        .slice(0, MAX_BUILDING_TYPES_PER_CLASSIFICATION)
        .map((type, typeIndex) => normalizeType(type, typeIndex + 1));
      const validTypeIds = new Set(types.map((type) => type.id));
      const createdAt = classification?.createdAt ?? nowIso();
      const updatedAt = classification?.updatedAt ?? createdAt;
      const demandDistribution = normalizeDemandDistributionMap(classification?.demandDistribution, types);

      return {
        id: trimName(classification?.id) || crypto.randomUUID(),
        name: trimName(classification?.name) || `Classification ${classificationIndex + 1}`,
        types,
        assignments: normalizeAssignments(
          classification?.assignments,
          validBuildingIds,
          validTypeIds,
        ),
        demandDistribution,
        createdAt,
        updatedAt,
      };
    });
}

export function createBuildingClassification(existingClassifications = []) {
  const timestamp = nowIso();
  return {
    id: crypto.randomUUID(),
    name: defaultClassificationName(existingClassifications),
    types: [],
    assignments: {},
    demandDistribution: {},
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}

export function addBuildingClassification(classifications) {
  if ((classifications ?? []).length >= MAX_BUILDING_CLASSIFICATIONS) {
    return { classifications, error: `You can create up to ${MAX_BUILDING_CLASSIFICATIONS} classifications.` };
  }

  return {
    classifications: [...(classifications ?? []), createBuildingClassification(classifications)],
    error: "",
  };
}

export function updateBuildingClassificationName(classifications, classificationId, name) {
  const timestamp = nowIso();
  const trimmed = trimName(name);

  return (classifications ?? []).map((classification) =>
    classification.id === classificationId
      ? {
          ...classification,
          name: trimmed || classification.name,
          updatedAt: timestamp,
        }
      : classification,
  );
}

export function deleteBuildingClassification(classifications, classificationId) {
  return (classifications ?? []).filter((classification) => classification.id !== classificationId);
}

export function addBuildingType(classifications, classificationId, requestedName = "") {
  let error = "";
  const timestamp = nowIso();
  const typeName = trimName(requestedName);

  if (!typeName) {
    return { classifications, error: "Enter a name before creating the type." };
  }

  const next = (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) {
      return classification;
    }

    if ((classification.types ?? []).length >= MAX_BUILDING_TYPES_PER_CLASSIFICATION) {
      error = `You can create up to ${MAX_BUILDING_TYPES_PER_CLASSIFICATION} types in each classification.`;
      return classification;
    }

    const nextType = {
      id: crypto.randomUUID(),
      name: typeName,
    };
    const nextDemandDistribution = {
      ...(classification.demandDistribution ?? {}),
      [nextType.id]: {
        pedestrian: 50,
        vehicle: 50,
        capacityConstant: 1,
      },
    };

    return {
      ...classification,
      types: [
        ...(classification.types ?? []),
        nextType,
      ],
      demandDistribution: nextDemandDistribution,
      updatedAt: timestamp,
    };
  });

  return { classifications: next, error };
}

export function updateBuildingTypeName(classifications, classificationId, typeId, name) {
  const timestamp = nowIso();
  const trimmed = trimName(name);

  return (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) {
      return classification;
    }

    return {
      ...classification,
      types: (classification.types ?? []).map((type) =>
        type.id === typeId
          ? {
              ...type,
              name: trimmed || type.name,
            }
          : type,
      ),
      updatedAt: timestamp,
    };
  });
}

export function deleteBuildingType(classifications, classificationId, typeId) {
  const timestamp = nowIso();

  return (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) {
      return classification;
    }

    const assignments = Object.fromEntries(
      Object.entries(classification.assignments ?? {}).filter(([, assignedTypeId]) => assignedTypeId !== typeId),
    );
    const demandDistribution = Object.fromEntries(
      Object.entries(classification.demandDistribution ?? {}).filter(([id]) => id !== typeId),
    );

    return {
      ...classification,
      types: (classification.types ?? []).filter((type) => type.id !== typeId),
      assignments,
      demandDistribution,
      updatedAt: timestamp,
    };
  });
}

export function setBuildingAssignment(classifications, classificationId, buildingId, typeId) {
  const timestamp = nowIso();

  return (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) {
      return classification;
    }

    const assignments = { ...(classification.assignments ?? {}) };
    if (!typeId || typeId === BUILDING_TYPE_UNKNOWN) {
      delete assignments[buildingId];
    } else {
      assignments[buildingId] = typeId;
    }

    return {
      ...classification,
      assignments,
      updatedAt: timestamp,
    };
  });
}

export function updateBuildingTypeDemandDistribution(classifications, classificationId, typeId, mode, value) {
  const timestamp = nowIso();

  return (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) {
      return classification;
    }

    const currentDistribution = normalizeDemandDistributionEntry(
      classification.demandDistribution?.[typeId],
      50,
    );
    const nextDemandDistribution = {
      ...(classification.demandDistribution ?? {}),
      [typeId]: mode === "capacityConstant"
        ? {
            ...currentDistribution,
            capacityConstant: normalizeCapacityConstant(value, 1),
          }
        : mode === "pedestrian"
          ? {
              ...currentDistribution,
              pedestrian: normalizeDemandPercentage(value, 50),
              vehicle: 100 - normalizeDemandPercentage(value, 50),
            }
          : {
              ...currentDistribution,
              pedestrian: 100 - normalizeDemandPercentage(value, 50),
              vehicle: normalizeDemandPercentage(value, 50),
            },
    };

    return {
      ...classification,
      demandDistribution: nextDemandDistribution,
      updatedAt: timestamp,
    };
  });
}

export function normalizeBuildingClassificationsForSignature(classifications = []) {
  return (classifications ?? [])
    .map((classification) => ({
      id: classification.id,
      name: classification.name,
      types: (classification.types ?? [])
        .map((type) => ({ id: type.id, name: type.name }))
        .sort((left, right) => left.id.localeCompare(right.id)),
      assignments: Object.fromEntries(
        Object.entries(classification.assignments ?? {}).sort(([left], [right]) =>
          left.localeCompare(right),
        ),
      ),
      demandDistribution: Object.fromEntries(
        Object.entries(classification.demandDistribution ?? {}).sort(([left], [right]) =>
          left.localeCompare(right),
        ),
      ),
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function assignedTypeName(classification, buildingId) {
  const typeId = classification?.assignments?.[buildingId] ?? null;
  if (!typeId) {
    return "unknown";
  }

  return classification?.types?.find((type) => type.id === typeId)?.name ?? "unknown";
}

export function buildingConfigJson({ modelName, buildings, buildingClassifications }) {
  const normalizedClassifications = normalizeBuildingClassifications(
    buildings,
    buildingClassifications,
  );

  return {
    schema_version: 1,
    model_name: modelName || null,
    exported_at: nowIso(),
    classification_count: normalizedClassifications.length,
    classifications: normalizedClassifications.map((classification) => ({
      id: classification.id,
      name: classification.name,
      created_at: classification.createdAt,
      updated_at: classification.updatedAt,
      types: (classification.types ?? []).map((type) => ({
        id: type.id,
        name: type.name,
      })),
      building_count: buildings?.features?.length ?? 0,
      demand_distribution: Object.fromEntries(
        (classification.types ?? []).map((type) => [
          type.id,
          normalizeDemandDistributionEntry(
            classification.demandDistribution?.[type.id],
            50,
          ),
        ]),
      ),
      buildings: (buildings?.features ?? []).map((feature) => {
        const buildingId = getFeatureId(feature);
        const typeId = classification.assignments?.[buildingId] ?? null;
        const type = classification.types?.find((item) => item.id === typeId) ?? null;

        return {
          name: getBuildingDisplayName(feature),
          way_id: buildingId,
          type: type?.name ?? "unknown",
          type_id: type?.id ?? null,
        };
      }),
    })),
  };
}
