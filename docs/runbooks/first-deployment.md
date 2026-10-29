# Runbook: first deployment to AWS

Result: `https://hq.<ip>.sslip.io` (private, 2FA) and `https://demo.<ip>.sslip.io`
(public, read-only) on one EC2 instance (ADR-0014). Estimated cost ~US$37/month.

Steps marked **(you)** need your AWS account or a decision; everything else is scripted.

## 0. Prerequisites (you)

1. An AWS account with billing set up. Enable MFA on the root user and stop using it.
2. Create an IAM user (or IAM Identity Center user) for Terraform with programmatic access
   and the `AdministratorAccess` policy for the first apply (tighten later).
3. On your PC install/update: AWS CLI v2 (your 2.0.30 is old — update it), the
   **Session Manager plugin**, and Terraform ≥ 1.6. Then `aws configure` with that user.

## 1. Create the infrastructure

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set alert_email (and region if needed)
terraform init
terraform plan        # review: 1 instance, 1 EIP, 1 bucket, IAM role, SG, alarm, budget
terraform apply
```

Note the outputs: `public_ip`, `suggested_hq_domain`, `suggested_demo_domain`,
`backup_bucket`, `connect`. **(you)** Confirm the AWS Budgets email subscription.

Bootstrap takes ~3 minutes after the instance starts (Docker, AWS CLI, clone, timers).

## 2. Add the production configuration (on the instance)

```bash
aws ssm start-session --target <instance_id> --region <region>   # the `connect` output
sudo -i
cd /opt/agent-hq/app
cp deploy/env.prod.example .env.prod && chmod 600 .env.prod
nano .env.prod
```

Fill in: `HQ_DOMAIN` / `DEMO_DOMAIN` (Terraform outputs), `CADDY_GLOBAL_OPTIONS` email,
`POSTGRES_PASSWORD`, `AGENT_HQ_SESSION_SECRET`, `AGENT_HQ_SANDBOX_TOKEN` (generate with
`openssl rand -base64 48`), and any integrations you use. Optional: copy the GitHub App
key to `/opt/agent-hq/app/secrets/github-app.pem` (`chmod 600`).

## 3. Deploy

```bash
deploy/scripts/deploy.sh main
```

The first run builds all images (~10 minutes on a t3.medium). Caddy then obtains the
certificates automatically.

## 4. Create the admin with 2FA (required in production)

```bash
docker compose --env-file .env.prod -f deploy/compose.prod.yaml -p agent-hq-prod exec api agent-hq create-admin --email you@example.com
docker compose --env-file .env.prod -f deploy/compose.prod.yaml -p agent-hq-prod exec api agent-hq enable-2fa --email you@example.com
```

Scan the printed URI with your authenticator app and enter the code to confirm.

## 5. Verify

- `https://<HQ_DOMAIN>` → sign in with password + authenticator code.
- `https://<DEMO_DOMAIN>` → demo loads without login; actions are hidden.
- `systemctl list-timers 'agent-hq-*'` → backup (daily) and health (5 min) timers.
- Run one backup now: `deploy/scripts/backup.sh`, then check S3.

## Moving to your own domain later

Point `hq.<domain>` and `demo.<domain>` (A records) to the Elastic IP, update `HQ_DOMAIN` /
`DEMO_DOMAIN` in `.env.prod`, run `deploy/scripts/deploy.sh`. Caddy issues new certificates.
