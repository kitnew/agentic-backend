from fastapi import APIRouter
from app.api.routes import health, messages

router = APIRouter()

router.include_router(health.router, prefix="/health")
router.include_router(messages.router, prefix="/api/v1/messages")