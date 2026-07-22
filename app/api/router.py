from fastapi import APIRouter
from app.api.routes import health, voice_sessions

router = APIRouter()

router.include_router(health.router, prefix="/health")
router.include_router(voice_sessions.router, prefix="/api/v1/voice")
