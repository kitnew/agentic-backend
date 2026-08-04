from pydantic import ValidationError

from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import (
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
    NewReservationRequest,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    RoomAvailabilityRequest,
)
from app.tenants.policies import (
    Clock,
    localized_response,
    reservation_cutoff_reached,
    tenant_local_datetime,
    utc_now,
)
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

        if capability_config.provider == "make_webhook":
            availability_guard = self._availability_guard(
                tenant_context, capability_request
            )
            if availability_guard:
                return availability_guard

        provider = self.registry.get(capability_config.provider)
        if not provider:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=capability_config.provider,
                error=f"Capability provider not found: {capability_config.provider}",
            )

        return provider.execute(tenant_context, capability_request)

    def _availability_guard(
        self,
        tenant_context: TenantContext,
        request: CapabilityRequest,
    ) -> CapabilityResult | None:
        if request.name != "reservation.change_request":
            return None
        try:
            validated = ReservationChangeRequest.model_validate(
                {
                    field: request.input[field]
                    for field in ReservationChangeRequest.model_fields
                    if field in request.input
                }
            )
        except ValidationError:
            return None
        if not validated.affects_availability:
            return None

        availability = self.execute(
            tenant_context,
            CapabilityRequest(
                name="reservation.check_availability",
                input={
                    "check_in": validated.check_in,
                    "check_out": validated.check_out,
                    "room_type": validated.room_type,
                    "room_count": validated.room_count,
                },
                metadata=request.metadata,
            ),
        )
        if availability.status == CapabilityStatus.SUCCESS and (
            availability.output or {}
        ).get("status") == "available":
            return None
        return CapabilityResult(
            name=request.name,
            status=(
                CapabilityStatus.FAILED
                if availability.status == CapabilityStatus.FAILED
                else CapabilityStatus.SKIPPED
            ),
            provider=availability.provider,
            user_message=availability.user_message,
            error=availability.error or "requested_stay_not_available",
            output=availability.output,
        )

    def _validate_request(
        self,
        tenant_context: TenantContext,
        request: CapabilityRequest,
    ) -> CapabilityResult | None:
        models = {
            "reservation.check_availability": RoomAvailabilityRequest,
            "reservation.create_request": NewReservationRequest,
            "reservation.change_request": ReservationChangeRequest,
            "reservation.cancel_request": ReservationCancellationRequest,
        }
        model = models.get(request.name)
        if model is None:
            return None
        try:
            validated = model.model_validate(
                {
                    field: request.input[field]
                    for field in model.model_fields
                    if field in request.input
                }
            )
        except ValidationError:
            return self._validation_error(
                request.name,
                (
                    "invalid_availability_request"
                    if request.name == "reservation.check_availability"
                    else "invalid_reservation_request"
                ),
                (
                    "Dátum odchodu musí byť neskôr ako dátum príchodu a počet izieb musí byť kladný."
                    if request.name == "reservation.check_availability"
                    else "Skontrolujte údaje žiadosti a potvrďte finálne detaily."
                ),
            )

        local_now = tenant_local_datetime(tenant_context, self.clock)
        if request.name == "reservation.create_request" and reservation_cutoff_reached(
            tenant_context, local_now
        ):
            locale = (request.metadata or {}).get("language")
            return self._validation_error(
                request.name,
                "reservation_cutoff_reached",
                localized_response(
                    tenant_context.reservation.cutoff_responses,
                    locale,
                    tenant_context.default_locale,
                ),
            )

        availability_request = validated
        if isinstance(validated, ReservationChangeRequest):
            if not validated.affects_availability:
                return None
            availability_request = RoomAvailabilityRequest(
                check_in=validated.check_in,
                check_out=validated.check_out,
                room_type=validated.room_type,
                room_count=validated.room_count,
            )
        elif not isinstance(validated, (RoomAvailabilityRequest, NewReservationRequest)):
            return None

        config = tenant_context.availability_config
        availability_capability = tenant_context.capabilities.get(
            "reservation.check_availability"
        )
        if (
            (
                not config
                and (
                    not availability_capability
                    or availability_capability.provider != "make_webhook"
                )
            )
            or (config and availability_request.room_type not in config.room_type_columns)
        ):
            return self._validation_error(
                request.name,
                "unsupported_room_type",
                "Tento typ izby nie je možné overiť.",
            )
        if (
            config
            and config.reject_past_check_in
            and availability_request.check_in < local_now.date()
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
