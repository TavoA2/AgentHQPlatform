# ADR-0004: Real-time updates via SSE backed by task_events + pg_notify

Status: Accepted (Sprint 0)

## Decision
- `task_events` is append-only with a `bigint` identity id. Writers insert the event and
  call `pg_notify('task_events', <id>)` in the same transaction.
- The API process keeps one dedicated `LISTEN` connection and fans events out to SSE
  subscribers, filtered by authorization (project access).
- SSE `id:` equals the event id. On reconnect, `Last-Event-ID` replays missed events from
  the table. Heartbeat comments every 15 s keep proxies from closing the stream.
- The UI (dashboard and 3D office) derives all agent/task visuals from these events and
  REST snapshots, never from client-side assumptions.

## Consequences
At-least-once delivery with client-side dedupe by id. WebSockets are unnecessary until
the client needs to push high-frequency messages.
