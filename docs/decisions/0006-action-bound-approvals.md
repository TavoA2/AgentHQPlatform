# ADR-0006: Action-bound, single-use human approvals

Status: Accepted (Sprint 0)

## Decision
- An `ApprovalRequest` stores the proposed action as canonical JSON
  (`action_type`, `target`, `parameters`) and `action_hash = sha256(canonical_json)`.
- Executing a tool whose policy requires approval needs an approval that is `APPROVED`,
  not expired, not consumed, for the same task, and whose hash matches the hash
  recomputed from the actual call arguments. Any parameter change → new approval.
- The approval is consumed atomically
  (`UPDATE … SET consumed_at = now() WHERE consumed_at IS NULL`) right before execution.
  Single use.
- Agents (including the CIO) have no permission to decide approvals; only an
  authenticated human user via the API.
- Every create/decide/expire/consume writes an `AuditEvent`.
- Default expiration 24 h (configurable per action type). An expired request moves the
  task to `FAILED` (reason `approval_expired`) unless the admin re-requests.

## Consequences
Approvals cannot be replayed or widened. Changing a plan after approval forces a new
human decision, which is intended.
