# Staging and production configuration

Compose staging and production use the environment files directly:

```text
infrastructure/compose/.env.staging
infrastructure/compose/.env.production
```

Copy the checked-in example, set restrictive permissions, and replace every
`replace-with-*` value:

```bash
cd infrastructure/compose
cp .env.production.example .env.production
chmod 600 .env.production
```

The example files are grouped in this order: deployment paths, database/Redis
and internal services, runtime tuning, MinIO recordings, LiveKit/SIP, provider
APIs, public URLs/TLS, authentication, and Docker logging. Keep that order when
adding variables so release reviews stay quick.

Generate values instead of inventing them:

```bash
# Random tokens, service secrets, API tokens, and MinIO passwords
openssl rand -hex 32

# Standard Base64 AES-256 integration encryption key (exactly 32 decoded bytes)
openssl rand -base64 32 | tr -d '\n'; echo

# Caddy Basic Auth hash; prompts for the password
docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

Use one generated value per variable. Do not reuse the Admin API token as an
agent/service secret. Keep credentials stable after PostgreSQL and MinIO are
initialized; changing their environment values alone does not rotate them.

For MinIO, use four separate values:

| Variable pair | Used by | Permission |
| --- | --- | --- |
| `MINIO_EGRESS_ACCESS_KEY` / `MINIO_EGRESS_SECRET_KEY` | LiveKit Egress | read/write recordings |
| `MINIO_WORKER_ACCESS_KEY` / `MINIO_WORKER_SECRET_KEY` | Job Worker | read-only recordings |

The two access keys can be stable names such as `agentic-egress` and
`agentic-worker`; generate only the secret values with `openssl rand -hex 32`.
`MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` are separate bootstrap/admin
credentials and must not be reused by either service.

`MINIO_REGION=eu-central-1` is the S3 signing region used by this MinIO
instance. It labels the local server as Frankfurt/central Europe; it does not
move Docker volume data to a European cloud region. The actual data location is
the server and its `minio-data` volume.

All deployment credentials are ordinary environment variables in the selected
`.env` file. This includes PostgreSQL, Backend, service-to-service, LiveKit,
provider, MinIO, and Grafana credentials. Keep the real `.env` files out of
Git and never print them in logs or support output.

The credential variables are:

```text
POSTGRES_PASSWORD
ADMIN_API_TOKEN
VOICE_AGENT_SERVICE_SECRET
JOB_WORKER_SERVICE_SECRET
LIVEKIT_API_SECRET
AZURE_OPENAI_API_KEY
MINIO_ROOT_PASSWORD
MINIO_EGRESS_SECRET_KEY
MINIO_WORKER_SECRET_KEY
GRAFANA_ADMIN_PASSWORD
```

Use the same stable values for an environment after its database and MinIO
volumes have been initialized. Changing `POSTGRES_PASSWORD` or
`MINIO_ROOT_PASSWORD` in `.env` does not rotate an already initialized service;
rotate those credentials through PostgreSQL or MinIO first.

Optional Google Sheets and managed-webhook files remain separate integration
files under `GOOGLE_SHEETS_CREDENTIALS_DIR`. They are not deployment
credentials and are mounted only at `/secrets`.

Validate and deploy with:

```bash
./scripts/ops.sh staging validate
./scripts/ops.sh staging deploy
./scripts/ops.sh production validate
./scripts/ops.sh production deploy
```

`validate` checks the merged Compose configuration and validates Caddy using
the environment values. `deploy` starts PostgreSQL, runs Alembic, then waits
for the application stack. It never deletes volumes.
