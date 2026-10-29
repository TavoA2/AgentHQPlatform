# Agent HQ

Internal AI virtual operations platform for **Veltrix Labs** (provisional brand): a human
administrator supervises specialized AI agents that plan, execute and report real work,
with human approval for sensitive actions.

> Status: **seven sprints delivered.** You can chat with Dixon in the dashboard: answers come
> from real tasks, approvals, agents and The Brain, and new work is proposed for you to
> confirm (Sprint 7). Dixon (the AI CIO, LangGraph) routes each
> request to a workflow and delegates it as visible subtasks: a DevOps agent reviews CI/CD,
> or a Software Engineer and a QA agent work in parallel on a change that QA tests in an
> isolated Docker sandbox. Results are verified by code against evidence, a human approves
> every outbound action (e.g. a draft pull request via a GitHub App), and everything is
> audited. The Brain holds scoped, versioned knowledge; a 3D office shows live agent state;
> a read-only public demo and a single-VM AWS deployment (HTTPS, 2FA, backups) are ready.
> See the [roadmap](docs/product-brief.md#roadmap) and the acceptance evidence below.

## What runs

```
browser ──► web (Next.js, :3000) ──/api──► api (FastAPI, :8000) ──► PostgreSQL
                                                    ▲                 ▲  jobs, events, audit,
                                                    │ SSE (LISTEN)    │  LangGraph checkpoints
                     worker (LangGraph CIO, DevOps, SW Engineer, QA) ─┘
                        │ model providers (mock | OpenAI)
                        │ GitHub REST API (read-only, allowlisted repos)
                        └─token─► sandbox runner ──Docker──► throwaway test containers
                                  (only holder of the Docker socket; offline, non-root)
```

## Repository layout

```
apps/
  api/          Python 3.13 · FastAPI · LangGraph · SQLAlchemy/Alembic — uv project
    src/agent_hq/
      api/            HTTP routes, auth, SSE
      orchestration/  CIO graph, plans, specialists, verification, worker
      sandbox/        sandbox runner service, client and contracts
      llm/            provider abstraction (mock, OpenAI), profile router
      security/       auth, approvals, policy engine
      integrations/   GitHub (read-only), report publisher (mock)
      tools.py        tool registry + the single, policy-checked execution path
      chat.py         chat with Dixon; chat_tools.py holds its read-only tools
      models.py       ORM models · migrations/ holds Alembic revisions
  web/          Next.js 16 (App Router) · TypeScript · Tailwind CSS v4
  sandbox-images/ images for sandboxed test runs (python: stdlib + pytest)
docs/           product brief, architecture, ADRs, security, sprint criteria
compose.yaml    local stack: db · migrate · api · worker · sandbox · web
compose.demo.yaml  public read-only demo (local)
deploy/         production compose, Caddyfile, scripts, systemd timers
infra/terraform/   AWS: EC2, Elastic IP, SSM, S3 backups, budget, auto-recovery
```

## Quick start

Requirements: Docker Desktop, Node 24, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env      # set POSTGRES_PASSWORD, AGENT_HQ_SESSION_SECRET, AGENT_HQ_SANDBOX_TOKEN, AGENT_HQ_GITHUB_TOKEN
docker compose up --build -d
docker compose exec api agent-hq create-admin --email you@example.com
```

Open http://localhost:3000, sign in, then:

1. **Projects** → create a project and authorize a repository (`owner/name`).
2. **Tasks** → for example
   - "Analyze owner/name and propose improvements to its CI/CD pipeline." (DevOps), or
   - "Implement a slugify helper in owner/name with tests." (Software Engineer + QA)
3. Watch the office, the plan and the event log update live; approve in **Approvals**;
   read the verified result (findings, or changeset + QA sandbox run) on the task page.
   **Dixon** is a chat with the CIO: ask what is going on or ask for work and confirm
   the proposal card. **Operations** shows queue, failures and per-agent usage. **Brain** holds company and
   project knowledge: add your services and policies there; Dixon uses them when planning.

Without `OPENAI_API_KEY` and model profiles the deterministic **mock** provider is used
(rule-based output over the real files). To use OpenAI, see `.env.example`.

Full setup, host-based development and verification commands:
[docs/development.md](docs/development.md).

## Documentation

- [Product brief](docs/product-brief.md) · [Architecture](docs/architecture/overview.md) ·
  [Data model](docs/architecture/data-model.md) · [Agents](docs/architecture/agents.md)
- [Threat model](docs/security/threat-model.md) · [Permission matrix](docs/security/permission-matrix.md)
- [Decisions (ADRs)](docs/decisions/README.md) · [Dependencies](docs/dependencies.md)
- Acceptance and evidence: [Sprint 1](docs/sprints/sprint-1-acceptance.md) ·
  [Sprint 2](docs/sprints/sprint-2-acceptance.md) · [Sprint 3](docs/sprints/sprint-3-acceptance.md) ·
  [Sprint 4](docs/sprints/sprint-4-acceptance.md) · [Sprint 5](docs/sprints/sprint-5-acceptance.md) ·
  [Sprint 6](docs/sprints/sprint-6-acceptance.md) · [Sprint 7](docs/sprints/sprint-7-acceptance.md)
- Runbooks: [First deployment](docs/runbooks/first-deployment.md) · [Operations](docs/runbooks/operations.md)
- Guides: [GitHub App](docs/guides/github-app.md) · [Notifications](docs/guides/notifications.md) ·
  [Public demo](docs/guides/public-demo.md)
