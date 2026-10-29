# shellcheck shell=bash
# Shared helpers for the production scripts. Sourced, not executed.
set -euo pipefail

# /etc/agent-hq.env is written by the bootstrap (AGENT_HQ_ROOT, AWS_REGION, BACKUP_BUCKET).
[ -f /etc/agent-hq.env ] && set -a && . /etc/agent-hq.env && set +a
ROOT="${AGENT_HQ_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$ROOT/.env.prod}"
PROJECT="${COMPOSE_PROJECT:-agent-hq-prod}"

[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE (see docs/runbooks/first-deployment.md)" >&2; exit 1; }
# shellcheck disable=SC1090
set -a && . "$ENV_FILE" && set +a

compose() {
  docker compose --env-file "$ENV_FILE" -f "$ROOT/deploy/compose.prod.yaml" -p "$PROJECT" "$@"
}

log() { echo "[$(date -u +%FT%TZ)] $*"; }
