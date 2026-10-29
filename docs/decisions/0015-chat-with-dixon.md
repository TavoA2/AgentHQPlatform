# ADR-0015: Chat with Dixon in the dashboard

Status: Accepted (Sprint 7). First step of the JARVIS-style assistant; proactive alerts,
voice and WhatsApp stay deferred.

## Context
The owner wants to talk to Dixon (the CIO) directly: ask what the team is doing, what is
waiting for approval, what The Brain knows, and ask for new work in plain language. The
chat must not become a side door around the policy engine, approvals or project isolation.

## Decisions

### 1. Turns run in the worker, through the existing job queue
- Sending a message stores the user message and a `pending` assistant message, and
  enqueues a `chat` job in the same transaction. The worker answers it and marks the
  message `complete` or `failed`. The dashboard polls the conversation while a reply is
  pending.
- Reasons: model calls stay in one process (the worker), replies survive API restarts,
  leases/retries are reused, and a slow model never hits the web proxy timeout.
- `jobs.task_id` becomes nullable and `jobs.conversation_id` is added; a check constraint
  requires exactly one of them. One pending reply per conversation (409 otherwise).
- Chat tools are read-only, so retrying a turn after a crash is safe.

### 2. Dixon in chat can read and propose, never act
- Chat tools (`chat.*`): overview, list/get tasks, list pending approvals, team status,
  knowledge search, and `chat.propose_task`. They are a separate registry with their own
  allowlist, argument validation, call limits and timeouts; unknown tools are denied.
- **No chat tool changes state.** `chat.propose_task` only stores a *proposal* on the
  assistant message. A task is created (and optionally started) only when the
  authenticated owner clicks the proposal card, which calls the normal task code path
  with CSRF/Origin checks and audit. A proposal can be accepted once.
- There is no tool to approve, reject, start, cancel or publish anything. Approvals stay
  on the Approvals page (ADR-0006).
- Tool outputs (task text, results, knowledge) are wrapped as untrusted data.

### 3. Scope
- A conversation is either **company-wide** or **bound to one project**, chosen when it is
  created and fixed afterwards. The scope is enforced in the tool queries, never taken
  from model output.
- Company-wide: task and approval metadata of all projects (what the owner's dashboard
  already shows) and **company** knowledge only. Bound: that project's tasks, approvals
  and knowledge plus company knowledge; proposals can only target that project.
- Conversations belong to the user who created them.

### 4. Model and usage
- Model profile `AGENT_HQ_CHAT_MODEL_PROFILE` (default `fast`), overridable per surface with
  `AGENT_HQ_MODEL_OVERRIDES={"cio_chat": "<provider>:<model>"}`.
- The prompt sends the last `AGENT_HQ_CHAT_HISTORY_MESSAGES` messages (default 20). Tool
  calls of earlier turns are not replayed; their outcome is in the assistant text.
- Each reply records provider, model, tokens and cost, and the tools it used, shown in the
  UI. The loop is bounded by `AGENT_HQ_AGENT_MAX_STEPS`.
- The mock provider answers deterministically from real tool results, so the chat works
  offline and in tests.

## Consequences
One new page and two tables; no streaming infrastructure (polling every ~1.5 s while a
reply is pending is enough for one admin). The public demo stays read-only: sending is a
write and is refused there.
