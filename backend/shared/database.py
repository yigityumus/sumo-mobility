"""PostgreSQL persistence shared by the API and workers."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg import sql
from psycopg.errors import Error as PsycopgError
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout


LOGGER = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class DatabaseService:
    def __init__(
        self,
        database_url: str,
        *,
        minimum_pool_size: int = 1,
        maximum_pool_size: int = 5,
        connect_timeout_seconds: int = 10,
    ) -> None:
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=minimum_pool_size,
            max_size=maximum_pool_size,
            timeout=connect_timeout_seconds,
            open=False,
            kwargs={"connect_timeout": connect_timeout_seconds},
        )
        self.connect_timeout_seconds = connect_timeout_seconds

    def initialize(self) -> None:
        self.pool.open(
            wait=True,
            timeout=self.connect_timeout_seconds,
        )
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("SELECT version FROM schema_migrations")
                applied = {str(row[0]) for row in cursor.fetchall()}

            for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = migration_path.stem
                if version in applied:
                    continue
                migration_sql = migration_path.read_text(encoding="utf-8")
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL(migration_sql))
                    cursor.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
            connection.commit()

    def close(self) -> None:
        self.pool.close()

    def healthcheck(self) -> bool:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)

    def upsert_model(
        self,
        model: dict[str, Any],
        storage_path: str,
    ) -> None:
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            return
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO campus_models (
                        id, name, created_at, updated_at, storage_path, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        storage_path = EXCLUDED.storage_path,
                        payload = EXCLUDED.payload,
                        synced_at = NOW()
                    """,
                    (
                        model_id,
                        str(model.get("name") or "Unnamed model"),
                        _parse_datetime(model.get("createdAt")),
                        _parse_datetime(model.get("updatedAt")),
                        storage_path,
                        Jsonb(model),
                    ),
                )
            connection.commit()

    def delete_model(self, model_id: str) -> None:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM simulation_runs WHERE model_id = %s",
                    (model_id,),
                )
                cursor.execute("DELETE FROM campus_models WHERE id = %s", (model_id,))
            connection.commit()

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload FROM campus_models WHERE id = %s",
                    (model_id,),
                )
                row = cursor.fetchone()
                return dict(row[0]) if row else None

    def list_models(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload
                    FROM campus_models
                    ORDER BY updated_at DESC NULLS LAST, synced_at DESC
                    """
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def upsert_simulation_run(
        self,
        record: dict[str, Any],
        storage_path: str,
    ) -> None:
        run_id = _parse_uuid(record.get("id"))
        if run_id is None:
            return
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO simulation_runs (
                        id, model_id, model_name, status, mode,
                        vehicle_count, pedestrian_count, duration_seconds,
                        simulation_start_at, simulation_end_at,
                        created_at, started_at, completed_at,
                        progress_percent, failure_reason, storage_path, payload,
                        cancel_requested_at, worker_id, attempt_count,
                        worker_heartbeat_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        model_id = EXCLUDED.model_id,
                        model_name = EXCLUDED.model_name,
                        status = EXCLUDED.status,
                        mode = EXCLUDED.mode,
                        vehicle_count = EXCLUDED.vehicle_count,
                        pedestrian_count = EXCLUDED.pedestrian_count,
                        duration_seconds = EXCLUDED.duration_seconds,
                        simulation_start_at = EXCLUDED.simulation_start_at,
                        simulation_end_at = EXCLUDED.simulation_end_at,
                        created_at = EXCLUDED.created_at,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at,
                        progress_percent = EXCLUDED.progress_percent,
                        failure_reason = EXCLUDED.failure_reason,
                        storage_path = EXCLUDED.storage_path,
                        payload = EXCLUDED.payload,
                        cancel_requested_at = COALESCE(
                            simulation_runs.cancel_requested_at,
                            EXCLUDED.cancel_requested_at
                        ),
                        worker_id = EXCLUDED.worker_id,
                        attempt_count = EXCLUDED.attempt_count,
                        worker_heartbeat_at = EXCLUDED.worker_heartbeat_at,
                        synced_at = NOW()
                    """,
                    (
                        run_id,
                        str(record.get("model_id") or ""),
                        str(record.get("model_name") or "Unnamed model"),
                        str(record.get("status") or "unknown"),
                        str(record.get("mode") or "sumo"),
                        _as_int(record.get("vehicle_count")),
                        _as_int(record.get("pedestrian_count")),
                        _as_int(record.get("duration_seconds")),
                        _parse_datetime(record.get("simulation_start_at")),
                        _parse_datetime(record.get("simulation_end_at")),
                        _parse_datetime(record.get("created_at")),
                        _parse_datetime(record.get("started_at")),
                        _parse_datetime(record.get("completed_at")),
                        _as_float(record.get("progress_percent")),
                        _optional_string(record.get("failure_reason")),
                        storage_path,
                        Jsonb(record),
                        _parse_datetime(record.get("stop_requested_at")),
                        _optional_string(record.get("worker_id")),
                        _as_int(record.get("attempt_count")),
                        _parse_datetime(record.get("worker_heartbeat_at")),
                    ),
                )
            connection.commit()

    def list_simulation_runs(self, model_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload, cancel_requested_at
                    FROM simulation_runs
                    WHERE model_id = %s
                    ORDER BY created_at DESC NULLS LAST, synced_at DESC
                    """,
                    (model_id,),
                )
                return [_run_payload(row[0], row[1]) for row in cursor.fetchall()]

    def get_simulation_run(
        self,
        run_id: str,
        model_id: str | None = None,
    ) -> dict[str, Any] | None:
        parsed_id = _parse_uuid(run_id)
        if parsed_id is None:
            return None
        query = "SELECT payload, cancel_requested_at FROM simulation_runs WHERE id = %s"
        parameters: tuple[Any, ...] = (parsed_id,)
        if model_id is not None:
            query += " AND model_id = %s"
            parameters = (parsed_id, model_id)
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                row = cursor.fetchone()
                return _run_payload(row[0], row[1]) if row else None

    def list_all_simulation_runs(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload, cancel_requested_at
                    FROM simulation_runs
                    ORDER BY created_at DESC NULLS LAST, synced_at DESC
                    """
                )
                return [_run_payload(row[0], row[1]) for row in cursor.fetchall()]

    def upsert_flow_calibration(self, record: dict[str, Any]) -> None:
        calibration_id = _parse_uuid(record.get("id"))
        if calibration_id is None:
            raise ValueError("A valid flow calibration id is required.")
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO flow_calibrations (
                        id, model_id, status, created_at, updated_at, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at,
                        payload = EXCLUDED.payload
                    """,
                    (
                        calibration_id,
                        str(record.get("model_id") or ""),
                        str(record.get("status") or "unknown"),
                        _parse_datetime(record.get("created_at")),
                        _parse_datetime(record.get("updated_at")),
                        Jsonb(record),
                    ),
                )
            connection.commit()

    def get_flow_calibration(self, calibration_id: str) -> dict[str, Any] | None:
        parsed_id = _parse_uuid(calibration_id)
        if parsed_id is None:
            return None
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload FROM flow_calibrations WHERE id = %s",
                    (parsed_id,),
                )
                row = cursor.fetchone()
                return dict(row[0]) if row else None

    def list_flow_calibrations(self, model_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload
                    FROM flow_calibrations
                    WHERE model_id = %s
                    ORDER BY created_at DESC
                    """,
                    (model_id,),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def request_simulation_cancel(
        self,
        run_id: str,
        model_id: str,
    ) -> dict[str, Any] | None:
        parsed_id = _parse_uuid(run_id)
        if parsed_id is None:
            return None
        requested_at = datetime.now(timezone.utc)
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload, cancel_requested_at
                    FROM simulation_runs
                    WHERE id = %s AND model_id = %s
                    FOR UPDATE
                    """,
                    (parsed_id, model_id),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                payload = _run_payload(row[0], row[1] or requested_at)
                payload["message"] = "Stopping simulation."
                cursor.execute(
                    """
                    UPDATE simulation_runs
                    SET cancel_requested_at = COALESCE(cancel_requested_at, %s),
                        payload = %s,
                        synced_at = NOW()
                    WHERE id = %s
                    """,
                    (requested_at, Jsonb(payload), parsed_id),
                )
            connection.commit()
        return payload

    def simulation_cancel_requested(self, run_id: str) -> bool:
        parsed_id = _parse_uuid(run_id)
        if parsed_id is None:
            return False
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT cancel_requested_at IS NOT NULL FROM simulation_runs WHERE id = %s",
                    (parsed_id,),
                )
                row = cursor.fetchone()
                return bool(row and row[0])

    def delete_simulation_run(self, run_id: str) -> None:
        parsed_id = _parse_uuid(run_id)
        if parsed_id is None:
            return
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM simulation_runs WHERE id = %s", (parsed_id,))
            connection.commit()

    def upsert_artifacts(self, run_id: str, run_directory: Path) -> int:
        parsed_id = _parse_uuid(run_id)
        if parsed_id is None or not run_directory.is_dir():
            return 0
        artifacts: list[tuple[uuid.UUID, str, int, datetime]] = []
        for path in run_directory.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            artifacts.append(
                (
                    parsed_id,
                    path.relative_to(run_directory).as_posix(),
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                )
            )
        if not artifacts:
            return 0
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO simulation_artifacts (
                        run_id, relative_path, size_bytes, modified_at
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (run_id, relative_path) DO UPDATE SET
                        size_bytes = EXCLUDED.size_bytes,
                        modified_at = EXCLUDED.modified_at,
                        synced_at = NOW()
                    """,
                    artifacts,
                )
            connection.commit()
        return len(artifacts)

    def upsert_object_artifacts(
        self,
        run_id: str,
        artifacts: list[dict[str, Any]],
    ) -> int:
        parsed_id = _parse_uuid(run_id)
        if parsed_id is None or not artifacts:
            return 0
        now = datetime.now(timezone.utc)
        rows = [
            (
                parsed_id,
                str(item["relative_path"]),
                _as_int(item.get("size_bytes")),
                now,
                str(item["object_key"]),
                _optional_string(item.get("etag")),
            )
            for item in artifacts
        ]
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO simulation_artifacts (
                        run_id, relative_path, size_bytes, modified_at,
                        storage_backend, object_key, etag
                    ) VALUES (%s, %s, %s, %s, 'object_storage', %s, %s)
                    ON CONFLICT (run_id, relative_path) DO UPDATE SET
                        size_bytes = EXCLUDED.size_bytes,
                        modified_at = EXCLUDED.modified_at,
                        storage_backend = EXCLUDED.storage_backend,
                        object_key = EXCLUDED.object_key,
                        etag = EXCLUDED.etag,
                        synced_at = NOW()
                    """,
                    rows,
                )
            connection.commit()
        return len(rows)

    def list_artifact_paths(self) -> dict[str, set[str]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT run_id::text, relative_path
                    FROM simulation_artifacts
                    ORDER BY run_id, relative_path
                    """
                )
                paths: dict[str, set[str]] = {}
                for run_id, relative_path in cursor.fetchall():
                    paths.setdefault(str(run_id), set()).add(str(relative_path))
                return paths

    def upsert_real_world_dataset(self, dataset: dict[str, Any]) -> None:
        dataset_id = _parse_uuid(dataset.get("id"))
        if dataset_id is None:
            raise ValueError("A valid real-world dataset id is required.")
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO real_world_datasets (
                        id, original_filename, object_key, checksum_sha256,
                        size_bytes, etag, status, observation_count,
                        observation_start, observation_end, error_message,
                        ingested_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (object_key) DO UPDATE SET
                        original_filename = EXCLUDED.original_filename,
                        checksum_sha256 = EXCLUDED.checksum_sha256,
                        size_bytes = EXCLUDED.size_bytes,
                        etag = EXCLUDED.etag,
                        status = EXCLUDED.status,
                        observation_count = EXCLUDED.observation_count,
                        observation_start = EXCLUDED.observation_start,
                        observation_end = EXCLUDED.observation_end,
                        error_message = EXCLUDED.error_message,
                        ingested_at = EXCLUDED.ingested_at,
                        updated_at = NOW()
                    """,
                    (
                        dataset_id,
                        str(dataset.get("original_filename") or "dataset.xlsx"),
                        str(dataset.get("object_key") or ""),
                        str(dataset.get("checksum_sha256") or ""),
                        _as_int(dataset.get("size_bytes")),
                        _optional_string(dataset.get("etag")),
                        str(dataset.get("status") or "pending"),
                        _as_int(dataset.get("observation_count")),
                        _parse_naive_datetime(dataset.get("observation_start")),
                        _parse_naive_datetime(dataset.get("observation_end")),
                        _optional_string(dataset.get("error_message")),
                        _parse_datetime(dataset.get("ingested_at")),
                    ),
                )
            connection.commit()

    def replace_real_world_observations(
        self,
        dataset: dict[str, Any],
        observations: list[dict[str, Any]],
    ) -> None:
        dataset_id = _parse_uuid(dataset.get("id"))
        if dataset_id is None:
            raise ValueError("A valid real-world dataset id is required.")
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM real_world_observations WHERE dataset_id = %s",
                    (dataset_id,),
                )
                cursor.executemany(
                    """
                    INSERT INTO real_world_observations (
                        dataset_id, row_number, segment_id, street, city,
                        observed_at, pedestrian_count, vehicle_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            dataset_id,
                            index,
                            str(item.get("segment_id") or ""),
                            str(item.get("street") or "Unknown street"),
                            str(item.get("city") or "Unknown city"),
                            _parse_naive_datetime(item.get("observed_at")),
                            _as_float(item.get("pedestrian_count")),
                            _as_float(item.get("vehicle_count")),
                        )
                        for index, item in enumerate(observations, start=1)
                    ],
                )
                cursor.execute(
                    """
                    UPDATE real_world_datasets
                    SET status = 'ready',
                        observation_count = %s,
                        observation_start = %s,
                        observation_end = %s,
                        error_message = NULL,
                        ingested_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        len(observations),
                        min((item["observed_at"] for item in observations), default=None),
                        max((item["observed_at"] for item in observations), default=None),
                        dataset_id,
                    ),
                )
            connection.commit()

    def list_real_world_datasets(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id::text, original_filename, object_key,
                           checksum_sha256, size_bytes, etag, status,
                           observation_count, observation_start,
                           observation_end, error_message, created_at,
                           ingested_at, updated_at
                    FROM real_world_datasets
                    ORDER BY created_at DESC, original_filename
                    """
                )
                return [_real_world_dataset_payload(row) for row in cursor.fetchall()]

    def list_real_world_sources(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH ordered AS (
                        SELECT o.segment_id, o.street, o.city, o.observed_at,
                               d.original_filename,
                               LAG(o.observed_at) OVER (
                                   PARTITION BY o.segment_id ORDER BY o.observed_at
                               ) AS previous_at
                        FROM real_world_observations o
                        JOIN real_world_datasets d ON d.id = o.dataset_id
                        WHERE d.status = 'ready'
                    )
                    SELECT segment_id, MIN(street), MIN(city),
                           ARRAY_AGG(DISTINCT original_filename ORDER BY original_filename),
                           MIN(observed_at), MAX(observed_at), COUNT(*),
                           MIN(EXTRACT(EPOCH FROM observed_at - previous_at)) FILTER (
                               WHERE previous_at IS NOT NULL
                                 AND observed_at > previous_at
                                 AND observed_at - previous_at <= INTERVAL '1 hour'
                           )
                    FROM ordered
                    GROUP BY segment_id
                    ORDER BY MIN(street), segment_id
                    """
                )
                return [
                    {
                        "id": str(row[0]),
                        "segment_id": str(row[0]),
                        "name": f"{row[1]} · Sensor {row[0]}",
                        "street": str(row[1]),
                        "city": str(row[2]),
                        "files": list(row[3] or []),
                        "start_at": row[4].isoformat(timespec="minutes"),
                        "end_at": row[5].isoformat(timespec="minutes"),
                        "observation_count": int(row[6]),
                        "interval_seconds": int(row[7] or 900),
                    }
                    for row in cursor.fetchall()
                ]

    def read_real_world_observations(
        self,
        segment_id: str,
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT o.segment_id, o.street, o.city, o.observed_at,
                           o.pedestrian_count, o.vehicle_count
                    FROM real_world_observations o
                    JOIN real_world_datasets d ON d.id = o.dataset_id
                    WHERE d.status = 'ready' AND o.segment_id = %s
                    ORDER BY o.observed_at, o.dataset_id, o.row_number
                    """,
                    (segment_id,),
                )
                return [
                    {
                        "segment_id": str(row[0]),
                        "street": str(row[1]),
                        "city": str(row[2]),
                        "observed_at": row[3],
                        "pedestrian_count": float(row[4]),
                        "vehicle_count": float(row[5]),
                    }
                    for row in cursor.fetchall()
                ]


_database: DatabaseService | None = None


def configure_database(
    database_url: str | None,
    *,
    minimum_pool_size: int = 1,
    maximum_pool_size: int = 5,
    connect_timeout_seconds: int = 10,
) -> None:
    global _database
    if not database_url:
        _database = None
        return
    _database = DatabaseService(
        database_url,
        minimum_pool_size=minimum_pool_size,
        maximum_pool_size=maximum_pool_size,
        connect_timeout_seconds=connect_timeout_seconds,
    )


def initialize_database() -> None:
    if _database is not None:
        _database.initialize()


def close_database() -> None:
    if _database is not None:
        _database.close()


def database_status() -> str:
    if _database is None:
        return "disabled"
    try:
        return "ok" if _database.healthcheck() else "unavailable"
    except (PsycopgError, PoolTimeout):
        return "unavailable"


def persist_model(model: dict[str, Any], storage_path: str) -> bool:
    if _database is None:
        return False
    model_id = str(model.get("id") or "").strip()
    try:
        _database.upsert_model(model, storage_path)
        return True
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not synchronize model %s to PostgreSQL", model_id)
        return False


def read_model_metadata(model_id: str) -> dict[str, Any] | None:
    if _database is None:
        return None
    try:
        return _database.get_model(model_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read model %s from PostgreSQL", model_id)
        return None


def read_all_model_metadata() -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.list_models()
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not list models from PostgreSQL")
        return None


def remove_model(model_id: str) -> bool:
    if _database is None:
        return False
    try:
        _database.delete_model(model_id)
        return True
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not remove model %s from PostgreSQL", model_id)
        return False


def persist_simulation_run(
    record: dict[str, Any],
    model_storage_dir: Path,
) -> bool:
    if _database is None:
        return False
    model_id = str(record.get("model_id") or "")
    run_id = str(record.get("id") or "")
    storage_path = (Path(model_id) / "simulations" / run_id).as_posix()
    try:
        _database.upsert_simulation_run(record, storage_path)
        return True
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not synchronize simulation %s to PostgreSQL", run_id)
        return False


def read_simulation_runs(model_id: str) -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.list_simulation_runs(model_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read simulations for model %s from PostgreSQL", model_id)
        return None


def read_simulation_run_metadata(
    run_id: str,
    model_id: str | None = None,
) -> dict[str, Any] | None:
    if _database is None:
        return None
    try:
        return _database.get_simulation_run(run_id, model_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read simulation %s from PostgreSQL", run_id)
        return None


def read_all_simulation_runs() -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.list_all_simulation_runs()
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not list simulations from PostgreSQL")
        return None


def persist_flow_calibration(record: dict[str, Any]) -> bool:
    if _database is None:
        return False
    try:
        _database.upsert_flow_calibration(record)
        return True
    except (PsycopgError, PoolTimeout, ValueError):
        LOGGER.exception("Could not persist flow calibration %s", record.get("id"))
        return False


def read_flow_calibration(calibration_id: str) -> dict[str, Any] | None:
    if _database is None:
        return None
    try:
        return _database.get_flow_calibration(calibration_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read flow calibration %s", calibration_id)
        return None


def read_flow_calibrations(model_id: str) -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.list_flow_calibrations(model_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not list flow calibrations for model %s", model_id)
        return None


def request_simulation_cancel(run_id: str, model_id: str) -> dict[str, Any] | None:
    if _database is None:
        return None
    try:
        return _database.request_simulation_cancel(run_id, model_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not request cancellation for simulation %s", run_id)
        return None


def simulation_cancel_requested(run_id: str) -> bool:
    if _database is None:
        return False
    try:
        return _database.simulation_cancel_requested(run_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read cancellation state for simulation %s", run_id)
        return False


def remove_simulation_run(run_id: str) -> bool:
    if _database is None:
        return False
    try:
        _database.delete_simulation_run(run_id)
        return True
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not remove simulation %s from PostgreSQL", run_id)
        return False


def persist_run_artifacts(run_id: str, run_directory: Path) -> int:
    if _database is None:
        return 0
    try:
        return _database.upsert_artifacts(run_id, run_directory)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not synchronize artifacts for simulation %s", run_id)
        return 0


def persist_object_artifacts(run_id: str, artifacts: list[dict[str, Any]]) -> int:
    if _database is None:
        return 0
    try:
        return _database.upsert_object_artifacts(run_id, artifacts)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not index object artifacts for simulation %s", run_id)
        return 0


def read_artifact_paths() -> dict[str, set[str]] | None:
    if _database is None:
        return None
    try:
        return _database.list_artifact_paths()
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read the simulation artifact index")
        return None


def persist_real_world_dataset(dataset: dict[str, Any]) -> bool:
    if _database is None:
        return False
    try:
        _database.upsert_real_world_dataset(dataset)
        return True
    except (PsycopgError, PoolTimeout, ValueError):
        LOGGER.exception("Could not persist real-world dataset %s", dataset.get("id"))
        return False


def persist_real_world_observations(
    dataset: dict[str, Any],
    observations: list[dict[str, Any]],
) -> bool:
    if _database is None:
        return False
    try:
        _database.replace_real_world_observations(dataset, observations)
        return True
    except (PsycopgError, PoolTimeout, ValueError):
        LOGGER.exception("Could not persist observations for dataset %s", dataset.get("id"))
        return False


def read_real_world_datasets() -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.list_real_world_datasets()
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not list real-world datasets")
        return None


def read_real_world_source_metadata() -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.list_real_world_sources()
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not list real-world sensor sources")
        return None


def read_real_world_observations(segment_id: str) -> list[dict[str, Any]] | None:
    if _database is None:
        return None
    try:
        return _database.read_real_world_observations(segment_id)
    except (PsycopgError, PoolTimeout):
        LOGGER.exception("Could not read observations for sensor %s", segment_id)
        return None


def sync_existing_storage(model_storage_dir: Path) -> dict[str, int]:
    counts = {"models": 0, "runs": 0, "artifacts": 0}
    if _database is None:
        return counts

    for model_path in model_storage_dir.glob("*/model.json"):
        model = _read_json(model_path)
        if model is None:
            continue
        model_id = str(model.get("id") or "")
        if _database.get_model(model_id) is None:
            _database.upsert_model(
                model,
                model_path.parent.relative_to(model_storage_dir).as_posix(),
            )
        counts["models"] += 1

    for record_path in model_storage_dir.glob("*/simulations/*/run.json"):
        record = _read_json(record_path)
        if record is None:
            continue
        storage_path = record_path.parent.relative_to(model_storage_dir).as_posix()
        run_id = str(record.get("id") or "")
        if _database.get_simulation_run(run_id) is None:
            _database.upsert_simulation_run(record, storage_path)
        counts["runs"] += 1
        counts["artifacts"] += _database.upsert_artifacts(
            run_id,
            record_path.parent,
        )
    return counts


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_naive_datetime(value: Any) -> datetime | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=None)


def _parse_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _optional_string(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _run_payload(payload: Any, cancel_requested_at: datetime | None) -> dict[str, Any]:
    record = dict(payload)
    if cancel_requested_at is not None:
        record["stop_requested_at"] = cancel_requested_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )
    return record


def _real_world_dataset_payload(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "original_filename": str(row[1]),
        "object_key": str(row[2]),
        "checksum_sha256": str(row[3]),
        "size_bytes": int(row[4]),
        "etag": row[5],
        "status": str(row[6]),
        "observation_count": int(row[7]),
        "observation_start": row[8].isoformat(timespec="minutes") if row[8] else None,
        "observation_end": row[9].isoformat(timespec="minutes") if row[9] else None,
        "error_message": row[10],
        "created_at": row[11].isoformat() if row[11] else None,
        "ingested_at": row[12].isoformat() if row[12] else None,
        "updated_at": row[13].isoformat() if row[13] else None,
    }
