from fastapi import FastAPI

from backend_core.bootstrap.lifespan import lifespan
from backend_core.bootstrap.settings import Settings
from backend_core.interfaces.http import router
from backend_core.platform.database import Database


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    if database is None:
        database = Database(str(settings.database_url))

    app = FastAPI(
        title="Agent Platform Backend Core",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.settings = settings

    app.include_router(router)

    return app
