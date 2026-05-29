from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.router import router as api_router
from app.infrastructure.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on application startup
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Mount the main API router
app.include_router(api_router)

@app.get("/")
def read_root():
    return {"Hello": "World"}