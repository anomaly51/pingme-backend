import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from aio_pika import IncomingMessage
from sqlalchemy import select

from app.models.user_model import Reminder
from app.services.reminder_queue import (
    READY_QUEUE,
    _connect,
    publish_reminder,
    setup_reminder_queues,
)
from app.sockets import sio
from db.database import SessionLocal


logger = logging.getLogger(__name__)


async def handle_reminder_message(message: IncomingMessage) -> None:
    async with message.process():
        payload = json.loads(message.body.decode("utf-8"))
        reminder_id = int(payload["reminder_id"])

        async with SessionLocal() as db:
            result = await db.execute(select(Reminder).where(Reminder.id == reminder_id))
            reminder = result.scalar_one_or_none()
            if reminder is None or reminder.status not in {"pending", "skipped"}:
                return

            now = datetime.now(UTC)
            if reminder.next_run_at > now:
                delay = int((reminder.next_run_at - now).total_seconds())
                await publish_reminder(reminder.id, max(delay, 1))
                return

            reminder.status = "pending"
            reminder.delivery_count += 1
            reminder.last_delivered_at = now
            reminder.next_run_at = now + timedelta(seconds=reminder.delivery_retry_delay_seconds)
            reminder.updated_at = now
            db.add(reminder)
            await db.commit()
            await db.refresh(reminder)

        await sio.emit(
            "reminder.due",
            {
                "id": reminder.id,
                "form_id": reminder.form_id,
                "title": reminder.title,
                "payload": reminder.payload,
                "retry_delay_seconds": reminder.retry_delay_seconds,
                "skip_count": reminder.skip_count,
            },
            room=f"user_{reminder.user_id}",
        )

        await publish_reminder(reminder.id, reminder.delivery_retry_delay_seconds)


async def run_reminder_worker() -> None:
    while True:
        try:
            connection = await _connect()
            async with connection:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=10)
                await setup_reminder_queues(channel)
                queue = await channel.get_queue(READY_QUEUE)
                await queue.consume(handle_reminder_message)
                await asyncio.Future()
        except Exception:
            logger.exception("Reminder worker crashed, reconnecting")
            await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_reminder_worker())


if __name__ == "__main__":
    main()
