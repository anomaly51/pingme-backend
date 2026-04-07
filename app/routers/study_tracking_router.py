from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import User
from app.schemas.study_schemas import StudyTrackingCreate
from app.security import get_current_user
from app.services.study_tracking import update_study_data
from db.database import get_db


router = APIRouter(prefix="/tracking", tags=["Tracking"])


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
async def add_study_tracking(data: StudyTrackingCreate, user: User = Depends(get_current_user_obj)):
    await update_study_data(email=user.email, activity=data.activity, hours=data.hours_spent)
    return {"message": "Data successfully saved to Google Sheets!"}
