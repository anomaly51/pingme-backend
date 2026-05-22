from datetime import UTC, datetime, timedelta

import jwt

from app.core import security


def test_access_token_default_lifetime_is_30_days() -> None:
    assert security.ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 24 * 30


def test_create_access_token_expires_in_30_days(monkeypatch) -> None:
    monkeypatch.setattr(security, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(security, "ALGORITHM", "HS256")
    monkeypatch.setattr(security, "ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 30)

    issued_at = datetime.now(UTC)
    token = security.create_access_token({"sub": "user@example.com"})
    payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
    expires_at = datetime.fromtimestamp(payload["exp"], UTC)

    assert payload["sub"] == "user@example.com"
    assert timedelta(days=29, hours=23, minutes=59) <= expires_at - issued_at <= timedelta(
        days=30, minutes=1
    )
