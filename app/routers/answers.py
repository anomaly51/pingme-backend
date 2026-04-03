from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Answer, Form, User
from app.schemas.form_schemas import AnswerCreate
from app.security import get_current_user
from db.database import get_db


router = APIRouter(prefix="/answers", tags=["Answers"])


async def get_current_user_obj(
    email: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_answer(
    answer_data: AnswerCreate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    form_query = select(Form).where(Form.id == answer_data.form_id)
    form_result = await db.execute(form_query)
    if not form_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Specified form not found")

    new_answer = Answer(
        form_id=answer_data.form_id,
        user_id=user.id,
        answers_data=answer_data.answers_data,
    )

    db.add(new_answer)
    await db.commit()
    await db.refresh(new_answer)

    return {"answer_id": new_answer.id, "message": "Answers saved"}
