from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.tenants.schemas import TenantContext


class DisabledProvider:
    provider_name = "disabled"

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.DISABLED,
            provider=self.provider_name,
            user_message="This action is disabled for this tenant.",
        )
