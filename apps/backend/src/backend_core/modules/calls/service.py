import hmac
import logging
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from agentic_observability.domain import CoreMetrics, domain_span
from contracts import (
    ConversationPersistenceStatus,
    HumanHandoffRequest,
    HumanHandoffResponse,
    InboundSipClaimRequest,
    RuntimeBundlePayload,
    RuntimeBundleProvenance,
    RuntimeHandoffDestination,
    VoiceAgentRuntimeContext,
)
from opentelemetry.trace import Tracer
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.application.messaging import EventBus
from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    CallSessionConflictError,
    CallSessionNotFoundError,
    CallSessionRouteUnavailableError,
    CallSessionTelephonyNotReadyError,
    HumanHandoffError,
)
from backend_core.modules.calls.events import call_event
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.schemas import CreateCallSessionRequest
from backend_core.modules.conversations.errors import (
    ConversationConflictError,
    ConversationNotFoundError,
)
from backend_core.modules.conversations.service import ConversationService
from backend_core.modules.tenants.errors import TenantNotFoundError
from backend_core.modules.tenants.models import TenantStatus
from backend_core.modules.tenants.release_repository import (
    InboundReleaseRuntime,
    TenantReleaseRepository,
)
from backend_core.modules.tenants.repository import (
    TelephonyRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import normalize_e164
from backend_core.platform.livekit import LiveKitAdapter
from backend_core.runtime.bundle_store import RuntimeBundleStore

logger = logging.getLogger(__name__)


class CallSessionService:
    def __init__(
        self,
        calls: CallSessionRepository,
        routes: TelephonyRepository,
        tenants: TenantRepository,
        conversations: ConversationService,
        events: EventBus,
        releases: TenantReleaseRepository,
        bundles: RuntimeBundleStore,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
        privacy_key: bytes | None = None,
    ) -> None:
        self._calls = calls
        self._routes = routes
        self._tenants = tenants
        self._conversations = conversations
        self._events = events
        self._tracer = tracer
        self._metrics = metrics
        self._privacy_key = privacy_key
        self._releases = releases
        self._bundles = bundles

    def _phone_hash(self, value: str) -> str:
        if self._privacy_key is None:
            return f"{value[:2]}…{value[-2:]}"
        return hmac.new(self._privacy_key, value.encode(), sha256).hexdigest()[:16]

    @staticmethod
    def _require_inbound_telephony_ready(resolution: InboundReleaseRuntime) -> None:
        state = resolution.provisioning
        if (
            state is None
            or state.status != "ready"
            or state.desired_revision_id != resolution.release.telephony_revision_id
            or state.applied_revision_id != resolution.release.telephony_revision_id
        ):
            raise CallSessionTelephonyNotReadyError

    @staticmethod
    def _require_runtime_bundle(bundle_payload: dict[str, object]) -> None:
        try:
            RuntimeBundlePayload.model_validate(bundle_payload)
        except ValidationError as error:
            raise CallSessionConfigUnavailableError from error

    async def create(
        self,
        data: CreateCallSessionRequest,
    ) -> tuple[CallSession, bool]:
        with domain_span(self._tracer, "call.prepare") as span:
            call, created = await self._create(data)
            if span is not None:
                span.set_attribute("tenant.id", str(call.tenant_id))
                span.set_attribute("call.id", str(call.id))
            return call, created

    async def _create(
        self,
        data: CreateCallSessionRequest,
    ) -> tuple[CallSession, bool]:
        existing = await self._calls.get_by_provider_call(
            data.provider,
            data.provider_call_id,
        )
        if existing is not None:
            return existing, False
        called_number = normalize_e164(data.called_number)
        resolution = (
            await self._releases.inbound_runtime(called_number)
            if called_number is not None
            else None
        )
        if resolution is None or resolution.tenant.status is not TenantStatus.ACTIVE:
            if self._metrics is not None:
                self._metrics.telephony_routing_failure("unknown_did")
            raise CallSessionRouteUnavailableError
        self._require_inbound_telephony_ready(resolution)
        self._require_runtime_bundle(resolution.bundle.payload)

        call = CallSession(
            tenant_id=resolution.tenant.id,
            tenant_release_id=resolution.release.id,
            runtime_bundle_id=resolution.bundle.id,
            channel=CallChannel.SIP,
            direction=CallDirection.INBOUND,
            provider=data.provider,
            provider_call_id=data.provider_call_id,
            caller_phone_e164=data.caller_phone_e164,
            room_name=data.room_name,
        )
        try:
            call, created = await self._calls.add_or_get(call)
            if created:
                await self._conversations.create_for_call(call.id, call.tenant_id)
                await self._events.publish(
                    call_event(call.id, call.tenant_id, "created")
                )
            return call, created
        except IntegrityError as error:
            raise CallSessionConflictError from error

    async def claim_inbound_sip(
        self,
        data: InboundSipClaimRequest,
    ) -> tuple[CallSession, bool]:
        with domain_span(self._tracer, "call.prepare") as span:
            call, created = await self._claim_inbound_sip(data)
            if span is not None:
                span.set_attribute("tenant.id", str(call.tenant_id))
                span.set_attribute("call.id", str(call.id))
            return call, created

    async def _claim_inbound_sip(
        self,
        data: InboundSipClaimRequest,
    ) -> tuple[CallSession, bool]:
        called_number = normalize_e164(data.called_number)
        if called_number is None:
            if self._metrics is not None:
                self._metrics.telephony_routing_failure("invalid_called_number")
            raise CallSessionRouteUnavailableError
        caller_number = normalize_e164(data.caller_number)
        existing = await self._calls.get_by_sip_call(
            "livekit", data.sip_call_id, data.sip_call_id_full
        )
        if existing is not None:
            await self._validate_sip_replay(
                existing, data, caller_number, called_number
            )
            logger.info(
                "Existing inbound SIP CallSession reused",
                extra={
                    "call_session_id": str(existing.id),
                    "sip_call_id": data.sip_call_id,
                    "room": data.room_name,
                    "tenant_id": str(existing.tenant_id),
                },
            )
            return existing, False

        resolution = await self._releases.inbound_runtime(called_number)
        if resolution is None or resolution.tenant.status is not TenantStatus.ACTIVE:
            if self._metrics is not None:
                self._metrics.telephony_routing_failure("unknown_did")
            raise CallSessionRouteUnavailableError
        self._require_inbound_telephony_ready(resolution)
        self._require_runtime_bundle(resolution.bundle.payload)
        logger.info(
            "Inbound SIP DID resolved",
            extra={
                "called_number_hash": self._phone_hash(called_number),
                "tenant_id": str(resolution.tenant.id),
            },
        )

        call = CallSession(
            tenant_id=resolution.tenant.id,
            tenant_release_id=resolution.release.id,
            runtime_bundle_id=resolution.bundle.id,
            channel=CallChannel.SIP,
            direction=CallDirection.INBOUND,
            provider="livekit",
            provider_call_id=data.sip_call_id_full or data.sip_call_id,
            caller_phone_e164=caller_number,
            called_phone_e164=called_number,
            caller_phone_raw=data.caller_number,
            called_phone_raw=data.called_number,
            sip_call_id=data.sip_call_id,
            sip_call_id_full=data.sip_call_id_full,
            sip_trunk_id=data.trunk_id,
            sip_dispatch_rule_id=data.dispatch_rule_id,
            livekit_participant_identity=data.participant_identity,
            room_name=data.room_name,
        )
        try:
            call, created = await self._calls.add_or_get(call)
            if not created:
                await self._validate_sip_replay(
                    call, data, caller_number, called_number
                )
                logger.info(
                    "Existing inbound SIP CallSession reused",
                    extra={
                        "call_session_id": str(call.id),
                        "sip_call_id": data.sip_call_id,
                        "room": data.room_name,
                        "tenant_id": str(call.tenant_id),
                    },
                )
                return call, False
            await self._conversations.create_for_call(call.id, call.tenant_id)
            await self._events.publish(call_event(call.id, call.tenant_id, "created"))
            logger.info(
                "Inbound SIP CallSession created",
                extra={
                    "call_session_id": str(call.id),
                    "sip_call_id": data.sip_call_id,
                    "room": data.room_name,
                    "tenant_id": str(call.tenant_id),
                },
            )
            return call, True
        except IntegrityError as error:
            raise CallSessionConflictError from error

    async def _validate_sip_replay(
        self,
        call: CallSession,
        data: InboundSipClaimRequest,
        caller_number: str | None,
        called_number: str,
    ) -> None:
        if (
            call.channel is not CallChannel.SIP
            or call.provider != "livekit"
            or call.sip_call_id != data.sip_call_id
            or (
                call.sip_call_id_full is not None
                and data.sip_call_id_full is not None
                and call.sip_call_id_full != data.sip_call_id_full
            )
            or call.caller_phone_e164 != caller_number
            or (caller_number is None and call.caller_phone_raw != data.caller_number)
            or call.called_phone_e164 != called_number
            or call.sip_trunk_id != data.trunk_id
            or call.sip_dispatch_rule_id != data.dispatch_rule_id
            or call.room_name != data.room_name
            or call.livekit_participant_identity != data.participant_identity
        ):
            raise CallSessionConflictError
        if call.sip_call_id_full is None and data.sip_call_id_full is not None:
            call.sip_call_id_full = data.sip_call_id_full
            await self._calls.flush()

    async def create_manual(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> tuple[CallSession, bool]:
        with domain_span(
            self._tracer, "call.prepare", {"tenant.id": str(tenant_id)}
        ) as span:
            call, created = await self._create_manual(
                tenant_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if span is not None:
                span.set_attribute("call.id", str(call.id))
            return call, created

    async def _create_manual(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> tuple[CallSession, bool]:
        if (idempotency_key is None) != (request_fingerprint is None):
            raise CallSessionConflictError
        if idempotency_key is not None:
            existing = await self._calls.get_by_admin_idempotency_key(idempotency_key)
            if existing is not None:
                if (
                    existing.tenant_id != tenant_id
                    or existing.admin_request_fingerprint != request_fingerprint
                    or existing.status is not CallSessionStatus.CREATED
                ):
                    raise CallSessionConflictError
                return existing, False
        tenant = await self._tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        runtime = await self._releases.active_runtime(tenant.id)
        if runtime is None or tenant.status is not TenantStatus.ACTIVE:
            raise CallSessionConfigUnavailableError
        self._require_runtime_bundle(runtime.bundle.payload)

        call_id = uuid4()
        room_name = f"call_{call_id}"
        provider_call_id = (
            f"manual:{sha256(idempotency_key.encode()).hexdigest()}"
            if idempotency_key is not None
            else room_name
        )
        call = CallSession(
            id=call_id,
            tenant_id=tenant.id,
            tenant_release_id=runtime.release.id,
            runtime_bundle_id=runtime.bundle.id,
            channel=CallChannel.WEB,
            direction=CallDirection.INBOUND,
            provider="livekit",
            provider_call_id=provider_call_id,
            room_name=room_name,
            admin_idempotency_key=idempotency_key,
            admin_request_fingerprint=request_fingerprint,
        )
        try:
            call, created = await self._calls.add_or_get(call)
            if not created:
                if (
                    call.tenant_id != tenant_id
                    or call.admin_request_fingerprint != request_fingerprint
                    or call.status is not CallSessionStatus.CREATED
                ):
                    raise CallSessionConflictError
                return call, False
            await self._conversations.create_for_call(call.id, call.tenant_id)
            await self._events.publish(call_event(call.id, call.tenant_id, "created"))
            return call, True
        except IntegrityError as error:
            raise CallSessionConflictError from error

    async def set_dispatch(self, call_id: UUID, dispatch_id: str) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.provider_dispatch_id is not None:
            if call.provider_dispatch_id != dispatch_id:
                raise CallSessionConflictError
            return call
        call.provider_dispatch_id = dispatch_id
        await self._calls.flush()
        return call

    async def get(self, call_id: UUID) -> CallSession:
        call = await self._calls.get(call_id)
        if call is None:
            raise CallSessionNotFoundError
        return call

    async def get_runtime_context(
        self,
        call_id: UUID,
    ) -> VoiceAgentRuntimeContext:
        call = await self.get(call_id)
        bundle = await self._bundles.get(
            call.tenant_id, call.tenant_release_id, call.runtime_bundle_id
        )
        if bundle is None:
            raise CallSessionConfigUnavailableError
        try:
            payload = RuntimeBundlePayload.model_validate(bundle.payload)
            provenance = RuntimeBundleProvenance.model_validate(bundle.provenance)
        except ValidationError as error:
            raise CallSessionConfigUnavailableError from error
        return VoiceAgentRuntimeContext(
            call_session_id=call.id,
            tenant_release_id=call.tenant_release_id,
            runtime_bundle_id=call.runtime_bundle_id,
            voice_runtime_revision_id=provenance.runtime_revision_id,
            voice_runtime=payload.voice_runtime,
            room_name=call.room_name,
            locale=payload.locale,
            timezone=payload.timezone,
            agent_display_name=payload.agent_display_name,
            greeting=payload.greeting,
            conversation_scope=payload.conversation_scope,
            prompt=payload.prompt,
            capabilities=payload.capabilities,
            handoff_destinations=payload.handoff_destinations,
        )

    async def transfer_to_human(
        self,
        call_id: UUID,
        data: HumanHandoffRequest,
        livekit: LiveKitAdapter,
    ) -> HumanHandoffResponse:
        call = await self._calls.get_for_update(call_id)
        if call is None:
            raise HumanHandoffError("call_not_transferable")
        if call.handoff_tool_call_id is not None:
            if (
                call.handoff_tool_call_id == data.tool_call_id
                and call.handoff_destination == data.destination
            ):
                return HumanHandoffResponse(destination=data.destination)
            raise HumanHandoffError("call_not_transferable")
        if (
            call.status is not CallSessionStatus.CONNECTED
            or call.channel is not CallChannel.SIP
            or call.provider != "livekit"
            or call.livekit_participant_identity is None
        ):
            raise HumanHandoffError("call_not_transferable")
        tenant = await self._tenants.get(call.tenant_id)
        if tenant is None or tenant.status is not TenantStatus.ACTIVE:
            raise HumanHandoffError("call_not_transferable")
        phone_number, destinations = await self._pinned_handoff(call)
        if not phone_number or not destinations:
            raise HumanHandoffError("handoff_not_configured")
        destination = destinations.get(data.destination)
        if destination is None:
            if self._metrics is not None:
                self._metrics.telephony_handoff_failure("unknown_destination")
            raise HumanHandoffError("unknown_destination")
        platform = await self._routes.platform()
        if (
            platform.outbound_trunk_id is None
            or platform.provisioning_status.value != "ready"
        ):
            if self._metrics is not None:
                self._metrics.telephony_handoff_failure("outbound_unavailable")
            raise HumanHandoffError("outbound_unavailable")
        try:
            participant_identity, sip_call_id = await livekit.create_sip_participant(
                room_name=call.room_name,
                participant_identity=f"handoff-{call.id}",
                phone_number=destination.phone_number,
                caller_number=phone_number,
                outbound_trunk_id=platform.outbound_trunk_id,
            )
        except Exception as error:
            if self._metrics is not None:
                self._metrics.telephony_handoff_failure("provider_failure")
            logger.exception(
                "LiveKit SIP handoff dial failed",
                extra={
                    "call_session_id": str(call.id),
                    "tenant_id": str(call.tenant_id),
                    "destination": data.destination,
                },
            )
            raise HumanHandoffError("transfer_failed") from error
        call.handoff_tool_call_id = data.tool_call_id
        call.handoff_destination = data.destination
        call.handoff_participant_identity = participant_identity
        call.handoff_sip_call_id = sip_call_id
        await self._calls.flush()
        logger.info(
            "Human handoff participant connected",
            extra={
                "call_session_id": str(call.id),
                "tenant_id": str(call.tenant_id),
                "destination": data.destination,
                "reason_supplied": data.reason is not None,
            },
        )
        return HumanHandoffResponse(destination=data.destination)

    async def _pinned_handoff(
        self, call: CallSession
    ) -> tuple[str | None, dict[str, RuntimeHandoffDestination]]:
        bundle = await self._bundles.get(
            call.tenant_id, call.tenant_release_id, call.runtime_bundle_id
        )
        if bundle is None:
            raise HumanHandoffError("telephony_not_ready")
        try:
            payload = RuntimeBundlePayload.model_validate(bundle.payload)
            provenance = RuntimeBundleProvenance.model_validate(bundle.provenance)
        except ValidationError as error:
            raise HumanHandoffError("telephony_not_ready") from error
        if not await self._bundles.telephony_ready(
            call.tenant_id, provenance.telephony_revision_id
        ):
            raise HumanHandoffError("telephony_not_ready")
        return payload.telephony.caller_number, payload.telephony.handoff_destinations

    async def relinquish_agent(
        self,
        call_id: UUID,
        conversation_status: ConversationPersistenceStatus,
    ) -> CallSession:
        call = await self._get_for_update(call_id)
        if (
            call.status is not CallSessionStatus.CONNECTED
            or call.handoff_tool_call_id is None
        ):
            raise CallSessionConflictError
        try:
            await self._conversations.close_for_call(call_id, conversation_status)
        except (ConversationConflictError, ConversationNotFoundError) as error:
            raise CallSessionConflictError from error
        return call

    async def mark_started(self, call_id: UUID) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.STARTED:
            return call
        if call.status is not CallSessionStatus.CREATED:
            raise CallSessionConflictError
        call.status = CallSessionStatus.STARTED
        call.started_at = datetime.now(UTC)
        await self._events.publish(call_event(call.id, call.tenant_id, "started"))
        await self._calls.flush()
        if self._metrics is not None:
            self._metrics.call_started()
        return call

    async def mark_connected(self, call_id: UUID) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.CONNECTED:
            return call
        if call.status is not CallSessionStatus.STARTED:
            raise CallSessionConflictError
        call.status = CallSessionStatus.CONNECTED
        call.connected_at = datetime.now(UTC)
        await self._events.publish(call_event(call.id, call.tenant_id, "connected"))
        await self._calls.flush()
        return call

    async def activate(self, call_id: UUID) -> CallSession:
        return await self.mark_started(call_id)

    async def end(
        self,
        call_id: UUID,
        conversation_status: ConversationPersistenceStatus,
    ) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.ENDED:
            try:
                await self._conversations.close_for_call(call_id, conversation_status)
            except ConversationConflictError as error:
                raise CallSessionConflictError from error
            return call
        if call.status is not CallSessionStatus.CONNECTED:
            raise CallSessionConflictError
        try:
            await self._conversations.close_for_call(call_id, conversation_status)
        except ConversationConflictError as error:
            raise CallSessionConflictError from error
        call.status = CallSessionStatus.ENDED
        call.ended_at = datetime.now(UTC)
        await self._events.publish(call_event(call.id, call.tenant_id, "ended"))
        await self._calls.flush()
        if self._metrics is not None:
            self._metrics.call_terminal(
                "completed",
                (call.ended_at - call.started_at).total_seconds()
                if call.started_at is not None
                else None,
                was_active=True,
            )
        return call

    async def complete(
        self,
        call_id: UUID,
        conversation_status: ConversationPersistenceStatus,
    ) -> CallSession:
        return await self.end(call_id, conversation_status)

    async def reconcile_missing_runtime(self, call_id: UUID) -> CallSession | None:
        call = await self._get_for_update(call_id)
        if call.status in (CallSessionStatus.ENDED, CallSessionStatus.FAILED):
            return None
        if call.status is CallSessionStatus.CONNECTED:
            conversation_status = ConversationPersistenceStatus.INCOMPLETE
            if call.handoff_tool_call_id is not None:
                status = await self._conversations.status_for_call(call_id)
                if status is not ConversationPersistenceStatus.OPEN:
                    conversation_status = status
            return await self.end(call_id, conversation_status)
        if call.status is CallSessionStatus.STARTED:
            return await self.fail(
                call_id,
                "runtime_unavailable",
                ConversationPersistenceStatus.INCOMPLETE,
            )
        return None

    async def fail(
        self,
        call_id: UUID,
        reason: str,
        conversation_status: ConversationPersistenceStatus,
    ) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.FAILED:
            if call.failure_reason != reason:
                raise CallSessionConflictError
            try:
                await self._conversations.close_for_call(call_id, conversation_status)
            except ConversationConflictError as error:
                raise CallSessionConflictError from error
            return call
        if call.status not in (
            CallSessionStatus.CREATED,
            CallSessionStatus.STARTED,
            CallSessionStatus.CONNECTED,
        ):
            raise CallSessionConflictError
        was_active = call.status in {
            CallSessionStatus.STARTED,
            CallSessionStatus.CONNECTED,
        }
        call.status = CallSessionStatus.FAILED
        call.ended_at = datetime.now(UTC)
        call.failure_reason = reason
        await self._events.publish(
            call_event(call.id, call.tenant_id, "failed", failure_reason=reason)
        )
        try:
            await self._conversations.close_for_call(call_id, conversation_status)
        except ConversationConflictError as error:
            raise CallSessionConflictError from error
        await self._calls.flush()
        if self._metrics is not None:
            self._metrics.call_terminal(
                "failed",
                (call.ended_at - call.started_at).total_seconds()
                if call.started_at is not None
                else None,
                was_active=was_active,
            )
        return call

    async def _get_for_update(self, call_id: UUID) -> CallSession:
        call = await self._calls.get_for_update(call_id)
        if call is None:
            raise CallSessionNotFoundError
        return call
