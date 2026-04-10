from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_user_obj
from app.models.user_model import User
from app.schemas.form_schemas import FormCreate, FormUpdate
from app.services.form_service import FormService


router = APIRouter(prefix="/forms", tags=["Forms"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_form(
    form_data: FormCreate,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form_id = await form_service.create_form(form_data, user)
    return {"form_id": form_id, "message": "Form created successfully"}


@router.get("")
async def get_all_forms(
    user: User = Depends(get_current_user_obj), form_service: FormService = Depends()
):
    forms = await form_service.get_all_forms(user)
    return [
        {
            "form_id": f.id,
            "title": f.title,
            "form_structure": f.form_structure,
            "schedule_crons": f.schedule_crons,
        }
        for f in forms
    ]


@router.get("/{form_id}")
async def get_form_by_id(
    form_id: int,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    form = await form_service.get_form_by_id(form_id, user)
    return {
        "form_id": form.id,
        "title": form.title,
        "form_structure": form.form_structure,
        "schedule_crons": form.schedule_crons,
    }


@router.put("/{form_id}")
async def update_form(
    form_id: int,
    form_data: FormUpdate,
    user: User = Depends(get_current_user_obj),
    form_service: FormService = Depends(),
):
    await form_service.update_form(form_id, form_data, user)
    return {"message": "Form updated successfully"}


@router.delete("/{form_id}")
async def delete_form(
    form_id: int, user: User = Depends(get_current_user_obj), form_service: FormService = Depends()
):
    await form_service.delete_form(form_id, user)
    return {"message": "Form has been deleted"}
