FROM python:3.12-slim


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.3.2 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VIRTUALENVS_IN_PROJECT=false

WORKDIR /code

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./

ARG INSTALL_DEV=false

RUN if [ "$INSTALL_DEV" = "true" ]; then \
        poetry install --with dev --no-interaction --no-ansi --no-root; \
    else \
        poetry install --only main --no-interaction --no-ansi --no-root; \
    fi

COPY ./app /code/app
COPY ./db /code/db
COPY ./alembic /code/alembic
COPY ./alembic.ini /code/alembic.ini
COPY ./scripts /code/scripts

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
