from pydantic import ValidationError

from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import (
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
    RoomAvailabilityRequest,
)
from app.tenants.policies import Clock, localized_response, tenant_local_datetime, utc_now
from app.tenants.schemas import TenantContext


class CapabilityRouter:
    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        *,
        clock: Clock = utc_now,
    ):
        self.registry = registry or CapabilityRegistry()
        self.clock = clock

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

        validation_error = self._validate_request(tenant_context, capability_request)
        if validation_error:
            return validation_error

        provider = self.registry.get(capability_config.provider)
        if not provider:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=capability_config.provider,
                error=f"Capability provider not found: {capability_config.provider}",
            )

        return provider.execute(tenant_context, capability_request)

    def _validate_request(
        self,
        tenant_context: TenantContext,
        request: CapabilityRequest,
    ) -> CapabilityResult | None:
        if request.name != "reservation.check_availability":
            return None
        try:
            availability_request = RoomAvailabilityRequest.model_validate(
                {
                    field: request.input.get(field)
                    for field in ("check_in", "check_out", "room_type", "room_count")
                }
            )
        except ValidationError:
            return self._validation_error(
                request.name,
                "invalid_availability_request",
                "Dátum odchodu musí byť neskôr ako dátum príchodu a počet izieb musí byť kladný.",
            )

        config = tenant_context.availability_config
        if not config or availability_request.room_type not in config.room_type_columns:
            return self._validation_error(
                request.name,
                "unsupported_room_type",
                "Tento typ izby nie je možné overiť.",
            )
        if (
            config.reject_past_check_in
            and availability_request.check_in
            < tenant_local_datetime(tenant_context, self.clock).date()
        ):
            locale = (request.metadata or {}).get("language")
            return self._validation_error(
                request.name,
                "past_check_in_not_allowed",
                localized_response(
                    config.past_check_in_responses,
                    locale,
                    tenant_context.default_locale,
                ),
            )
        return None

    def _validation_error(self, name: str, code: str, message: str) -> CapabilityResult:
        return CapabilityResult(
            name=name,
            status=CapabilityStatus.SKIPPED,
            provider="validation",
            user_message=message,
            error=code,
        )
