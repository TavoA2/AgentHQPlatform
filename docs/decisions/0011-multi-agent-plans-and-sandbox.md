# ADR-0011: Multi-agent plans, parallel waves and the sandbox runner

Status: Accepted (Sprint 2). Accepts option 1 of ADR-0009.

## Context
Sprint 2 adds the Software Engineer and QA agents, delegation between agents, independent
parallel work, result validation and recovery. QA must run tests on code it did not
write, which must never execute on the host or in the worker.

## Decisions

### 1. Workflow routing stays predictable
The CIO classifies each request into one of a fixed set of workflows (`cicd_review`,
`code_change`). The plan for each workflow is built by code as a small DAG of steps
(`agent`, `kind`, `depends_on`), not invented by the model. The model only fills in
objectives. New workflows are added in code with tests.

### 2. Delegation is visible as subtasks
Every plan step becomes a child `Task` (`parent_task_id`) assigned to its agent, with the
normal state machine (`QUEUED → RUNNING → IN_REVIEW → COMPLETED | FAILED`). Step output is
stored on the subtask, so a re-executed graph node reuses completed steps instead of
running them again.

### 3. Parallel waves
The graph executes the plan in waves: all steps whose dependencies are complete run
concurrently (bounded by `AGENT_HQ_MAX_PARALLEL_STEPS`), and each wave is a checkpointed
graph step. Steps only run in parallel when the plan marks them independent.

### 4. Deterministic validation per step
Each step kind has a code-level validator (evidence for findings, path and size limits for
changesets, consistency between the QA verdict and the sandbox exit code). A failed
validation retries the step once, then fails the task. A QA report can never say "ready"
when the sandbox run did not pass.

### 5. Sandbox runner (ADR-0009 option 1)
- A separate `sandbox` service is the **only** component with the Docker socket. The worker
  calls it over the internal network with a shared token; it publishes no host port.
- It runs only allowlisted **templates** (image + fixed command), never free-form commands.
- Each run is a fresh container: no network, non-root user (65534), all capabilities
  dropped, `no-new-privileges`, PID/memory/CPU limits, wall-clock timeout, and removal
  after the run. Workspace files are copied in as an archive; size and count are capped.
- Output is truncated and secret-redacted before it leaves the runner.
- Test images are built locally from `apps/sandbox-images/` and contain no credentials.

## Consequences
- The Docker socket gives the sandbox service host-level power; that is why it exposes a
  minimal API, requires a token and has no host port. gVisor (`runsc`) is the planned
  hardening for cloud deployment (Sprint 6).
- Sandbox images have no network at run time, so tests can use only what the image
  provides (Python stdlib + pytest in Sprint 2).
- Proposed code is never pushed: `changeset.propose` uses a mock adapter until GitHub
  write access (Sprint 5).
