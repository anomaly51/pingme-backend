from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.user_model import Reminder
from app.services.reminder_service import (
    ReminderService,
    parse_schedule_interval_seconds,
)
from tests.conftest import reg_and_login


@pytest.fixture(autouse=True)
def disable_rabbitmq_publish(monkeypatch):
    published: list[tuple[int, int]] = []

    async def fake_publish(reminder_id: int, delay_seconds: int = 0) -> None:
        published.append((reminder_id, delay_seconds))

    monkeypatch.setattr("app.services.reminder_service.publish_reminder", fake_publish)
    return published


@pytest.mark.asyncio
async def test_create_reminder_enqueues_and_returns_due_reminder(
    async_client, disable_rabbitmq_publish
):
    session = await reg_and_login(async_client)

    response = await async_client.post(
        "/reminders",
        json={
            "title": "How long did you play guitar?",
            "payload": {"activity": "guitar"},
            "retry_delay_seconds": 3600,
            "due_in_seconds": 0,
        },
        headers=session["headers"],
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "How long did you play guitar?"
    assert data["status"] == "pending"
    assert disable_rabbitmq_publish == [(data["id"], 0)]

    current = await async_client.get("/reminders/current", headers=session["headers"])
    assert current.status_code == 200
    assert [reminder["id"] for reminder in current.json()] == [data["id"]]


@pytest.mark.asyncio
async def test_skip_reminder_reschedules_it(async_client, disable_rabbitmq_publish):
    session = await reg_and_login(async_client)
    created = await async_client.post(
        "/reminders",
        json={"title": "Track guitar", "retry_delay_seconds": 3600},
        headers=session["headers"],
    )
    reminder_id = created.json()["id"]

    skipped = await async_client.post(
        f"/reminders/{reminder_id}/skip",
        json={"retry_delay_seconds": 1800},
        headers=session["headers"],
    )

    assert skipped.status_code == 200
    data = skipped.json()
    assert data["status"] == "skipped"
    assert data["skip_count"] == 1
    assert data["retry_delay_seconds"] == 1800
    assert disable_rabbitmq_publish[-1][0] == reminder_id
    assert 1700 <= disable_rabbitmq_publish[-1][1] <= 1800

    current = await async_client.get("/reminders/current", headers=session["headers"])
    assert current.json() == []


@pytest.mark.asyncio
async def test_complete_reminder_removes_it_from_current(async_client):
    session = await reg_and_login(async_client)
    created = await async_client.post(
        "/reminders",
        json={"title": "Track guitar"},
        headers=session["headers"],
    )
    reminder_id = created.json()["id"]

    completed = await async_client.post(
        f"/reminders/{reminder_id}/complete",
        headers=session["headers"],
    )

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None
    current = await async_client.get("/reminders/current", headers=session["headers"])
    assert current.json() == []


@pytest.mark.asyncio
async def test_answer_completion_completes_active_form_reminders(
    async_client, disable_rabbitmq_publish
):
    session = await reg_and_login(async_client)
    form = await async_client.post(
        "/forms",
        json={
            "title": "Guitar practice",
            "form_structure": {"fields": [{"name": "minutes", "type": "number"}]},
            "schedule_crons": [],
        },
        headers=session["headers"],
    )
    assert form.status_code == 201
    form_id = form.json()["form_id"]
    reminder = await async_client.post(
        "/reminders",
        json={
            "title": "How long did you play guitar?",
            "form_id": form_id,
            "payload": {"activity": "guitar"},
            "retry_delay_seconds": 3600,
        },
        headers=session["headers"],
    )
    assert reminder.status_code == 201
    reminder_id = reminder.json()["id"]

    answer = await async_client.post(
        f"/forms/{form_id}/answers",
        json={"answers_data": {"minutes": 45}},
        headers=session["headers"],
    )

    assert answer.status_code == 201
    assert answer.json()["completed_reminder_ids"] == [reminder_id]
    current = await async_client.get("/reminders/current", headers=session["headers"])
    assert current.json() == []


def test_parse_schedule_interval_seconds():
    assert parse_schedule_interval_seconds("@every 30m") == 1800
    assert parse_schedule_interval_seconds("@every 1h") == 3600
    assert parse_schedule_interval_seconds("@every 1d") == 86400
    assert parse_schedule_interval_seconds("*/15 * * * *") == 900
    assert parse_schedule_interval_seconds("0 9 * * *") is None


@pytest.mark.asyncio
async def test_form_scheduler_creates_reminder_and_prevents_duplicates(
    async_client, db_session, disable_rabbitmq_publish
):
    session = await reg_and_login(async_client)
    form = await async_client.post(
        "/forms",
        json={
            "title": "Guitar practice",
            "form_structure": {"fields": [{"name": "minutes", "type": "number"}]},
            "schedule_crons": ["@every 1h"],
            "reminder_enabled": True,
            "reminder_title": "How long did you play guitar?",
            "reminder_payload": {"activity": "guitar"},
            "skip_retry_delay_seconds": 1800,
            "delivery_retry_delay_seconds": 900,
        },
        headers=session["headers"],
    )
    assert form.status_code == 201

    service = ReminderService(db_session)
    created = await service.create_due_form_reminders(datetime.now(UTC))
    duplicate = await service.create_due_form_reminders(datetime.now(UTC) + timedelta(hours=2))

    assert len(created) == 1
    assert duplicate == []
    assert created[0].title == "How long did you play guitar?"
    assert created[0].payload == {"activity": "guitar"}
    assert created[0].retry_delay_seconds == 1800
    assert created[0].delivery_retry_delay_seconds == 900
    assert disable_rabbitmq_publish[-1] == (created[0].id, 0)


@pytest.mark.asyncio
async def test_requeue_stale_pending_reminders(async_client, db_session, disable_rabbitmq_publish):
    session = await reg_and_login(async_client)
    created = await async_client.post(
        "/reminders",
        json={
            "title": "Track guitar",
            "retry_delay_seconds": 3600,
        },
        headers=session["headers"],
    )
    reminder_id = created.json()["id"]
    reminder = (
        await db_session.execute(select(Reminder).where(Reminder.id == reminder_id))
    ).scalar_one()
    reminder.last_delivered_at = datetime.now(UTC) - timedelta(hours=2)
    reminder.delivery_retry_delay_seconds = 3600
    await db_session.commit()

    requeued = await ReminderService(db_session).requeue_stale_pending_reminders(datetime.now(UTC))

    assert [reminder.id for reminder in requeued] == [reminder_id]
    assert disable_rabbitmq_publish[-1] == (reminder_id, 0)


@pytest.mark.asyncio
async def test_due_in_seconds_delays_current_reminder(async_client, db_session):
    session = await reg_and_login(async_client)
    created = await async_client.post(
        "/reminders",
        json={"title": "Track guitar", "due_in_seconds": 3600},
        headers=session["headers"],
    )
    reminder_id = created.json()["id"]

    current = await async_client.get("/reminders/current", headers=session["headers"])
    assert current.json() == []

    reminder = (
        await db_session.execute(select(Reminder).where(Reminder.id == reminder_id))
    ).scalar_one()
    reminder.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    due = await async_client.get("/reminders/current", headers=session["headers"])
    assert [reminder["id"] for reminder in due.json()] == [reminder_id]
