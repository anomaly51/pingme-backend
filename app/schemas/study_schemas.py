from datetime import date

from pydantic import BaseModel


class StudyTrackingCreate(BaseModel):
    activity: str
    hours_spent: float


class FindOfferExtendRequest(BaseModel):
    spreadsheet_id: str | None = None
    worksheet_name: str | None = None
    today: date | None = None
