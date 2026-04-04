from pydantic import BaseModel


class StudyTrackingCreate(BaseModel):
    activity: str
    hours_spent: float
