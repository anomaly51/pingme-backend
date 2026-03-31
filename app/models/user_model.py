from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_email_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
