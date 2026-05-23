#!/bin/sh
set -eu

RUN_MIGRATIONS_NORMALIZED="$(printf '%s' "${RUN_MIGRATIONS:-true}" | tr '[:upper:]' '[:lower:]')"

if [ "$RUN_MIGRATIONS_NORMALIZED" = "true" ] \
  || [ "$RUN_MIGRATIONS_NORMALIZED" = "1" ] \
  || [ "$RUN_MIGRATIONS_NORMALIZED" = "yes" ]; then
  alembic upgrade head
fi

exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
