from fastapi import APIRouter

from backend_core.interfaces.http.health import router as health_router
from backend_core.modules.tenants import router as tenants_router

router = APIRouter()

router.include_router(health_router)
router.include_router(tenants_router)


@router.get("/")
def read_root():
    return {"Hello": "World"}
