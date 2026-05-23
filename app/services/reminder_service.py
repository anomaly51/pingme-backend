import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
            await self._ensure_user_active_form(data.form_id, user)

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
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Active reminder for this form already exists",
            ) from exc
        await self.db.refresh(reminder)
        await self.enqueue_reminder(reminder)
        return reminder

    async def get_current_reminders(self, user: User) -> list[Reminder]:
        return await self.list_reminders(
            user,
            statuses=ACTIVE_REMINDER_STATUSES,
            due_only=True,
            limit=100,
            offset=0,
        )

    async def list_reminders(
        self,
        user: User,
        statuses: set[str] | None = None,
        form_id: int | None = None,
        due_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Reminder]:
        query = select(Reminder).where(Reminder.user_id == user.id)
        if statuses:
            query = query.where(Reminder.status.in_(statuses))
        if form_id is not None:
            await self._ensure_user_form(form_id, user)
            query = query.where(Reminder.form_id == form_id)
        if due_only:
            query = query.where(Reminder.next_run_at <= datetime.now(UTC))
        query = (
            query.order_by(Reminder.next_run_at.asc(), Reminder.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_due_form_reminders(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now(UTC)
        result = await self.db.execute(
            select(Form, User)
            .join(User, User.id == Form.user_id)
            .where(
                Form.reminder_enabled.is_(True),
                Form.is_active.is_(True),
                Form.archived_at.is_(None),
            )
        )
        created: list[Reminder] = []
        for form, user in result.all():
            if not should_schedule_form_reminder(form, now, user.timezone):
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
            try:
                await self.db.commit()
            except IntegrityError:
                await self.db.rollback()
                continue
            await self.db.refresh(reminder)
            await self.enqueue_reminder(reminder)
            created.append(reminder)

        await self.db.commit()
        return created

    async def requeue_stale_pending_reminders(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now(UTC)
        result = await self.db.execute(
            select(Reminder)
            .outerjoin(Form, Form.id == Reminder.form_id)
            .where(
                Reminder.status == "pending",
                Reminder.last_delivered_at.is_not(None),
                Reminder.completed_at.is_(None),
                (Reminder.form_id.is_(None))
                | (
                    Form.reminder_enabled.is_(True)
                    & Form.is_active.is_(True)
                    & Form.archived_at.is_(None)
                ),
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
        next_run_at = ensure_aware_utc(reminder.next_run_at)
        delay_seconds = max(int((next_run_at - datetime.now(UTC)).total_seconds()), 0)
        try:
            publish_result = await publish_reminder(reminder.id, delay_seconds)
        except Exception as exc:
            reminder.enqueue_status = "failed"
            reminder.last_enqueue_error = str(exc)[:1000]
        else:
            if publish_result is False:
                reminder.enqueue_status = "failed"
                reminder.last_enqueue_error = "RabbitMQ publish failed"
            else:
                reminder.enqueue_status = "queued"
                reminder.last_enqueue_error = None
                reminder.enqueued_at = datetime.now(UTC)
        self.db.add(reminder)
        await self.db.commit()
        await self.db.refresh(reminder)

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

    async def _ensure_user_active_form(self, form_id: int, user: User) -> None:
        result = await self.db.execute(
            select(Form.id).where(
                Form.id == form_id,
                Form.user_id == user.id,
                Form.is_active.is_(True),
                Form.archived_at.is_(None),
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active form not found",
            )

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


def should_schedule_form_reminder(form: Form, now: datetime, timezone_name: str = "UTC") -> bool:
    now = ensure_aware_utc(now)
    if any(
        is_time_schedule_due(schedule, form.last_reminder_scheduled_at, now, timezone_name)
        for schedule in form.schedule_crons or []
    ):
        return True

    interval = next_schedule_interval_seconds(form.schedule_crons or [])
    if interval is None:
        return False

    last_scheduled_at = form.last_reminder_scheduled_at
    if last_scheduled_at is None:
        return True
    last_scheduled_at = ensure_aware_utc(last_scheduled_at)
    return last_scheduled_at + timedelta(seconds=interval) <= now


def is_time_schedule_due(
    schedule: str,
    last_scheduled_at: datetime | None,
    now: datetime,
    timezone_name: str,
) -> bool:
    parsed = parse_time_schedule(schedule)
    if parsed is None:
        return False
    now = ensure_aware_utc(now)

    weekdays, hour, minute = parsed
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")

    now_local = ensure_aware_utc(now).astimezone(timezone)
    if last_scheduled_at is None:
        search_start = now_local.date()
    else:
        search_start = ensure_aware_utc(last_scheduled_at).astimezone(timezone).date()

    days_to_check = (now_local.date() - search_start).days + 1
    days_to_check = max(1, min(days_to_check, 370))
    last_utc = ensure_aware_utc(last_scheduled_at) if last_scheduled_at else None
    for day_offset in range(days_to_check):
        local_day = search_start + timedelta(days=day_offset)
        if weekdays is not None and local_day.weekday() not in weekdays:
            continue
        due_local = datetime.combine(local_day, datetime.min.time(), tzinfo=timezone).replace(
            hour=hour,
            minute=minute,
        )
        due_utc = due_local.astimezone(UTC)
        if due_utc <= ensure_aware_utc(now) and (last_utc is None or due_utc > last_utc):
            return True
    return False


def parse_time_schedule(schedule: str) -> tuple[set[int] | None, int, int] | None:
    value = schedule.strip().lower()
    value = re.sub(r"^@(daily|time)\s+", "", value)
    value = re.sub(r"^daily\s+", "", value)

    weekday_aliases = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tuesday": 1,
        "wed": 2,
        "wednesday": 2,
        "thu": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "sat": 5,
        "saturday": 5,
        "sun": 6,
        "sunday": 6,
    }
    match = re.fullmatch(r"(?:(weekdays|weekends|[a-z,\s]+)\s+)?(\d{1,2}):(\d{2})", value)
    if match is None:
        return None

    day_part, hour_raw, minute_raw = match.groups()
    hour = int(hour_raw)
    minute = int(minute_raw)
    if hour > 23 or minute > 59:
        return None

    weekdays: set[int] | None = None
    if day_part:
        day_part = day_part.strip()
        if day_part == "weekdays":
            weekdays = {0, 1, 2, 3, 4}
        elif day_part == "weekends":
            weekdays = {5, 6}
        else:
            weekdays = set()
            for token in re.split(r"[\s,]+", day_part):
                if not token:
                    continue
                if token not in weekday_aliases:
                    return None
                weekdays.add(weekday_aliases[token])

    return weekdays, hour, minute


def ensure_aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
