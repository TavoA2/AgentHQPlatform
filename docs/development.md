# Local Development

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker Desktop (WSL2 backend) | Engine 29+ | Full stack |
| uv | 0.13+ | Python env, tests, lint (installs Python 3.13 itself) |
| Node.js | 24 LTS | Web app |

## Option A — everything in Docker

```bash
cp .env.example .env        # POSTGRES_PASSWORD, AGENT_HQ_SESSION_SECRET, AGENT_HQ_GITHUB_TOKEN
docker compose up --build -d
docker compose exec api agent-hq create-admin --email you@example.com
```

Services: `db`, `migrate` (runs `alembic upgrade head` once), `api` (reloads on changes
under `apps/api/src`), `worker` (agents), `sandbox` (the only service with the Docker
socket; runs tests in throwaway containers), `sandbox-python-image` (builds the test image
and exits) and `web` (production build; use option B for UI hot reload). After changing
worker code: `docker compose restart worker`.

## Option B — database in Docker, apps on the host

```bash
docker compose up -d db
```

Backend, from `apps/api` (each in its own terminal):

```bash
uv sync
uv run agent-hq migrate
uv run agent-hq create-admin --email you@example.com
uv run agent-hq serve --reload
uv run agent-hq worker
uv run agent-hq sandbox          # needs Docker; set AGENT_HQ_SANDBOX_URL=http://127.0.0.1:8080 for the worker
```

Build the sandbox test image once: `docker build -t agent-hq-sandbox-python:local apps/sandbox-images/python`.

Web, from `apps/web`:

```bash
npm install
npm run dev
```

The web app proxies `/api/*` to `API_INTERNAL_URL` (default `http://localhost:8000`).

## Operations

| Command (in `apps/api` or `docker compose exec api …`) | Purpose |
|---|---|
| `agent-hq migrate` | Apply database migrations |
| `agent-hq create-admin --email …` | Create the admin, or reset its password (prompted, min 12 chars) |
| `agent-hq worker` | Run the job worker (LangGraph agents) |
| `agent-hq verify-audit` | Recompute the audit log hash chain |
| `agent-hq sandbox` | Run the sandbox runner (needs Docker access) |

## Verification commands

Backend, from `apps/api` (the DB-backed tests create and migrate a separate
`<db>_test` database next to the one in `AGENT_HQ_DATABASE_URL`, and are skipped when it
is not set):

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest
```

PowerShell, with the Compose database running:

```powershell
$env:AGENT_HQ_DATABASE_URL = "postgresql+psycopg://agent_hq:<password>@127.0.0.1:5432/agent_hq"
uv run pytest
```

To also run the real-Docker sandbox test, build the sandbox image and set
`AGENT_HQ_DOCKER_TESTS=1`.

Web, from `apps/web`:

```bash
npm run lint && npm run typecheck && npm run build
```

## Notes for this machine (Windows + OneDrive)

- **Use `127.0.0.1`, not `localhost`, in database URLs.** On this machine `localhost`
  resolves to IPv6 first and Docker does not answer there, so connections hang.
- **Keep the Python virtualenv outside OneDrive.** OneDrive locks files while syncing and
  breaks `uv sync`. Set it once (PowerShell):
  `[Environment]::SetEnvironmentVariable("UV_PROJECT_ENVIRONMENT", "$env:LOCALAPPDATA\agent-hq\api-venv", "User")`
  and also `UV_LINK_MODE=copy`. Consider excluding `node_modules` and `.next` from sync or
  moving the repository out of OneDrive.
- psycopg's async driver needs a `SelectorEventLoop` on Windows; `agent-hq` commands and
  the test suite configure it automatically.
- Line endings are normalized to LF by `.gitattributes`.
