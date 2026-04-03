from typing import Any

from pydantic import BaseModel


class FormBase(BaseModel):
    title: str
    form_structure: dict[str, Any]
    schedule_crons: list[str]


class FormCreate(FormBase):
    pass


class FormUpdate(FormBase):
    pass


class AnswerCreate(BaseModel):
    form_id: int
    answers_data: dict[str, Any]
