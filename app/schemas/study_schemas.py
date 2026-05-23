from datetime import date

from pydantic import BaseModel, Field


class StudyTrackingCreate(BaseModel):
    activity: str = Field(min_length=1, max_length=500)
    hours_spent: float = Field(gt=0, le=24)


class FindOfferExtendRequest(BaseModel):
    spreadsheet_id: str | None = None
    worksheet_name: str | None = None
    today: date | None = None
