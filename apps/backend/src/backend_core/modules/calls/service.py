from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from contracts import (
    TENANT_CONFIG_SCHEMAS,
    ConversationPersistenceStatus,
    TenantCapabilityProfile,
    TenantConfigV2,
    TenantConfigV3,
    VoiceAgentPrompt,
    VoiceAgentRuntimeContext,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.modules.calls.errors import (
    CallSessionConfigUnavailableError,
    CallSessionConflictError,
    CallSessionNotFoundError,
    CallSessionRouteUnavailableError,
)
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.schemas import CreateCallSessionRequest
from backend_core.modules.capabilities.domain import runtime_definition
from backend_core.modules.conversations.errors import ConversationConflictError
from backend_core.modules.conversations.service import ConversationService
from backend_core.modules.tenants.errors import TenantNotFoundError
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


class CallSessionService:
    def __init__(
        self,
        calls: CallSessionRepository,
        routes: InboundRouteRepository,
        prompts: PromptCompositionRepository,
        tenants: TenantRepository,
        configs: ConfigRevisionRepository,
        conversations: ConversationService,
    ) -> None:
        self._calls = calls
        self._routes = routes
        self._prompts = prompts
        self._tenants = tenants
        self._configs = configs
        self._conversations = conversations

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

        _, prompt_set = await self._voice_config(
            tenant,
            config_revision,
        )

        call = CallSession(
            tenant_id=tenant.id,
            tenant_config_revision_id=config_revision.id,
            prompt_set_revision_id=prompt_set.id,
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
            return call, created
        except IntegrityError as error:
            raise CallSessionConflictError from error

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
        _, prompt_set = await self._voice_config(tenant, config_revision)

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
        config_revision = await self._configs.get(
            call.tenant_id,
            call.tenant_config_revision_id,
        )
        prompt_set = await self._prompts.revision(
            PromptSetRevision, call.prompt_set_revision_id, tenant_id=call.tenant_id
        )
        if config_revision is None or prompt_set is None:
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
        return VoiceAgentRuntimeContext(
            call_session_id=call.id,
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
                knowledge_context=knowledge.text,
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
    ) -> tuple[TenantConfigV3, PromptSetRevision]:
        try:
            config = TenantConfigV3.model_validate(config_revision.config)
        except ValidationError as error:
            raise CallSessionConfigUnavailableError from error
        if tenant.active_prompt_set_revision_id is None:
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
        return config, prompt_set

    async def activate(self, call_id: UUID) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.ACTIVE:
            return call
        if call.status is not CallSessionStatus.CREATED:
            raise CallSessionConflictError
        call.status = CallSessionStatus.ACTIVE
        call.started_at = datetime.now(UTC)
        await self._calls.flush()
        return call

    async def complete(
        self,
        call_id: UUID,
        conversation_status: ConversationPersistenceStatus,
    ) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.COMPLETED:
            try:
                await self._conversations.close_for_call(call_id, conversation_status)
            except ConversationConflictError as error:
                raise CallSessionConflictError from error
            return call
        if call.status is not CallSessionStatus.ACTIVE:
            raise CallSessionConflictError
        try:
            await self._conversations.close_for_call(call_id, conversation_status)
        except ConversationConflictError as error:
            raise CallSessionConflictError from error
        call.status = CallSessionStatus.COMPLETED
        call.ended_at = datetime.now(UTC)
        await self._calls.flush()
        return call

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
        if call.status not in (CallSessionStatus.CREATED, CallSessionStatus.ACTIVE):
            raise CallSessionConflictError
        call.status = CallSessionStatus.FAILED
        call.ended_at = datetime.now(UTC)
        call.failure_reason = reason
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
