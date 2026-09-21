"""MinIO/S3 object-storage primitives shared by services."""

from __future__ import annotations

import json
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from minio import Minio
from minio.error import S3Error


LOGGER = logging.getLogger(__name__)


class ObjectStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    relative_path: str
    object_key: str
    size_bytes: int
    etag: str | None


class ObjectStorage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        *,
        secure: bool,
        prefix: str,
    ) -> None:
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def initialize(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def healthcheck(self) -> bool:
        return self.client.bucket_exists(self.bucket)

    def object_key(self, relative_path: str | Path) -> str:
        raw = str(relative_path).replace("\\", "/").strip("/")
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or ".." in path.parts:
            raise ObjectStorageError(f"Invalid object path: {relative_path}")
        return "/".join(value for value in (self.prefix, path.as_posix()) if value)

    def exists(self, relative_path: str | Path) -> bool:
        try:
            self.client.stat_object(self.bucket, self.object_key(relative_path))
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return False
            raise ObjectStorageError(str(exc)) from exc

    def read_bytes(self, relative_path: str | Path) -> bytes | None:
        response = None
        try:
            response = self.client.get_object(self.bucket, self.object_key(relative_path))
            return response.read()
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return None
            raise ObjectStorageError(str(exc)) from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def read_json(self, relative_path: str | Path) -> dict[str, Any] | None:
        content = self.read_bytes(relative_path)
        if content is None:
            return None
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObjectStorageError(f"Invalid JSON object: {relative_path}") from exc
        return value if isinstance(value, dict) else None

    def write_bytes(
        self,
        relative_path: str | Path,
        content: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        from io import BytesIO

        key = self.object_key(relative_path)
        result = self.client.put_object(
            self.bucket,
            key,
            BytesIO(content),
            len(content),
            content_type=content_type or "application/octet-stream",
        )
        return StoredObject(str(relative_path), key, len(content), result.etag)

    def write_json(self, relative_path: str | Path, value: dict[str, Any]) -> StoredObject:
        return self.write_bytes(
            relative_path,
            json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def upload_file(self, source: Path, relative_path: str | Path) -> StoredObject:
        key = self.object_key(relative_path)
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        result = self.client.fput_object(
            self.bucket,
            key,
            str(source),
            content_type=content_type,
        )
        return StoredObject(str(relative_path), key, source.stat().st_size, result.etag)

    def download_file(self, relative_path: str | Path, destination: Path) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.fget_object(
                self.bucket,
                self.object_key(relative_path),
                str(destination),
            )
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return False
            raise ObjectStorageError(str(exc)) from exc

    def upload_tree(self, source: Path, relative_prefix: str | Path) -> list[StoredObject]:
        stored = []
        for path in source.rglob("*"):
            if path.is_file():
                local_relative_path = path.relative_to(source).as_posix()
                uploaded = self.upload_file(
                    path,
                    PurePosixPath(str(relative_prefix).replace("\\", "/"))
                    / local_relative_path,
                )
                stored.append(
                    StoredObject(
                        local_relative_path,
                        uploaded.object_key,
                        uploaded.size_bytes,
                        uploaded.etag,
                    )
                )
        return stored

    def download_prefix(self, relative_prefix: str | Path, destination: Path) -> int:
        prefix_key = self.object_key(relative_prefix).rstrip("/") + "/"
        downloaded = 0
        for item in self.client.list_objects(self.bucket, prefix=prefix_key, recursive=True):
            suffix = item.object_name.removeprefix(prefix_key)
            if not suffix:
                continue
            target = destination / PurePosixPath(suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.client.fget_object(self.bucket, item.object_name, str(target))
            downloaded += 1
        return downloaded

    def list_prefix(self, relative_prefix: str | Path) -> list[StoredObject]:
        prefix_key = self.object_key(relative_prefix).rstrip("/") + "/"
        return [
            StoredObject(
                item.object_name.removeprefix(prefix_key),
                item.object_name,
                int(item.size or 0),
                item.etag,
            )
            for item in self.client.list_objects(
                self.bucket,
                prefix=prefix_key,
                recursive=True,
            )
        ]

    def download_metadata(self, destination: Path) -> int:
        """Hydrate only small authoritative JSON records, never large artifacts."""
        prefix_key = f"{self.prefix}/" if self.prefix else ""
        downloaded = 0
        for item in self.client.list_objects(
            self.bucket,
            prefix=prefix_key,
            recursive=True,
        ):
            relative = item.object_name.removeprefix(prefix_key)
            if not (relative.endswith("/model.json") or relative.endswith("/run.json")):
                continue
            target = destination / PurePosixPath(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.client.fget_object(self.bucket, item.object_name, str(target))
            downloaded += 1
        return downloaded

    def delete_prefix(self, relative_prefix: str | Path) -> int:
        prefix_key = self.object_key(relative_prefix).rstrip("/") + "/"
        names = [
            item.object_name
            for item in self.client.list_objects(
                self.bucket,
                prefix=prefix_key,
                recursive=True,
            )
        ]
        if not names:
            return 0
        from minio.deleteobjects import DeleteObject

        errors = list(
            self.client.remove_objects(
                self.bucket,
                (DeleteObject(name) for name in names),
            )
        )
        if errors:
            raise ObjectStorageError(str(errors[0]))
        return len(names)


_storage: ObjectStorage | None = None
_reference_storage: ObjectStorage | None = None


def configure_object_storage(
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    bucket: str,
    *,
    secure: bool,
    prefix: str,
) -> None:
    global _storage
    if not endpoint:
        _storage = None
        return
    if not access_key or not secret_key:
        raise ObjectStorageError(
            "Object storage credentials are required when an endpoint is configured."
        )
    _storage = ObjectStorage(
        endpoint,
        access_key,
        secret_key,
        bucket,
        secure=secure,
        prefix=prefix,
    )


def configure_reference_object_storage(
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    bucket: str,
    *,
    secure: bool,
    prefix: str,
) -> None:
    global _reference_storage
    if not endpoint:
        _reference_storage = None
        return
    if not access_key or not secret_key:
        raise ObjectStorageError(
            "Reference-data storage credentials are required when an endpoint is configured."
        )
    _reference_storage = ObjectStorage(
        endpoint,
        access_key,
        secret_key,
        bucket,
        secure=secure,
        prefix=prefix,
    )


def initialize_object_storage() -> None:
    if _storage is not None:
        _storage.initialize()


def initialize_reference_object_storage() -> None:
    if _reference_storage is not None:
        _reference_storage.initialize()


def get_object_storage() -> ObjectStorage | None:
    return _storage


def get_reference_object_storage() -> ObjectStorage | None:
    return _reference_storage


def object_storage_status() -> str:
    if _storage is None:
        return "disabled"
    try:
        return "ok" if _storage.healthcheck() else "unavailable"
    except (ObjectStorageError, S3Error, OSError):
        return "unavailable"


def reference_object_storage_status() -> str:
    if _reference_storage is None:
        return "disabled"
    try:
        return "ok" if _reference_storage.healthcheck() else "unavailable"
    except (ObjectStorageError, S3Error, OSError):
        return "unavailable"


def model_object_path(model_id: str, suffix: str = "") -> str:
    safe_model_id = str(model_id).strip().replace("/", "_").replace("\\", "_")
    if not safe_model_id:
        raise ObjectStorageError("Model id is required.")
    return "/".join(value for value in (safe_model_id, suffix.strip("/")) if value)


def run_object_path(model_id: str, run_id: str, suffix: str = "") -> str:
    return model_object_path(
        model_id,
        "/".join(value for value in ("simulations", str(run_id), suffix.strip("/")) if value),
    )
