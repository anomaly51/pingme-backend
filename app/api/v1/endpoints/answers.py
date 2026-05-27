from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_current_user_obj
from app.api.rate_limit import rate_limit
from app.models.user_model import User
from app.schemas.form_schemas import (
    AnswerCreate,
    AnswerCreateResponse,
    AnswerCreateWithFormId,
    AnswerResponse,
    AnswerSaveResponse,
    AnswerStatsResponse,
)
from app.services.answer_service import AnswerService


router = APIRouter(tags=["Answers"])


@router.post("/answers", response_model=AnswerSaveResponse, status_code=status.HTTP_201_CREATED)
async def save_answer(
    answer_data: AnswerCreateWithFormId,
    user: User = Depends(get_current_user_obj),
    answer_service: AnswerService = Depends(),
    _rate_limit: None = Depends(rate_limit("create_answer", limit=120, window_seconds=300)),
):
    result = await answer_service.create_answer(answer_data.form_id, answer_data, user)

    return {"message": "Answers saved", "answer_id": result["answer_id"]}


@router.post(
    "/forms/{form_id}/answers",
    response_model=AnswerCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_answer(
    form_id: int,
    answer_data: AnswerCreate,
    user: User = Depends(get_current_user_obj),
    answer_service: AnswerService = Depends(),
    _rate_limit: None = Depends(rate_limit("create_answer", limit=120, window_seconds=300)),
):
    result = await answer_service.create_answer(form_id, answer_data, user)

    return {"message": "Answers saved", **result}


@router.get("/forms/{form_id}/answers/stats", response_model=AnswerStatsResponse)
async def get_form_answer_stats(
    form_id: int,
    user: User = Depends(get_current_user_obj),
    answer_service: AnswerService = Depends(),
):
    return await answer_service.get_form_answer_stats(form_id, user)


@router.get("/forms/{form_id}/answers", response_model=list[AnswerResponse])
async def get_form_answers(
    form_id: int,
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user_obj),
    answer_service: AnswerService = Depends(),
):
    answers = await answer_service.get_form_answers(
        form_id,
        user,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "answer_id": answer.id,
            "form_id": answer.form_id,
            "submission_id": answer.submission_id,
            "answers_data": answer.answers_data,
            "created_at": answer.created_at,
        }
        for answer in answers
    ]
