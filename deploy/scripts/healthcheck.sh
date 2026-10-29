#!/usr/bin/env bash
# Run by agent-hq-health.timer every 5 minutes. Restarts the private stack's app services
# after three consecutive failed readiness checks; logs go to the journal.
. "$(dirname "$0")/common.sh"

STATE=/var/lib/agent-hq-health.failures
check() {
  compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=10)" >/dev/null 2>&1
}

if check; then
  rm -f "$STATE"
  exit 0
fi

FAILURES=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$FAILURES" > "$STATE"
log "health check failed ($FAILURES in a row)"
if [ "$FAILURES" -ge 3 ]; then
  log "restarting api, worker and hq-web"
  compose up -d api worker hq-web
  rm -f "$STATE"
fi
exit 1
