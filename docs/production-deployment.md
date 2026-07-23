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

The real `.env.production`, credentials, certificates, backups, and Caddy state are ignored
or stored outside Git.

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

Verify `https://$API_DOMAIN/health`, load `https://$DEBUG_CHAT_DOMAIN/`, and connect a
LiveKit client to `wss://$LIVEKIT_DOMAIN`. Debug Chat is routed but the development auth
bypass is disabled in production, so anonymous session creation is expected to return 401.

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
