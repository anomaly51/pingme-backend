import os

import gspread
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import User
from app.schemas.study_schemas import StudyTrackingCreate
from app.security import get_current_user
from db.database import get_db


router = APIRouter(prefix="/tracking", tags=["Трекинг"])

# Подключаем нашего робота к Google (делается один раз при старте файла)
try:
    gc = gspread.service_account(filename="google_services.json")
except Exception as e:
    print(f"Ошибка загрузки ключей Google: {e}")


# Вспомогательная функция (такая же, как в прошлых файлах)
async def get_current_user_obj(
    email: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


@router.post("/study")
async def add_study_tracking(data: StudyTrackingCreate, user: User = Depends(get_current_user_obj)):
    try:
        # Открываем таблицу. Надежнее всего использовать ID таблицы из её ссылки.
        # Ссылка выглядит так: https://docs.google.com/spreadsheets/d/ВОТ_ЭТОТ_ДЛИННЫЙ_ID/edit
        sh = gc.open_by_key(os.getenv("GOOGLE_TABLE_ID"))

        # Берем первый лист таблицы
        worksheet = sh.sheet1

        # Формируем строку для добавления.
        # Если в твоей модели User нет поля name, используй user.email
        row_to_append = [user.email, data.activity, data.hours_spent]

        # Добавляем строку в конец таблицы
        worksheet.append_row(row_to_append)

        # Если дошли сюда, значит всё успешно, возвращаем 200 OK (FastAPI делает это по умолчанию)
        return {"message": "Data added to Google Sheet"}

    except Exception as e:
        # Если Гугл ругается (нет прав, неверный ID), выдаем 500 ошибку
        raise HTTPException(status_code=500, detail=f"Google Sheets Error: {str(e)}")
