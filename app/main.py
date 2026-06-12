from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.router import router as api_router
from app.capabilities.registry import CapabilityRegistry
from app.infrastructure.database import init_db
from app.tenants.loader import TenantConfigLoader

@asynccontextmanager
async def lifespan(app: FastAPI):
    TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Mount the main API router
app.include_router(api_router)

@app.get("/")
def read_root():
    return {"Hello": "World"}
