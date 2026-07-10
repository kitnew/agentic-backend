from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.agent_runtime.voice_processing_executor import VoiceProcessingExecutor
from app.api.router import router as api_router
from app.capabilities.registry import CapabilityRegistry
from app.infrastructure.database import init_db
from app.tenants.loader import TenantConfigLoader
from app.voice.audio.storage import get_voice_audio_storage_dir

@asynccontextmanager
async def lifespan(app: FastAPI):
    TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())
    init_db()
    app.state.voice_processing_executor = VoiceProcessingExecutor()
    try:
        yield
    finally:
        app.state.voice_processing_executor.shutdown()

app = FastAPI(lifespan=lifespan)
voice_audio_dir = get_voice_audio_storage_dir()
voice_audio_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/api/v1/voice/audio",
    StaticFiles(directory=str(voice_audio_dir)),
    name="voice-audio",
)

# Mount the main API router
app.include_router(api_router)

@app.get("/")
def read_root():
    return {"Hello": "World"}
