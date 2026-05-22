from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_user_obj
from app.models.user_model import User
from app.schemas.reminder_schemas import ReminderCreate, ReminderResponse, ReminderSkipRequest
from app.services.reminder_service import ReminderService


router = APIRouter(prefix="/reminders", tags=["Reminders"])


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    data: ReminderCreate,
    user: User = Depends(get_current_user_obj),
    reminder_service: ReminderService = Depends(),
):
    return await reminder_service.create_reminder(data, user)


@router.get("/current", response_model=list[ReminderResponse])
async def get_current_reminders(
    user: User = Depends(get_current_user_obj),
    reminder_service: ReminderService = Depends(),
):
    return await reminder_service.get_current_reminders(user)


@router.post("/{reminder_id}/skip", response_model=ReminderResponse)
async def skip_reminder(
    reminder_id: int,
    data: ReminderSkipRequest,
    user: User = Depends(get_current_user_obj),
    reminder_service: ReminderService = Depends(),
):
    return await reminder_service.skip_reminder(reminder_id, user, data.retry_delay_seconds)


@router.post("/{reminder_id}/complete", response_model=ReminderResponse)
async def complete_reminder(
    reminder_id: int,
    user: User = Depends(get_current_user_obj),
    reminder_service: ReminderService = Depends(),
):
    return await reminder_service.complete_reminder(reminder_id, user)


@router.post("/{reminder_id}/cancel", response_model=ReminderResponse)
async def cancel_reminder(
    reminder_id: int,
    user: User = Depends(get_current_user_obj),
    reminder_service: ReminderService = Depends(),
):
    return await reminder_service.cancel_reminder(reminder_id, user)
