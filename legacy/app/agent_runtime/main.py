from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent_runtime.voice_processing_executor import VoiceProcessingExecutor
from app.agent_runtime.voice_turn_processor import VoiceTurnProcessor
from app.agent_runtime.voice_ws import router as voice_router
from app.api.routes.messages import get_capability_executor, get_capability_router, get_tenant_config_loader
from app.capabilities.registry import CapabilityRegistry
from app.core.config import AgentRuntimeSettings
from app.infrastructure.database import init_db
from app.tenants.loader import TenantConfigLoader
from app.voice.session_token import VoiceRuntimeAuthenticator, VoiceSessionTokenCodec
from app.voice.stt.streaming import ElevenLabsStreamingSTTProvider


@asynccontextmanager
async def lifespan(app: FastAPI):
    TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())
    init_db()
    settings = AgentRuntimeSettings.from_env()
    loader = get_tenant_config_loader()
    app.state.tenant_config_loader = loader
    router = get_capability_router()
    capability_executor = get_capability_executor(loader, router)
    app.state.voice_authenticator = VoiceRuntimeAuthenticator(
        VoiceSessionTokenCodec(settings.session_token_secret)
    )
    app.state.voice_processing_executor = VoiceProcessingExecutor(
        turn_processor=VoiceTurnProcessor(capability_executor=capability_executor)
    )
    app.state.agent_runtime_settings = settings
    app.state.streaming_stt_provider = ElevenLabsStreamingSTTProvider()
    try:
        yield
    finally:
        app.state.voice_processing_executor.shutdown()


def create_agent_runtime_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    app.include_router(voice_router, prefix="/api/v1/voice")
    app.include_router(voice_router, prefix="/api/voice")
    return app


app = create_agent_runtime_app()
