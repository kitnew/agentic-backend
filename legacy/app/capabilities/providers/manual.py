from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.tenants.schemas import TenantContext


class ManualReservationProvider:
    provider_name = "manual"

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SUCCESS,
            provider=self.provider_name,
            user_message="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí.",
            output={
                "reservation_status": "pending_manual_confirmation",
            },
        )
