"""Durable RabbitMQ consumer runtime shared by worker services."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from pika.exceptions import AMQPError

from shared.message_broker import (
    BrokerMessage,
    MessageBrokerError,
    decode_delivery,
    open_consumer,
)


LOGGER = logging.getLogger(__name__)
HEALTH_MAX_AGE_SECONDS = 30


def healthcheck(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime <= HEALTH_MAX_AGE_SECONDS
    except OSError:
        return False


def _touch_health(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def run_worker(
    *,
    rabbitmq_url: str,
    queue_name: str,
    health_path: Path,
    handler: Callable[[BrokerMessage], None],
    terminal_failure_handler: Callable[[BrokerMessage, Exception], None] | None = None,
) -> None:
    """Consume one long-running job at a time while servicing AMQP heartbeats."""
    shutdown = threading.Event()

    def request_shutdown(_signal_number, _frame) -> None:
        shutdown.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=queue_name) as executor:
        while not shutdown.is_set():
            connection = None
            try:
                connection, channel = open_consumer(rabbitmq_url, queue_name)
                LOGGER.info("Consuming durable queue %s", queue_name)
                _touch_health(health_path)
                while not shutdown.is_set():
                    method, properties, body = channel.basic_get(
                        queue=queue_name,
                        auto_ack=False,
                    )
                    if method is None:
                        connection.process_data_events(time_limit=1)
                        _touch_health(health_path)
                        continue
                    try:
                        message = decode_delivery(method, properties, body)
                    except MessageBrokerError:
                        LOGGER.exception("Rejecting invalid message from %s", queue_name)
                        channel.basic_reject(method.delivery_tag, requeue=False)
                        continue

                    future: Future[None] = executor.submit(handler, message)
                    # Keep the delivery owned until the handler finishes. On a
                    # container shutdown Docker/Kubernetes may later kill this
                    # process; only then does RabbitMQ requeue the unacknowledged
                    # delivery. Closing early could let a second worker start the
                    # same SUMO run while this handler was still active.
                    while not future.done():
                        connection.process_data_events(time_limit=1)
                        _touch_health(health_path)
                    try:
                        future.result()
                    except Exception as exc:
                        LOGGER.exception("Job %s failed", message.message_id or "<unknown>")
                        if message.redelivered:
                            if terminal_failure_handler is not None:
                                try:
                                    terminal_failure_handler(message, exc)
                                except Exception:
                                    LOGGER.exception(
                                        "Could not persist terminal failure for job %s",
                                        message.message_id or "<unknown>",
                                    )
                            channel.basic_reject(method.delivery_tag, requeue=False)
                        else:
                            channel.basic_nack(method.delivery_tag, requeue=True)
                    else:
                        channel.basic_ack(method.delivery_tag)
                    _touch_health(health_path)
            except (AMQPError, MessageBrokerError, OSError):
                LOGGER.exception("Worker lost its RabbitMQ connection")
                shutdown.wait(5)
            finally:
                if connection is not None and connection.is_open:
                    connection.close()
        try:
            health_path.unlink(missing_ok=True)
        except OSError:
            pass


def worker_identity(prefix: str) -> str:
    return f"{prefix}:{os.environ.get('HOSTNAME') or 'local'}:{os.getpid()}"
