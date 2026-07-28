from backend_core.interfaces.http.health import router as health_router
from fastapi import APIRouter

router = APIRouter()

router.include_router(health_router)


@router.get("/")
def read_root():
    return {"Hello": "World"}
