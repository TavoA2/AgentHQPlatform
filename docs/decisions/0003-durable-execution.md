# ADR-0003: Durable execution — Postgres job queue + LangGraph checkpointer

Status: Accepted (Sprint 0)

## Context
Workflows must resume after process interruption, support human-approval pauses of
hours or days, and avoid double execution of side effects.

## Decision
- `jobs` table: `id, kind (start|resume|cancel), task_id, payload, status, attempts,
  max_attempts, run_after, locked_by, lease_expires_at, last_error`. Workers claim with
  `SELECT … FOR UPDATE SKIP LOCKED`, renew the lease by heartbeat, and a reaper requeues
  jobs whose lease expired.
- LangGraph graphs run with `thread_id = task_id` and the official PostgreSQL
  checkpointer (`langgraph-checkpoint-postgres`) so a resumed job continues from the last
  completed node.
- Human approval uses LangGraph `interrupt()`; the job finishes, and a new `resume` job is
  enqueued when the approval is decided.
- **Retries:** each tool declares `idempotent: bool` and a side-effect class. Only
  read-only or idempotent steps are retried automatically. Non-idempotent steps carry an
  idempotency key (`execution_id:node:attempt`); on an uncertain failure the task moves to
  `FAILED` flagged `needs_human_review` and is never auto-retried.
- **Concurrency:** global worker concurrency and a per-agent limit (config). Parallel
  subtasks (Sprint 2) only when the plan marks them independent.

## Consequences
No extra infrastructure. Throughput is limited by Postgres polling (adequate at this
scale). The checkpointer's tables are owned by the library; their `setup()` is invoked
from an Alembic migration so schema changes stay traceable.
