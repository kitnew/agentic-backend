FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.14.6-slim

COPY --from=uv /uv /bin/uv

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
COPY apps/backend/pyproject.toml apps/backend/pyproject.toml
COPY apps/job-worker/pyproject.toml apps/job-worker/pyproject.toml
COPY apps/voice-agent/pyproject.toml apps/voice-agent/pyproject.toml
COPY packages/contracts/pyproject.toml packages/contracts/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package job-worker --no-install-workspace

COPY apps/job-worker apps/job-worker
COPY packages/contracts packages/contracts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package job-worker

RUN useradd --create-home --uid 10001 app
USER app

CMD ["up"]
