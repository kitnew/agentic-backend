# Single-VM production deployment

This deployment keeps the existing application boundaries and adds one production-only
Compose override. It builds application images on the VM, runs one Caddy instance, and
self-hosts LiveKit Server without SIP.

## Requirements

- Linux VM with a public IPv4 address
- Docker Engine 24 or newer
- Docker Compose 2.24.4 or newer (`!reset` is used by the production override)
- DNS records for `API_DOMAIN`, `DEBUG_CHAT_DOMAIN`, and `LIVEKIT_DOMAIN`
- inbound firewall rules listed below
- outbound access to image registries, ACME, Azure OpenAI, and ElevenLabs

VM provisioning, firewall changes, DNS, registry access, and public TLS availability remain
external tasks.

## Configure

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Replace every placeholder. Generate independent secrets with `openssl rand -hex 32`.
`LIVEKIT_PUBLIC_URL` must equal `wss://$LIVEKIT_DOMAIN`, and `LIVEKIT_NODE_IP` must be the
VM's public IPv4 address. Put the Google service-account JSON at the path configured by
`GOOGLE_SERVICE_ACCOUNT_FILE`; it is mounted read-only as a Docker secret.

Protect Debug Chat with a dedicated username and a Caddy bcrypt hash. Generate the hash
interactively so the password is not stored in shell history:

```bash
docker run --rm -it caddy:2.11.4-alpine caddy hash-password
```

Set `DEBUG_CHAT_BASIC_AUTH_USER` and put the resulting hash in
`DEBUG_CHAT_BASIC_AUTH_HASH`, enclosed in single quotes so Compose preserves `$`.
Only the hash is passed to Caddy; never store the plaintext password in the environment.

The real `.env.production`, credentials, certificates, backups, and Caddy state are ignored
or stored outside Git.

### Restricted staging Debug Chat

This mechanism is only for explicitly authorized testing, not end-user authentication.
For a staging VM, set:

```dotenv
APP_ENV=staging
LIVEKIT_STAGING_AUTH_ENABLED=true
LIVEKIT_STAGING_AUTH_CREDENTIAL=replace-with-an-independent-openssl-rand-hex-32-value
LIVEKIT_STAGING_ALLOWED_TENANTS=tenant-id
```

The browser authenticates to Caddy, then calls only the Debug Chat server. That server adds
the staging credential to its private Backend Core request. Backend Core validates the
credential and independently enforces the same explicit tenant allowlist before issuing the
existing short-lived LiveKit participant token. With one configured tenant, the rendered
page contains only that tenant; crafted requests for any other tenant receive `403`.

Disable access by setting `LIVEKIT_STAGING_AUTH_ENABLED=false` and updating `api` and
`debug-chat`. Production must use `APP_ENV=production` and
`LIVEKIT_STAGING_AUTH_ENABLED=false`; Backend Core then rejects staging and development
debug credentials even if their values match.

Rotate access by generating a new staging credential, updating the one environment value
consumed by `api` and `debug-chat`, and running the deployment script. Rotate tester access
separately by generating a new Caddy hash, updating the Basic Auth variables, and recreating
`caddy`. Old credentials stop working after the corresponding containers are updated.

## Network

| Port | Protocol | Purpose |
|---|---|---|
| 80 | TCP | ACME HTTP challenge and HTTPS redirect |
| 443 | TCP | Caddy HTTPS for API, Debug Chat, and LiveKit signaling/WebSocket |
| 443 | UDP | Caddy HTTP/3 |
| 7881 | TCP | LiveKit ICE/TCP fallback |
| 3478 | UDP | LiveKit embedded TURN/UDP |
| 50000-50100 | UDP | LiveKit WebRTC media; configurable in `.env.production` |

PostgreSQL, Redis, API port 8000, Debug Chat port 8080, voice-agent health port 8081, and
LiveKit signaling port 7880 remain private on the Compose network.

Caddy owns TCP/UDP 443. TURN/TLS is intentionally not configured in this slice because it
needs a separate certificate and L4 TLS termination strategy. TURN/UDP remains available on
3478. SIP is not deployed.

## Deploy and operate

```bash
./deploy/deploy.sh
```

The script validates configuration, pulls pinned infrastructure images, builds tagged
application images, starts PostgreSQL/Redis/LiveKit, runs the existing advisory-lock-protected
database initialization and SQL migrations, updates the full stack, and waits for healthchecks.
It never removes volumes.

Manual commands use the same isolated production project:

```bash
docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml ps

docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=200

docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml stop
```

Verify `https://$API_DOMAIN/health`, load `https://$DEBUG_CHAT_DOMAIN/` with the configured
Basic Auth user, and connect a LiveKit client to `wss://$LIVEKIT_DOMAIN`.

For a production environment, verify that a staging credential cannot authorize a session:

```bash
curl -i -X POST "https://$API_DOMAIN/api/v1/voice/livekit/sessions" \
  -H 'Content-Type: application/json' \
  -H "X-LiveKit-Staging-Auth: $LIVEKIT_STAGING_AUTH_CREDENTIAL" \
  --data '{"tenant_id":"tenant-id"}'
```

The response must be `401`. The same request with
`X-LiveKit-Debug-Auth: debug-chat` must also return `401`.

For staging verification, an unauthenticated request to the Debug Chat hostname must return
`401` from Caddy, a wrong Basic Auth password must return `401`, and a valid tester login
must load the page:

```bash
curl -I "https://$DEBUG_CHAT_DOMAIN/"
curl -I -u "$DEBUG_CHAT_BASIC_AUTH_USER:wrong" "https://$DEBUG_CHAT_DOMAIN/"
curl -I -u "$DEBUG_CHAT_BASIC_AUTH_USER" "https://$DEBUG_CHAT_DOMAIN/"
```

Use browser developer tools to confirm the browser posts to
`/debug/livekit-session` on the Debug Chat hostname and never sends
`X-LiveKit-Staging-Auth`. To test backend credential rejection without changing the
deployment, send an intentionally invalid value directly to the API session endpoint; it
must return `401`:

```bash
curl -i -X POST "https://$API_DOMAIN/api/v1/voice/livekit/sessions" \
  -H 'Content-Type: application/json' \
  -H 'X-LiveKit-Staging-Auth: intentionally-invalid' \
  --data '{"tenant_id":"tenant-id"}'
```

To test tenant rejection, submit a crafted POST through the authenticated hostname:

```bash
curl -i -u "$DEBUG_CHAT_BASIC_AUTH_USER" \
  -H 'Content-Type: application/json' \
  --data '{"tenant_id":"not-allowlisted"}' \
  "https://$DEBUG_CHAT_DOMAIN/debug/livekit-session"
```

It must return `403` without contacting Backend Core. Inspect logs with the command above;
staging records contain environment, tenant, and outcome, never credentials or tokens.

## PostgreSQL backup and restore

Choose a host directory and run:

```bash
BACKUP_DIR=/var/backups/agentic-backend ./deploy/backup-postgres.sh
```

The script creates a timestamped `postgres-YYYYmmddTHHMMSSZ.sql.gz` and never deletes old
backups. Test restores before relying on them. Basic restore into the configured database:

```bash
gzip -dc /var/backups/agentic-backend/postgres-TIMESTAMP.sql.gz |
  docker compose --project-name agentic-backend-prod --env-file .env.production \
    -f docker-compose.yml -f docker-compose.prod.yml \
    exec -T postgres sh -c 'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

## Rollback

Keep previous application image tags on the VM or in your registry. Set `APP_IMAGE_TAG` to
the previous tag in `.env.production`, then update application services without rebuilding:

```bash
docker compose --project-name agentic-backend-prod --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --no-build api capability-worker voice-agent debug-chat
```

Database migrations are forward-only. Review schema compatibility before rolling application
images back across a migration.
