from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Answer, Form, User
from app.schemas.form_schemas import AnswerCreate
from db.database import get_db


class AnswerService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_answer(self, form_id: int, answer_data: AnswerCreate, user: User) -> int:

        form_query = select(Form).where(Form.id == form_id)
        form_result = await self.db.execute(form_query)

        if not form_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Specified form not found")

        new_answer = Answer(
            form_id=form_id,
            user_id=user.id,
            answers_data=answer_data.answers_data,
        )

        self.db.add(new_answer)
        await self.db.commit()
        await self.db.refresh(new_answer)

        return new_answer.id
