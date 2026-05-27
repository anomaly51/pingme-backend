from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.form_schemas import FormResponse


class FormGroupBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    form_ids: list[int] = Field(min_length=1)
    schedule_crons: list[str] = Field(default_factory=list)
    is_active: bool = True
    reminder_enabled: bool = False
    reminder_title: str | None = None
    reminder_payload: dict[str, Any] = Field(default_factory=dict)
    skip_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)
    delivery_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)


class FormGroupCreate(FormGroupBase):
    pass


class FormGroupUpdate(FormGroupBase):
    pass


class FormGroupResponse(BaseModel):
    group_id: int
    title: str
    description: str | None = None
    form_ids: list[int]
    forms: list[FormResponse]
    schedule_crons: list[str]
    is_active: bool
    archived_at: datetime | None = None
    reminder_enabled: bool
    reminder_title: str | None = None
    reminder_payload: dict[str, Any]
    skip_retry_delay_seconds: int
    delivery_retry_delay_seconds: int
    last_reminder_scheduled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FormGroupMutationResponse(BaseModel):
    message: str
    group_id: int
    group: FormGroupResponse


class GroupAnswerItem(BaseModel):
    form_id: int
    answers_data: dict[str, Any]


class FormGroupAnswerCreate(BaseModel):
    answers: list[GroupAnswerItem] = Field(min_length=1)


class FormGroupAnswerResponse(BaseModel):
    message: str
    submission_id: int
    answer_ids: list[int]
    completed_reminder_ids: list[int]
