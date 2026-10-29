# Runbook: day-2 operations

All commands run on the instance as root (`aws ssm start-session ...`, then `sudo -i`,
`cd /opt/agent-hq/app`). Shorthand used below:

```bash
alias hq='docker compose --env-file .env.prod -f deploy/compose.prod.yaml -p agent-hq-prod'
```

## Deploy and roll back

```bash
deploy/scripts/deploy.sh main          # or a tag: deploy/scripts/deploy.sh v1.3.0
```

The script records the current commit, deploys the new one and waits for the private API
to be ready; if it is not healthy within ~4 minutes it **rolls back automatically** to the
previous commit. Manual rollback: `deploy/scripts/deploy.sh <previous-commit-sha>`.
Database migrations run on every deploy (`migrate` service); they are forward-only, so for
a rollback across a migration restore the pre-deploy backup.

## Backups and restore

- Automatic: daily at 03:15 UTC to `s3://<bucket>/postgres/` (35-day retention, versioned).
- On demand: `deploy/scripts/backup.sh` (always run one **before** risky changes).
- Restore: `deploy/scripts/restore.sh latest` or `deploy/scripts/restore.sh <s3 key>`. It
  asks you to type `RESTORE`, stops the app services, restores, restarts and verifies the
  audit chain. Rehearsed against PostgreSQL in Sprint 6.
- The demo is not backed up: reset it with `hq rm -sf demo-db && docker volume rm agent-hq-prod_demo-db && deploy/scripts/deploy.sh`.

## Rotate secrets

| Secret | How | Side effects |
|---|---|---|
| `POSTGRES_PASSWORD` | `hq exec db psql -U agent_hq -c "ALTER USER agent_hq PASSWORD '<new>'"`, update `.env.prod`, `deploy.sh` | none |
| `AGENT_HQ_SESSION_SECRET` | update `.env.prod`, `deploy.sh` | logs everyone out; **2FA must be re-enrolled** (`disable-2fa` then `enable-2fa`) |
| `AGENT_HQ_SANDBOX_TOKEN` | update `.env.prod`, `deploy.sh` | none |
| OpenAI / GitHub token / Slack / Telegram | revoke at the provider, update `.env.prod`, `deploy.sh` | none |
| GitHub App key | generate a new key on the App page, replace `secrets/github-app.pem`, delete the old key, `hq restart worker` | none |

Lost authenticator: `hq exec api agent-hq disable-2fa --email you@...`, then enable again.

## Incident response

1. **Is it up?** `hq ps`; `curl -sk https://<HQ_DOMAIN>/api/health/ready`.
2. **Logs:** `hq logs --tail 200 api worker caddy` (JSON lines; `request_id` ties them).
3. **Self-healing:** the health timer restarts api/worker/web after 3 failed checks
   (`journalctl -u agent-hq-health`). EC2 auto-recovers on host failure (CloudWatch alarm).
4. **Suspected compromise:** stop agent work immediately with `hq stop worker sandbox`,
   rotate all secrets (table above), revoke the GitHub App installation, then inspect
   `agent-hq verify-audit` and the `audit_events` table before restarting.
5. **Disk full:** `docker system df`; `docker image prune -af`; logs are already capped.
6. Write a short postmortem (what happened, impact, fix, prevention).

## Cost control

- AWS Budget emails at 80% (actual) and 100% (forecast) of the monthly limit.
- Expected: ~US$37/month on demand (t3.medium ~30, disk ~3, public IP ~4, S3 <1). A
  1-year Compute Savings Plan brings it to ~US$25.
- Model spend is controlled at OpenAI (monthly limit in their dashboard); per-agent usage
  and estimated cost are visible on the Operations page.
- To pause everything cheaply: `hq stop` (instance still billed) or stop the instance in
  the console (only disk and IP are billed).
