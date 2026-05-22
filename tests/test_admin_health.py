import pytest

from tests.conftest import make_admin, make_customer, reg_and_login


@pytest.mark.asyncio
async def test_admin_overview_requires_admin_or_manager(async_client):
    customer = await make_customer()

    forbidden = await async_client.get("/admin/overview", headers=customer["headers"])
    assert forbidden.status_code == 403

    admin = await make_admin()
    allowed = await async_client.get("/admin/overview", headers=admin["headers"])
    assert allowed.status_code == 200
    assert "users" in allowed.json()
    assert "reminders_by_status" in allowed.json()


@pytest.mark.asyncio
async def test_admin_can_list_users(async_client):
    await reg_and_login(async_client)
    admin = await make_admin()

    response = await async_client.get("/admin/users", headers=admin["headers"])

    assert response.status_code == 200
    assert response.json()
