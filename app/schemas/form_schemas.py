from typing import Any

from pydantic import BaseModel, Field


class FormBase(BaseModel):
    title: str
    form_structure: dict[str, Any]
    schedule_crons: list[str]
    reminder_enabled: bool = False
    reminder_title: str | None = None
    reminder_payload: dict[str, Any] = Field(default_factory=dict)
    skip_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)
    delivery_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)


class FormCreate(FormBase):
    pass


class FormUpdate(FormBase):
    pass


class AnswerCreate(BaseModel):
    answers_data: dict[str, Any]
