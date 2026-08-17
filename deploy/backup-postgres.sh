#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.production"}
PROJECT_NAME=${COMPOSE_PROJECT_NAME:-agentic-backend-prod}
BACKUP_DIR=${BACKUP_DIR:-"$ROOT/backups"}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
final="$BACKUP_DIR/postgres-$timestamp.sql.gz"

fail() {
  echo "backup: $*" >&2
  exit 1
}

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    -f "$ROOT/docker-compose.yml" \
    -f "$ROOT/docker-compose.prod.yml" \
    "$@"
}

[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE"
mkdir -p "$BACKUP_DIR"
temp=$(mktemp "$BACKUP_DIR/.postgres-$timestamp.XXXXXX.sql")
compressed="$final.tmp"
trap 'rm -f "$temp" "$compressed"' EXIT HUP INT TERM

if ! compose exec -T postgres sh -c \
  'exec pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  >"$temp"
then
  fail "pg_dump failed"
fi
[ -s "$temp" ] || fail "pg_dump produced an empty backup"

gzip -c "$temp" >"$compressed" || fail "gzip failed"
[ -s "$compressed" ] || fail "compressed backup is empty"
mv "$compressed" "$final"

echo "Backup created: $final"
