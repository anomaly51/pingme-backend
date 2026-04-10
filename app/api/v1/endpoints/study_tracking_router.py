from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user_obj
from app.models.user_model import User
from app.schemas.socket_schemas import ConfirmStudyCreate
from app.schemas.study_schemas import StudyTrackingCreate
from app.services.tracking_service import TrackingService


router = APIRouter(prefix="/tracking", tags=["Tracking"])


@router.post("/study")
async def add_study_tracking(
    data: StudyTrackingCreate,
    user: User = Depends(get_current_user_obj),
    tracking_service: TrackingService = Depends(),
):
    return await tracking_service.add_study_tracking(data, user)


@router.post("/confirm")
async def confirm_study(
    data: ConfirmStudyCreate,
    user: User = Depends(get_current_user_obj),
    tracking_service: TrackingService = Depends(),
):
    return await tracking_service.confirm_study(data.confirm_name, user)
