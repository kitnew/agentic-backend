from backend_core.interfaces.http.health import router as health_router
from backend_core.modules.calls.router import admin_router as voice_admin_router
from backend_core.modules.calls.router import call_admin_router
from backend_core.modules.calls.router import router as calls_router
from backend_core.modules.calls.router import runtime_router as call_runtime_router
from backend_core.modules.conversations.router import (
    admin_router as conversation_admin_router,
)
from backend_core.modules.conversations.router import (
    internal_router as conversation_internal_router,
)
from backend_core.modules.integrations.router import router as integrations_router
from backend_core.modules.tenants import router as tenants_router
from backend_core.modules.tenants.authoring_router import router as authoring_router
from backend_core.modules.tenants.component_router import router as component_router
from backend_core.modules.tenants.discovery_router import router as discovery_router
from backend_core.modules.tenants.platform_component_router import (
    router as platform_component_router,
)
from backend_core.modules.tenants.router import (
    internal_router,
    telephony_platform_router,
)
from backend_core.runtime.capabilities.router import (
    runtime_router as capability_runtime_router,
)
from backend_core.runtime.capabilities.router import (
    voice_router as capability_voice_router,
)
from backend_core.runtime.capabilities.router import (
    worker_router as capability_worker_router,
)
from backend_core.runtime.finalization.router import router as finalization_router
from backend_core.runtime.finalization.webhook import router as livekit_webhook_router
from fastapi import APIRouter

admin_router = APIRouter()
admin_router.include_router(tenants_router)
admin_router.include_router(component_router)
admin_router.include_router(authoring_router)
admin_router.include_router(discovery_router)
admin_router.include_router(platform_component_router)
admin_router.include_router(telephony_platform_router)
admin_router.include_router(voice_admin_router)
admin_router.include_router(call_admin_router)
admin_router.include_router(conversation_admin_router)
admin_router.include_router(integrations_router)

router = APIRouter()

router.include_router(health_router)
router.include_router(admin_router)
router.include_router(internal_router)
router.include_router(calls_router)
router.include_router(call_runtime_router)
router.include_router(conversation_internal_router)
router.include_router(capability_voice_router)
router.include_router(capability_worker_router)
router.include_router(capability_runtime_router)
router.include_router(finalization_router)
router.include_router(livekit_webhook_router)


@router.get("/")
def read_root():
    return {"Hello": "World"}
