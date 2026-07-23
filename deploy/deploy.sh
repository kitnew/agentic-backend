#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env.production"}
PROJECT_NAME=${COMPOSE_PROJECT_NAME:-agentic-backend-prod}

fail() {
  echo "deploy: $*" >&2
  exit 1
}

env_value() {
  name=$1
  value=$(printenv "$name" 2>/dev/null || true)
  if [ -z "$value" ]; then
    value=$(awk -F= -v name="$name" '$1 == name { print substr($0, index($0, "=") + 1); exit }' "$ENV_FILE")
  fi
  case "$value" in
    \"*\") value=${value#\"}; value=${value%\"} ;;
    \'*\') value=${value#\'}; value=${value%\'} ;;
  esac
  printf '%s' "$value"
}

require_value() {
  name=$1
  value=$(env_value "$name")
  [ -n "$value" ] || fail "$name is required in $ENV_FILE"
  case "$value" in
    generate-*|replace-*|*.example.com|*://*.example.com|203.0.113.*)
      fail "$name still contains an example placeholder"
      ;;
  esac
}

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    -f "$ROOT/docker-compose.yml" \
    -f "$ROOT/docker-compose.prod.yml" \
    "$@"
}

wait_healthy() {
  service=$1
  timeout=${2:-180}
  elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    container=$(compose ps -q "$service")
    [ -n "$container" ] || fail "$service container was not created"
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")
    case "$health" in
      healthy|running) return 0 ;;
      unhealthy|exited|dead) fail "$service entered state: $health" ;;
    esac
    sleep 2
    elapsed=$((elapsed + 2))
  done
  fail "$service did not become healthy within ${timeout}s"
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE; copy .env.production.example and replace placeholders"

for name in \
  APP_IMAGE_TAG LIVEKIT_SERVER_IMAGE CADDY_IMAGE \
  APP_ENV API_DOMAIN DEBUG_CHAT_DOMAIN LIVEKIT_DOMAIN CADDY_EMAIL \
  DEBUG_CHAT_BASIC_AUTH_USER DEBUG_CHAT_BASIC_AUTH_HASH \
  POSTGRES_PASSWORD VOICE_SESSION_TOKEN_SECRET LIVEKIT_SESSION_AUTH_SECRET \
  LIVEKIT_API_KEY LIVEKIT_API_SECRET LIVEKIT_INTERNAL_URL LIVEKIT_PUBLIC_URL \
  LIVEKIT_NODE_IP AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY ELEVENLABS_API_KEY \
  GOOGLE_SERVICE_ACCOUNT_FILE
do
  require_value "$name"
done

environment=$(env_value APP_ENV)
case "$environment" in
  production)
    [ "$(env_value LIVEKIT_STAGING_AUTH_ENABLED)" = "false" ] ||
      fail "LIVEKIT_STAGING_AUTH_ENABLED must be false in production"
    ;;
  staging)
    [ "$(env_value LIVEKIT_STAGING_AUTH_ENABLED)" = "true" ] ||
      fail "LIVEKIT_STAGING_AUTH_ENABLED must be true in staging"
    for name in LIVEKIT_STAGING_AUTH_CREDENTIAL LIVEKIT_STAGING_ALLOWED_TENANTS
    do
      require_value "$name"
    done
    value=$(env_value LIVEKIT_STAGING_AUTH_CREDENTIAL)
    [ "${#value}" -ge 32 ] ||
      fail "LIVEKIT_STAGING_AUTH_CREDENTIAL must contain at least 32 characters"
    ;;
  *) fail "APP_ENV must be production or staging" ;;
esac

basic_auth_hash=$(env_value DEBUG_CHAT_BASIC_AUTH_HASH)
case "$basic_auth_hash" in
  '$2a$'*|'$2b$'*|'$2y$'*) ;;
  *) fail "DEBUG_CHAT_BASIC_AUTH_HASH must be a Caddy-compatible bcrypt hash" ;;
esac

for name in POSTGRES_PASSWORD VOICE_SESSION_TOKEN_SECRET LIVEKIT_SESSION_AUTH_SECRET LIVEKIT_API_SECRET
do
  value=$(env_value "$name")
  [ "${#value}" -ge 32 ] || fail "$name must contain at least 32 characters"
done

[ "$(env_value APP_IMAGE_TAG)" != "latest" ] || fail "APP_IMAGE_TAG must be immutable, not latest"
for name in LIVEKIT_SERVER_IMAGE CADDY_IMAGE
do
  value=$(env_value "$name")
  case "$value" in
    *:latest|*[!0-9A-Za-z._:/-]*) fail "$name must use a fixed, valid image tag" ;;
    *:*) ;;
    *) fail "$name must include an explicit image tag" ;;
  esac
done

[ "$(env_value LIVEKIT_INTERNAL_URL)" = "ws://livekit:7880" ] ||
  fail "LIVEKIT_INTERNAL_URL must be ws://livekit:7880"
[ "$(env_value LIVEKIT_PUBLIC_URL)" = "wss://$(env_value LIVEKIT_DOMAIN)" ] ||
  fail "LIVEKIT_PUBLIC_URL must be wss://LIVEKIT_DOMAIN"

credentials=$(env_value GOOGLE_SERVICE_ACCOUNT_FILE)
case "$credentials" in
  /*) credentials_path=$credentials ;;
  *) credentials_path="$ROOT/${credentials#./}" ;;
esac
[ -f "$credentials_path" ] || fail "Google service account file not found: $credentials_path"

compose config --quiet
compose pull postgres redis livekit caddy
compose build --pull api capability-worker voice-agent debug-chat

compose up -d postgres redis livekit
wait_healthy postgres
wait_healthy redis
wait_healthy livekit

compose run --rm --no-deps api \
  python -c 'from app.infrastructure.database import init_db; init_db()'

compose up -d --remove-orphans
for service in api voice-agent debug-chat caddy
do
  wait_healthy "$service"
done
wait_healthy capability-worker

echo "Production stack is healthy."
