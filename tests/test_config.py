import pytest

from app.core.config import validate_production_config


def test_validate_production_config_rejects_wildcard_cors(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db/app")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("COOKIE_SECURE", "true")

    with pytest.raises(RuntimeError, match="CORS_ORIGINS cannot contain"):
        validate_production_config()
