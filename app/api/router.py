from fastapi import APIRouter
from app.api.routes import conversations, health, messages

router = APIRouter()

router.include_router(health.router, prefix="/health")
router.include_router(conversations.router, prefix="/api/conversations")
router.include_router(conversations.router, prefix="/api/v1/conversations")
router.include_router(messages.router, prefix="/api/messages")
router.include_router(messages.router, prefix="/api/v1/messages")
