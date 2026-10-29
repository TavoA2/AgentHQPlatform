# ADR-0016: Proactive alerts from Dixon

Status: Accepted (Sprint 8). Extends ADR-0013 (notification outbox) and ADR-0015 (chat).
Voice and WhatsApp stay deferred.

## Context
The owner wants Dixon to speak first: say when something needs a decision, when work
finished or failed, and give a short daily briefing, without having to open the dashboard
and look.

## Decisions

### 1. One outbox, one more channel
- Every alert is a row in the existing `notifications` outbox, written in the same
  transaction as its cause (task milestones) or by the worker's scheduler (reminders,
  briefing). Delivery keeps its retry and no-duplicate semantics per channel.
- A new in-app channel, `app`, is always on: it posts the alert as a Dixon message in each
  recipient's **Alerts** conversation. Slack and Telegram, when configured, receive the same
  text. Recipients are active admins (and the read-only viewer in demo mode).

### 2. Alert kinds
| Kind | Trigger |
|---|---|
| `approval_requested`, `task_completed`, `task_failed` | top-level task milestones (as in ADR-0013); completed alerts include the verified outcome summary |
| `approval_reminder` | an approval is still pending after `AGENT_HQ_ALERT_APPROVAL_REMINDER_HOURS` (default 4; 0 = off), once per approval |
| `daily_brief` | once per day at `AGENT_HQ_ALERT_DAILY_BRIEF_HOUR_UTC` (default 13 = 07:00 Costa Rica; -1 = off); skipped when there is nothing to report |

### 3. Alerts are written by code, not by a model
- Alert text is built from database state (counts, titles, links, costs), so it never
  invents a status or a number and costs no tokens. Analysis is on demand: the owner can
  reply in the Alerts conversation and Dixon answers with the chat tools (ADR-0015).
- Alerts carry titles, statuses, short summaries and dashboard links only. Nothing can be
  approved from an alert, in the dashboard thread or in Slack/Telegram.
- Language: `AGENT_HQ_ALERT_LANGUAGE` (`en` | `es`).

### 4. Read state
- The Alerts conversation records the last message the owner has seen; the header shows
  the unread count next to Dixon. Marking as read is a normal authenticated write.

## Consequences
No new infrastructure: the worker's maintenance tick (every 10 s) schedules reminders and
the briefing; idempotency comes from checking the outbox for an existing alert with the
same key. Once Slack/Telegram are configured, the briefing and reminders reach the
owner's phone.
