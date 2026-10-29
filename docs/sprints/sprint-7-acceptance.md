# Sprint 7 — Chat with Dixon: Acceptance Criteria and Evidence

Verified on 2026-10-28: 189 backend tests (including the real Docker sandbox test), ruff,
mypy, web lint/typecheck/build, migration upgrade → downgrade → upgrade on the dev
database, and a browser check of `/chat` against the rebuilt local stack (mock model).

**Not verified:** answers from a real OpenAI model (the account has no API credit); the
mock provider answers deterministically from the real tool results.

## Conversation

| Criterion | Status | Evidence |
|---|---|---|
| Owner chats with Dixon in the dashboard; replies are grounded in real data | ✅ | `test_chat_answers_from_real_tasks` (real task title + status, team); browser: real tasks, team and approvals of the local instance |
| Replies run in the worker through the job queue; UI polls while pending | ✅ | Same test (202 + `pending`, completed by the worker); browser: "Dixon is checking…" then the reply |
| One pending reply per conversation; conversations are private to their user | ✅ | `test_one_pending_reply_ownership_and_redaction` (409; 404 for unknown/foreign) |
| Model, tokens and cost recorded per reply; tools used are visible | ✅ | Same tests (`mock:mock-fast`, tokens > 0); tool chips in the UI |
| Model errors fail the reply without retry; the owner can send again | ✅ | `test_model_configuration_errors_fail_the_reply_without_retry` |

## Security

| Criterion | Status | Evidence |
|---|---|---|
| Chat can only read and propose; a task exists only after the owner confirms, once | ✅ | `test_proposal_becomes_a_task_only_after_owner_confirmation` (0 tasks before the click; 409 on a second accept; audit `task.created` with `source: chat`); browser: proposal card, no task created |
| Unknown tools (start, approve) denied and audited | ✅ | `test_chat_scope_and_tool_policy_are_enforced_in_code` (`tasks.start`, `approvals.decide` denied; 4 `chat.tool_denied` audit rows) |
| Scope enforced in code: project chats cannot reach other projects; company chats see no project knowledge | ✅ | Same test (task, proposal and knowledge of client B unreachable from client A's chat and from a company chat) |
| Credentials pasted in chat are redacted before storage and model calls; CSRF required | ✅ | `test_one_pending_reply_ownership_and_redaction` |
| Public demo stays read-only, with a real seeded conversation | ✅ | `test_demo_seed_and_read_only_access` (4 completed messages, a proposal, POST message → 403) |

## Documentation

ADR-0015, permission matrix (chat tools), threat model (T20), data model, roadmap,
README, and `AGENT_HQ_CHAT_MODEL_PROFILE` / `cio_chat` override in the env examples.

## Known limitations

- No token streaming: the whole reply appears at once (polling every 1.5 s).
- Earlier turns' tool results are not replayed to the model; only the message text is.
- Proactive alerts, voice and WhatsApp remain deferred.
