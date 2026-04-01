import re
from typing import Annotated

from pydantic import AfterValidator, Field


def validate_password_complexity(value: str) -> str:
    if not re.search(r"[A-Z]", value):
        raise ValueError("Пароль должен содержать хотя бы одну заглавную букву (A-Z)")
    if not re.search(r"[a-z]", value):
        raise ValueError("Пароль должен содержать хотя бы одну строчную букву (a-z)")
    if not re.search(r"\d", value):
        raise ValueError("Пароль должен содержать хотя бы одну цифру (0-9)")
    return value


StrongPassword = Annotated[
    str, Field(min_length=8, max_length=50), AfterValidator(validate_password_complexity)
]
