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

All deployment credentials are ordinary environment variables in the selected
`.env` file. This includes PostgreSQL, Backend, service-to-service, LiveKit,
provider, MinIO, and Debug Chat credentials. Keep the real `.env` files out of
Git and never print them in logs or support output.

The credential variables are:

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
