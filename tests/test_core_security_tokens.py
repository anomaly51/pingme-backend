import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security
from app.core.security import (
    create_access_token,
    create_confirmation_token,
    create_refresh_token,
    decode_app_token,
    get_password_hash,
    verify_confirmation_token,
    verify_password,
    verify_token,
)


def test_password_hash_verifies_original_password():
    hashed = get_password_hash("Strongpassword123")
    assert verify_password("Strongpassword123", hashed) is True


def test_password_hash_rejects_wrong_password():
    hashed = get_password_hash("Strongpassword123")
    assert verify_password("Wrongpassword123", hashed) is False


def test_access_token_contains_access_type_and_subject():
    token = create_access_token({"sub": "user@example.com"})
    payload = decode_app_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["iss"] == security.JWT_ISSUER
    assert payload["aud"] == security.JWT_AUDIENCE
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload
    assert jwt.get_unverified_header(token)["kid"] == security.JWT_KEY_ID


def test_refresh_token_contains_refresh_type_and_subject():
    token = create_refresh_token({"sub": "user@example.com"})
    payload = decode_app_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["type"] == "refresh"
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_tokens_have_unique_jti_values():
    first = decode_app_token(create_access_token({"sub": "user@example.com"}))
    second = decode_app_token(create_access_token({"sub": "user@example.com"}))
    assert first["jti"] != second["jti"]


def test_decode_app_token_rejects_missing_key_id():
    token = jwt.encode(
        {
            "sub": "no-kid@example.com",
            "iss": security.JWT_ISSUER,
            "aud": security.JWT_AUDIENCE,
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": time.time(),
            "jti": "no-kid-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={},
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_app_token(token)


def test_decode_app_token_rejects_wrong_issuer():
    token = jwt.encode(
        {
            "sub": "wrong-issuer@example.com",
            "iss": "other-api",
            "aud": security.JWT_AUDIENCE,
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": time.time(),
            "jti": "wrong-issuer-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={"kid": security.JWT_KEY_ID},
    )
    with pytest.raises(jwt.InvalidIssuerError):
        decode_app_token(token)


def test_decode_app_token_rejects_wrong_audience():
    token = jwt.encode(
        {
            "sub": "wrong-audience@example.com",
            "iss": security.JWT_ISSUER,
            "aud": "other-client",
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": time.time(),
            "jti": "wrong-audience-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={"kid": security.JWT_KEY_ID},
    )
    with pytest.raises(jwt.InvalidAudienceError):
        decode_app_token(token)


def test_decode_app_token_rejects_missing_issuer_and_audience():
    token = jwt.encode(
        {
            "sub": "legacy@example.com",
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": time.time(),
            "jti": "legacy-token-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={"kid": security.JWT_KEY_ID},
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_app_token(token)


def test_verify_token_returns_none_for_expired_token():
    token = jwt.encode(
        {
            "sub": "expired@example.com",
            "iss": security.JWT_ISSUER,
            "aud": security.JWT_AUDIENCE,
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
            "iat": time.time(),
            "jti": "expired-token-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={"kid": security.JWT_KEY_ID},
    )
    assert verify_token(token) is None


def test_verify_token_returns_none_for_malformed_token():
    assert verify_token("not.a.jwt") is None


def test_decode_app_token_rejects_unknown_key_id():
    token = jwt.encode(
        {
            "sub": "unknown-kid@example.com",
            "iss": security.JWT_ISSUER,
            "aud": security.JWT_AUDIENCE,
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": time.time(),
            "jti": "unknown-kid-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={"kid": "missing-key"},
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_app_token(token)


def test_confirmation_token_verifies_email():
    token = create_confirmation_token("confirm@example.com")
    assert verify_confirmation_token(token) == "confirm@example.com"


def test_confirmation_verifier_rejects_access_token():
    token = create_access_token({"sub": "user@example.com"})
    assert verify_confirmation_token(token) is None


def test_confirmation_verifier_returns_expired_for_expired_token():
    token = jwt.encode(
        {
            "sub": "expired-confirm@example.com",
            "iss": security.JWT_ISSUER,
            "aud": security.JWT_AUDIENCE,
            "type": "confirmation",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
            "iat": time.time(),
            "jti": "expired-confirm-jti",
        },
        security.JWT_SECRET_KEY,
        algorithm=security.ALGORITHM,
        headers={"kid": security.JWT_KEY_ID},
    )
    assert verify_confirmation_token(token) == "expired"
