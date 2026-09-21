"""RabbitMQ publishing and consuming primitives shared by services."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pika
from pika.exceptions import AMQPError


LOGGER = logging.getLogger(__name__)


class MessageBrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerMessage:
    body: dict[str, Any]
    message_id: str
    redelivered: bool


def _parameters(rabbitmq_url: str) -> pika.URLParameters:
    parameters = pika.URLParameters(rabbitmq_url)
    parameters.heartbeat = 60
    parameters.blocked_connection_timeout = 30
    parameters.connection_attempts = 5
    parameters.retry_delay = 2
    return parameters


def _declare_queue(channel, queue_name: str) -> None:
    dead_letter_queue = f"{queue_name}.dead"
    channel.queue_declare(queue=dead_letter_queue, durable=True)
    channel.queue_declare(
        queue=queue_name,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": dead_letter_queue,
        },
    )


def publish_message(
    rabbitmq_url: str,
    queue_name: str,
    payload: dict[str, Any],
) -> str:
    message_id = str(uuid.uuid4())
    envelope = {
        "version": 1,
        "message_id": message_id,
        "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **payload,
    }
    try:
        connection = pika.BlockingConnection(_parameters(rabbitmq_url))
        try:
            channel = connection.channel()
            _declare_queue(channel, queue_name)
            channel.confirm_delivery()
            published = channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=pika.DeliveryMode.Persistent,
                    message_id=message_id,
                    timestamp=int(datetime.now(timezone.utc).timestamp()),
                ),
                mandatory=True,
            )
            if published is False:
                raise MessageBrokerError("RabbitMQ did not confirm the message.")
        finally:
            if connection.is_open:
                connection.close()
    except (AMQPError, OSError, ValueError) as exc:
        raise MessageBrokerError(f"Could not publish to RabbitMQ: {exc}") from exc
    return message_id


def broker_status(rabbitmq_url: str | None) -> str:
    if not rabbitmq_url:
        return "disabled"
    try:
        connection = pika.BlockingConnection(_parameters(rabbitmq_url))
        connection.close()
    except (AMQPError, OSError, ValueError):
        return "unavailable"
    return "ok"


def open_consumer(rabbitmq_url: str, queue_name: str):
    try:
        connection = pika.BlockingConnection(_parameters(rabbitmq_url))
        channel = connection.channel()
        _declare_queue(channel, queue_name)
        channel.basic_qos(prefetch_count=1)
        return connection, channel
    except (AMQPError, OSError, ValueError) as exc:
        raise MessageBrokerError(f"Could not connect to RabbitMQ: {exc}") from exc


def decode_delivery(method, properties, body: bytes) -> BrokerMessage:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MessageBrokerError("Queue message is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise MessageBrokerError("Queue message must contain a JSON object.")
    message_id = str(
        getattr(properties, "message_id", None)
        or payload.get("message_id")
        or ""
    )
    return BrokerMessage(
        body=payload,
        message_id=message_id,
        redelivered=bool(getattr(method, "redelivered", False)),
    )
