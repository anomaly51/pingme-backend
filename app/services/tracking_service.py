from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import Answer, User
from app.schemas.study_schemas import StudyTrackingCreate
from app.services.study_tracking import confirm_study_data, update_study_data
from app.sockets import sio
from db.database import get_db


EMAIL_TO_NAME = {
    "fesenko.kostya576@gmail.com": "Kostya",
    "vania@gmail.com": "Vania",
    "vlad@gmail.com": "Vlad",
    "kostya2@gmail.com": "Kostya2",
}


class TrackingService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add_study_tracking(self, data: StudyTrackingCreate, user: User) -> dict:
        row_idx = await update_study_data(
            email=user.email, activity=data.activity, hours=data.hours_spent
        )

        manager_query = select(Answer.user_id).where(Answer.form_id == 17).distinct()
        result = await self.db.execute(manager_query)
        manager_ids = result.scalars().all()

        student_name = user.email.split("@")[0].capitalize()
        payload = {
            "student_name": student_name,
            "activity": data.activity,
            "hours": data.hours_spent,
            "sheet_row_id": row_idx,
        }

        for m_id in manager_ids:
            await sio.emit("study_record.created", payload, room=f"user:{m_id}")

        return {"message": "Data added to Google Sheet"}

    async def confirm_study(self, confirm_name: str, user: User) -> dict:
        manager_name = EMAIL_TO_NAME.get(user.email)

        if not manager_name:
            raise HTTPException(
                status_code=403, detail="Your account does not have rights to verify."
            )

        await confirm_study_data(student_name=confirm_name, manager_name=manager_name)

        return {"message": f"{manager_name} checked for {confirm_name}"}
