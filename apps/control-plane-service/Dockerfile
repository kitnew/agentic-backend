FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.14.6-slim

COPY --from=uv /uv /bin/uv

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
COPY apps/agentctl/pyproject.toml apps/agentctl/pyproject.toml
COPY apps/backend/pyproject.toml apps/backend/pyproject.toml
COPY apps/control-plane-service/pyproject.toml apps/control-plane-service/pyproject.toml
COPY apps/job-worker/pyproject.toml apps/job-worker/pyproject.toml
COPY apps/voice-agent/pyproject.toml apps/voice-agent/pyproject.toml
COPY packages/contracts/pyproject.toml packages/contracts/pyproject.toml
COPY packages/observability/pyproject.toml packages/observability/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package control-plane-service --no-install-workspace

COPY apps/control-plane-service apps/control-plane-service
COPY packages/contracts packages/contracts
COPY packages/observability packages/observability

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package control-plane-service

RUN useradd --create-home --uid 10001 app
USER app

CMD ["control-plane-service"]
