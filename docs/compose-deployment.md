# Single-server Compose topology

Compose is layered by environment:

| Environment | Files | Services |
| --- | --- | --- |
| Development | `docker-compose.yml`, `docker-compose.dev.yml` | Backend, Voice Agent, Job Worker, Debug Chat, LiveKit, PostgreSQL, Redis |
| Staging | `docker-compose.yml`, `docker-compose.deploy.yml`, `.env.staging` | Development core plus Caddy, LiveKit SIP, LiveKit Egress, MinIO, MinIO init |
| Production | `docker-compose.yml`, `docker-compose.deploy.yml`, `.env.production` | Same as staging, under a separate Compose project and named volumes |

`application` is the private service network. `edge` contains only Caddy, Backend, Debug Chat, and LiveKit. Caddy reaches LiveKit at `livekit:7880`; LiveKit is bridge-networked, not host-networked. Caddy is the only HTTP/TLS edge and its admin API is disabled.

```text
Internet -- 80/443 --> Caddy --edge--> Backend / Debug Chat / LiveKit :7880
Internet -----------> LiveKit :7881/tcp, :7882/udp
Internet -----------> LiveKit SIP :5060/tcp+udp, :10000-20000/udp
application --------> PostgreSQL / Redis / MinIO / Egress / Voice Agent / Worker
```

## Required host firewall ports

| Port | Protocol | Owner | Exposure | Purpose |
| --- | --- | --- | --- | --- |
| 80 | TCP | Caddy | Public | ACME HTTP challenge and HTTPS redirect |
| 443 | TCP | Caddy | Public | API, Debug Chat, LiveKit HTTPS/WebSocket |
| 7881 | TCP | LiveKit | Public | RTC TCP fallback |
| 7882 | UDP | LiveKit | Public | RTC UDP mux |
| 5060 | TCP, UDP | LiveKit SIP | Public | SIP signaling |
| 10000-20000 | UDP | LiveKit SIP | Public | SIP RTP |

`7880` is deliberately private behind Caddy. PostgreSQL, Redis, Backend, Debug Chat, MinIO, Egress, health ports, and the Caddy admin API have no deployment host ports. The repository does not contain the server firewall configuration, so its current rules could not be read here; they must match this table before staging/production rollout. TURN is unchanged and remains deferred.

## Operations boundary

All deployment services use `unless-stopped`; `minio-init` uses `restart: "no"` and idempotently creates the bucket/users. Redis uses AOF on `redis-data`, preserving Streams across container/daemon restarts. Persistent state is `postgres-data`, `redis-data`, `minio-data`, `caddy-data`, and `caddy-config` (each Compose project scopes its own volumes).

Application images already run as UID 10001. Deployment adds `no-new-privileges`, read-only roots, and `/tmp` tmpfs to Backend, Voice Agent, and Job Worker; Caddy receives the same hardening. Debug Chat remains on upstream nginx defaults because its image needs nginx runtime writable paths. LiveKit, SIP, Egress, PostgreSQL, Redis, and MinIO keep upstream runtime permissions; Egress retains its pinned Chrome seccomp profile and Chrome sandbox. Backend/Worker receive 30s and Voice Agent 60s SIGTERM grace periods; backend closes its Redis consumers/outbox and Voice Agent drains sessions.

Docker uses the `local` logging driver, defaulting to five 10 MiB files per service. Caddy access logs go to stdout; Caddy does not log request bodies or headers. Egress is the resource-sensitive service (Chrome/encoding); no speculative CPU or memory caps are applied.

Production runs only built application images: deployment files have no application source bind mounts. Mounted configuration is read-only where applicable. Do not put MinIO behind Caddy.

## Staging/production secrets

For the step-by-step setup of every environment variable, see [Compose secrets and environment setup](compose-secrets-and-environments.md).

`.env.staging` and `.env.production` contain both deployment configuration and deployment credentials. Keep the real files out of Git, set mode `0600`, and never print their contents.

The current credential variables are:

```text
POSTGRES_PASSWORD
ADMIN_API_TOKEN
VOICE_AGENT_SERVICE_SECRET
JOB_WORKER_SERVICE_SECRET
LIVEKIT_API_SECRET
ELEVENLABS_API_KEY
AZURE_OPENAI_API_KEY
MINIO_ROOT_PASSWORD
MINIO_EGRESS_SECRET_KEY
MINIO_WORKER_SECRET_KEY
DEBUG_CHAT_BASIC_AUTH_HASH
```

The Worker’s optional Google Sheets and managed-webhook credential directory is a separate host path (`GOOGLE_SHEETS_CREDENTIALS_DIR`) and is mounted only at `/secrets`; it must remain outside the repository.

Back up PostgreSQL, MinIO recordings according to retention policy, and optionally Caddy data; Git already contains Compose/config definitions. `scripts/ops.sh` now performs PostgreSQL dumps only. A persistent MinIO volume is not an off-host backup; recording retention and off-host copies remain a separate operations slice.

## Canonical commands

```bash
# Development
docker compose --env-file infrastructure/compose/.env.dev \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.dev.yml up -d

# Staging
docker compose --env-file infrastructure/compose/.env.staging \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.deploy.yml up -d

# Production
docker compose --env-file infrastructure/compose/.env.production \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.deploy.yml up -d
```

Future deployment tooling must run migrations deliberately, not from Backend startup: bring up PostgreSQL, then run the migration container with the configured `DATABASE_URL`, then start the remaining services. `scripts/ops.sh` is the canonical implementation.

Validate each environment with `config`, `config --services`, and `./scripts/ops.sh <env> validate`. Secret contents are never printed.

## Operations CLI

Use `./scripts/ops.sh <staging|production> <command>`. It is the only wrapper around the two deployment Compose files and reads the matching ignored env file.

```bash
./scripts/ops.sh staging validate
./scripts/ops.sh staging deploy
./scripts/ops.sh production update
./scripts/ops.sh production status
./scripts/ops.sh production logs backend --follow
./scripts/ops.sh production backup
./scripts/ops.sh production restore /var/backups/agentic-backend/production/postgres/<timestamp>.dump
```

`deploy` validates, builds repository images, starts only PostgreSQL with Compose health waiting, runs `alembic ... upgrade head`, then starts the full stack with `--wait --remove-orphans`. `update` adds Compose image pulling before the same build/migrate/start sequence. Migration is never part of Backend startup.

`BACKUP_DIR` is required and must be an absolute path outside this repository. Backup files are private custom-format PostgreSQL archives at `<BACKUP_DIR>/<environment>/postgres/<UTC timestamp>.dump`; temporary files are validated then atomically published. Restore validates the archive, stops Backend before the Worker and Voice Agent, keeps PostgreSQL running, then uses `pg_restore --clean --if-exists`. No normal application writer runs during the destructive restore. On success, the CLI runs `alembic upgrade head` and starts the full stack with Compose health waiting. If archive validation, restore, or migration fails, writers remain stopped and the operator must resolve the failure before starting traffic. Production requires typing `production` or passing `--yes`. Restore never downgrades Alembic or rolls back application images—database restore and application rollback are separate operations.

`stop` is `docker compose stop`, never `down -v`: persistent volumes remain intact. The CLI does not implement MinIO off-host backup, rollback, CI/CD, SSH deployment, Docker Secrets, DNS, firewall, or certificate management.
