import os


TRUTHY = {"1", "true", "yes"}


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").lower() in {"prod", "production"}


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    if not raw:
        if is_production():
            return []
        return [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def cors_allow_credentials() -> bool:
    return "*" not in cors_origins()


def validate_production_config() -> None:
    if not is_production():
        return

    required = [
        "DATABASE_URL",
        "RABBITMQ_URL",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing production environment variables: {', '.join(missing)}")

    if not os.getenv("SECRET_KEY") and not os.getenv("JWT_SECRET_KEYS"):
        raise RuntimeError("SECRET_KEY or JWT_SECRET_KEYS must be configured in production")

    if not cors_origins():
        raise RuntimeError("CORS_ORIGINS must be configured in production")
    if "*" in cors_origins():
        raise RuntimeError("CORS_ORIGINS cannot contain '*' in production")

    if os.getenv("COOKIE_SECURE", "false").lower() not in TRUTHY:
        raise RuntimeError("COOKIE_SECURE must be true in production")
