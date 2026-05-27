from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.user_model import Answer, AnswerSubmission
from app.services.reminder_service import ReminderService
from tests.conftest import reg_and_login


async def create_basic_form(async_client, headers, title: str, field_name: str) -> int:
    response = await async_client.post(
        "/forms",
        json={
            "title": title,
            "form_structure": {"fields": [{"name": field_name, "type": "number"}]},
            "schedule_crons": [],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["form_id"]


@pytest.mark.asyncio
async def test_create_form_group_lists_forms(async_client):
    session = await reg_and_login(async_client)
    spent_form_id = await create_basic_form(async_client, session["headers"], "Spent", "amount")
    mood_form_id = await create_basic_form(async_client, session["headers"], "Mood", "mood_score")

    created = await async_client.post(
        "/form-groups",
        json={
            "title": "Evening check-in",
            "description": "Daily grouped report",
            "form_ids": [spent_form_id, mood_form_id],
            "schedule_crons": ["daily 20:00"],
            "reminder_enabled": True,
            "reminder_title": "Fill evening check-in",
            "reminder_payload": {"kind": "evening"},
        },
        headers=session["headers"],
    )

    assert created.status_code == 201, created.text
    group = created.json()["group"]
    assert group["form_ids"] == [spent_form_id, mood_form_id]
    assert [form["form_id"] for form in group["forms"]] == [spent_form_id, mood_form_id]

    listed = await async_client.get("/form-groups", headers=session["headers"])
    assert listed.status_code == 200
    assert listed.json()[0]["group_id"] == created.json()["group_id"]


@pytest.mark.asyncio
async def test_manual_group_reminder_and_batch_answers(async_client, db_session):
    session = await reg_and_login(async_client)
    spent_form_id = await create_basic_form(async_client, session["headers"], "Spent", "amount")
    mood_form_id = await create_basic_form(async_client, session["headers"], "Mood", "mood_score")
    group = await async_client.post(
        "/form-groups",
        json={
            "title": "Evening check-in",
            "form_ids": [spent_form_id, mood_form_id],
            "schedule_crons": [],
        },
        headers=session["headers"],
    )
    group_id = group.json()["group_id"]

    reminder = await async_client.post(
        "/reminders",
        json={
            "title": "Fill grouped forms",
            "form_group_id": group_id,
            "payload": {"source": "test"},
            "retry_delay_seconds": 3600,
        },
        headers=session["headers"],
    )
    assert reminder.status_code == 201
    assert reminder.json()["form_group_id"] == group_id

    saved = await async_client.post(
        f"/form-groups/{group_id}/answers",
        json={
            "answers": [
                {"form_id": spent_form_id, "answers_data": {"amount": 42.5, "category": "food"}},
                {"form_id": mood_form_id, "answers_data": {"mood_score": 8, "notes": ["ok"]}},
            ]
        },
        headers=session["headers"],
    )

    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["message"] == "Group answers saved"
    assert len(body["answer_ids"]) == 2
    assert body["completed_reminder_ids"] == [reminder.json()["id"]]

    submission = (
        await db_session.execute(
            select(AnswerSubmission).where(AnswerSubmission.id == body["submission_id"])
        )
    ).scalar_one()
    assert submission.form_group_id == group_id
    answers = (
        (
            await db_session.execute(
                select(Answer)
                .where(Answer.submission_id == body["submission_id"])
                .order_by(Answer.id)
            )
        )
        .scalars()
        .all()
    )
    assert [answer.form_id for answer in answers] == [spent_form_id, mood_form_id]
    assert answers[0].answers_data == {"amount": 42.5, "category": "food"}


@pytest.mark.asyncio
async def test_group_answer_rejects_form_outside_group(async_client):
    session = await reg_and_login(async_client)
    first_form_id = await create_basic_form(async_client, session["headers"], "First", "one")
    other_form_id = await create_basic_form(async_client, session["headers"], "Other", "two")
    group = await async_client.post(
        "/form-groups",
        json={"title": "One form group", "form_ids": [first_form_id], "schedule_crons": []},
        headers=session["headers"],
    )

    response = await async_client.post(
        f"/form-groups/{group.json()['group_id']}/answers",
        json={"answers": [{"form_id": other_form_id, "answers_data": {"two": 2}}]},
        headers=session["headers"],
    )

    assert response.status_code == 422
    assert "do not belong" in response.json()["detail"]


@pytest.mark.asyncio
async def test_scheduler_creates_group_reminder(async_client, db_session, monkeypatch):
    async def fake_publish(_reminder_id: int, _delay_seconds: int = 0) -> bool:
        return True

    monkeypatch.setattr("app.services.reminder_service.publish_reminder", fake_publish)
    session = await reg_and_login(async_client)
    form_id = await create_basic_form(async_client, session["headers"], "Spent", "amount")
    group = await async_client.post(
        "/form-groups",
        json={
            "title": "Evening check-in",
            "form_ids": [form_id],
            "schedule_crons": ["@every 1h"],
            "reminder_enabled": True,
            "reminder_title": "Fill evening check-in",
        },
        headers=session["headers"],
    )

    created = await ReminderService(db_session).create_due_form_group_reminders(datetime.now(UTC))

    assert len(created) == 1
    assert created[0].form_group_id == group.json()["group_id"]
    assert created[0].title == "Fill evening check-in"
