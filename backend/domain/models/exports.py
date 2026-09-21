"""Portable campus model exports."""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_export_name(raw_name: Any) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._ -]+", "_", str(raw_name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._ -")
    return cleaned or "area_model"


def _tags(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties") or {}
    tags = properties.get("tags")
    if isinstance(tags, dict):
        return tags

    metadata_keys = {
        "id", "version", "timestamp", "changeset", "user", "uid",
        "visible", "bounds", "nodes", "members",
    }
    return {key: value for key, value in properties.items() if key not in metadata_keys}


def _feature_id(feature: dict[str, Any]) -> str:
    if feature.get("id") is not None:
        return str(feature["id"])
    properties = feature.get("properties") or {}
    return f"{properties.get('type', 'unknown')}/{properties.get('id', 'unknown')}"


def _display_name(feature: dict[str, Any], fallback_prefix: str) -> str:
    tags = _tags(feature)
    return str(
        tags.get("name")
        or tags.get("ref")
        or tags.get("addr:housename")
        or tags.get("official_name")
        or f"{fallback_prefix} {_feature_id(feature)}"
    )


def _selected_features(collection: dict[str, Any], selected_ids: Iterable[str]) -> list[dict[str, Any]]:
    selected = {str(item) for item in selected_ids or []}
    return [feature for feature in (collection.get("features") or []) if _feature_id(feature) in selected]


def selected_feature_collection(
    collection: dict[str, Any],
    selected_ids: Iterable[str],
    boundary_feature: dict[str, Any] | None,
    feature_type: str,
    source: str,
) -> dict[str, Any]:
    selected = _selected_features(collection, selected_ids)
    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": source,
            "exported_at": now_iso(),
            "feature_type": feature_type,
            "selected_feature_count": len(selected),
            "area_boundary": (boundary_feature or {}).get("geometry"),
        },
        "features": selected,
    }


def area_building_configuration(
    buildings: dict[str, Any],
    selected_ids: Iterable[str],
    boundary_feature: dict[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    output = []
    for feature in _selected_features(buildings, selected_ids):
        feature_id = _feature_id(feature)
        osm_type, _, raw_id = feature_id.partition("/")
        tags = _tags(feature)
        output.append({
            "id": feature_id,
            "osm_type": (feature.get("properties") or {}).get("type") or osm_type,
            "osm_id": (feature.get("properties") or {}).get("id") or _safe_int(raw_id),
            "name": _display_name(feature, "Unnamed building"),
            "ref": tags.get("ref"),
            "building": tags.get("building"),
            "tags": tags,
            "geometry": feature.get("geometry"),
            "entrance": None,
            "pedestrian_edge": None,
            "pedestrian_position": None,
        })

    return {
        "schema_version": 1,
        "source": source,
        "exported_at": now_iso(),
        "area_boundary": (boundary_feature or {}).get("geometry"),
        "building_count": len(output),
        "buildings": output,
    }


def area_parking_configuration(
    parking_areas: dict[str, Any],
    selected_ids: Iterable[str],
    boundary_feature: dict[str, Any] | None,
    source: str,
    parking_specs: dict[str, Any],
) -> dict[str, Any]:
    output = []
    for feature in _selected_features(parking_areas, selected_ids):
        feature_id = _feature_id(feature)
        osm_type, _, raw_id = feature_id.partition("/")
        tags = _tags(feature)
        spec = parking_specs.get(feature_id) or {}
        output.append({
            "id": feature_id,
            "osm_type": (feature.get("properties") or {}).get("type") or osm_type,
            "osm_id": (feature.get("properties") or {}).get("id") or _safe_int(raw_id),
            "name": _display_name(feature, "Parking area"),
            "amenity": tags.get("amenity"),
            "parking": tags.get("parking"),
            "capacity": spec.get("capacity") or tags.get("capacity:motorcar") or tags.get("capacity"),
            "capacity_source": spec.get("capacitySource"),
            "access": spec.get("access") or tags.get("access"),
            "access_source": spec.get("accessSource"),
            "tags": tags,
            "geometry": feature.get("geometry"),
            "capacity_override": None,
            "vehicle_entrance": None,
            "vehicle_edge": None,
            "vehicle_position": None,
            "pedestrian_exit": None,
            "pedestrian_edge": None,
            "pedestrian_position": None,
        })

    return {
        "schema_version": 1,
        "source": source,
        "exported_at": now_iso(),
        "area_boundary": (boundary_feature or {}).get("geometry"),
        "parking_area_count": len(output),
        "parking_areas": output,
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_internal_roads(value: Any) -> str | list[str]:
    if isinstance(value, list):
        ids = [str(item).strip() for item in value if str(item).strip()]
        return ids or "not_found"
    if value == "not_found":
        return "not_found"
    return "not_checked"


def parking_config_json(model_name: str, parking_areas: dict[str, Any], parking_specs: dict[str, Any]) -> dict[str, Any]:
    output = []
    for feature in parking_areas.get("features") or []:
        feature_id = _feature_id(feature)
        spec = parking_specs.get(feature_id) or {}
        output.append({
            "name": spec.get("name") or _display_name(feature, "Parking area"),
            "way_id": spec.get("wayId") or feature_id,
            "access": spec.get("access"),
            "access_source": spec.get("accessSource"),
            "capacity": spec.get("capacity"),
            "capacity_source": spec.get("capacitySource"),
            "capacity_method": spec.get("capacityMethod"),
            "internal_roads": _normalize_internal_roads(spec.get("internalRoads")),
            "change_date": spec.get("changeDate"),
        })

    return {
        "schema_version": 1,
        "model_name": model_name or None,
        "exported_at": now_iso(),
        "parking_area_count": len(output),
        "parking_areas": output,
    }


def _normalise_building_classifications(
    buildings: dict[str, Any],
    classifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    valid_building_ids = {_feature_id(feature) for feature in buildings.get("features") or []}
    normalized = []
    for classification in classifications or []:
        types = classification.get("types") or []
        valid_type_ids = {str(item.get("id")) for item in types if item.get("id")}
        assignments = {
            str(building_id): str(type_id)
            for building_id, type_id in (classification.get("assignments") or {}).items()
            if str(building_id) in valid_building_ids and str(type_id) in valid_type_ids
        }
        normalized.append({**classification, "types": types, "assignments": assignments})
    return normalized


def building_config_json(
    model_name: str,
    buildings: dict[str, Any],
    building_classifications: list[dict[str, Any]],
) -> dict[str, Any]:
    classifications = _normalise_building_classifications(buildings, building_classifications)
    output = []
    for classification in classifications:
        types = classification.get("types") or []
        type_by_id = {str(item.get("id")): item for item in types}
        buildings_output = []
        for feature in buildings.get("features") or []:
            building_id = _feature_id(feature)
            type_id = (classification.get("assignments") or {}).get(building_id)
            type_item = type_by_id.get(str(type_id)) if type_id else None
            buildings_output.append({
                "name": _display_name(feature, "Unnamed building"),
                "way_id": building_id,
                "type": (type_item or {}).get("name") or "unknown",
                "type_id": (type_item or {}).get("id") if type_item else None,
            })
        output.append({
            "id": classification.get("id"),
            "name": classification.get("name"),
            "created_at": classification.get("createdAt"),
            "updated_at": classification.get("updatedAt"),
            "types": [{"id": item.get("id"), "name": item.get("name")} for item in types],
            "building_count": len(buildings.get("features") or []),
            "buildings": buildings_output,
        })

    return {
        "schema_version": 1,
        "model_name": model_name or None,
        "exported_at": now_iso(),
        "classification_count": len(output),
        "classifications": output,
    }


def _building_export(
    model_name: str,
    buildings: dict[str, Any],
    selected_ids: Iterable[str],
    boundary: dict[str, Any] | None,
    source: str,
    classifications: list[dict[str, Any]],
) -> dict[str, Any]:
    collection = selected_feature_collection(
        buildings,
        selected_ids,
        boundary,
        "buildings",
        source,
    )
    collection["configuration"] = {
        "schema_version": 1,
        "model_name": model_name,
        "classifications": _normalise_building_classifications(
            collection,
            classifications,
        ),
    }
    return collection


def _parking_export(
    model_name: str,
    parking_areas: dict[str, Any],
    selected_ids: Iterable[str],
    boundary: dict[str, Any] | None,
    source: str,
    parking_specs: dict[str, Any],
    parking_classifications: list[dict[str, Any]],
) -> dict[str, Any]:
    collection = selected_feature_collection(
        parking_areas,
        selected_ids,
        boundary,
        "parking_areas",
        source,
    )
    selected_feature_ids = {
        _feature_id(feature)
        for feature in collection["features"]
    }
    collection["configuration"] = {
        "schema_version": 1,
        "model_name": model_name,
        "parking_specs": {
            str(parking_id): spec
            for parking_id, spec in parking_specs.items()
            if str(parking_id) in selected_feature_ids
        },
        "classifications": [
            {
                **classification,
                "assignments": {
                    str(parking_id): type_id
                    for parking_id, type_id in (classification.get("assignments") or {}).items()
                    if str(parking_id) in selected_feature_ids
                },
            }
            for classification in parking_classifications
        ],
    }
    return collection


def _model_configuration(
    model: dict[str, Any],
    included_files: list[str],
) -> dict[str, Any]:
    category_data = {
        "buildings",
        "parkingAreas",
        "parkingSpecs",
        "buildingClassifications",
        "parkingClassifications",
        "sourceOsmBlob",
        "sourceOsmBase64",
    }
    return {
        "schema_version": 1,
        "exported_at": now_iso(),
        "included_files": included_files,
        "model": {
            key: value
            for key, value in model.items()
            if key not in category_data
        },
    }


def create_model_zip(
    model: dict[str, Any],
    source_osm: bytes | None,
    source_filename: str,
    *,
    include_osm: bool = True,
    include_buildings: bool = False,
    include_parking_areas: bool = False,
    include_model_config: bool = False,
) -> bytes:
    if not any((
        include_osm,
        include_buildings,
        include_parking_areas,
        include_model_config,
    )):
        raise ValueError("Select at least one file to export.")

    folder_name = sanitize_export_name(model.get("name"))
    buildings = model.get("buildings") or {"type": "FeatureCollection", "features": []}
    parking_areas = model.get("parkingAreas") or {"type": "FeatureCollection", "features": []}
    selected_building_ids = model.get("selectedBuildingIds") or []
    selected_parking_ids = model.get("selectedParkingIds") or []
    boundary = model.get("boundaryFeature")
    source = model.get("dataSourceLabel") or "Saved area model"
    parking_specs = model.get("parkingSpecs") or {}
    building_classifications = model.get("buildingClassifications") or []
    parking_classifications = model.get("parkingClassifications") or []

    included_files = []
    if include_osm:
        included_files.append(source_filename)
    if include_buildings:
        included_files.append("buildings.geojson")
    if include_parking_areas:
        included_files.append("parking_areas.geojson")
    if include_model_config:
        included_files.append("model_config.json")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        def write_json(path: str, value: Any) -> None:
            archive.writestr(path, json.dumps(value, ensure_ascii=False, indent=2))

        if include_osm:
            if source_osm is None:
                raise ValueError("The source OSM file is not available.")
            archive.writestr(f"{folder_name}/{source_filename}", source_osm)
        if include_buildings:
            write_json(
                f"{folder_name}/buildings.geojson",
                _building_export(
                    folder_name,
                    buildings,
                    selected_building_ids,
                    boundary,
                    source,
                    building_classifications,
                ),
            )
        if include_parking_areas:
            write_json(
                f"{folder_name}/parking_areas.geojson",
                _parking_export(
                    folder_name,
                    parking_areas,
                    selected_parking_ids,
                    boundary,
                    source,
                    parking_specs,
                    parking_classifications,
                ),
            )
        if include_model_config:
            write_json(
                f"{folder_name}/model_config.json",
                _model_configuration(model, included_files),
            )

    return buffer.getvalue()
