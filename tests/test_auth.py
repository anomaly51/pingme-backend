import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core import security
from app.core.security import create_refresh_token, decode_app_token
from app.models.user_model import AuthSession, BlockedToken, EmailAuthCode, User
from app.services.auth_service import AuthService
from tests.conftest import (
    TEST_PASSWORD,
    _session_maker,
    login_user,
    make_admin,
    make_customer,
    make_manager,
    reg_and_login,
    register_user,
)


def encode_test_token(payload: dict, secret: str | None = None, headers: dict | None = None) -> str:
    claims = {
        "iss": security.JWT_ISSUER,
        "aud": security.JWT_AUDIENCE,
        **payload,
    }
    return jwt.encode(
        claims,
        secret or security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers=headers if headers is not None else {"kid": security.JWT_KEY_ID},
    )


@pytest.mark.asyncio
async def test_register_success(async_client):
    email = f"u_{uuid.uuid4().hex}@test.com"
    response = await async_client.post(
        "/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert "id" in data
    assert data["roles"] == ["customer"]
    assert data["is_email_confirmed"] is False
    assert "created_at" in data
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_400(async_client):
    email = f"u_{uuid.uuid4().hex}@test.com"
    await async_client.post("/auth/register", json={"email": email, "password": TEST_PASSWORD})
    response = await async_client.post(
        "/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 400
    assert "detail" in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("notanemail", TEST_PASSWORD),
        ("", TEST_PASSWORD),
        ("   ", TEST_PASSWORD),
        ("valid@test.com", "lowercase123"),
        ("valid@test.com", "NoDigitsHere"),
        ("valid@test.com", "123"),
    ],
)
async def test_register_validation_returns_422(async_client, email, password):
    response = await async_client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_user_saved_in_db(async_client):
    email = f"u_{uuid.uuid4().hex}@test.com"
    await async_client.post("/auth/register", json={"email": email, "password": TEST_PASSWORD})
    async with _session_maker() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()

    assert user.hashed_password != TEST_PASSWORD
    assert "customer" in user.roles


@pytest.mark.asyncio
async def test_register_sends_email_verification_code(monkeypatch, async_client):
    sent_codes: list[tuple[str, str]] = []

    def fake_send(email: str, code: str) -> None:
        sent_codes.append((email, code))

    monkeypatch.setattr("app.services.auth_service.send_email_verification_code", fake_send)
    email = f"verify_{uuid.uuid4().hex}@test.com"

    response = await async_client.post(
        "/auth/register", json={"email": email, "password": TEST_PASSWORD}
    )

    assert response.status_code == 201
    assert sent_codes == [(email, sent_codes[0][1])]
    assert sent_codes[0][1].isdigit()
    assert len(sent_codes[0][1]) == 6


@pytest.mark.asyncio
async def test_confirm_email_with_code(monkeypatch, async_client):
    sent_codes: list[str] = []

    def fake_send(_email: str, code: str) -> None:
        sent_codes.append(code)

    monkeypatch.setattr("app.services.auth_service.send_email_verification_code", fake_send)
    email = f"confirm_{uuid.uuid4().hex}@test.com"
    await register_user(async_client, email=email)

    response = await async_client.post(
        "/auth/verify-email/confirm",
        json={"email": email, "code": sent_codes[-1]},
    )

    assert response.status_code == 200
    async with _session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        assert user.is_email_confirmed is True
        code = (
            await db.execute(select(EmailAuthCode).where(EmailAuthCode.email == email))
        ).scalar_one()
        assert code.used_at is not None


@pytest.mark.asyncio
async def test_request_email_verification_code_is_generic_for_missing_user(async_client):
    response = await async_client.post(
        "/auth/verify-email/request",
        json={"email": f"missing_{uuid.uuid4().hex}@test.com"},
    )

    assert response.status_code == 200
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_login_success_returns_tokens(async_client):
    user = await register_user(async_client)
    response = await async_client.post(
        "/auth/login",
        data={"username": user["email"], "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(async_client):
    user = await register_user(async_client)
    response = await async_client.post(
        "/auth/login",
        data={"username": user["email"], "password": "WrongPass999"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unconfirmed_email_returns_403(async_client):
    user = await register_user(async_client, confirm_email=False)
    response = await async_client.post(
        "/auth/login",
        data={"username": user["email"], "password": TEST_PASSWORD},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401(async_client):
    response = await async_client.post(
        "/auth/login",
        data={
            "username": f"ghost_{uuid.uuid4().hex}@nowhere.com",
            "password": "Whatever123",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{"password": TEST_PASSWORD}, {"username": "test@test.com"}, {}])
async def test_login_missing_form_fields_returns_422(async_client, data):
    response = await async_client.post("/auth/login", data=data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_multiple_times_generates_unique_tokens(async_client):
    user = await register_user(async_client)
    tokens = set()
    for _ in range(4):
        session = await login_user(async_client, user["email"])
        tokens.add(session["access_token"])

    assert len(tokens) == 4


@pytest.mark.asyncio
async def test_jwt_payload_has_expected_auth_claims(async_client):
    session = await reg_and_login(async_client)
    access = decode_app_token(session["access_token"])
    refresh = decode_app_token(session["refresh_token"])
    assert access["sub"] == session["email"]
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"
    assert refresh["exp"] > access["exp"]
    assert "jti" in access
    assert "iat" in access
    assert "password" not in access
    assert jwt.get_unverified_header(session["access_token"])["alg"] == "HS256"


@pytest.mark.asyncio
async def test_admin_can_assign_manager_role_by_email(async_client):
    admin = await make_admin()
    target = await register_user(async_client)
    response = await async_client.post(
        "/auth/assign-manager",
        json={"email": target["email"]},
        headers=admin["headers"],
    )
    assert response.status_code == 200
    assert "manager" in response.json()["roles"]
    assert "admin" not in response.json()["roles"]


@pytest.mark.asyncio
async def test_manager_cannot_assign_manager_role(async_client):
    manager = await make_manager()
    target = await register_user(async_client)
    response = await async_client.post(
        "/auth/assign-manager",
        json={"email": target["email"]},
        headers=manager["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_assignment_also_grants_manager_role_and_is_idempotent(async_client):
    admin = await make_admin()
    target = await register_user(async_client)
    for _ in range(2):
        response = await async_client.post(
            "/auth/assign-admin",
            json={"email": target["email"]},
            headers=admin["headers"],
        )
        assert response.status_code == 200

    roles = response.json()["roles"]
    assert roles.count("admin") == 1
    assert roles.count("manager") == 1


@pytest.mark.asyncio
async def test_assign_manager_missing_user_returns_400(async_client):
    admin = await make_admin()
    response = await async_client.post(
        "/auth/assign-manager",
        json={"email": f"missing_{uuid.uuid4().hex}@test.com"},
        headers=admin["headers"],
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_login_creates_confirmed_customer(monkeypatch, async_client):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(
        AuthService,
        "_verify_google_id_token",
        staticmethod(
            lambda _token, _client_id: {
                "aud": "google-client-id",
                "email": "google_user@test.com",
                "email_verified": "true",
            }
        ),
    )
    response = await async_client.post(
        "/auth/google",
        json={"id_token": "valid-google-id-token"},
    )
    assert response.status_code == 200
    me = await async_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "google_user@test.com"
    assert me.json()["is_email_confirmed"] is True
    assert me.json()["roles"] == ["customer"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"aud": "other-client-id", "email": "google_user@test.com", "email_verified": "true"},
        {"aud": "google-client-id", "email": "google_user@test.com", "email_verified": "false"},
        {"aud": "google-client-id", "email_verified": "true"},
    ],
)
async def test_google_login_rejects_invalid_payloads(monkeypatch, async_client, payload):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(
        AuthService,
        "_verify_google_id_token",
        staticmethod(lambda _token, _client_ids: payload),
    )
    response = await async_client.post(
        "/auth/google",
        json={"id_token": "invalid-google-id-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_google_login_returns_400_when_not_configured(monkeypatch, async_client):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_IDS", raising=False)
    response = await async_client.post(
        "/auth/google",
        json={"id_token": "valid-google-id-token"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_login_supports_multiple_client_ids(monkeypatch, async_client):
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "web-client-id,ios-client-id")
    monkeypatch.setattr(
        AuthService,
        "_verify_google_id_token",
        staticmethod(
            lambda _token, _client_ids: {
                "aud": "ios-client-id",
                "email": "google_multi@test.com",
                "email_verified": True,
            }
        ),
    )
    response = await async_client.post(
        "/auth/google",
        json={"id_token": "valid-google-id-token"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_google_login_confirms_existing_unconfirmed_user(monkeypatch, async_client):
    user = await register_user(
        async_client,
        email=f"google_existing_{uuid.uuid4().hex}@test.com",
        confirm_email=False,
    )
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(
        AuthService,
        "_verify_google_id_token",
        staticmethod(
            lambda _token, _client_ids: {
                "aud": "google-client-id",
                "email": user["email"],
                "email_verified": True,
            }
        ),
    )
    response = await async_client.post(
        "/auth/google",
        json={"id_token": "valid-google-id-token"},
    )
    assert response.status_code == 200

    async with _session_maker() as db:
        existing = (await db.execute(select(User).where(User.email == user["email"]))).scalar_one()
        assert existing.is_email_confirmed is True


@pytest.mark.asyncio
async def test_invalid_token_returns_401(async_client):
    response = await async_client.get(
        "/auth/me", headers={"Authorization": "Bearer totally.invalid.token"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(async_client):
    token = encode_test_token(
        {
            "sub": "nobody@test.com",
            "type": "access",
            "exp": int(time.time()) - 10,
            "jti": uuid.uuid4().hex,
        }
    )
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_as_access_returns_401(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {session['refresh_token']}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_token_without_jti_returns_401(async_client):
    session = await reg_and_login(async_client)
    token = encode_test_token(
        {
            "sub": session["email"],
            "type": "access",
            "exp": int(time.time()) + 3600,
        }
    )
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_token_with_wrong_issuer_returns_401(async_client):
    session = await reg_and_login(async_client)
    token = encode_test_token(
        {
            "sub": session["email"],
            "type": "access",
            "iss": "other-api",
            "exp": int(time.time()) + 3600,
            "jti": uuid.uuid4().hex,
        }
    )
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_token_without_kid_returns_401(async_client):
    session = await reg_and_login(async_client)
    token = encode_test_token(
        {
            "sub": session["email"],
            "type": "access",
            "exp": int(time.time()) + 3600,
            "jti": uuid.uuid4().hex,
        },
        headers={},
    )
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_nonexistent_user_returns_401(async_client):
    token = encode_test_token(
        {
            "sub": f"ghost_{uuid.uuid4().hex}@nowhere.com",
            "type": "access",
            "exp": int(time.time()) + 3600,
            "jti": uuid.uuid4().hex,
        }
    )
    response = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_blocks_access_and_refresh_tokens(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.post(
        "/auth/logout",
        json={"refresh_token": session["refresh_token"]},
        headers=session["headers"],
    )
    assert response.status_code == 200
    assert (await async_client.get("/auth/me", headers=session["headers"])).status_code == 401

    async with _session_maker() as db:
        access_jti = decode_app_token(session["access_token"])["jti"]
        refresh_jti = decode_app_token(session["refresh_token"])["jti"]
        blocked = (
            (
                await db.execute(
                    select(BlockedToken.token).where(
                        BlockedToken.token.in_([access_jti, refresh_jti])
                    )
                )
            )
            .scalars()
            .all()
        )

    assert set(blocked) == {access_jti, refresh_jti}


@pytest.mark.asyncio
async def test_double_logout_returns_401(async_client):
    session = await reg_and_login(async_client)
    await async_client.post(
        "/auth/logout",
        json={"refresh_token": session["refresh_token"]},
        headers=session["headers"],
    )
    response = await async_client.post(
        "/auth/logout",
        json={"refresh_token": session["refresh_token"]},
        headers=session["headers"],
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_invalid_refresh_token_still_blocks_access(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.post(
        "/auth/logout",
        json={"refresh_token": "not-a-real-token"},
        headers=session["headers"],
    )
    assert response.status_code == 200
    assert (await async_client.get("/auth/me", headers=session["headers"])).status_code == 401


@pytest.mark.asyncio
async def test_logout_a_does_not_affect_session_b(async_client):
    first = await reg_and_login(async_client)
    second = await reg_and_login(async_client)
    await async_client.post(
        "/auth/logout",
        json={"refresh_token": first["refresh_token"]},
        headers=first["headers"],
    )
    response = await async_client.get("/auth/me", headers=second["headers"])
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_returns_new_token_pair_and_rotates_refresh(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"] != session["access_token"]
    assert data["refresh_token"] != session["refresh_token"]

    reused = await async_client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_replayed_jti(async_client):
    session = await reg_and_login(async_client)
    payload = decode_app_token(session["refresh_token"])
    first = await async_client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    assert first.status_code == 200
    replay_token = encode_test_token(
        {
            "sub": payload["sub"],
            "type": "refresh",
            "iat": time.time(),
            "exp": datetime.now(UTC) + timedelta(days=7),
            "jti": payload["jti"],
        }
    )
    replay = await async_client.post("/auth/refresh", json={"refresh_token": replay_token})
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_concurrent_refresh_allows_only_one_rotation(async_client):
    session = await reg_and_login(async_client)
    responses = await asyncio.gather(
        async_client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]}),
        async_client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]}),
    )
    assert sorted(response.status_code for response in responses) == [200, 401]


@pytest.mark.asyncio
async def test_refresh_invalid_inputs_return_errors(async_client):
    session = await reg_and_login(async_client)
    invalid = await async_client.post("/auth/refresh", json={"refresh_token": "garbage.token"})
    access = await async_client.post(
        "/auth/refresh", json={"refresh_token": session["access_token"]}
    )
    missing = await async_client.post("/auth/refresh", json={})
    assert invalid.status_code == 401
    assert access.status_code == 401
    assert missing.status_code == 200


@pytest.mark.asyncio
async def test_refresh_token_rejected_after_password_change(async_client):
    user = await make_customer()
    old_refresh_token = create_refresh_token({"sub": user["email"]})
    change = await async_client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "NewPass999"},
        headers=user["headers"],
    )
    assert change.status_code == 200
    response = await async_client.post(
        "/auth/refresh",
        json={"refresh_token": old_refresh_token},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_change_password_success_and_login_with_new_password(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "NewPassword123"},
        headers=session["headers"],
    )
    assert response.status_code == 200

    old_login = await async_client.post(
        "/auth/login",
        data={"username": session["email"], "password": TEST_PASSWORD},
    )
    new_login = await async_client.post(
        "/auth/login",
        data={"username": session["email"], "password": "NewPassword123"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_change_password_validation_and_auth_errors(async_client):
    session = await reg_and_login(async_client)
    wrong_old = await async_client.post(
        "/auth/change-password",
        json={"old_password": "WrongOldPass999", "new_password": "NewPassword123"},
        headers=session["headers"],
    )
    no_upper = await async_client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "lowercase123"},
        headers=session["headers"],
    )
    no_auth = await async_client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "NewPassword123"},
    )
    assert wrong_old.status_code == 401
    assert no_upper.status_code == 422
    assert no_auth.status_code == 401


@pytest.mark.asyncio
async def test_change_password_invalidates_current_token(async_client):
    session = await reg_and_login(async_client)
    assert (await async_client.get("/auth/me", headers=session["headers"])).status_code == 200
    await async_client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "NewPassword123"},
        headers=session["headers"],
    )
    response = await async_client.get("/auth/me", headers=session["headers"])
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_code_changes_password(monkeypatch, async_client):
    sent_codes: list[str] = []

    def fake_send(_email: str, code: str) -> None:
        sent_codes.append(code)

    monkeypatch.setattr("app.services.auth_service.send_password_reset_code", fake_send)
    user = await register_user(async_client)

    request = await async_client.post(
        "/auth/password-reset/request",
        json={"email": user["email"]},
    )
    assert request.status_code == 200
    assert sent_codes

    confirm = await async_client.post(
        "/auth/password-reset/confirm",
        json={
            "email": user["email"],
            "code": sent_codes[-1],
            "new_password": "ResetPass123",
        },
    )
    assert confirm.status_code == 200

    old_login = await async_client.post(
        "/auth/login",
        data={"username": user["email"], "password": TEST_PASSWORD},
    )
    new_login = await async_client.post(
        "/auth/login",
        data={"username": user["email"], "password": "ResetPass123"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_request_is_generic_for_missing_user(async_client):
    response = await async_client.post(
        "/auth/password-reset/request",
        json={"email": f"missing_{uuid.uuid4().hex}@test.com"},
    )

    assert response.status_code == 200
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_password_reset_rejects_reused_code(monkeypatch, async_client):
    sent_codes: list[str] = []

    def fake_send(_email: str, code: str) -> None:
        sent_codes.append(code)

    monkeypatch.setattr("app.services.auth_service.send_password_reset_code", fake_send)
    user = await register_user(async_client)
    await async_client.post("/auth/password-reset/request", json={"email": user["email"]})

    first = await async_client.post(
        "/auth/password-reset/confirm",
        json={
            "email": user["email"],
            "code": sent_codes[-1],
            "new_password": "ResetPass123",
        },
    )
    second = await async_client.post(
        "/auth/password-reset/confirm",
        json={
            "email": user["email"],
            "code": sent_codes[-1],
            "new_password": "ResetPass456",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_password_reset_locks_code_after_too_many_attempts(monkeypatch, async_client):
    sent_codes: list[str] = []

    def fake_send(_email: str, code: str) -> None:
        sent_codes.append(code)

    monkeypatch.setattr("app.services.auth_service.send_password_reset_code", fake_send)
    user = await register_user(async_client)
    await async_client.post("/auth/password-reset/request", json={"email": user["email"]})

    for _ in range(5):
        response = await async_client.post(
            "/auth/password-reset/confirm",
            json={
                "email": user["email"],
                "code": "000000",
                "new_password": "ResetPass123",
            },
        )
        assert response.status_code == 400

    locked = await async_client.post(
        "/auth/password-reset/confirm",
        json={
            "email": user["email"],
            "code": sent_codes[-1],
            "new_password": "ResetPass123",
        },
    )
    assert locked.status_code == 400


@pytest.mark.asyncio
async def test_login_cleans_expired_blocked_tokens(async_client):
    user = await register_user(async_client)
    async with _session_maker() as db:
        db.add(
            BlockedToken(
                token=uuid.uuid4().hex,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await db.commit()

    response = await async_client.post(
        "/auth/login",
        data={"username": user["email"], "password": TEST_PASSWORD},
    )
    assert response.status_code == 200

    async with _session_maker() as db:
        count = (
            (
                await db.execute(
                    select(BlockedToken).where(BlockedToken.expires_at <= datetime.now(UTC))
                )
            )
            .scalars()
            .all()
        )
        assert count == []


@pytest.mark.asyncio
async def test_get_me_returns_user_data(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.get("/auth/me", headers=session["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == session["email"]
    assert isinstance(data["id"], int)
    assert "customer" in data["roles"]
    assert "created_at" in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_legacy_users_me_routes_work(async_client):
    session = await reg_and_login(async_client)
    response = await async_client.get("/users/me", headers=session["headers"])
    secrets = await async_client.get("/users/me/secrets", headers=session["headers"])
    assert response.status_code == 200
    assert response.json()["email"] == session["email"]
    assert secrets.status_code == 200


@pytest.mark.asyncio
async def test_get_me_without_auth_returns_401(async_client):
    response = await async_client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_multiple_sessions_same_user(async_client):
    user = await register_user(async_client)
    first = await login_user(async_client, user["email"])
    second = await login_user(async_client, user["email"])
    assert (await async_client.get("/auth/me", headers=first["headers"])).status_code == 200
    assert (await async_client.get("/auth/me", headers=second["headers"])).status_code == 200
    await async_client.post(
        "/auth/logout",
        json={"refresh_token": first["refresh_token"]},
        headers=first["headers"],
    )
    assert (await async_client.get("/auth/me", headers=first["headers"])).status_code == 401
    assert (await async_client.get("/auth/me", headers=second["headers"])).status_code == 200


@pytest.mark.asyncio
async def test_sessions_can_be_listed_and_revoked(async_client):
    session = await reg_and_login(async_client)
    sessions = await async_client.get("/auth/sessions", headers=session["headers"])
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    assert sessions.json()[0]["current"] is True

    revoke = await async_client.delete(
        f"/auth/sessions/{sessions.json()[0]['session_id']}",
        headers=session["headers"],
    )
    assert revoke.status_code == 200

    response = await async_client.get("/auth/me", headers=session["headers"])
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_revoke_other_sessions_keeps_current_session(async_client):
    user = await register_user(async_client)
    first = await login_user(async_client, user["email"])
    second = await login_user(async_client, user["email"])

    response = await async_client.delete("/auth/sessions", headers=second["headers"])
    assert response.status_code == 200

    assert (await async_client.get("/auth/me", headers=first["headers"])).status_code == 401
    assert (await async_client.get("/auth/me", headers=second["headers"])).status_code == 200

    async with _session_maker() as db:
        sessions = (
            (await db.execute(select(AuthSession).where(AuthSession.user_id == user["id"])))
            .scalars()
            .all()
        )
        assert len(sessions) == 2
        assert sum(session.revoked_at is not None for session in sessions) == 1


@pytest.mark.asyncio
async def test_password_changed_at_updated_in_db(async_client):
    session = await reg_and_login(async_client)
    async with _session_maker() as db:
        user = (await db.execute(select(User).where(User.email == session["email"]))).scalar_one()
        assert user.password_changed_at is None

    await async_client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "NewPass999"},
        headers=session["headers"],
    )
    async with _session_maker() as db:
        user = (await db.execute(select(User).where(User.email == session["email"]))).scalar_one()
        assert user.password_changed_at is not None
        assert user.password_changed_at > datetime.now(UTC) - timedelta(seconds=10)
