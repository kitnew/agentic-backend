from fastapi import FastAPI
from backend_core.bootstrap.lifespan import lifespan
from backend_core.interfaces.http import router

def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Platform Backend Core",
        lifespan=lifespan,
    )

    app.include_router(router)

    return app