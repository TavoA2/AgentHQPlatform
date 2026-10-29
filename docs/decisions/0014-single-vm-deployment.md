# ADR-0014: Single-VM AWS deployment with Caddy, SSM and S3 backups

Status: Accepted (Sprint 6)

## Context
One administrator, low traffic, a public read-only demo and a private instance. The owner
chose AWS, a single VM, no domain yet. Operational simplicity and predictable cost
(about US$37/month on demand in us-east-1: t3.medium ~30, 40 GB gp3 ~3, public IPv4 ~4,
S3 <1; ~US$25 with a 1-year Savings Plan) matter more than horizontal scale.

## Decisions

1. **One EC2 instance** (t3.medium, Ubuntu 24.04, encrypted gp3 volume) runs Docker
   Compose (`deploy/compose.prod.yaml`) with two fully separate stacks on separate Docker
   networks and databases: the **private** Agent HQ and the **public demo**.
2. **Caddy** is the only container with published ports (80/443) and obtains Let's Encrypt
   certificates automatically. Hostnames are configuration (`HQ_DOMAIN`, `DEMO_DOMAIN`);
   until a domain exists, `sslip.io` names derived from the Elastic IP are used
   (e.g. `hq.3-91-10-20.sslip.io`). Caddy adds HSTS and security headers.
3. **No SSH.** The security group opens only 80/443. Administration uses **AWS Systems
   Manager Session Manager** (instance role with `AmazonSSMManagedInstanceCore`), so there
   are no keys to leak and no port 22.
4. **Secrets** live only in `/opt/agent-hq/.env.prod` and `/opt/agent-hq/secrets/` on the
   instance (root-owned, 600), never in Terraform state, user data, images or Git.
   Moving them to AWS Secrets Manager is a later improvement.
5. **2FA is mandatory in production.** The admin must enroll TOTP before logging in when
   `AGENT_HQ_ENVIRONMENT=production` (closes the residual risk from ADR-0007).
6. **Backups:** a systemd timer runs `pg_dump` of the private database daily to an S3
   bucket (versioned, encrypted, public access blocked, 35-day lifecycle). The instance
   role may only `PutObject`/`GetObject` under that bucket's `postgres/` prefix. Restore
   is scripted and rehearsed. The demo database is not backed up (it is reseedable).
7. **Cost and health monitoring:** an AWS Budget emails at 80% and 100% of the monthly
   limit; a CloudWatch alarm recovers the instance on system status-check failure; a local
   health timer restarts unhealthy services; container logs are size-capped.
8. **Images are built on the instance** from a Git checkout (`deploy/deploy.sh`). A
   registry (GHCR) can replace this when deploys become frequent.
9. **CI security gates:** secret scanning (gitleaks), Python and npm dependency audits,
   and container image scanning (Trivy, report-only at first).

## Consequences
Single point of failure, accepted for this stage (recovery: instance auto-recovery + S3
restore). Scaling path: move the database to RDS and services to ECS when usage justifies
it — no application change needed.
