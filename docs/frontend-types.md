# Frontend types

Generate the current OpenAPI schema with:

```bash
poetry run python scripts/export_openapi.py
```

Then generate a TypeScript client in the frontend repo with any OpenAPI-compatible tool, for example:

```bash
npx openapi-typescript docs/openapi.json -o src/api/types.ts
```

The backend source of truth is `docs/openapi.json`, generated from FastAPI route schemas.
