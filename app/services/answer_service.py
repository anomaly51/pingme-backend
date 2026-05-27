from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Answer, Form, Reminder, User
from app.schemas.form_schemas import (
    AnswerCreate,
    AnswerStatsResponse,
)
from app.services.reminder_service import ACTIVE_REMINDER_STATUSES
from db.database import get_db


class AnswerService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_answer(self, form_id: int, answer_data: AnswerCreate, user: User) -> dict:
        form_query = select(Form).where(Form.id == form_id, Form.user_id == user.id)
        form_result = await self.db.execute(form_query)
        form = form_result.scalar_one_or_none()

        if not form:
            raise HTTPException(status_code=404, detail="Specified form not found")

        new_answer = Answer(
            form_id=form_id,
            user_id=user.id,
            answers_data=answer_data.answers_data,
        )

        self.db.add(new_answer)
        await self.db.commit()
        await self.db.refresh(new_answer)

        completed_reminder_ids = await self.complete_active_form_reminders(form_id, user)

        return {
            "answer_id": new_answer.id,
            "completed_reminder_ids": completed_reminder_ids,
        }

    async def complete_active_form_reminders(self, form_id: int, user: User) -> list[int]:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(Reminder).where(
                Reminder.form_id == form_id,
                Reminder.user_id == user.id,
                Reminder.status.in_(ACTIVE_REMINDER_STATUSES),
            )
        )
        reminders = list(result.scalars().all())
        for reminder in reminders:
            reminder.status = "completed"
            reminder.completed_at = now
            reminder.next_run_at = now
            reminder.updated_at = now
            self.db.add(reminder)

        if reminders:
            await self.db.commit()

        return [reminder.id for reminder in reminders]

    async def get_form_answers(
        self,
        form_id: int,
        user: User,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Answer]:
        form_query = select(Form.id).where(Form.id == form_id, Form.user_id == user.id)
        form_result = await self.db.execute(form_query)

        if not form_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Specified form not found")

        answers_query = (
            select(Answer)
            .where(Answer.form_id == form_id, Answer.user_id == user.id)
            .order_by(Answer.created_at.desc(), Answer.id.desc())
        )
        if created_from is not None:
            answers_query = answers_query.where(Answer.created_at >= created_from)
        if created_to is not None:
            answers_query = answers_query.where(Answer.created_at <= created_to)
        answers_query = answers_query.limit(limit).offset(offset)
        answers_result = await self.db.execute(answers_query)
        return list(answers_result.scalars().all())

    async def get_form_answer_stats(self, form_id: int, user: User) -> AnswerStatsResponse:
        form_query = select(Form.id).where(Form.id == form_id, Form.user_id == user.id)
        form_result = await self.db.execute(form_query)
        if not form_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Specified form not found")

        count_result = await self.db.execute(
            select(
                func.count(Answer.id),
                func.min(Answer.created_at),
                func.max(Answer.created_at),
            ).where(Answer.form_id == form_id, Answer.user_id == user.id)
        )
        total_answers, first_answer_at, last_answer_at = count_result.one()

        answers_result = await self.db.execute(
            select(Answer.answers_data).where(Answer.form_id == form_id, Answer.user_id == user.id)
        )
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for answers_data in answers_result.scalars().all():
            for key, value in answers_data.items():
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                totals[key] = totals.get(key, 0.0) + float(value)
                counts[key] = counts.get(key, 0) + 1

        numeric_averages = {
            key: round(total / counts[key], 4) for key, total in totals.items() if counts[key]
        }
        return AnswerStatsResponse(
            form_id=form_id,
            total_answers=total_answers,
            first_answer_at=first_answer_at,
            last_answer_at=last_answer_at,
            numeric_averages=numeric_averages,
            completion_rate=None,
        )
