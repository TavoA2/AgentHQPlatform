# Sprint 5 — External Integrations and Public Demo: Acceptance Criteria and Evidence

Verified on 2026-10-29: 179 backend tests (including the real Docker sandbox test), lint,
mypy, web lint/build; the main stack redeployed with the new migration; the demo stack
built from scratch with `compose.demo.yaml` and checked in a browser.

## GitHub (real pull requests)

| Criterion | Status | Evidence |
|---|---|---|
| GitHub App auth: JWT (RS256) → one-hour, repo-scoped installation token, cached | ✅ | `test_app_token_flow_and_draft_pr_only` (JWT verified with the public key; token requested for one repo with contents + pull_requests only; cached) |
| Approved changeset → new branch, one commit, **draft** PR; no merge, no updates | ✅ | Same test (only GET/POST, `draft: true`, `refs/heads/agent-hq/...`); `test_approved_changeset_opens_a_real_draft_pr` |
| Without project opt-in or App → mock adapter, visible in the approval target | ✅ | `test_code_change_happy_path` (mock target); real target `github://acme/shop/pulls` when enabled |
| Pushed content bound to the approval | ✅ | `test_pr_content_must_match_the_approved_hash`; adapter re-hashes the changeset |

## Notifications

| Criterion | Status | Evidence |
|---|---|---|
| Approval needed / completed / failed → Slack + Telegram via transactional outbox with retries | ✅ | `test_notifications_are_delivered_once_with_retries` (Telegram fails once, retried; Slack not duplicated) |
| Only top-level tasks; nothing sent without channels | ✅ | Same test (no subtask messages); `test_notifications_skip_when_no_channel` |
| No secrets in messages; no approval via chat | ✅ | Same test asserts no secret in payloads; messages carry a dashboard link only |

## Demo mode

| Criterion | Status | Evidence |
|---|---|---|
| Visitors browse without login as a read-only viewer | ✅ | `test_demo_seed_and_read_only_access`; browser check on :3100 |
| Every state change refused (403), including approvals and login | ✅ | Same test; `curl -X POST /api/projects` → 403 on the demo stack |
| Refuses to start with real credentials or non-mock models | ✅ | `test_demo_refuses_real_credentials` |
| `seed-demo` runs the real workflows; idempotent; only in demo mode | ✅ | Same test; demo stack log "demo data seeded" |
| Demo banner, actions hidden | ✅ | Browser check: banner, no Sign out, approvals show "Waiting for the owner's decision" |

## Guides

- [GitHub App](../guides/github-app.md) · [Notifications](../guides/notifications.md) ·
  [Public demo](../guides/public-demo.md)

## Not yet verified against the real services

- A real GitHub App installation, real Slack and real Telegram were **not** exercised:
  they need the owner to create the App/webhook/bot (guides above). The adapters are tested
  against faithful fakes of the GitHub, Slack and Telegram HTTP APIs.
- Google Drive and MCP tools were deprioritized by the owner for this sprint.
