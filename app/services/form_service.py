from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Form, User
from app.schemas.form_schemas import FormCreate, FormUpdate
from db.database import get_db


class FormService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_form(self, form_data: FormCreate, user: User) -> int:
        new_form = Form(
            user_id=user.id,
            title=form_data.title,
            form_structure=form_data.form_structure,
            schedule_crons=form_data.schedule_crons,
        )
        self.db.add(new_form)
        await self.db.commit()
        await self.db.refresh(new_form)
        return new_form.id

    async def get_all_forms(self, user: User) -> list[Form]:
        query = select(Form).where(Form.user_id == user.id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_form_by_id(self, form_id: int, user: User) -> Form:
        query = select(Form).where(Form.id == form_id, Form.user_id == user.id)
        result = await self.db.execute(query)
        form = result.scalar_one_or_none()

        if not form:
            raise HTTPException(status_code=404, detail="Form not found")
        return form

    async def update_form(self, form_id: int, form_data: FormUpdate, user: User) -> None:
        form = await self.get_form_by_id(form_id, user)

        form.title = form_data.title
        form.form_structure = form_data.form_structure
        form.schedule_crons = form_data.schedule_crons

        await self.db.commit()

    async def delete_form(self, form_id: int, user: User) -> None:
        form = await self.get_form_by_id(form_id, user)

        await self.db.delete(form)
        await self.db.commit()
