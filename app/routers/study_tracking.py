import os

import gspread
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import User
from app.schemas.study_schemas import StudyTrackingCreate
from app.security import get_current_user
from db.database import get_db


router = APIRouter(prefix="/tracking", tags=["Tracking"])

try:
    gc = gspread.service_account(filename="google_services.json")
except Exception as e:
    print(f"Google credentials load error: {e}")


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
    try:
        sh = gc.open_by_key(os.getenv("GOOGLE_TABLE_ID"))
        worksheet = sh.sheet1
        row_to_append = [user.email, data.activity, data.hours_spent]
        worksheet.append_row(row_to_append)
        return {"message": "Data added to Google Sheet"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Sheets Error: {str(e)}")
