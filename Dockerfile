FROM python:3.14.6-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.14.6-slim AS runtime

RUN useradd --uid 10001 --create-home appuser
WORKDIR /app
RUN chown appuser:appuser /app
COPY --from=build --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS voice-agent
EXPOSE 8081
RUN python -m livekit.agents download-files
CMD ["python", "-m", "app.voice_agent.server", "start"]

FROM runtime AS api
EXPOSE 8000

FROM node:24.7.0-alpine AS debug-chat-assets
WORKDIR /build
COPY debug-chat/package.json debug-chat/package-lock.json ./
RUN npm ci --omit=dev

FROM python:3.14.6-slim AS debug-chat
RUN useradd --uid 10001 --create-home appuser
WORKDIR /app/debug-chat
COPY --chown=appuser:appuser debug-chat/server.py debug-chat/index.html debug-chat/livekit-controller.js ./
COPY --from=debug-chat-assets --chown=appuser:appuser \
    /build/node_modules/livekit-client/dist/livekit-client.umd.js \
    ./node_modules/livekit-client/dist/livekit-client.umd.js
ENV DEBUG_CHAT_HOST=0.0.0.0 DEBUG_CHAT_PORT=8080 PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8080
CMD ["python", "server.py"]
