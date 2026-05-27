from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import (
    Answer,
    AnswerSubmission,
    Form,
    FormGroup,
    FormGroupItem,
    Reminder,
    User,
)
from app.schemas.form_group_schemas import (
    FormGroupAnswerCreate,
    FormGroupCreate,
    FormGroupResponse,
    FormGroupUpdate,
)
from app.services.form_service import form_to_response
from app.services.reminder_service import ACTIVE_REMINDER_STATUSES
from db.database import get_db


class FormGroupService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_group(self, data: FormGroupCreate, user: User) -> tuple[FormGroup, list[Form]]:
        forms = await self._get_user_forms(data.form_ids, user)
        now = datetime.now(UTC)
        group = FormGroup(
            user_id=user.id,
            title=data.title,
            description=data.description,
            schedule_crons=data.schedule_crons,
            is_active=data.is_active,
            reminder_enabled=data.reminder_enabled,
            reminder_title=data.reminder_title,
            reminder_payload=data.reminder_payload,
            skip_retry_delay_seconds=data.skip_retry_delay_seconds,
            delivery_retry_delay_seconds=data.delivery_retry_delay_seconds,
            updated_at=now,
        )
        self.db.add(group)
        await self.db.flush()
        self._add_group_items(group.id, data.form_ids)
        await self.db.commit()
        await self.db.refresh(group)
        return group, forms

    async def list_groups(
        self, user: User, include_archived: bool = False
    ) -> list[tuple[FormGroup, list[Form]]]:
        query = select(FormGroup).where(FormGroup.user_id == user.id)
        if not include_archived:
            query = query.where(FormGroup.archived_at.is_(None))
        query = query.order_by(FormGroup.id.desc())
        result = await self.db.execute(query)
        groups = list(result.scalars().all())
        return [(group, await self._get_group_forms(group.id)) for group in groups]

    async def get_group(self, group_id: int, user: User) -> tuple[FormGroup, list[Form]]:
        group = await self._get_user_group(group_id, user)
        forms = await self._get_group_forms(group.id)
        return group, forms

    async def update_group(
        self, group_id: int, data: FormGroupUpdate, user: User
    ) -> tuple[FormGroup, list[Form]]:
        group = await self._get_user_group(group_id, user)
        forms = await self._get_user_forms(data.form_ids, user)
        group.title = data.title
        group.description = data.description
        group.schedule_crons = data.schedule_crons
        group.is_active = data.is_active
        group.reminder_enabled = data.reminder_enabled
        group.reminder_title = data.reminder_title
        group.reminder_payload = data.reminder_payload
        group.skip_retry_delay_seconds = data.skip_retry_delay_seconds
        group.delivery_retry_delay_seconds = data.delivery_retry_delay_seconds
        group.updated_at = datetime.now(UTC)

        await self.db.execute(delete(FormGroupItem).where(FormGroupItem.group_id == group.id))
        self._add_group_items(group.id, data.form_ids)
        await self.db.commit()
        await self.db.refresh(group)
        return group, forms

    async def archive_group(self, group_id: int, user: User) -> tuple[FormGroup, list[Form]]:
        group = await self._get_user_group(group_id, user)
        now = datetime.now(UTC)
        group.is_active = False
        group.archived_at = now
        group.updated_at = now
        await self.db.commit()
        await self.db.refresh(group)
        return group, await self._get_group_forms(group.id)

    async def restore_group(self, group_id: int, user: User) -> tuple[FormGroup, list[Form]]:
        group = await self._get_user_group(group_id, user)
        group.is_active = True
        group.archived_at = None
        group.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(group)
        return group, await self._get_group_forms(group.id)

    async def save_group_answers(
        self, group_id: int, data: FormGroupAnswerCreate, user: User
    ) -> dict:
        group = await self._get_user_group(group_id, user)
        group_form_ids = [form.id for form in await self._get_group_forms(group.id)]
        allowed_form_ids = set(group_form_ids)
        submitted_form_ids = [answer.form_id for answer in data.answers]

        if len(submitted_form_ids) != len(set(submitted_form_ids)):
            raise HTTPException(
                status_code=422,
                detail="Each form can be answered only once per group submission",
            )
        unknown_form_ids = sorted(set(submitted_form_ids) - allowed_form_ids)
        if unknown_form_ids:
            detail = f"Forms do not belong to this group: {', '.join(map(str, unknown_form_ids))}"
            raise HTTPException(
                status_code=422,
                detail=detail,
            )

        submission = AnswerSubmission(user_id=user.id, form_group_id=group.id)
        self.db.add(submission)
        await self.db.flush()

        answers: list[Answer] = []
        for answer_data in data.answers:
            answer = Answer(
                form_id=answer_data.form_id,
                user_id=user.id,
                submission_id=submission.id,
                answers_data=answer_data.answers_data,
            )
            self.db.add(answer)
            answers.append(answer)

        await self.db.commit()
        for answer in answers:
            await self.db.refresh(answer)

        completed_reminder_ids = await self.complete_active_group_reminders(group.id, user)
        return {
            "submission_id": submission.id,
            "answer_ids": [answer.id for answer in answers],
            "completed_reminder_ids": completed_reminder_ids,
        }

    async def complete_active_group_reminders(self, group_id: int, user: User) -> list[int]:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(FormGroupItem).where(FormGroupItem.group_id == group_id)
        )
        form_ids = [item.form_id for item in result.scalars().all()]

        reminder_query = select(Reminder).where(
            Reminder.user_id == user.id,
            Reminder.status.in_(ACTIVE_REMINDER_STATUSES),
        )
        if form_ids:
            reminder_query = reminder_query.where(
                (Reminder.form_group_id == group_id) | (Reminder.form_id.in_(form_ids))
            )
        else:
            reminder_query = reminder_query.where(Reminder.form_group_id == group_id)

        reminders = list((await self.db.execute(reminder_query)).scalars().all())
        for reminder in reminders:
            reminder.status = "completed"
            reminder.completed_at = now
            reminder.next_run_at = now
            reminder.updated_at = now
            self.db.add(reminder)

        if reminders:
            await self.db.commit()

        return [reminder.id for reminder in reminders]

    async def _get_user_group(self, group_id: int, user: User) -> FormGroup:
        result = await self.db.execute(
            select(FormGroup).where(FormGroup.id == group_id, FormGroup.user_id == user.id)
        )
        group = result.scalar_one_or_none()
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form group not found",
            )
        return group

    async def _get_user_forms(self, form_ids: list[int], user: User) -> list[Form]:
        unique_ids = list(dict.fromkeys(form_ids))
        result = await self.db.execute(
            select(Form).where(
                Form.id.in_(unique_ids),
                Form.user_id == user.id,
                Form.archived_at.is_(None),
            )
        )
        forms = list(result.scalars().all())
        found_ids = {form.id for form in forms}
        missing_ids = [form_id for form_id in unique_ids if form_id not in found_ids]
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forms not found: {', '.join(map(str, missing_ids))}",
            )
        return sorted(forms, key=lambda form: unique_ids.index(form.id))

    async def _get_group_forms(self, group_id: int) -> list[Form]:
        result = await self.db.execute(
            select(Form)
            .join(FormGroupItem, FormGroupItem.form_id == Form.id)
            .where(FormGroupItem.group_id == group_id)
            .order_by(FormGroupItem.sort_order, FormGroupItem.id)
        )
        return list(result.scalars().all())

    def _add_group_items(self, group_id: int, form_ids: list[int]) -> None:
        for sort_order, form_id in enumerate(dict.fromkeys(form_ids)):
            self.db.add(FormGroupItem(group_id=group_id, form_id=form_id, sort_order=sort_order))


def form_group_to_response(group: FormGroup, forms: list[Form]) -> FormGroupResponse:
    return FormGroupResponse(
        group_id=group.id,
        title=group.title,
        description=group.description,
        form_ids=[form.id for form in forms],
        forms=[form_to_response(form) for form in forms],
        schedule_crons=group.schedule_crons,
        is_active=group.is_active,
        archived_at=group.archived_at,
        reminder_enabled=group.reminder_enabled,
        reminder_title=group.reminder_title,
        reminder_payload=group.reminder_payload,
        skip_retry_delay_seconds=group.skip_retry_delay_seconds,
        delivery_retry_delay_seconds=group.delivery_retry_delay_seconds,
        last_reminder_scheduled_at=group.last_reminder_scheduled_at,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )
