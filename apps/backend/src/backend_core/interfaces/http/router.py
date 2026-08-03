from fastapi import APIRouter

from backend_core.interfaces.http.health import router as health_router
from backend_core.modules.calls.router import admin_router as voice_admin_router
from backend_core.modules.calls.router import router as calls_router
from backend_core.modules.calls.router import runtime_router as call_runtime_router
from backend_core.modules.tenants import router as tenants_router
from backend_core.modules.tenants.router import internal_router

router = APIRouter()

router.include_router(health_router)
router.include_router(tenants_router)
router.include_router(internal_router)
router.include_router(calls_router)
router.include_router(call_runtime_router)
router.include_router(voice_admin_router)


@router.get("/")
def read_root():
    return {"Hello": "World"}
