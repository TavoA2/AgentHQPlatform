# ADR-0013: GitHub App writes, notification outbox and a public demo mode

Status: Accepted (Sprint 5). Supersedes the "fine-grained PAT" part of ADR-0008 for writes.

## Context
Proposed changes should become real pull requests, the owner wants to be notified on
Slack/Telegram, and a public link is needed for the portfolio — without exposing the real
instance, its data or its credentials.

## Decisions

### 1. GitHub writes through a GitHub App
- The App is installed only on the repositories the owner selects, with the minimum
  permissions: *Contents: read & write*, *Pull requests: read & write*, *Metadata: read*.
- The worker signs a short JWT with the App's private key (a file mounted read-only, never
  in the database or environment values) and exchanges it for an **installation token that
  expires in one hour**, cached until shortly before expiry.
- Writes are additionally gated **per project**: the project's GitHub integration must have
  `pull_requests: true`. Otherwise the existing mock adapter is used.
- The approval target says which adapter will run (`github://owner/repo/pulls` vs
  `mock://…`), so the human approves the real effect, bound to the changeset hash.
- The adapter only ever: creates a new branch `agent-hq/<task>-r<run>` from the default
  branch, adds one commit with the changeset files, and opens a **draft** pull request.
  It never pushes to an existing branch, never touches the default branch, never merges.
- Read operations keep working with the fine-grained read-only token when no App is
  configured (ADR-0008).

### 2. Notifications through a transactional outbox
- Notifications (approval requested, task completed, task failed) are written to a
  `notifications` table **in the same transaction** as the event that causes them, and
  delivered by the worker with retries and backoff. A crash never loses or invents one.
- Channels: Slack incoming webhook and Telegram bot. Secrets live in environment variables
  only and are never logged (URLs containing tokens are not logged).
- Messages carry only a title, a status and a link to the dashboard. **Nothing can be
  approved from a chat message**; approval stays in the authenticated dashboard.

### 3. Read-only public demo mode
- `AGENT_HQ_DEMO_MODE=true` turns an instance into a public showcase: visitors are served
  as a read-only `viewer` without logging in, and every state-changing request is refused
  server-side (403). The UI shows a demo banner and hides actions.
- A demo instance refuses to start if any real credential is configured (OpenAI key,
  GitHub token or App, notification secrets) and always uses the mock model provider.
- `agent-hq seed-demo` fills a demo database by running the **real** workflows end to end
  against a bundled sample repository, mock model and fake sandbox, so the demo shows
  genuine pipeline output, not hand-written fixtures.
- The demo is deployed separately from the private production instance (Sprint 6).

## Consequences
GitHub writes are reversible (draft PRs on new branches) and reviewable in GitHub. The
outbox adds one table and a send loop to the worker; no queue infrastructure. The demo
cannot leak real data because it is a separate deployment with no credentials.
