import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Form, Reminder, User
from app.schemas.reminder_schemas import ReminderCreate
from app.services.reminder_queue import publish_reminder
from db.database import SessionLocal, get_db


ACTIVE_REMINDER_STATUSES = {"pending", "skipped"}
REMINDER_SCHEDULER_INTERVAL_SECONDS = 60
logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_reminder(self, data: ReminderCreate, user: User) -> Reminder:
        if data.form_id is not None:
            await self._ensure_user_form(data.form_id, user)

        now = datetime.now(UTC)
        reminder = Reminder(
            user_id=user.id,
            form_id=data.form_id,
            title=data.title,
            payload=data.payload,
            status="pending",
            retry_delay_seconds=data.retry_delay_seconds,
            delivery_retry_delay_seconds=data.retry_delay_seconds,
            next_run_at=now + timedelta(seconds=data.due_in_seconds),
            skip_count=0,
            delivery_count=0,
            updated_at=now,
        )
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        await self.enqueue_reminder(reminder)
        return reminder

    async def get_current_reminders(self, user: User) -> list[Reminder]:
        result = await self.db.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user.id,
                Reminder.status.in_(ACTIVE_REMINDER_STATUSES),
                Reminder.next_run_at <= datetime.now(UTC),
            )
            .order_by(Reminder.next_run_at.asc(), Reminder.id.asc())
        )
        return list(result.scalars().all())

    async def create_due_form_reminders(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now(UTC)
        result = await self.db.execute(select(Form).where(Form.reminder_enabled.is_(True)))
        created: list[Reminder] = []
        for form in result.scalars().all():
            if not should_schedule_form_reminder(form, now):
                continue

            if await self._has_active_form_reminder(form.user_id, form.id):
                form.last_reminder_scheduled_at = now
                self.db.add(form)
                continue

            reminder = Reminder(
                user_id=form.user_id,
                form_id=form.id,
                title=form.reminder_title or form.title,
                payload=form.reminder_payload or {"form_id": form.id},
                status="pending",
                retry_delay_seconds=form.skip_retry_delay_seconds,
                delivery_retry_delay_seconds=form.delivery_retry_delay_seconds,
                next_run_at=now,
                skip_count=0,
                delivery_count=0,
                updated_at=now,
            )
            form.last_reminder_scheduled_at = now
            self.db.add(form)
            self.db.add(reminder)
            await self.db.commit()
            await self.db.refresh(reminder)
            await self.enqueue_reminder(reminder)
            created.append(reminder)

        await self.db.commit()
        return created

    async def requeue_stale_pending_reminders(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now(UTC)
        result = await self.db.execute(
            select(Reminder).where(
                Reminder.status == "pending",
                Reminder.last_delivered_at.is_not(None),
                Reminder.completed_at.is_(None),
            )
        )
        requeued: list[Reminder] = []
        for reminder in result.scalars().all():
            if reminder.last_delivered_at is None:
                continue

            if (
                reminder.last_delivered_at
                + timedelta(seconds=reminder.delivery_retry_delay_seconds)
                > now
            ):
                continue

            reminder.next_run_at = now
            reminder.updated_at = now
            self.db.add(reminder)
            await self.db.commit()
            await self.db.refresh(reminder)
            await self.enqueue_reminder(reminder)
            requeued.append(reminder)

        return requeued

    async def skip_reminder(
        self,
        reminder_id: int,
        user: User,
        retry_delay_seconds: int | None = None,
    ) -> Reminder:
        reminder = await self._get_user_reminder(reminder_id, user)
        if reminder.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reminder is already completed",
            )

        now = datetime.now(UTC)
        delay = retry_delay_seconds or reminder.retry_delay_seconds
        reminder.status = "skipped"
        reminder.retry_delay_seconds = delay
        reminder.next_run_at = now + timedelta(seconds=delay)
        reminder.skip_count += 1
        reminder.last_delivered_at = None
        reminder.updated_at = now
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        await self.enqueue_reminder(reminder)
        return reminder

    async def complete_reminder(self, reminder_id: int, user: User) -> Reminder:
        reminder = await self._get_user_reminder(reminder_id, user)
        now = datetime.now(UTC)
        reminder.status = "completed"
        reminder.completed_at = now
        reminder.updated_at = now
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        return reminder

    async def cancel_reminder(self, reminder_id: int, user: User) -> Reminder:
        reminder = await self._get_user_reminder(reminder_id, user)
        now = datetime.now(UTC)
        reminder.status = "cancelled"
        reminder.updated_at = now
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)
        return reminder

    async def enqueue_reminder(self, reminder: Reminder) -> None:
        delay_seconds = max(int((reminder.next_run_at - datetime.now(UTC)).total_seconds()), 0)
        await publish_reminder(reminder.id, delay_seconds)

    async def _get_user_reminder(self, reminder_id: int, user: User) -> Reminder:
        result = await self.db.execute(
            select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user.id)
        )
        reminder = result.scalar_one_or_none()
        if reminder is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
        return reminder

    async def _ensure_user_form(self, form_id: int, user: User) -> None:
        result = await self.db.execute(
            select(Form.id).where(Form.id == form_id, Form.user_id == user.id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    async def _has_active_form_reminder(self, user_id: int, form_id: int) -> bool:
        result = await self.db.execute(
            select(Reminder.id).where(
                Reminder.user_id == user_id,
                Reminder.form_id == form_id,
                Reminder.status.in_(ACTIVE_REMINDER_STATUSES),
            )
        )
        return result.scalar_one_or_none() is not None


def parse_schedule_interval_seconds(schedule: str) -> int | None:
    value = schedule.strip().lower()
    every_match = re.fullmatch(r"@every\s+(\d+)\s*([mhd])", value)
    if every_match:
        amount = int(every_match.group(1))
        unit = every_match.group(2)
        return amount * {"m": 60, "h": 3600, "d": 86400}[unit]

    cron_match = re.fullmatch(r"\*/(\d+)\s+\*\s+\*\s+\*\s+\*", value)
    if cron_match:
        return int(cron_match.group(1)) * 60

    return None


def next_schedule_interval_seconds(schedule_crons: list[str]) -> int | None:
    intervals = [
        interval
        for schedule in schedule_crons
        if (interval := parse_schedule_interval_seconds(schedule)) is not None
    ]
    if not intervals:
        return None
    return min(intervals)


def should_schedule_form_reminder(form: Form, now: datetime) -> bool:
    interval = next_schedule_interval_seconds(form.schedule_crons or [])
    if interval is None:
        return False

    last_scheduled_at = form.last_reminder_scheduled_at
    if last_scheduled_at is None:
        return True
    if last_scheduled_at.tzinfo is None:
        last_scheduled_at = last_scheduled_at.replace(tzinfo=UTC)
    return last_scheduled_at + timedelta(seconds=interval) <= now


async def run_reminder_scheduler() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                service = ReminderService(db)
                await service.create_due_form_reminders()
                await service.requeue_stale_pending_reminders()
        except Exception:
            logger.exception("Reminder scheduler failed")

        await asyncio.sleep(REMINDER_SCHEDULER_INTERVAL_SECONDS)
