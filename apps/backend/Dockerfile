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
    uv sync --frozen --no-dev --package backend-core --no-install-workspace

COPY apps/backend apps/backend
COPY packages/contracts packages/contracts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package backend-core

RUN useradd --create-home --uid 10001 app
USER app

CMD ["sh", "-c", "alembic -c apps/backend/alembic.ini upgrade head && exec uvicorn backend_core.main:app --host 0.0.0.0 --port 8000"]
