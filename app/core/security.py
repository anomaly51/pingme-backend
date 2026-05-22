import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from jwt import PyJWTError
from passlib.context import CryptContext


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=4 if os.getenv("TESTING") == "True" else 12,
)

SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-change-me-secret-key-32chars"
if os.getenv("ENVIRONMENT", "development").lower() in {"prod", "production"} and not os.getenv(
    "SECRET_KEY"
):
    raise RuntimeError("SECRET_KEY environment variable is required in production")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or SECRET_KEY
JWT_SECRET_KEYS = os.getenv("JWT_SECRET_KEYS")
JWT_KEY_ID = os.getenv("JWT_KEY_ID", "default")
JWT_ISSUER = os.getenv("JWT_ISSUER", "project-root-api")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "project-root-client")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))


def _jwt_headers() -> dict[str, str]:
    return {"kid": JWT_KEY_ID}


def _jwt_claims() -> dict[str, str]:
    return {"iss": JWT_ISSUER, "aud": JWT_AUDIENCE}


def _jwt_key_ring() -> dict[str, str]:
    if JWT_SECRET_KEYS:
        parsed = json.loads(JWT_SECRET_KEYS)
        if not isinstance(parsed, dict) or not parsed:
            raise jwt.InvalidTokenError("JWT_SECRET_KEYS must be a non-empty JSON object")
        return {str(kid): str(secret) for kid, secret in parsed.items()}

    return {JWT_KEY_ID: JWT_SECRET_KEY}


def _get_decode_key(token: str) -> str:
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if not kid:
        raise jwt.InvalidTokenError("JWT header does not contain kid")

    try:
        return _jwt_key_ring()[kid]
    except KeyError:
        raise jwt.InvalidTokenError("Unknown JWT kid") from None


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update(
        {
            **_jwt_claims(),
            "exp": expire,
            "iat": time.time(),
            "type": "access",
            "jti": uuid.uuid4().hex,
        }
    )
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM, headers=_jwt_headers())


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update(
        {
            **_jwt_claims(),
            "exp": expire,
            "iat": time.time(),
            "type": "refresh",
            "jti": uuid.uuid4().hex,
        }
    )
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM, headers=_jwt_headers())


def create_confirmation_token(email: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode = {
        **_jwt_claims(),
        "sub": email,
        "exp": expire,
        "iat": time.time(),
        "type": "confirmation",
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM, headers=_jwt_headers())


def decode_app_token(token: str) -> dict:
    return jwt.decode(
        token,
        _get_decode_key(token),
        algorithms=[ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["exp", "iss", "aud", "sub", "type", "jti"]},
    )


def verify_confirmation_token(token: str) -> str | None:
    try:
        payload = decode_app_token(token)
        if payload.get("type") != "confirmation":
            return None
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return "expired"
    except jwt.PyJWTError:
        return None


def verify_token(token: str) -> str | None:
    try:
        payload = decode_app_token(token)
        return payload.get("sub")
    except PyJWTError:
        return None
