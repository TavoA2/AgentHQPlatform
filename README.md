# Agent HQ

Internal AI virtual operations platform for **Veltrix Labs** (provisional brand): a human
administrator supervises specialized AI agents (CIO, DevOps, Software Engineer, QA) that
plan, execute and report real work, with human approval for sensitive actions.

> Status: **Sprint 0 — foundation.** Architecture, security model and a runnable skeleton.
> No agents run yet. See the [roadmap](docs/product-brief.md#roadmap).

## Repository layout

```
apps/
  api/          Python 3.13 · FastAPI · (LangGraph from Sprint 1) — uv project
  web/          Next.js 16 (App Router) · TypeScript · Tailwind CSS v4
docs/
  product-brief.md        What Agent HQ is / is not, principles, roadmap
  architecture/           Overview + component diagram, data model, agent design
  decisions/              ADRs (0001–0009)
  security/               Threat model, agent permission matrix
  sprints/                Sprint acceptance criteria
  development.md          Local setup and verification commands
.github/workflows/ci.yml  Lint, typecheck, tests, image builds
compose.yaml              db + api + web for local development
```

A `packages/shared-contracts` package is deliberately not created yet: Sprint 1 will
generate TypeScript types from the FastAPI OpenAPI schema instead of maintaining a
hand-written shared package.

## Quick start

Requirements: Docker Desktop, Node 24, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env      # then set POSTGRES_PASSWORD and AGENT_HQ_SESSION_SECRET
docker compose up --build
```

- Web: http://localhost:3000
- API: http://localhost:8000/health/ready · docs at http://localhost:8000/docs

Full instructions, host-based development and verification commands:
[docs/development.md](docs/development.md).

## Documentation

- [Product brief](docs/product-brief.md)
- [Architecture overview](docs/architecture/overview.md)
- [Data model](docs/architecture/data-model.md)
- [Agent design](docs/architecture/agents.md)
- [Threat model](docs/security/threat-model.md) · [Permission matrix](docs/security/permission-matrix.md)
- [Decisions (ADRs)](docs/decisions/README.md)
- [Sprint 1 acceptance criteria](docs/sprints/sprint-1-acceptance.md)
