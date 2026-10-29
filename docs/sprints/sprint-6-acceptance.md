# Sprint 6 — Cloud Deployment and Operations: Acceptance Criteria and Evidence

Verified on 2026-10-28 locally: 184 backend tests (including the real Docker sandbox
test), lint/mypy, web lint/build, `terraform fmt`/`validate`, shellcheck, and a full
rehearsal of `deploy/compose.prod.yaml` behind Caddy (internal CA).

**Not verified:** an actual `terraform apply` on AWS and Let's Encrypt issuance — they need
the owner's AWS account (docs/runbooks/first-deployment.md).

## Security

| Criterion | Status | Evidence |
|---|---|---|
| TOTP 2FA: CLI enrollment, single-use codes, encrypted secret | ✅ | `tests/test_two_factor.py` (replay rejected, ±1 step, secret encrypted and bound to the session secret) |
| 2FA mandatory in production | ✅ | `test_production_requires_two_factor`; rehearsal login → 403 "two-factor authentication is required in production" |
| Only 80/443 exposed; no SSH; SSM administration | ✅ | Terraform SG (80, 443, 443/udp only); SSM managed-instance policy; no key pair |
| HTTPS, HSTS, security headers, secure cookies | ✅ | Rehearsal: HSTS, `X-Frame-Options: DENY`, `nosniff`, `X-Robots-Tag` on HQ; HTTP → 308 to HTTPS |
| Private and demo isolated | ✅ | Separate networks/databases; demo network is `internal`; rehearsal: demo write → 403, HQ API → 401 |
| Containers cannot read instance credentials | ✅ | IMDSv2 required with hop limit 1 |

## Infrastructure (Terraform)

| Criterion | Status | Evidence |
|---|---|---|
| EC2, EIP, SG, SSM role, encrypted gp3 | ✅ | `infra/terraform/main.tf`; `terraform validate` |
| S3 backups: versioned, encrypted, private, lifecycle, TLS-only; prefix-scoped IAM | ✅ | Same |
| Budget alerts and auto-recovery alarm | ✅ | `aws_budgets_budget` (80% actual, 100% forecast), `StatusCheckFailed_System` → recover |
| No secrets in Terraform or user data | ✅ | Secrets are created on the instance (runbook step 2) |

## Operations

| Criterion | Status | Evidence |
|---|---|---|
| Deploy with automatic rollback; backup; restore; health self-healing | ✅ | `deploy/scripts/*.sh` (shellcheck clean); systemd timers |
| Backup → restore rehearsed | ✅ | Rehearsal: backup, change (+1 audit row), restore → original state, `audit chain OK` |
| Runbooks | ✅ | `docs/runbooks/first-deployment.md`, `docs/runbooks/operations.md` (deploy/rollback, backup/restore, secret rotation, incident response, cost) |

## CI/CD

| Criterion | Status | Evidence |
|---|---|---|
| Secret scanning (full history) | ✅ | gitleaks with a justified allowlist (two revoked tokens, test fixtures); clean locally |
| Dependency audits | ✅ | `pip-audit` and `npm audit` (high): no known vulnerabilities locally |
| Image scanning | ✅ | Trivy job (report-only for now) |
| Infrastructure checks | ✅ | Terraform fmt/validate, shellcheck, `compose config` in CI |

## Cost (corrected)

About **US$37/month** on demand in us-east-1 (t3.medium ~30, 40 GB gp3 ~3, public IPv4
~4, S3 <1); ~US$25 with a 1-year Savings Plan. The budget alert defaults to US$45.
