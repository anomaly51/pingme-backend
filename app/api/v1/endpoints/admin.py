from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import RoleChecker
from app.models.user_model import Answer, Form, Reminder, User
from app.schemas.admin_schemas import (
    AdminOverviewResponse,
    AdminReminderResponse,
    AdminUserResponse,
)
from db.database import get_db


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def get_overview(
    _user: User = Depends(RoleChecker(["admin", "manager"])),
    db: AsyncSession = Depends(get_db),
):
    users = await scalar_count(db, select(func.count(User.id)))
    forms = await scalar_count(db, select(func.count(Form.id)))
    active_forms = await scalar_count(
        db,
        select(func.count(Form.id)).where(Form.archived_at.is_(None), Form.is_active.is_(True)),
    )
    answers = await scalar_count(db, select(func.count(Answer.id)))
    failed_enqueue_reminders = await scalar_count(
        db,
        select(func.count(Reminder.id)).where(Reminder.enqueue_status == "failed"),
    )
    stale_pending_reminders = await scalar_count(
        db,
        select(func.count(Reminder.id)).where(
            Reminder.status == "pending",
            Reminder.last_delivered_at < datetime.now(UTC) - timedelta(hours=24),
        ),
    )

    status_rows = await db.execute(
        select(Reminder.status, func.count(Reminder.id)).group_by(Reminder.status)
    )
    return AdminOverviewResponse(
        users=users,
        forms=forms,
        active_forms=active_forms,
        answers=answers,
        reminders_by_status={status: count for status, count in status_rows.all()},
        failed_enqueue_reminders=failed_enqueue_reminders,
        stale_pending_reminders=stale_pending_reminders,
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(RoleChecker(["admin", "manager"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.id.desc()).limit(limit).offset(offset))
    return [
        AdminUserResponse(
            id=user.id,
            email=user.email,
            roles=user.roles or [],
            is_email_confirmed=user.is_email_confirmed,
            timezone=user.timezone,
            created_at=user.created_at,
        )
        for user in result.scalars().all()
    ]


@router.get("/reminders/failed", response_model=list[AdminReminderResponse])
async def list_failed_reminders(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(RoleChecker(["admin", "manager"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Reminder)
        .where(Reminder.enqueue_status == "failed")
        .order_by(Reminder.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [reminder_to_admin_response(reminder) for reminder in result.scalars().all()]


async def scalar_count(db: AsyncSession, query: object) -> int:
    result = await db.execute(query)
    return int(result.scalar_one())


def reminder_to_admin_response(reminder: Reminder) -> AdminReminderResponse:
    return AdminReminderResponse(
        id=reminder.id,
        user_id=reminder.user_id,
        form_id=reminder.form_id,
        title=reminder.title,
        status=reminder.status,
        enqueue_status=reminder.enqueue_status,
        last_enqueue_error=reminder.last_enqueue_error,
        delivery_count=reminder.delivery_count,
        next_run_at=reminder.next_run_at,
        updated_at=reminder.updated_at,
    )
