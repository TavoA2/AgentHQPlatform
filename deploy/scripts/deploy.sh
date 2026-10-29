#!/usr/bin/env bash
# Deploy a Git ref (default: origin/main) and roll back automatically if the private API
# does not become healthy. Usage: deploy.sh [git-ref]   e.g. deploy.sh v1.2.0
. "$(dirname "$0")/common.sh"

REF="${1:-origin/main}"
cd "$ROOT"
PREVIOUS="$(git rev-parse HEAD)"

log "fetching and checking out $REF (current $PREVIOUS)"
git fetch --tags origin
git checkout --detach "$REF"

wait_healthy() {
  for _ in $(seq 1 40); do
    if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')" >/dev/null 2>&1; then
      return 0
    fi
    sleep 6
  done
  return 1
}

log "building and starting both stacks"
if compose up --build -d --remove-orphans && wait_healthy; then
  log "deployed $(git rev-parse --short HEAD)"
  docker image prune -f >/dev/null
  exit 0
fi

log "deployment unhealthy: rolling back to $PREVIOUS"
git checkout --detach "$PREVIOUS"
compose up --build -d --remove-orphans
if wait_healthy; then
  log "rolled back to $PREVIOUS"
else
  log "ROLLBACK ALSO UNHEALTHY: see docs/runbooks/operations.md (Incident response)"
fi
exit 1
