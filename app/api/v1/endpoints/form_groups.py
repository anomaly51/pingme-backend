from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_current_user_obj
from app.models.user_model import User
from app.schemas.form_group_schemas import (
    FormGroupAnswerCreate,
    FormGroupAnswerResponse,
    FormGroupCreate,
    FormGroupMutationResponse,
    FormGroupResponse,
    FormGroupUpdate,
)
from app.services.form_group_service import FormGroupService, form_group_to_response


router = APIRouter(prefix="/form-groups", tags=["Form Groups"])


@router.post("", response_model=FormGroupMutationResponse, status_code=status.HTTP_201_CREATED)
async def create_form_group(
    data: FormGroupCreate,
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    group, forms = await service.create_group(data, user)
    return {
        "message": "Form group created successfully",
        "group_id": group.id,
        "group": form_group_to_response(group, forms),
    }


@router.get("", response_model=list[FormGroupResponse])
async def list_form_groups(
    include_archived: bool = Query(default=False),
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    groups = await service.list_groups(user, include_archived)
    return [form_group_to_response(group, forms) for group, forms in groups]


@router.get("/{group_id}", response_model=FormGroupResponse)
async def get_form_group(
    group_id: int,
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    group, forms = await service.get_group(group_id, user)
    return form_group_to_response(group, forms)


@router.put("/{group_id}", response_model=FormGroupMutationResponse)
async def update_form_group(
    group_id: int,
    data: FormGroupUpdate,
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    group, forms = await service.update_group(group_id, data, user)
    return {
        "message": "Form group updated successfully",
        "group_id": group.id,
        "group": form_group_to_response(group, forms),
    }


@router.post("/{group_id}/archive", response_model=FormGroupMutationResponse)
async def archive_form_group(
    group_id: int,
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    group, forms = await service.archive_group(group_id, user)
    return {
        "message": "Form group archived successfully",
        "group_id": group.id,
        "group": form_group_to_response(group, forms),
    }


@router.post("/{group_id}/restore", response_model=FormGroupMutationResponse)
async def restore_form_group(
    group_id: int,
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    group, forms = await service.restore_group(group_id, user)
    return {
        "message": "Form group restored successfully",
        "group_id": group.id,
        "group": form_group_to_response(group, forms),
    }


@router.post(
    "/{group_id}/answers",
    response_model=FormGroupAnswerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_form_group_answers(
    group_id: int,
    data: FormGroupAnswerCreate,
    user: User = Depends(get_current_user_obj),
    service: FormGroupService = Depends(),
):
    result = await service.save_group_answers(group_id, data, user)
    return {"message": "Group answers saved", **result}
