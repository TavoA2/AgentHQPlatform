# Notifications (Slack and Telegram)

Agent HQ sends a short message when a task **needs your approval**, **completes** or
**fails** (top-level tasks only). Messages contain the task title, status and a link to the
dashboard — never secrets or task content — and **nothing can be approved from a chat
message**. Configure one channel, both, or none (then notifications are skipped).

Set the dashboard address used in links:

```
AGENT_HQ_PUBLIC_URL=http://localhost:3000
```

## Slack

1. https://api.slack.com/apps → **Create New App** → **From scratch** → pick a workspace.
2. **Incoming Webhooks** → turn on → **Add New Webhook to Workspace** → choose a channel.
3. Copy the webhook URL into `.env` (it is a secret):

```
AGENT_HQ_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Telegram

1. In Telegram, talk to **@BotFather** → `/newbot` → follow the prompts → copy the token.
2. Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy
   `"chat":{"id": ...}`.
3. In `.env`:

```
AGENT_HQ_TELEGRAM_BOT_TOKEN=<token from BotFather>
AGENT_HQ_TELEGRAM_CHAT_ID=<your chat id>
```

Apply with `docker compose up -d --force-recreate worker`.

Delivery uses an outbox table with retries (up to 5 attempts with backoff); a channel that
already received a message is never sent it twice. Failures show in the worker logs and in
the `notifications` table, never with the secret URL.
