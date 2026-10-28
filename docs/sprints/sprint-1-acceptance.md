# Sprint 1 — Acceptance Criteria and Evidence

Goal: prove that a human can create a task, the AI CIO coordinates a real specialist
workflow, and the system records the result with evidence.

Status legend: ✅ verified (test or recorded check) · ⏳ pending (owner action) ·
🔁 changed by an owner decision.

Verified on 2026-10-28: `apps/api` 129 tests passing against PostgreSQL 17, ruff and mypy
(strict) clean; `apps/web` lint, typecheck and production build passing; full Docker
Compose stack run end-to-end against the real `TavoA2/AgentHQPlatform` repository.

## Platform

| Criterion | Status | Evidence |
|---|---|---|
| `docker compose up` starts db, migrate, api, worker, web; migrations from scratch; health OK | ✅ | Compose run; `migrate` service; test bootstrap migrates a fresh DB |
| Admin via `agent-hq create-admin`; HttpOnly session cookie; 401 when unauthenticated; login rate limit; logout revokes server-side | ✅ | `tests/test_api.py` (login, 401 sweep, 429 after 5 failures, logout) |
| CSRF and Origin enforced on state changes | ✅ | `test_state_changes_require_csrf_and_same_origin` |
| Projects/tasks CRUD with validation; filters by project, agent, status | ✅ | `test_projects_tasks_and_filters`, `test_invalid_model_override_rejected` |
| Agent registry with status derived from real executions | ✅ | `test_full_workflow_with_approval` (CIO `WAITING_APPROVAL`, DevOps `IDLE`) |

## Orchestration

| Criterion | Status | Evidence |
|---|---|---|
| Start enqueues a job; worker runs the CIO graph; every transition writes task + audit events | ✅ | Status sequence asserted in `test_full_workflow_with_approval`; audit chain verified |
| Invalid transitions rejected (all pairs) | ✅ | `tests/test_domain.py` (81 pairs) |
| Recovery: crash mid-execution resumes from checkpoint without repeating completed steps | ✅ | `test_worker_crash_resumes_from_checkpoint` (`cio.analyze` called once), `test_expired_lease_is_requeued` |
| Configurable model provider; workflow passes with `mock` in CI | ✅ | All workflow tests use the mock provider |
| Manual run with OpenAI produces a valid report | ⏳ | Needs `OPENAI_API_KEY` + profiles in `.env` |
| Token usage and estimated cost recorded per execution | ✅ | `tokens_in`/`cost_usd` asserted in `test_full_workflow_with_approval` |
| Budget exceeded → `budget_exceeded` | 🔁 | Owner decision: no token budget (ADR-0010). Loop guards remain: `max_steps_exceeded` |

## DevOps agent use case

| Criterion | Status | Evidence |
|---|---|---|
| Lists and reads CI/CD files via the GitHub API; result passes verification (findings reference fetched files) | ✅ | Tests with fake GitHub; E2E against the real repo read 8 files |
| Non-allowlisted repository denied by the policy engine and audited, even if the model asks | ✅ | `test_prompt_injection_cannot_trigger_unauthorized_tools` (no request reached `evil/*`) |
| Prompt injection in a repository file causes no non-allowed tool call | ✅ | Same test: 4 injected calls (other repo, `.env`, publish, decide approval) all denied and audited |
| Unverifiable output never completes | ✅ | `test_unverifiable_result_is_never_completed` (one retry, then `verification_failed`) |

## Approvals

| Criterion | Status | Evidence |
|---|---|---|
| CIO raises approval for `report.publish_external`; task `WAITING_APPROVAL`; shows agent, action, target, justification, impact, risk, evidence, expiry | ✅ | `test_full_workflow_with_approval` |
| Approve resumes and the mock adapter executes exactly once; reject fails the task; expired approval unusable | ✅ | `test_full_workflow_with_approval`, `test_rejection_fails_task_without_side_effect`, `test_expired_approval_cannot_be_used` |
| Changed parameters after approval refused (hash mismatch) | ✅ | `test_changed_parameters_and_double_consumption_are_refused` |
| Approval cannot be consumed twice (concurrency) | ✅ | Same test: 5 concurrent consumers, exactly 1 succeeds |
| Cancel while waiting cancels the approval | ✅ | `test_cancel_while_waiting_for_approval` |

## UI

| Criterion | Status | Evidence |
|---|---|---|
| Login, projects, task list with filters, task detail (executions, outputs, events), approvals queue with approve/reject | ✅ | `apps/web` pages; exercised end-to-end through the web proxy |
| Live updates via SSE; reconnect replays missed events | ✅ | E2E received 33 events through the Next.js proxy; `tests/test_sse.py` (Last-Event-ID replay + filtering) |
| Office placeholder showing real agent status | ✅ | 2D office on `/` from `/agents` (also the reduced-motion fallback) |

## Quality

| Criterion | Status | Evidence |
|---|---|---|
| ruff, mypy, pytest (api) and lint, typecheck, build (web) in CI | ✅ | `.github/workflows/ci.yml` (Postgres service for DB tests) |
| JSON logs with request/task ids; secrets redacted | ✅ | `X-Request-ID` middleware + `test_request_id_header_is_set_and_validated`; `tests/test_logging.py` |
| README documents setup and verification; limitations listed | ✅ | README, `docs/development.md`, below |

## Known limitations (carried to later sprints)

- OpenAI adapter is implemented but not yet exercised against the real API (⏳ above).
- Login throttling is in-memory (single API process); move to the database before
  running more than one API instance.
- OpenTelemetry tracing is not wired yet; logs and task events are the observability
  surface for now.
- `report.publish_external` uses a mock adapter; no external system is contacted.
- TypeScript types mirror the API by hand; generate them from OpenAPI in Sprint 2.
- shadcn/ui and TanStack Query are deferred until the UI grows (ADR-0002 allows this).
- The CIO execution row shows the model of its last call (`fast` profile for the summary).
