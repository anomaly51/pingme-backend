from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


FIELD_TYPES = {"text", "number", "select", "checkbox", "boolean", "date", "time"}


class FormBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    form_structure: dict[str, Any]
    schedule_crons: list[str]
    is_active: bool = True
    reminder_enabled: bool = False
    reminder_title: str | None = None
    reminder_payload: dict[str, Any] = Field(default_factory=dict)
    skip_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)
    delivery_retry_delay_seconds: int = Field(default=3600, ge=60, le=60 * 60 * 24 * 30)

    @field_validator("form_structure")
    @classmethod
    def validate_form_structure(cls, value: dict[str, Any]) -> dict[str, Any]:
        validate_form_structure_contract(value)
        return value


class FormCreate(FormBase):
    pass


class FormUpdate(FormBase):
    pass


class ReminderSettingsUpdate(BaseModel):
    schedule_crons: list[str] | None = None
    reminder_enabled: bool | None = None
    reminder_title: str | None = None
    reminder_payload: dict[str, Any] | None = None
    skip_retry_delay_seconds: int | None = Field(default=None, ge=60, le=60 * 60 * 24 * 30)
    delivery_retry_delay_seconds: int | None = Field(default=None, ge=60, le=60 * 24 * 60 * 30)


class FormResponse(BaseModel):
    form_id: int
    title: str
    description: str | None = None
    form_structure: dict[str, Any]
    schedule_crons: list[str]
    is_active: bool
    archived_at: datetime | None = None
    reminder_enabled: bool
    reminder_title: str | None = None
    reminder_payload: dict[str, Any]
    skip_retry_delay_seconds: int
    delivery_retry_delay_seconds: int
    last_reminder_scheduled_at: datetime | None = None


class FormMutationResponse(BaseModel):
    message: str
    form_id: int
    form: FormResponse


class AnswerCreate(BaseModel):
    answers_data: dict[str, Any]


def validate_form_structure_contract(value: dict[str, Any]) -> None:  # noqa: C901
    fields = value.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("form_structure.fields must be a non-empty list")

    seen_names: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("Each form field must be an object")

        name = field.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each form field must have a non-empty name")
        if name in seen_names:
            raise ValueError(f"Duplicate form field name: {name}")
        seen_names.add(name)

        field_type = field.get("type")
        if field_type not in FIELD_TYPES:
            raise ValueError(f"Unsupported form field type: {field_type}")

        label = field.get("label")
        if label is not None and not isinstance(label, str):
            raise ValueError(f"Field {name} label must be a string")

        required = field.get("required", False)
        if not isinstance(required, bool):
            raise ValueError(f"Field {name} required must be boolean")

        if field_type == "select":
            options = field.get("options")
            if not isinstance(options, list) or not options:
                raise ValueError(f"Select field {name} must define options")
            if any(not isinstance(option, str) or not option for option in options):
                raise ValueError(f"Select field {name} options must be non-empty strings")

        if field_type == "number":
            for bound in ("min", "max"):
                if bound in field and not isinstance(field[bound], int | float):
                    raise ValueError(f"Number field {name} {bound} must be numeric")
            if "min" in field and "max" in field and field["min"] > field["max"]:
                raise ValueError(f"Number field {name} min cannot be greater than max")


def validate_answers_against_form_structure(  # noqa: C901
    answers_data: dict[str, Any],
    form_structure: dict[str, Any],
) -> None:
    validate_form_structure_contract(form_structure)
    fields = {field["name"]: field for field in form_structure["fields"]}
    unknown_fields = set(answers_data) - set(fields)
    if unknown_fields:
        raise ValueError(f"Unknown answer fields: {', '.join(sorted(unknown_fields))}")

    for name, field in fields.items():
        value = answers_data.get(name)
        if field.get("required", False) and value is None:
            raise ValueError(f"Field {name} is required")
        if value is None:
            continue

        field_type = field["type"]
        if field_type == "text" and not isinstance(value, str):
            raise ValueError(f"Field {name} must be text")
        if field_type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"Field {name} must be numeric")
            if "min" in field and value < field["min"]:
                raise ValueError(f"Field {name} is below minimum")
            if "max" in field and value > field["max"]:
                raise ValueError(f"Field {name} is above maximum")
        if field_type == "select" and value not in field["options"]:
            raise ValueError(f"Field {name} has invalid option")
        if field_type in {"checkbox", "boolean"} and not isinstance(value, bool):
            raise ValueError(f"Field {name} must be boolean")
        if field_type in {"date", "time"} and not isinstance(value, str):
            raise ValueError(f"Field {name} must be a string")


class AnswerCreateResponse(BaseModel):
    message: str
    answer_id: int
    completed_reminder_ids: list[int]


class AnswerResponse(BaseModel):
    answer_id: int
    form_id: int
    answers_data: dict[str, Any]
    created_at: datetime


class AnswerStatsResponse(BaseModel):
    form_id: int
    total_answers: int
    first_answer_at: datetime | None = None
    last_answer_at: datetime | None = None
    numeric_averages: dict[str, float] = Field(default_factory=dict)
    completion_rate: float | None = None

    model_config = ConfigDict(from_attributes=True)
