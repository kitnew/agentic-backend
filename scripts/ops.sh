#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_DIR="$ROOT/infrastructure/compose"
BASE_COMPOSE="$COMPOSE_DIR/docker-compose.yml"
DEPLOY_COMPOSE="$COMPOSE_DIR/docker-compose.deploy.yml"
REQUIRED_STACK_SERVICES=(
  postgres
  redis
  nats
  backend
  control-plane-service
  voice-agent
  job-worker
  admin-web
  livekit
  livekit-egress
  livekit-sip
  minio
  minio-init
  caddy
)
OPTIONAL_STACK_SERVICES=(prometheus tempo otel-collector grafana)

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

usage() {
  local exit_code="${1:-2}"
  cat >&2 <<'EOF'
Usage: ./scripts/ops.sh <staging|production> <command> [options]

Commands:
  validate
  config [--show-secrets]
  pull
  build
  migrate
  db-init
  db-reset [--yes]
  deploy
  update
  release
  doctor
  status
  logs SERVICE [--follow]
  restart SERVICE
  stop
  backup
  restore FILE [--yes]
EOF
  exit "$exit_code"
}

if [[ $# -eq 1 && ("$1" == "--help" || "$1" == "-h") ]]; then
  usage 0
fi
[[ $# -ge 2 ]] || usage

ENVIRONMENT="$1"
COMMAND="$2"
shift 2

case "$ENVIRONMENT" in
  staging | production) ENV_FILE="$COMPOSE_DIR/.env.$ENVIRONMENT" ;;
  *) die "environment must be staging or production" ;;
esac

if [[ "$COMMAND" == "--help" || "$COMMAND" == "-h" ]]; then
  usage 0
fi

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

config() {
  local show_secrets=false
  if [[ $# -gt 1 ]]; then
    usage
  elif [[ $# -eq 1 ]]; then
    [[ "$1" == "--show-secrets" ]] || usage
    show_secrets=true
  fi

  check_compose
  if [[ "$show_secrets" == true ]]; then
    printf 'WARNING: resolved Compose output may contain secrets.\n' >&2
    compose config
    return
  fi

  printf 'Compose configuration: valid\n'
  printf 'Environment: %s\n' "$ENVIRONMENT"
  printf 'Services:\n'
  compose config --services
  printf 'Volumes:\n'
  compose config --volumes
}

ensure_postgres() {
  compose up -d --wait --wait-timeout 180 postgres
}

postgres_database_name() {
  compose exec -T postgres sh -ec 'printf "%s\n" "$POSTGRES_DB"' | tr -d '\r\n'
}

safe_database_identifier() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

database_exists() {
  local database_name="$1"
  compose exec -T postgres sh -ec \
    "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres -Atqc \"SELECT 1 FROM pg_database WHERE datname = '$database_name'\"" \
    | grep -Fxq 1
}

ensure_database() {
  local database_name
  database_name="$(postgres_database_name)"
  safe_database_identifier "$database_name" || die "unsafe PostgreSQL database name: $database_name"
  if database_exists "$database_name"; then
    return
  fi

  printf 'Creating PostgreSQL database: %s\n' "$database_name"
  compose exec -T postgres sh -ec 'createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
}

run_migration() {
  compose run --rm --no-deps --user root --entrypoint /bin/sh backend -ec '
    exec alembic -c apps/backend/alembic.ini upgrade head
  '
}

database_init() {
  check_compose
  ensure_postgres
  ensure_database
  printf 'Applying Backend Alembic revisions.\n'
  run_migration
}

database_prepare() {
  ensure_postgres
  ensure_database
  printf 'Applying Backend Alembic revisions.\n'
  run_migration
}

database_reset() {
  local assume_yes=false
  if [[ $# -gt 1 ]]; then
    usage
  elif [[ $# -eq 1 ]]; then
    [[ "$1" == "--yes" ]] || usage
    assume_yes=true
  fi

  check_compose
  ensure_postgres

  local database_name
  database_name="$(postgres_database_name)"
  safe_database_identifier "$database_name" || die "unsafe PostgreSQL database name: $database_name"
  ensure_database

  if [[ "$ENVIRONMENT" == production && "$assume_yes" != true ]]; then
    [[ -t 0 ]] || die "production db-reset requires interactive confirmation or --yes"
    printf 'WARNING: this permanently deletes PostgreSQL database "%s"\n' "$database_name" >&2
    printf 'Environment: %s\n' "$ENVIRONMENT" >&2
    printf 'Type "production" to continue: ' >&2
    local confirmation
    read -r confirmation
    [[ "$confirmation" == "production" ]] || die "production db-reset cancelled"
  fi

  printf 'Stopping services that may use PostgreSQL.\n'
  compose stop backend control-plane-service job-worker voice-agent
  printf 'Dropping PostgreSQL database: %s\n' "$database_name"
  compose exec -T postgres sh -ec \
    "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres -c 'DROP DATABASE \"$database_name\" WITH (FORCE);'"
  compose exec -T postgres sh -ec 'createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  database_init
}

verify_stack() {
  if ! compose up -d --remove-orphans "${OPTIONAL_STACK_SERVICES[@]}"; then
    printf 'warning: optional observability services could not be started; continuing.\n' >&2
  fi
  compose up -d --wait --wait-timeout 180 --remove-orphans "${REQUIRED_STACK_SERVICES[@]}"
  compose ps
}

service_exists() {
  compose config --services | grep -Fqx -- "$1"
}

require_service() {
  service_exists "$1" || die "unknown service for $ENVIRONMENT: $1"
}

environment_value() {
  local key="$1" value
  if [[ -n "${!key-}" ]]; then
    value="${!key}"
  else
    value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); value = $0} END {print value}' "$ENV_FILE")"
  fi
  if [[ -z "$value" ]]; then
    value="$(compose config --environment | awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); value = $0} END {print value}')"
  fi
  printf '%s\n' "$value"
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
  compose stop backend control-plane-service
  compose stop job-worker voice-agent
  compose exec -T postgres sh -ec 'exec pg_restore --clean --if-exists --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" -' <"$backup_file"
  run_migration
  verify_stack
}

service_running() {
  if compose ps --status running --services | grep -Fqx -- "$1"; then
    return 0
  fi
  return 1
}

postgres_doctor() {
  service_running postgres || return 1
  compose exec -T postgres sh -ec 'pg_isready -U "$POSTGRES_USER" -d postgres' >/dev/null 2>&1 || return 1
  local database_name
  database_name="$(postgres_database_name)"
  safe_database_identifier "$database_name" || return 1
  database_exists "$database_name"
}

redis_doctor() {
  service_running redis || return 1
  compose exec -T redis redis-cli ping 2>/dev/null | grep -Fxq PONG
}

nats_doctor() {
  service_running nats || return 1
  compose exec -T nats wget -q -O /dev/null http://localhost:8222/healthz >/dev/null 2>&1
}

backend_health_doctor() {
  service_running backend || return 1
  compose exec -T backend python -c \
    "from urllib.request import urlopen; raise SystemExit(urlopen('http://127.0.0.1:8000/health', timeout=3).status != 200)" \
    >/dev/null 2>&1
}

backend_ready_doctor() {
  service_running backend || return 1
  compose exec -T backend python -c \
    "from urllib.request import urlopen; raise SystemExit(urlopen('http://127.0.0.1:8000/ready', timeout=3).status != 200)" \
    >/dev/null 2>&1
}

control_plane_health_doctor() {
  service_running control-plane-service || return 1
  compose exec -T control-plane-service python -c \
    "from urllib.request import urlopen; raise SystemExit(urlopen('http://127.0.0.1:8000/health', timeout=3).status != 200)" \
    >/dev/null 2>&1
}

control_plane_ready_doctor() {
  service_running control-plane-service || return 1
  compose exec -T control-plane-service python -c \
    "from urllib.request import urlopen; raise SystemExit(urlopen('http://127.0.0.1:8000/ready', timeout=3).status != 200)" \
    >/dev/null 2>&1
}

minio_doctor() {
  service_running minio || return 1
  compose exec -T minio curl -fsS http://localhost:9000/minio/health/ready >/dev/null 2>&1
}

grafana_doctor() {
  service_running grafana || return 1
  compose exec -T grafana wget -q -O /dev/null http://localhost:3000/api/health >/dev/null 2>&1
}

livekit_doctor() {
  service_running livekit || return 1
  compose exec -T livekit wget -q -O /dev/null http://localhost:7880/ >/dev/null 2>&1
}

egress_doctor() {
  service_running livekit-egress || return 1
  compose exec -T livekit-egress curl -fsS http://localhost:8080/ >/dev/null 2>&1
}

sip_doctor() {
  service_running livekit-sip || return 1
  compose exec -T livekit-sip wget -q -O /dev/null http://localhost:8080/ >/dev/null 2>&1
}

caddy_doctor() {
  service_running caddy || return 1
  compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
}

doctor_check() {
  local requirement="$1" label="$2"
  shift 2
  if "$@" >/dev/null 2>&1; then
    printf '[OK] %s\n' "$label"
  elif [[ "$requirement" == required ]]; then
    printf '[FAIL] %s [REQUIRED]\n' "$label"
    DOCTOR_REQUIRED_FAILED=1
  else
    printf '[WARN] %s [OPTIONAL]\n' "$label"
    DOCTOR_OPTIONAL_FAILED=1
  fi
}

doctor() {
  DOCTOR_REQUIRED_FAILED=0
  DOCTOR_OPTIONAL_FAILED=0
  printf '%s doctor\n\n' "$ENVIRONMENT"

  if docker info >/dev/null 2>&1; then
    printf '[OK] Docker daemon\n'
  else
    printf '[FAIL] Docker daemon\n'
    printf '\nResult: unhealthy\n'
    return 1
  fi

  if compose config --quiet >/dev/null 2>&1; then
    printf '[OK] Compose configuration\n'
  else
    printf '[FAIL] Compose configuration\n'
    printf '\nResult: unhealthy\n'
    return 1
  fi

  doctor_check required "PostgreSQL" postgres_doctor
  doctor_check required "Redis" redis_doctor
  doctor_check required "NATS" nats_doctor
  doctor_check required "MinIO" minio_doctor
  doctor_check required "Backend container" service_running backend
  doctor_check required "Backend health endpoint" backend_health_doctor
  doctor_check required "Backend readiness endpoint" backend_ready_doctor
  doctor_check required "Control Plane container" service_running control-plane-service
  doctor_check required "Control Plane health endpoint" control_plane_health_doctor
  doctor_check required "Control Plane readiness endpoint" control_plane_ready_doctor
  doctor_check required "Worker" service_running job-worker
  doctor_check required "Voice agent" service_running voice-agent
  doctor_check required "Admin Web" service_running admin-web
  doctor_check required "LiveKit" livekit_doctor
  doctor_check required "LiveKit Egress" egress_doctor
  doctor_check required "LiveKit SIP" sip_doctor
  doctor_check optional "Prometheus" service_running prometheus
  doctor_check optional "Tempo" service_running tempo
  doctor_check optional "OTel collector" service_running otel-collector
  doctor_check optional "Grafana" grafana_doctor
  doctor_check required "Caddy" caddy_doctor

  if (( DOCTOR_REQUIRED_FAILED == 0 )); then
    if (( DOCTOR_OPTIONAL_FAILED > 0 )); then
      printf '\nResult: healthy (optional checks degraded)\n'
      return 0
    fi
    printf '\nResult: healthy\n'
    return 0
  fi
  printf '\nResult: unhealthy\n'
  return 1
}

git_branch() {
  git -C "$ROOT" symbolic-ref --short -q HEAD 2>/dev/null || printf '(detached)\n'
}

git_commit() {
  git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || printf 'unknown\n'
}

status() {
  check_compose
  printf 'Environment: %s\n' "$ENVIRONMENT"
  printf 'Git branch: %s\n' "$(git_branch)"
  printf 'Git commit: %s\n' "$(git_commit)"
  if [[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]]; then
    printf 'Working tree: dirty\n\n'
  else
    printf 'Working tree: clean\n\n'
  fi
  compose ps
}

release() {
  [[ $# -eq 0 ]] || usage
  check_compose
  local top_level
  top_level="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" || die "not a Git worktree: $ROOT"
  [[ "$top_level" == "$ROOT" ]] || die "Git worktree root mismatch: $top_level"
  if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    printf 'error: release requires a clean Git working tree\n' >&2
    git -C "$ROOT" status --short >&2
    exit 1
  fi

  printf 'Fetching Git updates.\n'
  git -C "$ROOT" fetch --prune || die "git fetch failed"
  printf 'Updating checkout with git pull --ff-only.\n'
  git -C "$ROOT" pull --ff-only || die "git pull --ff-only failed; checkout was not rewritten"
  exec "$ROOT/scripts/ops.sh" "$ENVIRONMENT" update
}

case "$COMMAND" in
  validate)
    [[ $# -eq 0 ]] || usage
    validate
    ;;
  config)
    config "$@"
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
    check_compose
    database_prepare
    ;;
  db-init)
    [[ $# -eq 0 ]] || usage
    database_init
    ;;
  db-reset)
    database_reset "$@"
    ;;
  deploy)
    [[ $# -eq 0 ]] || usage
    validate
    compose build
    database_prepare
    verify_stack
    doctor
    ;;
  update)
    [[ $# -eq 0 ]] || usage
    validate
    compose pull
    compose build
    database_prepare
    verify_stack
    doctor
    ;;
  release)
    release "$@"
    ;;
  doctor)
    [[ $# -eq 0 ]] || usage
    doctor
    ;;
  status)
    [[ $# -eq 0 ]] || usage
    status
    ;;
  logs)
    [[ $# -ge 1 && $# -le 2 ]] || usage
    service="$1"
    require_service "$service"
    if [[ $# -eq 2 ]]; then
      [[ "$2" == "--follow" ]] || usage
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
