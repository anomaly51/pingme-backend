from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.user_model import Reminder
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
