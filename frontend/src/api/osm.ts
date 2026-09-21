import type { CampusFeaturesPayload } from "../types/campus";
import { postBlob, postForm, postJson } from "./client";

export function extractCampusFeatures(coordinates: unknown) {
  return postJson<CampusFeaturesPayload>(
    "/api/features",
    { coordinates },
    "Feature request failed.",
  );
}

export function uploadOsmFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return postForm<CampusFeaturesPayload>(
    "/api/osm-upload",
    formData,
    "OSM upload failed.",
  );
}

export function downloadOsmExtract(coordinates: unknown) {
  return postBlob(
    "/api/osm-extract",
    { coordinates },
    "OSM extract failed.",
  );
}
