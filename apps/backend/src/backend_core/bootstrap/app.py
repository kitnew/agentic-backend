from fastapi import FastAPI

from backend_core.bootstrap.lifespan import lifespan
from backend_core.bootstrap.settings import Settings
from backend_core.interfaces.http import router
from backend_core.platform.control_plane import ControlPlaneClient
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    livekit: LiveKitAdapter | None = None,
) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    if database is None:
        database = Database(str(settings.database_url))
    if livekit is None:
        livekit = LiveKitAdapter(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key.get_secret_value(),
            api_secret=settings.livekit_api_secret.get_secret_value(),
            participant_token_ttl_seconds=(
                settings.livekit_participant_token_ttl_seconds
            ),
        )

    app = FastAPI(
        title="Agent Platform Backend Core",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.settings = settings
    app.state.livekit = livekit
    app.state.control_plane = ControlPlaneClient(
        str(settings.control_plane_url),
        settings.backend_core_service_secret.get_secret_value(),
        settings.internal_api_audience,
    )
    app.state.outbox_tracer = None
    app.state.core_metrics = None

    app.include_router(router)

    return app
