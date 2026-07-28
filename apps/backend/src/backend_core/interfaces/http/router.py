from fastapi import APIRouter

from backend_core.interfaces.http.health import router as health_router

router = APIRouter()

router.include_router(health_router, prefix="/health")

@router.get("/")
def read_root():
    return {"Hello": "World"}