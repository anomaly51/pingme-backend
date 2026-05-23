from pydantic import BaseModel, Field


class ConfirmStudyCreate(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=80)
