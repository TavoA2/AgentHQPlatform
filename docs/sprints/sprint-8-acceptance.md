# Sprint 8 — Proactive Alerts: Acceptance Criteria and Evidence

Verified on 2026-10-29: 192 backend tests (including the real Docker sandbox test), ruff,
mypy, web lint/typecheck/build, migration upgrade → downgrade → upgrade with no model
drift, the rebuilt local stack, and a freshly seeded demo stack checked in a browser.

**Not verified:** delivery to real Slack/Telegram accounts (no webhook or bot configured);
the channels are exercised against fakes in tests, as in Sprint 5.

## Alerts

| Criterion | Status | Evidence |
|---|---|---|
| Milestones (approval needed, completed with verified outcome, failed) appear as Dixon messages in an Alerts thread | ✅ | `test_milestones_reach_the_alerts_thread_and_read_state`; demo browser check: 6 alerts with outcome summaries and task links |
| Same alerts on Slack/Telegram via the outbox, once per channel, with retries | ✅ | `test_notifications_are_delivered_once_with_retries` (`app` + `slack`, then `telegram`, no duplicates) |
| In-app channel always on, even without external channels | ✅ | `test_notifications_go_in_app_without_external_channels` |
| Approval reminder after N hours, once per approval, off with 0 | ✅ | `test_approval_reminder_is_sent_once` |
| Daily briefing from database facts (completed, failed, in progress, approvals, Brain reviews, model usage), once per day; quiet days skipped; English or Spanish | ✅ | `test_daily_brief_is_built_from_facts_once_per_day` |
| Unread badge on Dixon in the header; opening the thread marks it read | ✅ | Same milestone test (`unread` 1 → 0 → 1); badge visible in the demo |
| The owner can reply in the Alerts thread and Dixon answers with the chat tools | ✅ | Same milestone test |

## Security

| Criterion | Status | Evidence |
|---|---|---|
| Alerts are written by code, cost no tokens and never invent facts | ✅ | Alert messages record 0 tokens; text is built only from outbox payloads |
| Nothing can be approved from an alert | ✅ | Briefing test: the approval stays `pending`; alerts carry links only (T18) |
| Public demo: alerts visible to the viewer, still read-only | ✅ | `test_demo_seed_and_read_only_access` (alerts + chat threads; writes 403) |

## Reliability fix

New jobs now take `run_after` from the database clock. Two tests failed once in a full run
because the Windows host clock and the Docker Postgres clock had drifted apart, which could
delay a new job; the full suite passed after the fix.

## Configuration

`AGENT_HQ_ALERT_LANGUAGE` (`en`|`es`), `AGENT_HQ_ALERT_APPROVAL_REMINDER_HOURS` (default 4),
`AGENT_HQ_ALERT_DAILY_BRIEF_HOUR_UTC` (default 13 = 07:00 in Costa Rica; -1 = off).
