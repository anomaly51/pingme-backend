from sqlalchemy import text

from app.services.reminder_queue import _connect
from db.database import SessionLocal


async def check_database() -> bool:
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def check_rabbitmq() -> bool:
    try:
        connection = await _connect()
        async with connection:
            return True
    except Exception:
        return False
