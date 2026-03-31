FROM python:3.12-slim


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.3.2 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /code

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./


RUN poetry install --only main --no-interaction --no-ansi --no-root

COPY ./app /code/app
COPY ./db /code/db

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]