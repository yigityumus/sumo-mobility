import type { CampusFeatureCollection, ParkingClassification } from "../types/campus.ts";
import { getFeatureId } from "./osmFeatures.ts";

export const MAX_PARKING_CLASSIFICATIONS = 10;
export const MAX_PARKING_TYPES_PER_CLASSIFICATION = 10;
export const PARKING_TYPE_UNKNOWN = "__unknown__";

const nowIso = () => new Date().toISOString();
const trimName = (value: unknown) => String(value ?? "").trim();

function normalizeAssignments(
  assignments: Record<string, string> | undefined,
  validParkingIds: Set<string>,
  validTypeIds: Set<string>,
) {
  return Object.fromEntries(
    Object.entries(assignments ?? {}).filter(
      ([parkingId, typeId]) => validParkingIds.has(parkingId) && validTypeIds.has(typeId),
    ),
  );
}

export function normalizeParkingClassifications(
  parkingAreas: { features?: CampusFeatureCollection["features"] },
  existingClassifications: ParkingClassification[] = [],
): ParkingClassification[] {
  const validParkingIds = new Set((parkingAreas?.features ?? []).map(getFeatureId));

  return (existingClassifications ?? [])
    .slice(0, MAX_PARKING_CLASSIFICATIONS)
    .map((classification, classificationIndex) => {
      const types = (classification?.types ?? [])
        .slice(0, MAX_PARKING_TYPES_PER_CLASSIFICATION)
        .map((type, typeIndex) => ({
          id: trimName(type?.id) || crypto.randomUUID(),
          name: trimName(type?.name) || `Type ${typeIndex + 1}`,
        }));
      const validTypeIds = new Set(types.map((type) => type.id));
      const createdAt = classification?.createdAt ?? nowIso();

      return {
        id: trimName(classification?.id) || crypto.randomUUID(),
        name: trimName(classification?.name) || `Classification ${classificationIndex + 1}`,
        types,
        assignments: normalizeAssignments(classification?.assignments, validParkingIds, validTypeIds),
        createdAt,
        updatedAt: classification?.updatedAt ?? createdAt,
      };
    });
}

export function updateParkingClassificationName(
  classifications: ParkingClassification[],
  classificationId: string,
  name: string,
) {
  const trimmed = trimName(name);
  return (classifications ?? []).map((classification) =>
    classification.id === classificationId
      ? { ...classification, name: trimmed || classification.name, updatedAt: nowIso() }
      : classification,
  );
}

export function deleteParkingClassification(
  classifications: ParkingClassification[],
  classificationId: string,
) {
  return (classifications ?? []).filter((classification) => classification.id !== classificationId);
}

export function addParkingType(
  classifications: ParkingClassification[],
  classificationId: string,
  requestedName = "",
) {
  const name = trimName(requestedName);
  if (!name) return { classifications, error: "Enter a name before creating the type." };

  let error = "";
  const next = (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) return classification;
    if ((classification.types ?? []).length >= MAX_PARKING_TYPES_PER_CLASSIFICATION) {
      error = `You can create up to ${MAX_PARKING_TYPES_PER_CLASSIFICATION} types in each classification.`;
      return classification;
    }
    return {
      ...classification,
      types: [...(classification.types ?? []), { id: crypto.randomUUID(), name }],
      updatedAt: nowIso(),
    };
  });
  return { classifications: next, error };
}

export function updateParkingTypeName(
  classifications: ParkingClassification[],
  classificationId: string,
  typeId: string,
  name: string,
) {
  const trimmed = trimName(name);
  return (classifications ?? []).map((classification) =>
    classification.id === classificationId
      ? {
          ...classification,
          types: (classification.types ?? []).map((type) =>
            type.id === typeId ? { ...type, name: trimmed || type.name } : type,
          ),
          updatedAt: nowIso(),
        }
      : classification,
  );
}

export function deleteParkingType(
  classifications: ParkingClassification[],
  classificationId: string,
  typeId: string,
) {
  return (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) return classification;
    return {
      ...classification,
      types: (classification.types ?? []).filter((type) => type.id !== typeId),
      assignments: Object.fromEntries(
        Object.entries(classification.assignments ?? {}).filter(([, assignedTypeId]) => assignedTypeId !== typeId),
      ),
      updatedAt: nowIso(),
    };
  });
}

export function setParkingAssignment(
  classifications: ParkingClassification[],
  classificationId: string,
  parkingId: string,
  typeId: string,
) {
  return (classifications ?? []).map((classification) => {
    if (classification.id !== classificationId) return classification;
    const assignments = { ...(classification.assignments ?? {}) };
    if (!typeId || typeId === PARKING_TYPE_UNKNOWN) delete assignments[parkingId];
    else assignments[parkingId] = typeId;
    return { ...classification, assignments, updatedAt: nowIso() };
  });
}

export function normalizeParkingClassificationsForSignature(
  classifications: ParkingClassification[] = [],
) {
  return (classifications ?? [])
    .map((classification) => ({
      id: classification.id,
      name: classification.name,
      types: (classification.types ?? [])
        .map((type) => ({ id: type.id, name: type.name }))
        .sort((left, right) => left.id.localeCompare(right.id)),
      assignments: Object.fromEntries(
        Object.entries(classification.assignments ?? {}).sort(([left], [right]) => left.localeCompare(right)),
      ),
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
}
