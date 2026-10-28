# Agent Permission Matrix

Enforced by the policy engine (`security/policy.py`, Sprint 1) before every tool call.
Prompts describe these limits but are **not** the enforcement mechanism.

Legend: ✅ allowed · 🔒 allowed only with a matching human approval (ADR-0006) ·
❌ denied · — not applicable yet

## Side-effect classes

| Class | Meaning | Auto-retry |
|---|---|---|
| `read` | No external state change | Yes |
| `internal_write` | Changes Agent HQ state only (tasks, notes) | Yes if idempotent |
| `external_write` | Changes state outside Agent HQ, reversible | Never |
| `irreversible` | Deploys, deletes, payments, external messages, publishing | Never; always 🔒 |

## Tools × agents

| Tool | Class | CIO | DevOps | SW Eng (S2) | QA (S2) | Sprint |
|---|---|---|---|---|---|---|
| `tasks.create_subtask` | internal_write | ✅ | ❌ | ❌ | ❌ | 2 |
| `tasks.assign_agent` | internal_write | ✅ | ❌ | ❌ | ❌ | 2 |
| `tasks.record_result` | internal_write | ✅ | ✅ own task | ✅ own task | ✅ own task | 2 |
| `approvals.request` | internal_write | ✅ | ✅ | ✅ | ✅ | 2 |
| `approvals.decide` | — | ❌ | ❌ | ❌ | ❌ | never (humans only) |
| `github.list_tree` | read | ❌ | ✅ allowlisted repo | ✅ | ✅ | 1 |
| `github.read_file` | read | ❌ | ✅ allowlisted repo + path filter | ✅ | ✅ | 1 |
| `github.list_workflow_runs` | read | ❌ | ✅ allowlisted repo | ❌ | ✅ | 1 |
| `report.publish_external` (mock adapter) | external_write | 🔒 | ❌ | ❌ | ❌ | 1 (sample approval) |
| `github.create_branch` / `push` | external_write | ❌ | 🔒 | 🔒 | ❌ | 5 |
| `github.open_pull_request` | external_write | ❌ | 🔒 | 🔒 | ❌ | 5 |
| `github.merge_protected` | irreversible | ❌ | ❌ | ❌ | ❌ | human only |
| `sandbox.run_tests` | read (isolated) | ❌ | ✅ | ✅ | ✅ | 2 |
| `deploy.production` | irreversible | ❌ | 🔒 | ❌ | ❌ | 6 |
| `knowledge.search` | read | ✅ project scope | ✅ project scope | ✅ | ✅ | 3 |
| `knowledge.propose_fact` | internal_write (unverified) | ✅ | ✅ | ✅ | ✅ | 3 |
| `knowledge.approve_fact` | — | ❌ | ❌ | ❌ | ❌ | humans only |
| `messaging.send_external` | irreversible | 🔒 | ❌ | ❌ | ❌ | 5 |

## Cross-cutting rules

1. **Project scope:** the project of the running task is injected by the runtime; tools
   ignore any project/repository identifier that is not authorized for that project.
2. **Delegation:** only the CIO delegates, and only to agents enabled in the registry
   and permitted for the project.
3. **Self-approval:** no agent can decide, consume or forge an approval.
4. **Limits per tool:** timeout, max response bytes, max calls per execution.
5. **Loop guards (ADR-0010):** max model calls per specialist run and max graph steps;
   exceeding them fails the task with reason `max_steps_exceeded`. There is no token
   budget.
6. **Audit:** every denied call and every 🔒 call writes an `AuditEvent`.
