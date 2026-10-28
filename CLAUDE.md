# Agent HQ — guidance for coding agents

Read [docs/product-brief.md](docs/product-brief.md) first. Architecture lives in
`docs/architecture/`, decisions in `docs/decisions/` (ADRs), security in `docs/security/`.

## Working rules

- Work sprint by sprint. Do not start the next sprint without explicit approval from the
  owner. Current sprint: **Sprint 0 complete; Sprint 1 pending approval.**
- A change that contradicts an ADR needs a new ADR that supersedes it, not a silent
  deviation.
- Security is enforced in code (policy engine, approvals, project scoping), never only in
  prompts. Check [permission-matrix.md](docs/security/permission-matrix.md) before adding
  any tool.
- Never hardcode model names, API keys, the brand name or credentials. Config lives in
  `apps/api/src/agent_hq/config.py` (env prefix `AGENT_HQ_`).
- Never report tests or deployments as passing without running them.
- No new infrastructure (Redis, Kafka, vector DB, Kubernetes) without a concrete
  requirement recorded in an ADR. No empty modules or speculative abstractions.

## Commands

Backend (`apps/api`): `uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest`
Web (`apps/web`): `npm run lint && npm run typecheck && npm run build`
Stack: `docker compose up --build`

## Web app

`apps/web` uses Next.js 16 with Cache Components; APIs differ from older Next.js.
Read `apps/web/AGENTS.md` and the bundled docs in `apps/web/node_modules/next/dist/docs/`
before writing frontend code.
