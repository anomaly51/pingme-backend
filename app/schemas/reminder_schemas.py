from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ReminderStatus = Literal["pending", "skipped", "completed", "cancelled"]
ReminderEnqueueStatus = Literal["pending", "queued", "failed"]


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    form_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)
    due_in_seconds: int = Field(default=0, ge=0, le=60 * 60 * 24 * 30)


class ReminderSkipRequest(BaseModel):
    retry_delay_seconds: int | None = Field(default=None, ge=60, le=60 * 60 * 24 * 30)


class ReminderResponse(BaseModel):
    id: int
    form_id: int | None
    title: str
    payload: dict[str, Any]
    status: ReminderStatus
    retry_delay_seconds: int
    delivery_retry_delay_seconds: int
    next_run_at: datetime
    skip_count: int
    delivery_count: int
    last_delivered_at: datetime | None = None
    enqueue_status: ReminderEnqueueStatus = "pending"
    last_enqueue_error: str | None = None
    enqueued_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
