"""SUMO simulation worker service entry point."""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from domain.simulations.service import (
    claim_simulation_run,
    execute_simulation_run,
    mark_simulation_queue_failure,
    read_simulation_run,
)
from shared.config import get_settings
from shared.database import (
    close_database,
    configure_database,
    initialize_database,
    persist_object_artifacts,
)
from shared.message_broker import BrokerMessage, publish_message
from shared.object_storage import (
    configure_object_storage,
    get_object_storage,
    initialize_object_storage,
    model_object_path,
    run_object_path,
)
from shared.worker_runtime import healthcheck, run_worker, worker_identity


LOGGER = logging.getLogger(__name__)
HEALTH_PATH = Path("/tmp/campus-sumo-simulation-worker.health")


def _handler(message: BrokerMessage) -> None:
    settings = get_settings()
    if message.body.get("type") != "simulation.run.requested":
        raise ValueError("Unsupported simulation message type.")
    model_id = str(message.body.get("model_id") or "")
    run_id = str(message.body.get("run_id") or "")
    if not model_id or not run_id:
        raise ValueError("Simulation message is missing model_id or run_id.")

    storage = get_object_storage()
    if storage is not None:
        model_dir = settings.model_storage_dir / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        storage.download_file(
            model_object_path(model_id, "model.json"),
            model_dir / "model.json",
        )
        storage.download_file(
            model_object_path(model_id, "source.osm.xml"),
            model_dir / "source.osm.xml",
        )
        storage.download_prefix(
            run_object_path(model_id, run_id),
            model_dir / "simulations" / run_id,
        )

    claimed = claim_simulation_run(
        settings.model_storage_dir,
        model_id,
        run_id,
        worker_identity("simulation-worker"),
    )
    if claimed is not None:
        try:
            execute_simulation_run(settings.model_storage_dir, model_id, run_id)
        finally:
            if storage is not None:
                run_dir = settings.model_storage_dir / model_id / "simulations" / run_id
                uploaded = storage.upload_tree(
                    run_dir,
                    run_object_path(model_id, run_id),
                )
                persist_object_artifacts(
                    run_id,
                    [item.__dict__ for item in uploaded],
                )

    record = read_simulation_run(settings.model_storage_dir, model_id, run_id)
    if record is None or record.get("status") not in {"completed", "failed"}:
        raise RuntimeError("Simulation worker did not produce a terminal run record.")
    publish_message(
        settings.rabbitmq_url or "",
        settings.analytics_queue_name,
        {
            "type": "simulation.run.finished",
            "model_id": model_id,
            "run_id": run_id,
            "status": record["status"],
        },
    )
    if storage is not None:
        run_dir = settings.model_storage_dir / model_id / "simulations" / run_id
        if run_dir.is_dir():
            shutil.rmtree(run_dir)


def _terminal_failure(message: BrokerMessage, _error: Exception) -> None:
    model_id = str(message.body.get("model_id") or "")
    run_id = str(message.body.get("run_id") or "")
    if not model_id or not run_id:
        return
    settings = get_settings()
    mark_simulation_queue_failure(
        settings.model_storage_dir,
        model_id,
        run_id,
        "Simulation job could not be processed after retry. Check the worker logs.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Consume SUMO simulation jobs.")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return 0 if healthcheck(HEALTH_PATH) else 1

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.rabbitmq_url:
        raise SystemExit("RABBITMQ_URL is required for the simulation worker.")
    configure_database(
        settings.database_url,
        minimum_pool_size=settings.database_pool_min_size,
        maximum_pool_size=settings.database_pool_max_size,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    initialize_database()
    configure_object_storage(
        settings.object_storage_endpoint,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.object_storage_bucket,
        secure=settings.object_storage_secure,
        prefix=settings.object_storage_prefix,
    )
    initialize_object_storage()
    try:
        run_worker(
            rabbitmq_url=settings.rabbitmq_url,
            queue_name=settings.simulation_queue_name,
            health_path=HEALTH_PATH,
            handler=_handler,
            terminal_failure_handler=_terminal_failure,
        )
    finally:
        close_database()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
