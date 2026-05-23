import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select

from app.models.user_model import Reminder, User
from app.services.email_service import send_push_notification, send_reminder_notification
from app.services.reminder_queue import (
    READY_QUEUE,
    _connect,
    publish_reminder,
    setup_reminder_queues,
)
from app.services.reminder_service import ensure_aware_utc
from app.sockets import sio
from db.database import SessionLocal


logger = logging.getLogger(__name__)


async def handle_reminder_message(message: AbstractIncomingMessage) -> None:
    async with message.process():
        payload = json.loads(message.body.decode("utf-8"))
        reminder_id = int(payload["reminder_id"])

        async with SessionLocal() as db:
            result = await db.execute(
                select(Reminder, User)
                .join(User, User.id == Reminder.user_id)
                .where(Reminder.id == reminder_id)
            )
            row = result.one_or_none()
            if row is None:
                return
            reminder, user = row
            if reminder is None or reminder.status not in {"pending", "skipped"}:
                return

            now = datetime.now(UTC)
            next_run_at = ensure_aware_utc(reminder.next_run_at)
            if next_run_at > now:
                delay = int((next_run_at - now).total_seconds())
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

        reminder_payload = {
            "id": reminder.id,
            "form_id": reminder.form_id,
            "title": reminder.title,
            "payload": reminder.payload,
            "retry_delay_seconds": reminder.retry_delay_seconds,
            "delivery_retry_delay_seconds": reminder.delivery_retry_delay_seconds,
            "skip_count": reminder.skip_count,
            "delivery_count": reminder.delivery_count,
            "next_run_at": ensure_aware_utc(reminder.next_run_at).isoformat(),
        }
        preferences = user.notification_preferences or {}
        if preferences.get("realtime", True):
            await sio.emit("reminder.due", reminder_payload, room=f"user_{reminder.user_id}")

        if preferences.get("email", False):
            try:
                await asyncio.to_thread(send_reminder_notification, user.email, reminder.title)
            except Exception:
                logger.exception("Could not send reminder email %s", reminder.id)

        if preferences.get("push", False) and user.push_token:
            try:
                await asyncio.to_thread(
                    send_push_notification,
                    user.push_token,
                    reminder.title,
                    reminder_payload,
                )
            except Exception:
                logger.exception("Could not send reminder push %s", reminder.id)

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
