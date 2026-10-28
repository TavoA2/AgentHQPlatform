# Local Development

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker Desktop (WSL2 backend) | 4.x / Engine 29+ | Postgres and the full stack |
| uv | 0.13+ | Python env, tests, lint (installs Python 3.13 itself) |
| Node.js | 24 LTS | Web app |

Python does not need to be installed globally; `uv` downloads the pinned interpreter.

## Option A — everything in Docker

```bash
cp .env.example .env        # set POSTGRES_PASSWORD and AGENT_HQ_SESSION_SECRET
docker compose up --build
```

The API reloads on changes under `apps/api/src`. The web container runs a production
build; for UI work use option B for hot reload.

## Option B — database in Docker, apps on the host (recommended for daily work)

```bash
docker compose up -d db
```

Backend (from `apps/api`):

```bash
uv sync
uv run agent-hq serve --reload
```

Web (from `apps/web`):

```bash
npm install
npm run dev
```

The web app proxies `/api/*` to `API_INTERNAL_URL` (default `http://localhost:8000`).

## Verification commands

Backend, from `apps/api`:

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest
```

With the database running, also run the DB-backed tests (PowerShell:
`$env:AGENT_HQ_DATABASE_URL="..."`):

```bash
AGENT_HQ_DATABASE_URL=postgresql+psycopg://agent_hq:<password>@localhost:5432/agent_hq uv run pytest
```

Web, from `apps/web`:

```bash
npm run lint && npm run typecheck && npm run build
```

Stack smoke test:

```bash
curl -s http://localhost:8000/health/ready
```

## Notes for this machine

- The repository lives under OneDrive. `node_modules`, `.venv` and `.next` are large and
  churn constantly; exclude them from sync (OneDrive → Settings → "Choose folders", or
  move the repo outside OneDrive) to avoid slow installs and file-lock errors.
- Line endings are normalized to LF by `.gitattributes`.
