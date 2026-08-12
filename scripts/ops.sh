#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_DIR="$ROOT/infrastructure/compose"
BASE_COMPOSE="$COMPOSE_DIR/docker-compose.yml"
DEPLOY_COMPOSE="$COMPOSE_DIR/docker-compose.deploy.yml"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
Usage: ./scripts/ops.sh <staging|production> <command> [arguments]

Commands:
  validate | config | pull | build | migrate | deploy | update | status | stop | backup
  logs <service> [--follow]
  restart <service>
  restore <backup-file> [--yes]
EOF
  exit "${1:-2}"
}

[[ $# -ge 2 ]] || usage
ENVIRONMENT="$1"
COMMAND="$2"
shift 2

case "$ENVIRONMENT" in
  staging | production) ENV_FILE="$COMPOSE_DIR/.env.$ENVIRONMENT" ;;
  *) die "environment must be staging or production" ;;
esac

[[ -f "$ENV_FILE" ]] || die "environment file is missing: $ENV_FILE"
command -v docker >/dev/null || die "docker is required"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$BASE_COMPOSE" -f "$DEPLOY_COMPOSE" "$@"
}

check_compose() {
  if ! compose config --quiet; then
    die "Compose preflight failed for $ENVIRONMENT; check $ENV_FILE"
  fi
}

validate() {
  check_compose
  compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
}

ensure_postgres() {
  compose up -d --wait postgres
}

run_migration() {
  compose run --rm --no-deps backend alembic -c apps/backend/alembic.ini upgrade head
}

migrate() {
  check_compose
  ensure_postgres
  run_migration
}

verify_stack() {
  compose up -d --wait --remove-orphans
  compose ps
}

service_exists() {
  compose config --services | grep -Fqx -- "$1"
}

require_service() {
  service_exists "$1" || die "unknown service for $ENVIRONMENT: $1"
}

environment_value() {
  compose config --environment | awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); value = $0} END {print value}'
}

backup() {
  check_compose
  local backup_root backup_dir timestamp temporary target
  backup_root="$(environment_value BACKUP_DIR)"
  [[ -n "$backup_root" ]] || die "BACKUP_DIR must be set in $ENV_FILE"
  [[ "$backup_root" = /* ]] || die "BACKUP_DIR must be an absolute path outside the repository"

  mkdir -p -- "$backup_root"
  backup_root="$(cd -- "$backup_root" && pwd -P)"
  case "$backup_root" in
    "$ROOT" | "$ROOT"/*) die "BACKUP_DIR must be outside the repository" ;;
  esac

  ensure_postgres
  backup_dir="$backup_root/$ENVIRONMENT/postgres"
  umask 077
  mkdir -p -- "$backup_dir"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="$backup_dir/$timestamp.dump"
  [[ ! -e "$target" ]] || die "backup already exists: $target"
  temporary="$(mktemp "$backup_dir/.${timestamp}.XXXXXX.tmp")"

  if ! compose exec -T postgres sh -ec 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >"$temporary"; then
    rm -f -- "$temporary"
    die "PostgreSQL dump failed"
  fi
  if ! compose exec -T postgres sh -ec 'exec pg_restore --list -' <"$temporary" >/dev/null; then
    rm -f -- "$temporary"
    die "PostgreSQL dump validation failed"
  fi
  if ! ln -- "$temporary" "$target"; then
    rm -f -- "$temporary"
    die "could not atomically create backup: $target"
  fi
  rm -f -- "$temporary"
  printf '%s\n' "$target"
}

restore() {
  [[ $# -ge 1 && $# -le 2 ]] || usage
  local backup_file="$1"
  local assume_yes=false
  if [[ $# -eq 2 ]]; then
    [[ "$2" == --yes ]] || usage
    assume_yes=true
  fi
  [[ -f "$backup_file" ]] || die "backup file does not exist: $backup_file"

  if [[ "$ENVIRONMENT" == production && "$assume_yes" != true ]]; then
    [[ -t 0 ]] || die "production restore requires interactive confirmation or --yes"
    local confirmation
    read -r -p "Restore production from $backup_file? Type production: " confirmation
    [[ "$confirmation" == production ]] || die "production restore cancelled"
  fi

  check_compose
  ensure_postgres
  compose exec -T postgres sh -ec 'exec pg_restore --list -' <"$backup_file" >/dev/null
  compose stop backend
  compose stop job-worker voice-agent
  compose exec -T postgres sh -ec 'exec pg_restore --clean --if-exists --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" -' <"$backup_file"
  run_migration
  verify_stack
}

case "$COMMAND" in
  validate)
    [[ $# -eq 0 ]] || usage
    validate
    ;;
  config)
    [[ $# -eq 0 ]] || usage
    compose config
    ;;
  pull)
    [[ $# -eq 0 ]] || usage
    check_compose
    compose pull
    ;;
  build)
    [[ $# -eq 0 ]] || usage
    check_compose
    compose build
    ;;
  migrate)
    [[ $# -eq 0 ]] || usage
    migrate
    ;;
  deploy)
    [[ $# -eq 0 ]] || usage
    validate
    compose build
    migrate
    verify_stack
    ;;
  update)
    [[ $# -eq 0 ]] || usage
    validate
    compose pull
    compose build
    migrate
    verify_stack
    ;;
  status)
    [[ $# -eq 0 ]] || usage
    check_compose
    compose ps
    ;;
  logs)
    [[ $# -ge 1 && $# -le 2 ]] || usage
    service="$1"
    require_service "$service"
    if [[ $# -eq 2 ]]; then
      [[ "$2" == --follow ]] || usage
      compose logs --tail=200 --follow "$service"
    else
      compose logs --tail=200 "$service"
    fi
    ;;
  restart)
    [[ $# -eq 1 ]] || usage
    require_service "$1"
    compose restart "$1"
    ;;
  stop)
    [[ $# -eq 0 ]] || usage
    check_compose
    compose stop
    ;;
  backup)
    [[ $# -eq 0 ]] || usage
    backup
    ;;
  restore)
    restore "$@"
    ;;
  *)
    die "unknown command: $COMMAND"
    ;;
esac
