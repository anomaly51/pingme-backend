import json
import logging
import os
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message


logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
READY_EXCHANGE = os.getenv("REMINDER_READY_EXCHANGE", "reminders.ready")
READY_QUEUE = os.getenv("REMINDER_READY_QUEUE", "reminders.ready")
READY_ROUTING_KEY = os.getenv("REMINDER_READY_ROUTING_KEY", "reminder.due")
DELAY_QUEUE = os.getenv("REMINDER_DELAY_QUEUE", "reminders.delay")


async def _connect() -> aio_pika.abc.AbstractRobustConnection:
    return await aio_pika.connect_robust(RABBITMQ_URL)


async def setup_reminder_queues(channel: aio_pika.abc.AbstractChannel) -> None:
    ready_exchange = await channel.declare_exchange(
        READY_EXCHANGE,
        ExchangeType.DIRECT,
        durable=True,
    )
    ready_queue = await channel.declare_queue(READY_QUEUE, durable=True)
    await ready_queue.bind(ready_exchange, routing_key=READY_ROUTING_KEY)
    await channel.declare_queue(
        DELAY_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": READY_EXCHANGE,
            "x-dead-letter-routing-key": READY_ROUTING_KEY,
        },
    )


async def publish_reminder(reminder_id: int, delay_seconds: int = 0) -> bool:
    try:
        connection = await _connect()
        async with connection:
            channel = await connection.channel()
            await setup_reminder_queues(channel)
            payload: dict[str, Any] = {"reminder_id": reminder_id}
            message = Message(
                json.dumps(payload).encode("utf-8"),
                delivery_mode=DeliveryMode.PERSISTENT,
                expiration=max(delay_seconds, 0) * 1000 if delay_seconds > 0 else None,
            )

            if delay_seconds > 0:
                await channel.default_exchange.publish(message, routing_key=DELAY_QUEUE)
            else:
                exchange = await channel.get_exchange(READY_EXCHANGE)
                await exchange.publish(message, routing_key=READY_ROUTING_KEY)
        return True
    except Exception:
        logger.exception("Could not publish reminder %s", reminder_id)
        return False
