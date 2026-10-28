# ADR-0010: Sprint 1 refinements — no token budget, checkpointer setup, model choice

Status: Accepted (Sprint 1). Supersedes the budget clause of ADR-0005 and the
checkpointer-setup clause of ADR-0003.

## Context
The owner decided (2026-10-28) not to cap token usage per task. The owner also chose the
initial OpenAI models.

## Decision
1. **No per-task or daily token budget.** Every model call still records provider, model,
   tokens and estimated cost on its `TaskExecution` for visibility.
2. **Loop guards stay.** They are not budgets; they stop a stuck agent:
   `AGENT_HQ_AGENT_MAX_STEPS` (model calls per specialist execution) and
   `AGENT_HQ_GRAPH_RECURSION_LIMIT` (graph steps per run). Exceeding them fails the task
   with reason `max_steps_exceeded`.
3. A **monthly spend limit configured in the OpenAI dashboard** is the external cost
   safeguard (owner action, outside Agent HQ).
4. Initial model profiles: `reasoning → openai:gpt-6.1-sol`, `fast → openai:gpt-6-luna`.
   They live only in configuration (`AGENT_HQ_MODEL_PROFILE_*`); the code default is the
   deterministic `mock` provider so nothing calls a paid API unless configured.
5. The LangGraph checkpointer tables are created by the library's idempotent `setup()` at
   worker start-up (and in the test bootstrap) instead of inside an Alembic migration:
   the library owns that schema and its own migration table (`checkpoint_migrations`).

## Consequences
Cost is observable but not enforced in-app; a runaway loop is still bounded by step
limits. Threat T7 in the threat model is updated accordingly.
