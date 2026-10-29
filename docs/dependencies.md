# Resolved Dependency Versions

Source of truth is the lockfiles (`apps/api/uv.lock`, `apps/web/package-lock.json`).
This table records the direct dependencies as resolved and verified together.

Last verified: 2026-10-29 (Sprint 8) — lint, typecheck, 192 backend tests against
PostgreSQL 17 (including the real Docker sandbox test), web build and the full Docker
Compose stack passing. Sandbox image: python:3.13-slim + pytest 9.2.0.

## Runtime / infrastructure

| Component | Version |
|---|---|
| Python (container / local via uv) | 3.13 |
| Caddy (production edge) | 2.11 |
| Terraform (AWS provider) | ≥ 1.6 (~> 6.0) |
| Node.js | 24 LTS |
| PostgreSQL | 17 (alpine image) |
| uv | 0.13 |

## Backend (`apps/api`)

| Package | Version | Purpose |
|---|---|---|
| fastapi | 0.162.0 | HTTP API |
| uvicorn[standard] | 0.54.0 | ASGI server |
| pydantic / pydantic-settings | 2.14.1 / 2.16.2 | Contracts, configuration |
| sqlalchemy[asyncio] | 2.1.6 | ORM |
| alembic | 1.20.1 | Migrations |
| psycopg[binary] / psycopg-pool | 3.3.6 / 3.3.3 | PostgreSQL driver, pool for the checkpointer |
| langgraph | 1.2.18 | CIO workflow graph, interrupts |
| langgraph-checkpoint-postgres | 3.2.0 | Durable checkpoints |
| openai | 3.40.0 | OpenAI adapter (Chat Completions) |
| argon2-cffi | 25.1.0 | Password hashing |
| httpx | 0.28.1 | GitHub and sandbox clients, test client |
| docker | 7.2.0 | Sandbox runner only (Docker Engine API) |
| pyjwt[crypto] | 2.15.1 | GitHub App JWT (RS256) |
| pyotp | 2.10.0 | Admin TOTP 2FA |
| pytest / ruff / mypy (dev) | 9.2.0 / 0.17.3 / 2.4.0 | Quality gates |

## Web (`apps/web`)

| Package | Version |
|---|---|
| next | 16.4.3 |
| react / react-dom | 19.3.0 |
| tailwindcss | 4.3.3 |
| typescript | 5.9.3 |
| eslint | 9.39.5 |
| three | 0.186.1 |
| @react-three/fiber | 9.8.2 |
| @react-three/drei | 10.7.9 |

## Known notes

- Starlette warns that using `httpx` with its `TestClient` is deprecated in favour of
  `httpx2`. Harmless today; revisit when upgrading Starlette/FastAPI.
- On Windows hosts, psycopg async requires a `SelectorEventLoop`; handled in
  `agent_hq.cli` and `tests/conftest.py`. Containers (Linux) are unaffected.
