# Sprint 2 — Multi-agent collaboration: Acceptance Criteria and Evidence

Goal: the AI CIO delegates a code change to a Software Engineer and a QA agent working
in parallel where possible; QA runs real tests in an isolated sandbox; results are
validated before a human approves proposing the change.

Use case: *"Implement <small change> in owner/repo with tests."* The change is proposed
(mock pull request), never pushed.

Verified on 2026-10-28: 160 backend tests passing against PostgreSQL 17 (including the
real Docker sandbox test), lint/mypy clean, web lint/typecheck/build passing, and an
end-to-end run of the full Compose stack against `TavoA2/AgentHQPlatform` (3 subtasks
completed, sandbox 3 passed / exit 0, approval → COMPLETED, 45 SSE events).

## Agents and delegation

| Criterion | Status | Evidence |
|---|---|---|
| Software Engineer returns a changeset (files + tests + rationale) within limits | ✅ | `test_code_change_happy_path`; E2E changeset |
| QA test plan runs **in parallel** with implementation, then QA runs tests and reports | ✅ | Overlapping executions asserted in `test_code_change_happy_path` |
| CIO routes to `cicd_review` or `code_change`; Sprint 1 review unchanged | ✅ | `test_cicd_requests_still_route_to_devops` + all Sprint 1 tests |
| Every plan step is a visible subtask with status, agent and output | ✅ | Subtasks API + Plan view on the task page |

## Sandbox

| Criterion | Status | Evidence |
|---|---|---|
| Fresh container, no network, non-root, capped resources, timeout; worker has no Docker | ✅ | `test_real_sandbox_isolation_and_timeout` (uid 65534, network blocked, hung test killed); worker container has no socket |
| Only allowlisted templates; no arbitrary commands via the API | ✅ | `test_only_allowlisted_templates_exist`, `test_runner_requires_token`, path/size tests |
| Runaway test killed at timeout and reported | ✅ | Same real-Docker test (`timed_out=True`) |

## Validation and safety

| Criterion | Status | Evidence |
|---|---|---|
| QA "ready" with failing tests rejected by code | ✅ | `test_qa_cannot_report_ready_when_tests_fail` |
| Changeset touching secrets or exceeding limits rejected | ✅ | `test_changeset_touching_secrets_is_rejected` (never reaches the sandbox) |
| Agents cannot use each other's tools; denials audited | ✅ | `test_agents_cannot_use_each_others_tools` (3 denials) |
| Proposing the changeset needs an action-bound human approval | ✅ | `changeset.propose` approval in the happy path; consumed once |
| Failing tests trigger one rework round, then fail | ✅ | `test_failing_tests_trigger_one_rework_round`, `test_persistent_failures_fail_the_task` |

## Recovery and monitoring

| Criterion | Status | Evidence |
|---|---|---|
| Crash during a parallel wave resumes without re-running completed steps | ✅ | `test_crash_in_parallel_wave_does_not_rerun_finished_steps` |
| `/metrics/summary` with tasks, queue, failed jobs, running executions, per-agent usage | ✅ | `test_metrics_summary`; Operations page |

## Known limitations

- Sandbox images are offline and contain Python + pytest only; tests that need project
  dependencies cannot run yet (a per-project image build is a later sprint).
- The sandbox service holds the Docker socket; gVisor/rootless Docker are planned for cloud.
- `changeset.propose` and `report.publish_external` use mock adapters until Sprint 5.
- Real-model behaviour (OpenAI) for the new agents has not been exercised: the account has
  no API credit; all runs used the deterministic mock provider.
- OpenTelemetry tracing is still not wired; `/metrics/summary` is pull-based JSON.
