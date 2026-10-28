# Sprint 1 — Acceptance Criteria

Goal: prove that a human can create a task, the AI CIO coordinates a real specialist
workflow, and the system records the result with evidence.

Each criterion must be demonstrated by an automated test (unit or integration) or a
documented manual verification step with captured output. Nothing is marked done on
assertion alone.

## Platform

- [ ] `docker compose up` starts `db`, `api`, `worker`, `web`; `alembic upgrade head`
      creates the schema from scratch; health and readiness endpoints return 200.
- [ ] Admin is created with `agent-hq create-admin`; login sets an HttpOnly session
      cookie; unauthenticated requests to protected endpoints return 401; login is
      rate-limited; logout revokes the session server-side.
- [ ] CRUD for projects and tasks with validation; list endpoints filter by project,
      agent and status.
- [ ] Agent registry exposes CIO and DevOps with status derived from real executions.

## Orchestration

- [ ] Starting a task enqueues a job; the worker runs the CIO graph; status follows the
      state machine and every transition produces a task event and audit event.
- [ ] Invalid status transitions are rejected (table-driven test covers all pairs).
- [ ] **Recovery:** killing the worker mid-execution and restarting it resumes the task
      from the last checkpoint without repeating completed steps (integration test).
- [ ] Model provider is configurable via env; the full workflow passes with the `mock`
      provider in CI; a manual run with OpenAI produces a valid report (documented).
- [ ] Token usage and estimated cost are recorded per execution; exceeding the task
      budget fails the task with `budget_exceeded`.

## DevOps agent use case

- [ ] For a project with an authorized repository, the DevOps agent lists and reads
      CI/CD files via the GitHub API and returns a `CicdRecommendation` that passes
      verification (findings reference fetched files only).
- [ ] Requests for a repository not on the project allowlist are denied by the policy
      engine and audited, even when the model asks for it (test with mock provider
      emitting a malicious tool call).
- [ ] A prompt-injection string inside a repository file does not cause any non-allowed
      tool call (test).

## Approvals

- [ ] The CIO raises an approval for `report.publish_external`; the task enters
      `WAITING_APPROVAL`; the approval shows agent, action, target, justification,
      impact, risk, evidence and expiry.
- [ ] Approving resumes the workflow and the mock adapter executes exactly once;
      rejecting fails the task; an expired approval cannot be used.
- [ ] Changing any action parameter after approval is refused (hash mismatch test).
- [ ] An approval cannot be consumed twice (concurrency test).

## UI

- [ ] Dashboard: login, projects list, task list with filters, task detail with
      execution history, outputs and events, approvals queue with approve/reject.
- [ ] Live updates via SSE without page reload; reconnect replays missed events.
- [ ] Lightweight office placeholder (2D or simple 3D) showing each agent's real status.

## Quality

- [ ] `ruff`, `mypy`, `pytest` (api) and `lint`, `typecheck`, `build` (web) pass in CI.
- [ ] Logs are JSON with request/task ids; a test proves secrets are redacted.
- [ ] README documents setup and verification commands; known limitations are listed.
