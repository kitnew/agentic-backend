from fastapi import APIRouter
from app.api.routes import conversations, health, messages, voice

router = APIRouter()

router.include_router(health.router, prefix="/health")
router.include_router(conversations.router, prefix="/api/conversations")
router.include_router(conversations.router, prefix="/api/v1/conversations")
router.include_router(messages.router, prefix="/api/messages")
router.include_router(messages.router, prefix="/api/v1/messages")
router.include_router(voice.router, prefix="/api/voice")
router.include_router(voice.router, prefix="/api/v1/voice")
