from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.agent.profiles.loader import AgentProfileLoader
from app.api.router import router as api_router
from app.capabilities.registry import CapabilityRegistry
from app.infrastructure.database import init_db
from app.tenants.loader import TenantConfigLoader

@asynccontextmanager
async def lifespan(app: FastAPI):
    AgentProfileLoader().validate_all()
    tenant_contexts = TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())
    profile_loader = AgentProfileLoader()
    for tenant_context in tenant_contexts:
        profile_loader.load(tenant_context.agent.profile)
    # Initialize database tables on application startup
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Mount the main API router
app.include_router(api_router)

@app.get("/")
def read_root():
    return {"Hello": "World"}
