"""Campus model persistence and object-storage access."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from shared.database import (
    persist_model,
    read_all_model_metadata,
    read_model_metadata,
    remove_model,
)
from shared.object_storage import get_object_storage, model_object_path


class ModelStoreError(ValueError):
    pass


def _safe_model_id(model_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(model_id or "").strip())
    if not cleaned:
        raise ModelStoreError("Model id is required.")
    return cleaned


def _model_dir(base_dir: Path, model_id: str) -> Path:
    return base_dir / _safe_model_id(model_id)


def _model_path(base_dir: Path, model_id: str) -> Path:
    return _model_dir(base_dir, model_id) / "model.json"


def _source_path(base_dir: Path, model_id: str) -> Path:
    return _model_dir(base_dir, model_id) / "source.osm.xml"


def strip_frontend_blob_fields(model: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(model)
    cleaned.pop("sourceOsmBlob", None)
    return cleaned


def ensure_storage_dir(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)


def save_model(
    base_dir: Path,
    model: dict[str, Any],
    source_osm_bytes: bytes | None = None,
    source_osm_filename: str | None = None,
) -> dict[str, Any]:
    ensure_storage_dir(base_dir)

    model_id = str(model.get("id") or "").strip()
    if not model_id:
        raise ModelStoreError("Model id is required.")

    model_directory = _model_dir(base_dir, model_id)
    model_directory.mkdir(parents=True, exist_ok=True)

    saved_model = strip_frontend_blob_fields(model)

    if source_osm_bytes:
        _source_path(base_dir, model_id).write_bytes(source_osm_bytes)
        storage = get_object_storage()
        if storage is not None:
            storage.write_bytes(
                model_object_path(model_id, "source.osm.xml"),
                source_osm_bytes,
                content_type="application/xml",
            )
        if source_osm_filename:
            saved_model["sourceOsmFilename"] = source_osm_filename
        saved_model["sourceOsmCached"] = True
    else:
        saved_model["sourceOsmCached"] = source_osm_exists(base_dir, model_id)

    _model_path(base_dir, model_id).write_text(
        json.dumps(saved_model, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    storage = get_object_storage()
    if storage is not None:
        storage.write_json(model_object_path(model_id, "model.json"), saved_model)
    persist_model(saved_model, model_directory.relative_to(base_dir).as_posix())

    return saved_model


def read_model(base_dir: Path, model_id: str) -> dict[str, Any] | None:
    database_model = read_model_metadata(str(model_id))
    if database_model is not None:
        return database_model
    storage = get_object_storage()
    if storage is not None:
        stored_model = storage.read_json(model_object_path(model_id, "model.json"))
        if stored_model is not None:
            return stored_model
    path = _model_path(base_dir, model_id)
    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def delete_model(base_dir: Path, model_id: str) -> bool:
    directory = _model_dir(base_dir, model_id)
    model_exists = read_model(base_dir, model_id) is not None
    if not model_exists:
        return False
    storage = get_object_storage()
    if storage is not None:
        storage.delete_prefix(model_object_path(model_id))
    if directory.exists():
        shutil.rmtree(directory)
    remove_model(str(model_id))
    return True


def list_models(base_dir: Path) -> list[dict[str, Any]]:
    ensure_storage_dir(base_dir)
    summaries: list[dict[str, Any]] = []

    database_models = read_all_model_metadata()
    if database_models is not None:
        models = database_models
    else:
        models = []
        for model_path in base_dir.glob("*/model.json"):
            try:
                models.append(json.loads(model_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue

    for model in models:
        summaries.append(
            {
                "id": model.get("id"),
                "name": model.get("name"),
                "createdAt": model.get("createdAt"),
                "updatedAt": model.get("updatedAt"),
                "buildingCount": len(model.get("buildings", {}).get("features", []) or []),
                "parkingCount": len(model.get("parkingAreas", {}).get("features", []) or []),
                "selectedBuildingCount": len(model.get("selectedBuildingIds", []) or []),
                "selectedParkingCount": len(model.get("selectedParkingIds", []) or []),
                "sourceOsmCached": source_osm_exists(base_dir, str(model.get("id"))),
            }
        )

    return sorted(summaries, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)


def source_osm_exists(base_dir: Path, model_id: str) -> bool:
    storage = get_object_storage()
    return bool(
        (storage is not None and storage.exists(model_object_path(model_id, "source.osm.xml")))
        or _source_path(base_dir, model_id).exists()
    )


def read_source_osm(base_dir: Path, model_id: str) -> bytes | None:
    storage = get_object_storage()
    if storage is not None:
        content = storage.read_bytes(model_object_path(model_id, "source.osm.xml"))
        if content is not None:
            path = _source_path(base_dir, model_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return content
    path = _source_path(base_dir, model_id)
    if not path.exists():
        return None
    return path.read_bytes()


def write_source_osm(base_dir: Path, model_id: str, content: bytes) -> None:
    directory = _model_dir(base_dir, model_id)
    directory.mkdir(parents=True, exist_ok=True)
    _source_path(base_dir, model_id).write_bytes(content)
    storage = get_object_storage()
    if storage is not None:
        storage.write_bytes(
            model_object_path(model_id, "source.osm.xml"),
            content,
            content_type="application/xml",
        )


def source_osm_filename(model: dict[str, Any]) -> str:
    return str(model.get("sourceOsmFilename") or "area_osm_extract.osm.xml")
