# Architecture Decision Records

Format: Context → Decision → Consequences. Status is `Accepted`, `Proposed` or
`Superseded by ADR-XXXX`. Never edit an accepted ADR's decision; supersede it.

| # | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith with api + worker processes | Accepted |
| [0002](0002-tooling-and-versions.md) | Tooling and dependency version policy | Accepted |
| [0003](0003-durable-execution.md) | Durable execution: Postgres job queue + LangGraph checkpointer | Accepted |
| [0004](0004-realtime-sse.md) | Real-time updates via SSE backed by task_events + pg_notify | Accepted |
| [0005](0005-model-provider-abstraction.md) | Model provider abstraction and model profiles | Accepted |
| [0006](0006-action-bound-approvals.md) | Action-bound, single-use human approvals | Accepted |
| [0007](0007-admin-authentication.md) | Admin authentication: password + server-side sessions | Accepted |
| [0008](0008-github-read-only-access.md) | Read-only GitHub access for Sprint 1 | Accepted |
| [0009](0009-execution-sandboxing.md) | Code/shell execution sandboxing | Accepted (option 1) |
| [0010](0010-sprint-1-refinements.md) | No token budget, checkpointer setup, initial models | Accepted |
| [0011](0011-multi-agent-plans-and-sandbox.md) | Multi-agent plans, parallel waves, sandbox runner | Accepted |
