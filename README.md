# Agent HQ

Internal AI virtual operations platform for **Veltrix Labs** (provisional brand): a human
administrator supervises specialized AI agents that plan, execute and report real work,
with human approval for sensitive actions.

> Status: **Sprint 1 — functional MVP.** An AI CIO (LangGraph) delegates a read-only
> CI/CD review of an authorized GitHub repository to a DevOps agent, verifies the result
> against evidence, asks a human to approve publishing it, and records everything.
> See the [roadmap](docs/product-brief.md#roadmap) and
> [Sprint 1 acceptance](docs/sprints/sprint-1-acceptance.md).

## What runs

```
browser ──► web (Next.js, :3000) ──/api──► api (FastAPI, :8000) ──► PostgreSQL
                                                    ▲                 ▲  jobs, events, audit,
                                                    │ SSE (LISTEN)    │  LangGraph checkpoints
                                    worker (LangGraph CIO + DevOps) ──┘
                                        │ model providers (mock | OpenAI)
                                        └ GitHub REST API (read-only, allowlisted repos)
```

## Repository layout

```
apps/
  api/          Python 3.13 · FastAPI · LangGraph · SQLAlchemy/Alembic — uv project
    src/agent_hq/
      api/            HTTP routes, auth, SSE
      orchestration/  CIO graph, DevOps agent, verification, worker
      llm/            provider abstraction (mock, OpenAI), profile router
      security/       auth, approvals, policy engine
      integrations/   GitHub (read-only), report publisher (mock)
      tools.py        tool registry + the single, policy-checked execution path
      models.py       ORM models · migrations/ holds Alembic revisions
  web/          Next.js 16 (App Router) · TypeScript · Tailwind CSS v4
docs/           product brief, architecture, ADRs, security, sprint criteria
compose.yaml    db · migrate · api · worker · web
```

## Quick start

Requirements: Docker Desktop, Node 24, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env      # set POSTGRES_PASSWORD, AGENT_HQ_SESSION_SECRET, AGENT_HQ_GITHUB_TOKEN
docker compose up --build -d
docker compose exec api agent-hq create-admin --email you@example.com
```

Open http://localhost:3000, sign in, then:

1. **Projects** → create a project and authorize a repository (`owner/name`).
2. **Tasks** → "Analyze owner/name and propose improvements to its CI/CD pipeline."
3. Watch the office and the task's event log update live; approve the publication in
   **Approvals**; read the verified findings on the task page.

Without `OPENAI_API_KEY` and model profiles the deterministic **mock** provider is used
(rule-based output over the real files). To use OpenAI, see `.env.example`.

Full setup, host-based development and verification commands:
[docs/development.md](docs/development.md).

## Documentation

- [Product brief](docs/product-brief.md) · [Architecture](docs/architecture/overview.md) ·
  [Data model](docs/architecture/data-model.md) · [Agents](docs/architecture/agents.md)
- [Threat model](docs/security/threat-model.md) · [Permission matrix](docs/security/permission-matrix.md)
- [Decisions (ADRs)](docs/decisions/README.md) · [Dependencies](docs/dependencies.md)
- [Sprint 1 acceptance criteria and evidence](docs/sprints/sprint-1-acceptance.md)
