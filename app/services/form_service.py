from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Form, User
from app.schemas.form_schemas import FormCreate, FormResponse, FormUpdate, ReminderSettingsUpdate
from db.database import get_db


class FormService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_form(self, form_data: FormCreate, user: User) -> Form:
        new_form = Form(
            user_id=user.id,
            title=form_data.title,
            description=form_data.description,
            form_structure=form_data.form_structure,
            schedule_crons=form_data.schedule_crons,
            is_active=form_data.is_active,
            reminder_enabled=form_data.reminder_enabled,
            reminder_title=form_data.reminder_title,
            reminder_payload=form_data.reminder_payload,
            skip_retry_delay_seconds=form_data.skip_retry_delay_seconds,
            delivery_retry_delay_seconds=form_data.delivery_retry_delay_seconds,
        )
        self.db.add(new_form)
        await self.db.commit()
        await self.db.refresh(new_form)
        return new_form

    async def get_all_forms(self, user: User, include_archived: bool = False) -> list[Form]:
        query = select(Form).where(Form.user_id == user.id)
        if not include_archived:
            query = query.where(Form.archived_at.is_(None))
        query = query.order_by(Form.id.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_form_by_id(self, form_id: int, user: User) -> Form:
        query = select(Form).where(Form.id == form_id, Form.user_id == user.id)
        result = await self.db.execute(query)
        form = result.scalar_one_or_none()

        if not form:
            raise HTTPException(status_code=404, detail="Form not found")
        return form

    async def update_form(self, form_id: int, form_data: FormUpdate, user: User) -> Form:
        form = await self.get_form_by_id(form_id, user)

        form.title = form_data.title
        form.description = form_data.description
        form.form_structure = form_data.form_structure
        form.schedule_crons = form_data.schedule_crons
        form.is_active = form_data.is_active
        form.reminder_enabled = form_data.reminder_enabled
        form.reminder_title = form_data.reminder_title
        form.reminder_payload = form_data.reminder_payload
        form.skip_retry_delay_seconds = form_data.skip_retry_delay_seconds
        form.delivery_retry_delay_seconds = form_data.delivery_retry_delay_seconds

        await self.db.commit()
        await self.db.refresh(form)
        return form

    async def update_reminder_settings(
        self, form_id: int, form_data: ReminderSettingsUpdate, user: User
    ) -> Form:
        form = await self.get_form_by_id(form_id, user)
        for key, value in form_data.model_dump(exclude_unset=True).items():
            setattr(form, key, value)
        await self.db.commit()
        await self.db.refresh(form)
        return form

    async def archive_form(self, form_id: int, user: User) -> Form:
        form = await self.get_form_by_id(form_id, user)
        now = datetime.now(UTC)
        form.is_active = False
        form.archived_at = now
        await self.db.commit()
        await self.db.refresh(form)
        return form

    async def restore_form(self, form_id: int, user: User) -> Form:
        form = await self.get_form_by_id(form_id, user)
        form.is_active = True
        form.archived_at = None
        await self.db.commit()
        await self.db.refresh(form)
        return form

    async def delete_form(self, form_id: int, user: User) -> None:
        await self.archive_form(form_id, user)


def form_to_response(form: Form) -> FormResponse:
    return FormResponse(
        form_id=form.id,
        title=form.title,
        description=form.description,
        form_structure=form.form_structure,
        schedule_crons=form.schedule_crons,
        is_active=form.is_active,
        archived_at=form.archived_at,
        reminder_enabled=form.reminder_enabled,
        reminder_title=form.reminder_title,
        reminder_payload=form.reminder_payload,
        skip_retry_delay_seconds=form.skip_retry_delay_seconds,
        delivery_retry_delay_seconds=form.delivery_retry_delay_seconds,
        last_reminder_scheduled_at=form.last_reminder_scheduled_at,
    )
