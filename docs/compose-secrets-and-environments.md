# Staging and production configuration

This document explains the values required by the single-server Compose deployment and how to provision its host-side secret files.

The deployment has two inputs:

```text
infrastructure/compose/.env.staging
infrastructure/compose/.env.production
    ordinary configuration only

SECRETS_DIR
    password and credential files, outside Git
```

Do not put production credentials in either environment file. The `.env.*` files are ignored by Git; they still must not contain migrated secrets because Compose would pass them to containers as environment variables.

## 1. Create the environment files

Start from the checked-in examples:

```bash
cd /path/to/agentic-backend-new/infrastructure/compose
cp .env.staging.example .env.staging
cp .env.production.example .env.production
chmod 600 .env.staging .env.production
```

Edit both files. Keep the project names and use different values for staging and production where state or credentials are environment-specific.

At minimum, replace every `replace-with-*` value. Defaults such as `redis://redis:6379/0`, `7881`, `7882`, `5060`, `10000-20000`, retention windows, and log rotation may remain unchanged unless the deployment has an explicit reason to change them.

## 2. Values that are generated locally

These values do not come from an external provider. Generate them once, store them in the appropriate secret file or env file, and keep them stable for that environment.

### Secret files

Required files under `SECRETS_DIR`:

| File | Used by | How to obtain |
| --- | --- | --- |
| `postgres_password` | PostgreSQL, Backend | Generate a random value. This becomes the PostgreSQL superuser password on first database initialization. |
| `admin_api_token` | Backend | Generate a random token of at least 32 characters. This is the internal/admin API credential. |
| `voice_agent_service_secret` | Backend, Voice Agent | Generate a random token of at least 32 characters. Use the same file for both services. |
| `job_worker_service_secret` | Backend, Job Worker | Generate a random token of at least 32 characters. Use the same file for both services. |
| `livekit_api_secret` | Backend, LiveKit, SIP, Egress, Voice Agent | Generate one random value and use it for the whole environment. `LIVEKIT_API_KEY` in the env file is its matching identifier. |
| `elevenlabs_api_key` | Voice Agent | Obtain from the ElevenLabs account; do not generate a local replacement. |
| `azure_openai_api_key` | Voice Agent, Job Worker | Obtain from the Azure OpenAI resource; do not generate a local replacement. |
| `minio_root_password` | MinIO, MinIO-init | Generate a random value. It is used only for bootstrap/admin access. |
| `minio_egress_secret_key` | MinIO-init, Egress | Generate a random value for the Egress write identity. |
| `minio_worker_secret_key` | MinIO-init, Job Worker | Generate a random value for the Worker read identity. |
| `debug_chat_basic_auth_hash` | Caddy | Generate a bcrypt hash of the operator-selected Debug Chat password. Store only the hash, never the plaintext password. |

PostgreSQL and MinIO bootstrap passwords are initialization credentials. Replacing their files later does not change an already initialized database or MinIO instance by itself; rotate those credentials through the service-native procedure and then update the corresponding file.

Generate random values without putting them in shell history:

```bash
openssl rand -hex 32
```

For each generated value, write it as one file with no trailing application configuration:

```bash
umask 077
printf '%s' "$(openssl rand -hex 32)" \
  > /opt/agentic-backend/secrets/staging/admin_api_token
chmod 600 /opt/agentic-backend/secrets/staging/admin_api_token
```

Repeat for the generated files. Do not use the same random value for different files, except that the same `voice_agent_service_secret`, `job_worker_service_secret`, and `livekit_api_secret` file is intentionally consumed by their listed services.

For convenience, this loop creates only the locally generated files. It does not overwrite existing files and it does not create provider credentials:

```bash
secret_dir=/opt/agentic-backend/secrets/staging
umask 077
for name in \
  postgres_password \
  admin_api_token \
  voice_agent_service_secret \
  job_worker_service_secret \
  livekit_api_secret \
  minio_root_password \
  minio_egress_secret_key \
  minio_worker_secret_key; do
  if [ ! -e "$secret_dir/$name" ]; then
    openssl rand -hex 32 > "$secret_dir/$name"
    chmod 600 "$secret_dir/$name"
  fi
done
```

Run the same loop with the production directory only after checking that staging and production are intentionally isolated. Never copy a production secret directory into staging or commit either directory.

Create the directories first:

```bash
sudo install -d -m 700 /opt/agentic-backend/secrets/staging
sudo install -d -m 700 /opt/agentic-backend/secrets/production
sudo chown -R "$USER:$USER" /opt/agentic-backend/secrets
```

If the deployment user cannot own `/opt/agentic-backend`, create the directories as root and write files with `sudo`, while preserving directory mode `0700` and file mode `0600`.

### Debug Chat hash

Generate a bcrypt hash using the exact pinned Caddy image:

```bash
docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

Save the resulting hash, including its `$2...` prefix, without quotes:

```bash
umask 077
printf '%s' '$2a$...' \
  > /opt/agentic-backend/secrets/staging/debug_chat_basic_auth_hash
chmod 600 /opt/agentic-backend/secrets/staging/debug_chat_basic_auth_hash
```

The username is ordinary configuration in `DEBUG_CHAT_BASIC_AUTH_USER`. The password itself must not be stored in `.env`, Git, Caddyfile, or documentation.

## 3. Values obtained from external systems

These are configuration values, identifiers, or provider credentials. The deployment cannot invent them correctly.

| Variable | Meaning | Source |
| --- | --- | --- |
| `API_DOMAIN` | Public Backend/API hostname | DNS zone you control. Create an A/AAAA record to the server. |
| `DEBUG_CHAT_DOMAIN` | Public Debug Chat hostname | DNS zone you control. Create an A/AAAA record to the server. |
| `LIVEKIT_DOMAIN` | Public LiveKit signaling hostname | DNS zone you control. Create an A/AAAA record to the server. |
| `CADDY_EMAIL` | ACME certificate contact | Real operations email address. Caddy uses it for certificate registration/renewal notices. |
| `LIVEKIT_NODE_IP` | Public address advertised in RTC ICE candidates | Public IPv4 address of the server, or the explicitly configured reachable address. Do not use `127.0.0.1` in staging/production. |
| `LIVEKIT_PUBLIC_URL` | Public signaling URL | Usually `wss://` followed by `LIVEKIT_DOMAIN`, for example `wss://livekit.staging.example.com`. |
| `LIVEKIT_API_KEY` | LiveKit key identifier | Generate a stable identifier such as `LK_STAGING_<random>`; it is not the secret and remains in the env file. The matching secret is `livekit_api_secret`. |
| `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` | Existing LiveKit SIP outbound trunk resource ID | Obtain from the existing LiveKit/Telnyx SIP provisioning flow. Do not invent `ST_replace_me`. |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint | Azure Portal, OpenAI resource → endpoint. |
| `AZURE_OPENAI_DEPLOYMENT` | Actual Azure model deployment name | Azure OpenAI resource → Model deployments. |
| `AZURE_OPENAI_MODEL` | Repository logical model name | The logical model key expected by the application configuration. Keep it aligned with the deployment mapping; it is not necessarily the Azure deployment name. |
| `AZURE_OPENAI_API_VERSION` | Azure OpenAI API version | The version supported by the selected Azure deployment/API. Keep staging and production explicit. |
| `MINIO_ROOT_USER` | MinIO bootstrap username | Choose a stable non-default identifier. It is configuration, but never use a public/default value. |
| `MINIO_EGRESS_ACCESS_KEY` | MinIO Egress identity name | Choose a stable identifier, for example `egress_staging`. |
| `MINIO_WORKER_ACCESS_KEY` | MinIO Worker identity name | Choose a stable identifier, for example `worker_staging`. |
| `AGENTCTL_API_URL` | Control Plane/Backend API URL used by `agentctl` | Use the reachable API URL, normally `https://` plus `API_DOMAIN`. It is not used to provision Compose secrets. |

The following values are normally unchanged between environments because they are internal Compose addresses or topology defaults:

```env
REDIS_URL=redis://redis:6379/0
LIVEKIT_URL=ws://livekit:7880
BACKEND_CORE_URL=http://backend:8000
LIVEKIT_EGRESS_REDIS_ADDRESS=redis:6379
LIVEKIT_SIP_REDIS_ADDRESS=redis:6379
MINIO_ENDPOINT_INTERNAL=http://minio:9000
MINIO_WORKER_ENDPOINT=minio:9000
MINIO_BUCKET=call-recordings
MINIO_SECURE=false
```

The public ports are part of the existing firewall contract:

```env
LIVEKIT_TCP_PORT=7881
LIVEKIT_UDP_PORT=7882
LIVEKIT_SIP_PORT=5060
LIVEKIT_SIP_RTP_PORT=10000-20000
```

Do not change these ranges casually; update the separately managed firewall if they are intentionally changed.

## 4. Azure and ElevenLabs setup

### Azure OpenAI

For each environment, obtain or confirm:

1. the Azure OpenAI resource endpoint;
2. an API key for that resource;
3. the deployed model name;
4. the API version supported by that deployment;
5. the repository logical model key in `AZURE_OPENAI_MODEL`.

Put only the endpoint, deployment name, API version, and logical model name in `.env.staging` or `.env.production`. Put the API key in `azure_openai_api_key`.

### ElevenLabs

Create or obtain the ElevenLabs API key from the account/project used by that environment. Put it only in `elevenlabs_api_key`. Do not put it in `ELEVENLABS_API_KEY` in staging/production `.env` files.

## 5. MinIO identities

MinIO uses three separate credential pairs:

```text
root user + minio_root_password
MINIO_EGRESS_ACCESS_KEY + minio_egress_secret_key
MINIO_WORKER_ACCESS_KEY + minio_worker_secret_key
```

The `minio-init` one-shot service creates the `call-recordings` bucket and applies the Egress read/write and Worker read-only policies idempotently. Do not merge these identities or rotate only one side of a pair without restarting/reinitializing the affected service.

## 6. Optional Worker integration files

`GOOGLE_SHEETS_CREDENTIALS_DIR` is separate from `SECRETS_DIR`. For an environment that does not use Google Sheets or managed webhooks, leave:

```env
GOOGLE_SHEETS_CREDENTIAL_FILE_MAP={}
```

and no integration files are required.

If integrations are enabled, create a separate directory outside Git, for example:

```text
/opt/agentic-backend/integration-secrets/staging/
/opt/agentic-backend/integration-secrets/production/
```

Put tenant Google service-account JSON files and `managed-webhooks.json` there, then set the existing mapping variables consistently. These files are mounted to `/secrets`, not mixed with Docker Secrets under `/run/secrets`.

The old repository directories `secrets/` and `infrastructure/compose/secrets/` are development/integration leftovers. Do not put staging/production deployment credentials there.

## 7. Validation workflow

After creating one environment’s configuration and files:

```bash
./scripts/ops.sh staging validate
```

Then inspect the resolved service list without printing secret contents:

```bash
docker compose \
  --env-file infrastructure/compose/.env.staging \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.deploy.yml \
  config --services
```

Expected deployment services are:

```text
backend
voice-agent
job-worker
debug-chat
livekit
postgres
redis
caddy
livekit-sip
livekit-egress
minio
minio-init
```

Repeat for production before `deploy` or `update`:

```bash
./scripts/ops.sh production validate
```

`validate` fails if `SECRETS_DIR` is missing, relative, inside the repository, or if any required file is missing, unreadable, or empty. It never prints secret contents.

## 8. First deployment

Once validation passes:

```bash
./scripts/ops.sh staging deploy
./scripts/ops.sh production deploy
```

`deploy` builds repository-owned images, starts PostgreSQL, runs the explicit Alembic migration, starts the full stack, and waits for Compose health/status. Migrations are not run automatically by Backend startup.

For later releases:

```bash
./scripts/ops.sh staging update
./scripts/ops.sh production update
```

## 9. Rotation and backups

Secret rotation is not automated in this slice. Replace the relevant host file, set restrictive permissions, and recreate/restart only the services that consume it. Coordinate credential rotation with the provider or MinIO policy state.

PostgreSQL backups are created by:

```bash
./scripts/ops.sh production backup
```

The backup is written under `BACKUP_DIR/production/postgres/`. A persistent MinIO volume is not an off-host recording backup; MinIO backup/retention automation is deferred.

Production restore is a maintenance operation. The CLI confirms the destructive action, stops Backend/Worker/Voice Agent writers, keeps PostgreSQL running, restores the dump, runs `alembic upgrade head`, and starts the application stack only after the restore succeeds.
