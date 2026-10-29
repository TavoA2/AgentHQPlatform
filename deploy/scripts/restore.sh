#!/usr/bin/env bash
# Restore the private database from a backup and verify the audit chain.
# Usage: restore.sh latest | restore.sh postgres/2026/10/29/031500-agent_hq.dump | restore.sh /path/to/file.dump
# Stops the API and worker during the restore; the demo stack is untouched.
. "$(dirname "$0")/common.sh"

SOURCE="${1:?usage: restore.sh latest|<s3 key>|<local file>}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if [ -f "$SOURCE" ]; then
  cp "$SOURCE" "$TMP"
elif [ -n "${BACKUP_DIR:-}" ] && [ "$SOURCE" = latest ]; then
  cp "$(find "$BACKUP_DIR" -name '*.dump' | sort | tail -1)" "$TMP"
else
  : "${BACKUP_BUCKET:?BACKUP_BUCKET is not set}"
  KEY="$SOURCE"
  if [ "$SOURCE" = latest ]; then
    KEY="$(aws s3 ls "s3://$BACKUP_BUCKET/postgres/" --recursive --region "${AWS_REGION:-us-east-1}" | sort | tail -1 | awk '{print $4}')"
  fi
  aws s3 cp "s3://$BACKUP_BUCKET/$KEY" "$TMP" --region "${AWS_REGION:-us-east-1}"
fi

read -r -p "This REPLACES the private database with the backup. Type RESTORE to continue: " ok
[ "$ok" = RESTORE ] || { echo "aborted"; exit 1; }

log "stopping api, worker and web"
compose stop api worker hq-web
log "restoring"
compose exec -T db pg_restore -U "${POSTGRES_USER:-agent_hq}" -d "${POSTGRES_DB:-agent_hq}" \
  --clean --if-exists --no-owner --single-transaction < "$TMP"
compose start api worker hq-web
log "verifying audit chain"
compose exec -T api agent-hq verify-audit
log "restore complete"
