"""Analytics worker service entry point."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from domain.analytics.service import (
    ANALYTICS_SNAPSHOT_FILENAME,
    AnalyticsError,
    analytics_run_directory,
    generate_analytics_snapshot,
)
from domain.calibration.service import advance_flow_calibration
from domain.simulations.service import read_simulation_run
from shared.config import get_settings
from shared.database import (
    close_database,
    configure_database,
    initialize_database,
    persist_object_artifacts,
    persist_run_artifacts,
)
from shared.message_broker import BrokerMessage
from shared.object_storage import (
    configure_object_storage,
    get_object_storage,
    initialize_object_storage,
    run_object_path,
)
from shared.worker_runtime import healthcheck, run_worker


LOGGER = logging.getLogger(__name__)
HEALTH_PATH = Path("/tmp/campus-sumo-analytics-worker.health")


def _handler(message: BrokerMessage) -> None:
    settings = get_settings()
    if message.body.get("type") != "simulation.run.finished":
        raise ValueError("Unsupported analytics message type.")
    run_id = str(message.body.get("run_id") or "")
    if not run_id:
        raise ValueError("Analytics message is missing run_id.")
    model_id = str(message.body.get("model_id") or "")
    if not model_id:
        raise ValueError("Analytics message is missing model_id.")
    storage = get_object_storage()
    if storage is not None:
        storage.download_prefix(
            run_object_path(model_id, run_id),
            settings.model_storage_dir / model_id / "simulations" / run_id,
        )
    analytics = None
    try:
        analytics = generate_analytics_snapshot(settings.model_storage_dir, run_id)
    except AnalyticsError:
        # A preparation failure may have logs but no metric outputs. It is a
        # valid terminal run, so index its artifacts without retrying forever.
        LOGGER.info("Run %s has no analytics payload to cache", run_id)
    record = read_simulation_run(settings.model_storage_dir, model_id, run_id)
    if record is not None and record.get("calibration"):
        advance_flow_calibration(
            settings.model_storage_dir,
            record,
            analytics,
            rabbitmq_url=settings.rabbitmq_url or "",
            simulation_queue_name=settings.simulation_queue_name,
        )
        if analytics is not None:
            snapshot_path = (
                analytics_run_directory(settings.model_storage_dir, run_id)
                / ANALYTICS_SNAPSHOT_FILENAME
            )
            snapshot_path.write_text(
                json.dumps(analytics, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
    persist_run_artifacts(
        run_id,
        analytics_run_directory(settings.model_storage_dir, run_id),
    )
    if storage is not None:
        run_dir = analytics_run_directory(settings.model_storage_dir, run_id)
        uploaded = storage.upload_tree(run_dir, run_object_path(model_id, run_id))
        persist_object_artifacts(run_id, [item.__dict__ for item in uploaded])
        shutil.rmtree(run_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Consume analytics generation jobs.")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return 0 if healthcheck(HEALTH_PATH) else 1

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.rabbitmq_url:
        raise SystemExit("RABBITMQ_URL is required for the analytics worker.")
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
            queue_name=settings.analytics_queue_name,
            health_path=HEALTH_PATH,
            handler=_handler,
        )
    finally:
        close_database()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
