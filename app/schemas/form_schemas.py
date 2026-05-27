from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FormBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    form_structure: dict[str, Any]
    schedule_crons: list[str]
    is_active: bool = True
    reminder_enabled: bool = False
    reminder_title: str | None = None
    reminder_payload: dict[str, Any] = Field(default_factory=dict)
    skip_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)
    delivery_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)


class FormCreate(FormBase):
    pass


class FormUpdate(FormBase):
    pass


class ReminderSettingsUpdate(BaseModel):
    schedule_crons: list[str] | None = None
    reminder_enabled: bool | None = None
    reminder_title: str | None = None
    reminder_payload: dict[str, Any] | None = None
    skip_retry_delay_seconds: int | None = Field(default=None, ge=60, le=60 * 60 * 24 * 30)
    delivery_retry_delay_seconds: int | None = Field(default=None, ge=60, le=60 * 24 * 60 * 30)


class FormResponse(BaseModel):
    form_id: int
    title: str
    description: str | None = None
    form_structure: dict[str, Any]
    schedule_crons: list[str]
    is_active: bool
    archived_at: datetime | None = None
    reminder_enabled: bool
    reminder_title: str | None = None
    reminder_payload: dict[str, Any]
    skip_retry_delay_seconds: int
    delivery_retry_delay_seconds: int
    last_reminder_scheduled_at: datetime | None = None


class FormMutationResponse(BaseModel):
    message: str
    form_id: int
    form: FormResponse


class AnswerCreate(BaseModel):
    answers_data: dict[str, Any]


class AnswerCreateWithFormId(AnswerCreate):
    form_id: int


class AnswerCreateResponse(BaseModel):
    message: str
    answer_id: int
    completed_reminder_ids: list[int]


class AnswerSaveResponse(BaseModel):
    message: str
    answer_id: int


class AnswerResponse(BaseModel):
    answer_id: int
    form_id: int
    submission_id: int | None = None
    answers_data: dict[str, Any]
    created_at: datetime


class AnswerStatsResponse(BaseModel):
    form_id: int
    total_answers: int
    first_answer_at: datetime | None = None
    last_answer_at: datetime | None = None
    numeric_averages: dict[str, float] = Field(default_factory=dict)
    completion_rate: float | None = None

    model_config = ConfigDict(from_attributes=True)
