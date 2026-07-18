from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.tenants.schemas import TenantContext


class CapabilityRouter:
    def __init__(self, registry: CapabilityRegistry | None = None):
        self.registry = registry or CapabilityRegistry()

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        capability_config = tenant_context.capabilities.get(capability_request.name)
        if not capability_config:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.DISABLED,
                provider="disabled",
                user_message="This capability is not configured for this tenant.",
            )

        if not capability_config.enabled:
            disabled_provider = self.registry.get("disabled")
            if disabled_provider:
                return disabled_provider.execute(tenant_context, capability_request)

            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.DISABLED,
                provider=capability_config.provider,
                user_message="This capability is disabled for this tenant.",
            )

        provider = self.registry.get(capability_config.provider)
        if not provider:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=capability_config.provider,
                error=f"Capability provider not found: {capability_config.provider}",
            )

        return provider.execute(tenant_context, capability_request)
