# Resolved Dependency Versions

Source of truth is the lockfiles (`apps/api/uv.lock`, `apps/web/package-lock.json`).
This table records the direct dependencies as resolved and verified together.

Last verified: 2026-10-28 (Sprint 0) — lint, typecheck, tests and Docker builds passing.

## Runtime / infrastructure

| Component | Version |
|---|---|
| Python (container / local via uv) | 3.13 |
| Node.js | 24 LTS |
| PostgreSQL | 17 (alpine image) |
| uv | 0.13 |

## Backend (`apps/api`)

| Package | Version |
|---|---|
| fastapi | 0.162.0 |
| uvicorn[standard] | 0.54.0 |
| pydantic | 2.14.1 |
| pydantic-settings | 2.16.2 |
| sqlalchemy[asyncio] | 2.1.6 |
| psycopg[binary] | 3.3.6 |
| pytest (dev) | 9.2.0 |
| httpx (dev) | 0.28.1 |
| ruff (dev) | 0.17.3 |
| mypy (dev) | 2.4.0 |

Added in Sprint 1 (to be recorded here when resolved): alembic, langgraph,
langgraph-checkpoint-postgres, argon2-cffi, openai, opentelemetry packages.

## Web (`apps/web`)

| Package | Version |
|---|---|
| next | 16.4.3 |
| react / react-dom | 19.3.0 |
| tailwindcss | 4.3.3 |
| typescript | 5.9.3 |
| eslint | 9.39.5 |

## Known notes

- Starlette warns that using `httpx` with its `TestClient` is deprecated in favour of
  `httpx2`. Harmless today; revisit when upgrading Starlette/FastAPI.
- On Windows hosts, psycopg async requires a `SelectorEventLoop`; handled in
  `agent_hq.cli` and `tests/conftest.py`. Containers (Linux) are unaffected.
