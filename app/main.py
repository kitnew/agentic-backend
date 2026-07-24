from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.router import router as api_router
from app.capabilities.registry import CapabilityRegistry
from app.core.config import InboundSipSettings, VoiceBackendAuthSettings
from app.infrastructure.database import init_db
from app.tenants.loader import TenantConfigLoader

@asynccontextmanager
async def lifespan(app: FastAPI):
    tenants = TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())
    sip = InboundSipSettings.from_env()
    sip.validate()
    if sip.enabled:
        VoiceBackendAuthSettings.from_env().validate()
        if not any(tenant.voice.inbound_dids for tenant in tenants):
            raise ValueError("INBOUND_SIP_ENABLED requires at least one configured tenant DID")
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(api_router)

@app.get("/")
def read_root():
    return {"Hello": "World"}
