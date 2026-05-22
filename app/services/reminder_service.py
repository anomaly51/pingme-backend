from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Form, Reminder, User
from app.schemas.reminder_schemas import ReminderCreate
from app.services.reminder_queue import publish_reminder
from db.database import get_db


ACTIVE_REMINDER_STATUSES = {"pending", "skipped"}


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
            next_run_at=now + timedelta(seconds=data.due_in_seconds),
            skip_count=0,
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
