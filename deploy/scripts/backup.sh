#!/usr/bin/env bash
# Dump the private database (custom format) to S3, or to BACKUP_DIR when set (rehearsals).
# The demo database is not backed up: it is reseeded from code.
. "$(dirname "$0")/common.sh"

STAMP="$(date -u +%Y/%m/%d/%H%M%S)"
NAME="postgres/${STAMP}-agent_hq.dump"

dump() {
  compose exec -T db pg_dump -U "${POSTGRES_USER:-agent_hq}" -d "${POSTGRES_DB:-agent_hq}" \
    --format=custom --no-owner
}

if [ -n "${BACKUP_DIR:-}" ]; then
  mkdir -p "$BACKUP_DIR/$(dirname "$NAME")"
  dump > "$BACKUP_DIR/$NAME"
  log "backup written to $BACKUP_DIR/$NAME ($(wc -c < "$BACKUP_DIR/$NAME") bytes)"
else
  : "${BACKUP_BUCKET:?BACKUP_BUCKET is not set}"
  dump | aws s3 cp - "s3://$BACKUP_BUCKET/$NAME" --sse AES256 --region "${AWS_REGION:-us-east-1}"
  log "backup uploaded to s3://$BACKUP_BUCKET/$NAME"
fi
