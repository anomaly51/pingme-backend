from pydantic import BaseModel


class ConfirmStudyCreate(BaseModel):
    confirm_name: str
