from fastapi import FastAPI, HTTPException, Request, status

from control_plane import SERVICE_NAME
from control_plane.runtime.lifecycle import ServiceLifecycle


def create_http_app(lifecycle: ServiceLifecycle) -> FastAPI:
    app = FastAPI(title="Agentic Backend Control Plane", lifespan=lifecycle.lifespan)
    app.state.lifecycle = lifecycle

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        runtime: ServiceLifecycle = request.app.state.lifecycle
        readiness = await runtime.readiness()
        if readiness.ready:
            return {"status": "ok", "service": SERVICE_NAME}
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unavailable",
                "service": SERVICE_NAME,
                "checks": {
                    "postgres": readiness.postgres,
                    "nats": readiness.nats,
                },
            },
        )

    return app
