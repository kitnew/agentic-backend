from datetime import UTC, datetime
from uuid import UUID

from contracts import TenantConfigV2
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
from backend_core.modules.tenants.models import PromptBundleRevisionStatus
from backend_core.modules.tenants.repository import (
    InboundRouteRepository,
    PromptBundleRevisionRepository,
)


class CallSessionService:
    def __init__(
        self,
        calls: CallSessionRepository,
        routes: InboundRouteRepository,
        prompt_bundles: PromptBundleRevisionRepository,
    ) -> None:
        self._calls = calls
        self._routes = routes
        self._prompt_bundles = prompt_bundles

    async def create(self, data: CreateCallSessionRequest) -> CallSession:
        resolution = await self._routes.resolve(data.called_number, lock_tenant=True)
        if resolution is None:
            raise CallSessionRouteUnavailableError
        tenant, config_revision = resolution

        try:
            config = TenantConfigV2.model_validate(config_revision.config)
        except ValidationError as error:
            raise CallSessionConfigUnavailableError from error
        prompt_revision = await self._prompt_bundles.get(
            tenant.id,
            config.prompt_bundle_revision_id,
        )
        if (
            prompt_revision is None
            or prompt_revision.status is not PromptBundleRevisionStatus.PUBLISHED
        ):
            raise CallSessionConfigUnavailableError

        call = CallSession(
            tenant_id=tenant.id,
            tenant_config_revision_id=config_revision.id,
            prompt_bundle_revision_id=prompt_revision.id,
            channel=CallChannel.SIP,
            direction=CallDirection.INBOUND,
            provider=data.provider,
            provider_call_id=data.provider_call_id,
            room_name=data.room_name,
        )
        try:
            return await self._calls.add(call)
        except IntegrityError as error:
            raise CallSessionConflictError from error

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

    async def complete(self, call_id: UUID) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.COMPLETED:
            return call
        if call.status is not CallSessionStatus.ACTIVE:
            raise CallSessionConflictError
        call.status = CallSessionStatus.COMPLETED
        call.ended_at = datetime.now(UTC)
        await self._calls.flush()
        return call

    async def fail(self, call_id: UUID, reason: str) -> CallSession:
        call = await self._get_for_update(call_id)
        if call.status is CallSessionStatus.FAILED:
            if call.failure_reason != reason:
                raise CallSessionConflictError
            return call
        if call.status not in (CallSessionStatus.CREATED, CallSessionStatus.ACTIVE):
            raise CallSessionConflictError
        call.status = CallSessionStatus.FAILED
        call.ended_at = datetime.now(UTC)
        call.failure_reason = reason
        await self._calls.flush()
        return call

    async def _get_for_update(self, call_id: UUID) -> CallSession:
        call = await self._calls.get_for_update(call_id)
        if call is None:
            raise CallSessionNotFoundError
        return call
