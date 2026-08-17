# Single-VM production deployment

This deployment keeps the existing application boundaries and adds one production-only
Compose override. It builds application images on the VM, runs one Caddy instance, and
self-hosts LiveKit Server with optional inbound SIP.

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

Do not copy `app/.env`: it is development-only and its LiveKit URLs and debug settings are
not valid for this deployment.

Generate each shared secret independently. The following command prints ready-to-paste
assignments but does not modify `.env.production`:

```bash
for name in POSTGRES_PASSWORD VOICE_SESSION_TOKEN_SECRET LIVEKIT_SESSION_AUTH_SECRET
do
  printf '%s=' "$name"
  openssl rand -hex 32
done
```

Generate the LiveKit API key and secret with the pinned server image:

```bash
docker run --rm livekit/livekit-server:v1.13.1 generate-keys
```

Copy its `API Key` into `LIVEKIT_API_KEY` and `API Secret` into
`LIVEKIT_API_SECRET`. These are separate from both application authentication secrets.

Protect Debug Chat with a chosen username and a Caddy bcrypt hash. Generate the hash
interactively so the plaintext password is not stored in shell history:

```bash
docker run --rm -it caddy:2.11.4-alpine caddy hash-password
```

Set `DEBUG_CHAT_BASIC_AUTH_USER` and put the resulting hash in
`DEBUG_CHAT_BASIC_AUTH_HASH`, enclosed in single quotes so Compose preserves `$`.
Only the hash is passed to Caddy; never store the plaintext password in the environment.

Replace or verify these environment-specific values:

| Variable | Required value |
|---|---|
| `APP_IMAGE_TAG` | immutable tag for this release; never `latest` |
| `API_DOMAIN` | API DNS name pointing to the VM |
| `DEBUG_CHAT_DOMAIN` | restricted Debug Chat DNS name pointing to the VM |
| `LIVEKIT_DOMAIN` | LiveKit DNS name pointing to the VM |
| `CADDY_EMAIL` | real ACME contact email |
| `DEBUG_CHAT_BASIC_AUTH_USER` | chosen tester username |
| `LIVEKIT_PUBLIC_URL` | exactly `wss://` followed by `LIVEKIT_DOMAIN` |
| `LIVEKIT_NODE_IP` | public IPv4 address of the VM |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` | staging-scoped Azure credentials |
| `ELEVENLABS_API_KEY` | staging-scoped ElevenLabs credential |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | existing JSON file path, readable by Docker |

Keep `LIVEKIT_INTERNAL_URL=ws://livekit:7880` for application containers. The
host-networked SIP service separately uses `LIVEKIT_SIP_INTERNAL_URL=ws://127.0.0.1:7880`
and `LIVEKIT_SIP_REDIS_ADDRESS=127.0.0.1:6379`. The image repository names, pinned
infrastructure images, PostgreSQL names, LiveKit port range, log rotation, and backup path
already have usable defaults; change them only when the server layout requires it.

The deployment script rejects empty values, example domains, placeholders, short/reused
secrets, `latest` tags, invalid Caddy hashes, inconsistent LiveKit URLs, and a missing Google
service-account file before it starts or updates containers.

Validate the completed file without pulling images, building, or starting anything:

```bash
./deploy/deploy.sh --check
```

Fix the reported value and repeat until it prints `Deployment configuration is valid.`

The real `.env.production`, credentials, certificates, backups, and Caddy state are ignored
or stored outside Git.

### Restricted staging Debug Chat

This mechanism is only for explicitly authorized testing, not end-user authentication.
For a staging VM, change the three mode/tenant values and generate a fourth independent
secret:

```bash
printf 'LIVEKIT_STAGING_AUTH_CREDENTIAL='
openssl rand -hex 32
```

Paste that output and set:

```dotenv
APP_ENV=staging
LIVEKIT_STAGING_AUTH_ENABLED=true
LIVEKIT_STAGING_AUTH_CREDENTIAL=<generated value>
LIVEKIT_STAGING_ALLOWED_TENANTS=demo_restaurant
```

Use a comma-separated list only when multiple tenants are intentionally authorized. Do not
reuse `VOICE_SESSION_TOKEN_SECRET`, `LIVEKIT_SESSION_AUTH_SECRET`, or `LIVEKIT_API_SECRET`.

The browser authenticates to Caddy, then calls only the Debug Chat server. That server adds
the staging credential to its private Backend Core request. Backend Core validates the
credential and independently enforces the same explicit tenant allowlist before issuing the
existing short-lived LiveKit participant token. With one configured tenant, the rendered
page contains only that tenant; crafted requests for any other tenant receive `403`.

Disable access by setting `LIVEKIT_STAGING_AUTH_ENABLED=false` and updating `api` and
`debug-chat`; the credential and allowlist may then be empty. Production must use
`APP_ENV=production` and
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
| 5060 | TCP/UDP | Optional LiveKit SIP signalling; configurable |
| 10000-20000 | UDP | Optional LiveKit SIP RTP; configurable |
| 8082 | TCP | Optional LiveKit SIP health endpoint; keep firewalled/private |

PostgreSQL, API port 8000, Debug Chat port 8080, and voice-agent health port 8081 remain
private on the Compose network. LiveKit port 7880 and Redis port 6379 are bound to host
loopback only for the host-networked SIP service; Redis is never publicly exposed.

Caddy owns TCP/UDP 443. TURN/TLS is intentionally not configured in this slice because it
needs a separate certificate and L4 TLS termination strategy. TURN/UDP remains available on
3478. SIP ports are opened only when inbound SIP is enabled; see
[`inbound-livekit-sip.md`](inbound-livekit-sip.md).

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
