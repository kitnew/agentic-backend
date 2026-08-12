import logging
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from contracts import (
    TENANT_CONFIG_SCHEMAS,
    ConversationPersistenceStatus,
    EffectiveVoiceRuntime,
    InboundSipClaimRequest,
    TenantCapabilityProfile,
    TenantConfigV2,
    TenantConfigV3,
    VoiceAgentPrompt,
    VoiceAgentRuntimeContext,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.application.messaging import EventBus
from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    CallSessionConflictError,
    CallSessionLegacyRuntimeError,
    CallSessionNotFoundError,
    CallSessionRouteUnavailableError,
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
from backend_core.modules.conversations.errors import ConversationConflictError
from backend_core.modules.conversations.service import ConversationService
from backend_core.modules.tenants.errors import TenantNotFoundError
from backend_core.modules.tenants.knowledge import render_knowledge_context
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    KnowledgeBaseRevision,
    ProfilePromptRevision,
    PromptRevisionStatus,
    PromptSetRevision,
    SystemPromptRevision,
    Tenant,
    TenantConfigRevision,
    TenantPromptRevision,
    TenantStatus,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    PromptCompositionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import normalize_e164
from backend_core.runtime.capabilities.domain import runtime_definition
from backend_core.runtime.voice.models import (
    RuntimeRevisionStatus,
    VoiceRuntimeRevision,
)
from backend_core.runtime.voice.repository import VoiceRuntimeRepository

logger = logging.getLogger(__name__)


class CallSessionService:
    def __init__(
        self,
        calls: CallSessionRepository,
        routes: InboundRouteRepository,
        prompts: PromptCompositionRepository,
        tenants: TenantRepository,
        configs: ConfigRevisionRepository,
        runtimes: VoiceRuntimeRepository,
        conversations: ConversationService,
        events: EventBus,
    ) -> None:
        self._calls = calls
        self._routes = routes
        self._prompts = prompts
        self._tenants = tenants
        self._configs = configs
        self._runtimes = runtimes
        self._conversations = conversations
        self._events = events

    async def create(
        self,
        data: CreateCallSessionRequest,
    ) -> tuple[CallSession, bool]:
        existing = await self._calls.get_by_provider_call(
            data.provider,
            data.provider_call_id,
        )
        if existing is not None:
            return existing, False
        resolution = await self._routes.resolve(data.called_number, lock_tenant=True)
        if resolution is None:
            raise CallSessionRouteUnavailableError
        tenant, config_revision = resolution

        _, prompt_set, voice_runtime = await self._voice_config(
            tenant,
            config_revision,
        )

        call = CallSession(
            tenant_id=tenant.id,
            tenant_config_revision_id=config_revision.id,
            prompt_set_revision_id=prompt_set.id,
            voice_runtime_revision_id=voice_runtime.id,
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
        called_number = normalize_e164(data.called_number)
        if called_number is None:
            raise CallSessionRouteUnavailableError
        caller_number = normalize_e164(data.caller_number)
        existing = await self._calls.get_by_sip_call(
            "livekit", data.sip_call_id, data.sip_call_id_full
        )
        if existing is not None:
            await self._validate_sip_replay(existing, data, caller_number, called_number)
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

        resolution = await self._routes.resolve(called_number, lock_tenant=True)
        if resolution is None:
            raise CallSessionRouteUnavailableError
        tenant, config_revision = resolution
        logger.info(
            "Inbound SIP DID resolved",
            extra={"called_number": called_number, "tenant_id": str(tenant.id)},
        )
        _, prompt_set, voice_runtime = await self._voice_config(
            tenant, config_revision
        )
        call = CallSession(
            tenant_id=tenant.id,
            tenant_config_revision_id=config_revision.id,
            prompt_set_revision_id=prompt_set.id,
            voice_runtime_revision_id=voice_runtime.id,
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
            or (
                caller_number is None
                and call.caller_phone_raw != data.caller_number
            )
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
        if (
            tenant.status is not TenantStatus.ACTIVE
            or tenant.active_config_revision_id is None
        ):
            raise CallSessionConfigUnavailableError
        config_revision = await self._configs.get(
            tenant.id,
            tenant.active_config_revision_id,
        )
        if (
            config_revision is None
            or config_revision.status is not ConfigRevisionStatus.PUBLISHED
            or config_revision.published_at is None
        ):
            raise CallSessionConfigUnavailableError
        _, prompt_set, voice_runtime = await self._voice_config(tenant, config_revision)

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
            tenant_config_revision_id=config_revision.id,
            prompt_set_revision_id=prompt_set.id,
            voice_runtime_revision_id=voice_runtime.id,
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
        if call.voice_runtime_revision_id is None:
            raise CallSessionLegacyRuntimeError
        config_revision = await self._configs.get(
            call.tenant_id,
            call.tenant_config_revision_id,
        )
        prompt_set = await self._prompts.revision(
            PromptSetRevision, call.prompt_set_revision_id, tenant_id=call.tenant_id
        )
        voice_runtime = await self._runtimes.voice_revision(
            call.tenant_id, call.voice_runtime_revision_id
        )
        if config_revision is None or prompt_set is None or voice_runtime is None:
            raise CallSessionConfigUnavailableError
        try:
            model = TENANT_CONFIG_SCHEMAS.get(config_revision.schema_version)
            if model is None:
                raise CallSessionConfigUnavailableError
            config = model.model_validate(config_revision.config)
        except ValidationError as error:
            raise CallSessionConfigUnavailableError from error
        if not isinstance(config, (TenantConfigV2, TenantConfigV3)):
            raise CallSessionConfigUnavailableError
        system = await self._prompts.revision(
            SystemPromptRevision, prompt_set.system_prompt_revision_id
        )
        profile = await self._prompts.revision(
            ProfilePromptRevision, prompt_set.profile_prompt_revision_id
        )
        tenant_prompt = await self._prompts.revision(
            TenantPromptRevision,
            prompt_set.tenant_prompt_revision_id,
            tenant_id=call.tenant_id,
        )
        knowledge = await self._prompts.revision(
            KnowledgeBaseRevision,
            prompt_set.knowledge_base_revision_id,
            tenant_id=call.tenant_id,
        )
        if any(item is None for item in (system, profile, tenant_prompt, knowledge)):
            raise CallSessionConfigUnavailableError
        assert system is not None
        assert profile is not None
        assert tenant_prompt is not None
        assert knowledge is not None
        knowledge_documents = await self._prompts.knowledge_snapshot(
            call.tenant_id, knowledge.id
        )
        return VoiceAgentRuntimeContext(
            call_session_id=call.id,
            voice_runtime_revision_id=voice_runtime.id,
            voice_runtime=EffectiveVoiceRuntime.model_validate(
                voice_runtime.effective_settings
            ),
            room_name=call.room_name,
            locale=config.localization.default_locale,
            timezone=config.localization.timezone,
            agent_display_name=config.agent.display_name,
            greeting=config.agent.greeting,
            conversation_scope=config.conversation.scope.value,
            prompt=VoiceAgentPrompt(
                system_prompt=system.text,
                profile_prompt=profile.text,
                tenant_prompt=tenant_prompt.text,
                knowledge_context=render_knowledge_context(
                    [
                        (document.key, document_revision.content)
                        for _, document, document_revision in knowledge_documents
                    ]
                ),
                knowledge_base_revision_id=knowledge.id,
            ),
            capabilities=[
                runtime_definition(key, profile)
                for key, profile in config.capabilities.items()
                if isinstance(profile, TenantCapabilityProfile) and profile.enabled
            ],
        )

    async def _voice_config(
        self,
        tenant: Tenant,
        config_revision: TenantConfigRevision,
    ) -> tuple[TenantConfigV3, PromptSetRevision, VoiceRuntimeRevision]:
        try:
            config = TenantConfigV3.model_validate(config_revision.config)
        except ValidationError as error:
            raise CallSessionConfigUnavailableError from error
        if tenant.active_prompt_set_revision_id is None:
            raise CallSessionConfigUnavailableError
        if tenant.active_voice_runtime_revision_id is None:
            raise CallSessionConfigUnavailableError
        prompt_set = await self._prompts.revision(
            PromptSetRevision,
            tenant.active_prompt_set_revision_id,
            tenant_id=tenant.id,
        )
        if (
            prompt_set is None
            or prompt_set.status is not PromptRevisionStatus.PUBLISHED
        ):
            raise CallSessionConfigUnavailableError
        voice_runtime = await self._runtimes.voice_revision(
            tenant.id, tenant.active_voice_runtime_revision_id
        )
        if (
            voice_runtime is None
            or voice_runtime.status is not RuntimeRevisionStatus.PUBLISHED
        ):
            raise CallSessionConfigUnavailableError
        return config, prompt_set, voice_runtime

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
            return await self.end(call_id, ConversationPersistenceStatus.INCOMPLETE)
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
        return call

    async def _get_for_update(self, call_id: UUID) -> CallSession:
        call = await self._calls.get_for_update(call_id)
        if call is None:
            raise CallSessionNotFoundError
        return call
