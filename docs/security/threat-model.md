# Threat Model (Sprint 0 baseline)

Method: assets → trust boundaries → STRIDE-style threats → controls. Revisit at the start
of every sprint that adds a tool, integration or agent.

## Assets

| Asset | Why it matters |
|---|---|
| Provider API keys, GitHub token, future cloud credentials | Financial loss, repository/infra compromise |
| Client project data (repos, requirements, knowledge) | Confidentiality between clients, contractual risk |
| Approval decisions | They authorize irreversible actions |
| Audit log | Accountability; must be tamper-evident |
| Admin session | Full control of the platform |
| Model budget | Runaway loops cost real money |

## Trust boundaries

1. Browser ↔ Next.js proxy ↔ API (authenticated admin).
2. API/worker ↔ PostgreSQL (trusted, private network).
3. Worker ↔ model provider (outbound; **model output is untrusted**).
4. Worker ↔ GitHub and future integrations (outbound; **content is untrusted**).
5. Worker ↔ sandbox runner (Sprint 2; executed code is untrusted).

## Threats and controls

| # | Threat | Control |
|---|---|---|
| T1 | **Prompt injection** via repo files, web pages, tool output or uploaded docs makes an agent call a dangerous tool | Tools are authorized by the server-side policy engine, not by the model. Sensitive tools need action-bound human approval (ADR-0006). Untrusted content is wrapped and labelled as data in prompts. Read-only tool set in Sprint 1. |
| T2 | Agent escalates privileges (CIO approves its own action, agent calls a tool outside its role) | Permission matrix enforced in code. No agent has an "approve" capability. Policy decisions are audited. |
| T3 | **Cross-project data leakage** | Every query on project-scoped data is filtered by `project_id` from the task context, not from model output. Knowledge retrieval (Sprint 3) is filtered by scope in SQL. Integrations are bound to one project. |
| T4 | Secret exfiltration via logs, agent responses or prompts | Secrets never enter prompts or the DB. Log redaction filter (key names + token patterns). Output scanner flags token-like strings before persisting agent output. |
| T5 | Approval replay or widening | SHA-256 action hash, single-use consumption, expiry, audit (ADR-0006). |
| T6 | Session hijacking / CSRF | HttpOnly+SameSite cookies, CSRF token, Origin check, server-side session revocation, login rate limit (ADR-0007). |
| T7 | Runaway cost / denial of wallet | No in-app token budget (owner decision, ADR-0010). Loop guards: max model calls per specialist run, graph recursion limit, per-tool call limits and timeouts, worker concurrency. Usage and estimated cost recorded per execution. Monthly spend limit set in the provider dashboard. |
| T8 | Arbitrary code / shell execution on host | No shell tools. Tests run only through the sandbox runner (ADR-0011): allowlisted templates, throwaway container, no network, uid 65534, all capabilities dropped, no-new-privileges, CPU/memory/PID limits, timeout, output redacted. Only the sandbox service holds the Docker socket; it has no host port and requires a token. Worker has no Docker socket. |
| T9 | Audit log tampering | Append-only enforced by database triggers on `audit_events` and `task_events` (UPDATE/DELETE raise), hash chain `prev_hash → hash`, `agent-hq verify-audit`. A separate non-owner DB role is planned for cloud deployment. |
| T10 | Malicious or oversized tool responses (DoS, parser bugs) | Size caps, timeouts, strict Pydantic validation of tool outputs, path allowlists for repository reads. |
| T11 | Supply-chain compromise of dependencies or CI | Lockfiles, `--locked` installs, Dependabot, SHA-pinned actions before secrets reach CI, least-privilege `GITHUB_TOKEN` permissions. |
| T12 | False success reports | Task cannot reach `COMPLETED` without a recorded verification result and evidence references; QA/verification is a separate step from execution. |
| T13 | Database exposed on the network | Postgres port bound to `127.0.0.1` locally; private subnet in cloud; separate DB role for the app without superuser. |
| T15 | Leaked GitHub write credential | GitHub App with one-hour, repository-scoped installation tokens; private key only as a mounted file; per-project opt-in; draft PRs on new branches only, never merge (ADR-0013). |
| T16 | Approved PR content swapped before pushing | The adapter re-hashes the changeset it is about to push and refuses unless it equals the approved hash. |
| T17 | Public demo abused to act or leak data | Separate deployment and database; refuses to start with credentials; all writes rejected before routing; mock model only. |
| T19 | Exposed admin surface on the internet | HTTPS only (HSTS), mandatory TOTP 2FA in production, single-use codes, login throttling, no SSH (SSM only), only ports 80/443 open, IMDSv2 with hop limit 1 so containers cannot read instance credentials. |
| T18 | Chat channel spoofing an approval | Notifications are outbound only; approvals require the authenticated dashboard. |
| T14 | Docker socket abuse via the sandbox service (socket = host root) | Minimal API (one operation, fixed templates), bearer token, internal network only, input size/path validation. Planned: gVisor runtime and rootless Docker for cloud (Sprint 6). |

## Residual risks (as of Sprint 6)

- ~~Password-only admin~~ → TOTP 2FA, mandatory in production (Sprint 6).
- ~~PAT for writes~~ → GitHub App for writes (Sprint 5); a read-only PAT may still be used for reads.
- Audit hash-chain verification is manual (`agent-hq verify-audit`, also run after restores).
- Single VM: no high availability; mitigated by EC2 auto-recovery and S3 backups (ADR-0014).
- Secrets in a root-only file on the instance rather than a secrets manager.
- The sandbox service holds the Docker socket (gVisor/rootless Docker not yet applied).
- Login throttling is in-memory (single API process).
