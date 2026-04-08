from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Answer, User
from app.schemas.socket_schemas import ConfirmStudyCreate
from app.schemas.study_schemas import StudyTrackingCreate
from app.security import get_current_user
from app.services.study_tracking import confirm_study_data, update_study_data
from app.sockets import sio
from db.database import get_db


router = APIRouter(prefix="/tracking", tags=["Tracking"])

EMAIL_TO_NAME = {
    "fesenko.kostya576@gmail.com": "Kostya",
    "vania@gmail.com": "Vania",
    "vlad@gmail.com": "Vlad",
    "kostya2@gmail.com": "Kostya2",
}


async def get_current_user_obj(
    email: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/study")
async def add_study_tracking(
    data: StudyTrackingCreate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    row_idx = await update_study_data(
        email=user.email, activity=data.activity, hours=data.hours_spent
    )

    manager_query = select(Answer.user_id).where(Answer.form_id == 17).distinct()
    result = await db.execute(manager_query)
    manager_ids = result.scalars().all()

    student_name = user.email.split("@")[0].capitalize()
    payload = {
        "student_name": student_name,
        "activity": data.activity,
        "hours": data.hours_spent,
        "sheet_row_id": row_idx,
    }

    for m_id in manager_ids:
        await sio.emit("new_study_data", payload, room=f"user_{m_id}")

    return {"message": "Data added to Google Sheet"}


@router.post("/confirm")
async def confirm_study(
    data: ConfirmStudyCreate, current_user: User = Depends(get_current_user_obj)
):
    manager_name = EMAIL_TO_NAME.get(current_user.email)

    if not manager_name:
        raise HTTPException(status_code=403, detail="Your account does not have rights to verify.")

    await confirm_study_data(student_name=data.confirm_name, manager_name=manager_name)

    return {"message": f"{manager_name} checked for {data.confirm_name}"}
