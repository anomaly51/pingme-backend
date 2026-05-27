from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_current_user_obj
from app.models.user_model import User
from app.schemas.form_schemas import (
    FormCreate,
    FormMutationResponse,
    FormResponse,
    FormUpdate,
    ReminderSettingsUpdate,
)
from app.services.form_service import FormService, form_to_response


router = APIRouter(prefix="/forms", tags=["Forms"])


@router.post("", response_model=FormMutationResponse, status_code=status.HTTP_201_CREATED)
async def create_form(
    form_data: FormCreate,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.create_form(form_data, user)
    return {
        "form_id": form.id,
        "form": form_to_response(form),
        "message": "Form created successfully",
    }


@router.get("", response_model=list[FormResponse])
async def get_all_forms(
    include_archived: bool = Query(default=False),
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    forms = await form_service.get_all_forms(user, include_archived)
    return [form_to_response(form) for form in forms]


@router.get("/{form_id}", response_model=FormResponse)
async def get_form_by_id(
    form_id: int,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.get_form_by_id(form_id, user)
    return form_to_response(form)


@router.put("/{form_id}", response_model=FormMutationResponse)
async def update_form(
    form_id: int,
    form_data: FormUpdate,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.update_form(form_id, form_data, user)
    return {
        "form_id": form.id,
        "form": form_to_response(form),
        "message": "Form updated successfully",
    }


@router.patch("/{form_id}/reminder-settings", response_model=FormMutationResponse)
async def update_reminder_settings(
    form_id: int,
    form_data: ReminderSettingsUpdate,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.update_reminder_settings(form_id, form_data, user)
    return {
        "form_id": form.id,
        "form": form_to_response(form),
        "message": "Reminder settings updated successfully",
    }


@router.post("/{form_id}/archive", response_model=FormMutationResponse)
async def archive_form(
    form_id: int,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.archive_form(form_id, user)
    return {
        "form_id": form.id,
        "form": form_to_response(form),
        "message": "Form archived successfully",
    }


@router.post("/{form_id}/restore", response_model=FormMutationResponse)
async def restore_form(
    form_id: int,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.restore_form(form_id, user)
    return {
        "form_id": form.id,
        "form": form_to_response(form),
        "message": "Form restored successfully",
    }


@router.delete("/{form_id}")
async def delete_form(
    form_id: int, user: User = Depends(get_current_user_obj), form_service: FormService = Depends()
):
    await form_service.delete_form(form_id, user)
    return {"message": "Form has been deleted successfully"}
