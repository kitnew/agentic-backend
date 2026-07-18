from fastapi import FastAPI

from backend.apps.api.router import router
from backend.bootstrap.lifespan import lifespan
from backend.bootstrap.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.include_router(router)

    return app


app = create_app()