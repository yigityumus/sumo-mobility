"""Reference-workbook validation, object storage, and PostgreSQL ingestion."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.database import (
    persist_real_world_dataset,
    persist_real_world_observations,
    read_real_world_datasets,
)
from shared.object_storage import ObjectStorage, StoredObject, get_reference_object_storage

from .series import RealWorldDataError, SensorObservation, parse_workbook_bytes


class ReferenceDataError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_filename(filename: str) -> str:
    basename = Path(str(filename or "dataset.xlsx")).name
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", basename).strip("._")
    return cleaned or "dataset.xlsx"


def _dataset_id(bucket: str, object_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"minio://{bucket}/{object_key}"))


def _observation_records(
    observations: tuple[SensorObservation, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "segment_id": item.segment_id,
            "street": item.street,
            "city": item.city,
            "observed_at": item.observed_at,
            "pedestrian_count": item.pedestrian_count,
            "vehicle_count": item.vehicle_count,
        }
        for item in observations
    ]


def _ingest_content(
    storage: ObjectStorage,
    *,
    stored: StoredObject,
    content: bytes,
    filename: str,
) -> dict[str, Any]:
    checksum = hashlib.sha256(content).hexdigest()
    dataset = {
        "id": _dataset_id(storage.bucket, stored.object_key),
        "original_filename": _safe_filename(filename),
        "object_key": stored.object_key,
        "checksum_sha256": checksum,
        "size_bytes": len(content),
        "etag": stored.etag,
        "status": "processing",
        "observation_count": 0,
        "observation_start": None,
        "observation_end": None,
        "error_message": None,
        "ingested_at": None,
    }
    try:
        observations = parse_workbook_bytes(content, dataset["original_filename"])
        if not observations:
            raise RealWorldDataError("The workbook contains no readable sensor observations.")
        dataset["observation_count"] = len(observations)
        dataset["observation_start"] = min(item.observed_at for item in observations)
        dataset["observation_end"] = max(item.observed_at for item in observations)
        if not persist_real_world_dataset(dataset):
            raise ReferenceDataError("PostgreSQL rejected the dataset metadata.")
        if not persist_real_world_observations(
            dataset,
            _observation_records(observations),
        ):
            raise ReferenceDataError("PostgreSQL rejected the normalized observations.")
    except (RealWorldDataError, ReferenceDataError) as exc:
        dataset["status"] = "failed"
        dataset["error_message"] = str(exc)
        persist_real_world_dataset(dataset)
        raise ReferenceDataError(str(exc)) from exc

    dataset["status"] = "ready"
    dataset["ingested_at"] = _now_iso()
    return dataset


def sync_reference_data() -> dict[str, int]:
    """Ingest new or changed legacy workbook objects after MinIO initialization."""
    storage = get_reference_object_storage()
    existing = read_real_world_datasets()
    if storage is None or existing is None:
        return {"discovered": 0, "ingested": 0, "skipped": 0, "failed": 0}

    by_key = {str(item["object_key"]): item for item in existing}
    counts = {"discovered": 0, "ingested": 0, "skipped": 0, "failed": 0}
    for item in storage.list_prefix("legacy"):
        if not item.relative_path.lower().endswith(".xlsx"):
            continue
        counts["discovered"] += 1
        previous = by_key.get(item.object_key)
        if (
            previous is not None
            and previous.get("status") == "ready"
            and previous.get("etag") == item.etag
            and int(previous.get("size_bytes") or 0) == item.size_bytes
        ):
            counts["skipped"] += 1
            continue
        relative_path = f"legacy/{item.relative_path}"
        content = storage.read_bytes(relative_path)
        if content is None:
            counts["failed"] += 1
            continue
        try:
            _ingest_content(
                storage,
                stored=item,
                content=content,
                filename=Path(item.relative_path).name,
            )
        except ReferenceDataError:
            counts["failed"] += 1
        else:
            counts["ingested"] += 1
    return counts


def upload_reference_dataset(
    content: bytes,
    filename: str,
    *,
    maximum_bytes: int,
) -> dict[str, Any]:
    storage = get_reference_object_storage()
    if storage is None:
        raise ReferenceDataError("Reference-data object storage is not configured.")
    safe_filename = _safe_filename(filename)
    if not safe_filename.lower().endswith(".xlsx"):
        raise ReferenceDataError("Only .xlsx sensor workbooks are supported.")
    if not content:
        raise ReferenceDataError("The uploaded workbook is empty.")
    if len(content) > maximum_bytes:
        raise ReferenceDataError("The uploaded workbook exceeds the configured size limit.")

    checksum = hashlib.sha256(content).hexdigest()
    for dataset in read_real_world_datasets() or []:
        if dataset.get("status") == "ready" and dataset.get("checksum_sha256") == checksum:
            return dataset

    # Validate before making the immutable source object authoritative.
    observations = parse_workbook_bytes(content, safe_filename)
    if not observations:
        raise ReferenceDataError("The workbook contains no readable sensor observations.")
    upload_id = str(uuid.uuid4())
    stored = storage.write_bytes(
        f"uploads/{upload_id}/{safe_filename}",
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return _ingest_content(
        storage,
        stored=stored,
        content=content,
        filename=safe_filename,
    )


def list_reference_datasets() -> list[dict[str, Any]]:
    datasets = read_real_world_datasets()
    if datasets is None:
        raise ReferenceDataError("PostgreSQL is required for reference datasets.")
    return datasets
