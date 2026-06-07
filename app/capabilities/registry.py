from typing import Protocol

from app.capabilities.providers.disabled import DisabledProvider
from app.capabilities.providers.google_sheets import GoogleSheetsReservationProvider
from app.capabilities.providers.manual import ManualReservationProvider
from app.capabilities.schemas import CapabilityRequest, CapabilityResult
from app.tenants.schemas import TenantContext


class CapabilityProvider(Protocol):
    provider_name: str

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        pass


class CapabilityRegistry:
    def __init__(self):
        self.providers: dict[str, CapabilityProvider] = {
            "disabled": DisabledProvider(),
            "google_sheets": GoogleSheetsReservationProvider(),
            "manual": ManualReservationProvider(),
        }

    def get(self, provider_name: str) -> CapabilityProvider | None:
        return self.providers.get(provider_name)
