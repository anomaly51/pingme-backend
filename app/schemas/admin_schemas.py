from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AdminUserResponse(BaseModel):
    id: int
    email: str
    roles: list[str]
    is_email_confirmed: bool
    timezone: str
    created_at: datetime | None = None


class AdminReminderResponse(BaseModel):
    id: int
    user_id: int
    form_id: int | None
    title: str
    status: str
    enqueue_status: str
    last_enqueue_error: str | None = None
    delivery_count: int
    next_run_at: datetime
    updated_at: datetime


class AdminOverviewResponse(BaseModel):
    users: int
    forms: int
    active_forms: int
    answers: int
    reminders_by_status: dict[str, int]
    failed_enqueue_reminders: int
    stale_pending_reminders: int


class AdminPayloadResponse(BaseModel):
    data: dict[str, Any]
