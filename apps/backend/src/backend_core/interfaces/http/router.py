from backend_core.interfaces.http.health import router as health_router
from backend_core.modules.calls.router import router as calls_router
from backend_core.modules.tenants import router as tenants_router
from backend_core.modules.tenants.router import internal_router
from fastapi import APIRouter

router = APIRouter()

router.include_router(health_router)
router.include_router(tenants_router)
router.include_router(internal_router)
router.include_router(calls_router)


@router.get("/")
def read_root():
    return {"Hello": "World"}
