from fastapi import Depends

from app.application.capabilities.boundary import CapabilityExecutor, InProcessCapabilityExecutor
from app.application.capabilities.redis_executor import RedisCapabilityExecutor
from app.capabilities.router import CapabilityRouter
from app.core.config import CapabilitySettings
from app.tenants.loader import TenantConfigLoader


def get_tenant_config_loader() -> TenantConfigLoader:
    return TenantConfigLoader()


def get_capability_router() -> CapabilityRouter:
    return CapabilityRouter()


def get_capability_executor(
    tenant_config_loader: TenantConfigLoader = Depends(get_tenant_config_loader),
    capability_router: CapabilityRouter = Depends(get_capability_router),
) -> CapabilityExecutor:
    settings = CapabilitySettings.from_env()
    if settings.execution_mode == "redis":
        return RedisCapabilityExecutor(settings=settings)
    return InProcessCapabilityExecutor(
        tenant_config_loader=tenant_config_loader,
        capability_router=capability_router,
    )


def get_finalization_publisher() -> RedisCapabilityExecutor:
    return RedisCapabilityExecutor(settings=CapabilitySettings.from_env())
