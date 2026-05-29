from fastapi import APIRouter
from app.backend.api.messages import messages_router

router = APIRouter(prefix="/api")

router.include_router(messages_router)

@router.get("/health")
def health():
    return {"status": "ok"}