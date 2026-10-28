# ADR-0001: Modular monolith with api + worker processes

Status: Accepted (Sprint 0)

## Context
One administrator, a handful of agents, low request volume. Agent runs are long (minutes)
and must survive restarts. Operational simplicity matters more than independent scaling.

## Decision
A single Python package (`agent_hq`) with internal module boundaries, started as two
processes from the same image: `api` (FastAPI) and `worker` (job runner executing
LangGraph graphs). PostgreSQL is the only stateful dependency. The web client is a
separate Next.js app.

## Consequences
- One codebase, one migration history, one image to build and scan.
- Long-running agent work never blocks HTTP workers.
- Module boundaries are enforced by convention and review (e.g. `api/` never imports
  `orchestration/` internals; it enqueues jobs). An import-linter rule can be added if
  boundaries erode.
- Redis/Celery/Kafka are not needed; revisit only if the Postgres queue becomes a
  measured bottleneck.
