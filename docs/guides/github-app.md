# Setting up the GitHub App (real pull requests)

Agent HQ opens **draft** pull requests through a GitHub App (ADR-0013). The App can only
create branches, commits and pull requests in the repositories you install it on; Agent HQ
never merges and never writes to existing branches. Every pull request still needs your
approval in the dashboard first.

## 1. Create the App

1. GitHub → your avatar → **Settings** → **Developer settings** → **GitHub Apps** →
   **New GitHub App**.
2. **GitHub App name:** `agent-hq-<your-name>` (must be unique on GitHub).
3. **Homepage URL:** your site or `http://localhost:3000`.
4. **Webhook:** uncheck **Active** (Agent HQ does not need webhooks).
5. **Repository permissions** — set only these, leave everything else at *No access*:
   - **Contents:** Read and write
   - **Pull requests:** Read and write
   - **Metadata:** Read-only (mandatory)
6. **Where can this GitHub App be installed?** → **Only on this account**.
7. **Create GitHub App**. Note the **App ID** shown at the top.

## 2. Generate the private key

1. On the App page, **Private keys** → **Generate a private key**. A `.pem` file downloads.
2. Move it into the project as `secrets/github-app.pem` (the `secrets/` folder is
   gitignored). Never commit it, paste it in chat or put it in `.env`.

## 3. Install the App on selected repositories

1. On the App page → **Install App** → your account → **Only select repositories** →
   choose the repositories Agent HQ may propose changes to → **Install**.

## 4. Configure Agent HQ

In `.env`:

```
AGENT_HQ_GITHUB_APP_ID=<the App ID>
AGENT_HQ_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github-app.pem
```

Recreate the worker so it picks up the key (Compose mounts `./secrets` read-only):

```bash
docker compose up -d --force-recreate worker
```

## 5. Enable pull requests per project

In the dashboard → **Projects** → tick **Allow approved changes to open draft pull
requests** for the project and save. Projects without the tick keep using the mock adapter.

## Revoking access

Uninstall the App from the repositories, or delete the private key on the App page. Agent
HQ's tokens expire within an hour on their own.
