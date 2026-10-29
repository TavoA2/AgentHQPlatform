# Public demo (portfolio link)

The demo is a **separate, read-only deployment** with sample clients and data produced by
the real agent pipeline (ADR-0013). It never shares a database or credentials with your
private instance.

## Run it locally

```bash
docker compose -f compose.demo.yaml -p agent-hq-demo up --build -d
```

Open http://localhost:3100 — no login. Visitors can explore the 3D office, tasks (plans,
changesets, QA sandbox results), approvals, The Brain and operations. Every change is
refused by the API (403), and the UI hides actions.

Reset it with fresh data:

```bash
docker compose -f compose.demo.yaml -p agent-hq-demo down -v
docker compose -f compose.demo.yaml -p agent-hq-demo up --build -d
```

## What it contains

`agent-hq seed-demo` runs the real workflows against a bundled sample repository with the
deterministic mock model and an in-process sandbox:

- **Acme Shop:** a completed CI/CD review, a completed code change (Software Engineer + QA,
  tests run in the sandbox stand-in), and a review waiting for approval.
- **Globex:** a request that fails with `clarification_required` (two repositories, no
  repository named) — showing that the CIO asks instead of guessing.
- Company and project knowledge in The Brain, and execution summaries awaiting review.

## Safety rules (enforced in code)

- `AGENT_HQ_DEMO_MODE=true` refuses to start if any real credential is set (OpenAI key,
  GitHub token or App, Slack, Telegram) or if a non-mock model is configured.
- All non-GET requests are rejected before routing.
- No worker or sandbox runs in the demo; nothing executes after seeding.

## Publishing the link

Deployment to the cloud is Sprint 6. Until then, a short screen recording of the demo is a
good portfolio asset.
