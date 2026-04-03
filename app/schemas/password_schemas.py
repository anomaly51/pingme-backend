import re
from typing import Annotated

from pydantic import AfterValidator, Field


def validate_password_complexity(value: str) -> str:
    if not re.search(r"[A-Z]", value):
        raise ValueError("Password must contain at least one uppercase letter (A-Z)")
    if not re.search(r"[a-z]", value):
        raise ValueError("Password must contain at least one lowercase letter (a-z)")
    if not re.search(r"\d", value):
        raise ValueError("Password must contain at least one digit (0-9)")
    return value


StrongPassword = Annotated[
    str, Field(min_length=8, max_length=50), AfterValidator(validate_password_complexity)
]
