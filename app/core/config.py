import os


TRUTHY = {"1", "true", "yes"}


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").lower() in {"prod", "production"}


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    if not raw:
        return [] if is_production() else ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def validate_production_config() -> None:
    if not is_production():
        return

    required = [
        "SECRET_KEY",
        "DATABASE_URL",
        "RABBITMQ_URL",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing production environment variables: {', '.join(missing)}")

    if not cors_origins():
        raise RuntimeError("CORS_ORIGINS must be configured in production")

    if os.getenv("COOKIE_SECURE", "false").lower() not in TRUTHY:
        raise RuntimeError("COOKIE_SECURE must be true in production")
