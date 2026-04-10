from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_user_obj
from app.models.user_model import User
from app.schemas.form_schemas import AnswerCreate
from app.services.answer_service import AnswerService


router = APIRouter(prefix="/forms/{form_id}/answers", tags=["Answers"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_answer(
    form_id: int,
    answer_data: AnswerCreate,
    user: User = Depends(get_current_user_obj),
    answer_service: AnswerService = Depends(),
):
    answer_id = await answer_service.create_answer(form_id, answer_data, user)

    return {"answer_id": answer_id, "message": "Answers saved"}
