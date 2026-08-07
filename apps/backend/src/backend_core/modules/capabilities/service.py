import json
import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    CapabilityConfirmationResponse,
    CapabilityInvocationRequest,
    CapabilityInvocationResponse,
    CapabilityInvocationStatus,
    IntegrationJob,
    ReservationRequestSubmitted,
    TenantCapabilityProfile,
    TenantConfigV2,
    WorkerResultReport,
)

from backend_core.modules.calls.models import CallSessionStatus
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.capabilities.domain import (
    SEMANTIC_KEY,
    CapabilityValidationError,
    compile_plan,
    definition,
    normalize_input,
    semantic_result,
    validate_agent_input,
    validate_business_input,
    validate_result_for_plan,
)
from backend_core.modules.capabilities.execution import (
    TechnicalResultProjectionError,
    project_execution_outcome,
)
from backend_core.modules.capabilities.models import (
    CapabilityConfirmation,
    CapabilityInvocation,
    OutboxMessage,
)
from backend_core.modules.capabilities.repository import CapabilityInvocationRepository
from backend_core.modules.conversations.repository import ConversationRepository
from backend_core.modules.integrations.models import (
    IntegrationConnectionStatus,
    provider_for_plan_type,
)
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.models import ConfigRevisionStatus, TenantStatus
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)

logger = logging.getLogger(__name__)


class CapabilityInvocationService:
    def __init__(
        self,
        invocations: CapabilityInvocationRepository,
        calls: CallSessionRepository,
        conversations: ConversationRepository,
        tenants: TenantRepository,
        configs: ConfigRevisionRepository,
        connections: IntegrationConnectionRepository,
    ) -> None:
        self._invocations = invocations
        self._calls = calls
        self._conversations = conversations
        self._tenants = tenants
        self._configs = configs
        self._connections = connections

    async def _validate_request(
        self, call_id: UUID, request: CapabilityInvocationRequest
    ) -> tuple[Any, Any, TenantCapabilityProfile, Any, dict[str, object]]:
        call = await self._calls.get(call_id)
        if call is None:
            raise CapabilityValidationError("call_not_found", "Call does not exist")
        tenant = await self._tenants.get(call.tenant_id)
        if tenant is None or tenant.status is not TenantStatus.ACTIVE:
            raise CapabilityValidationError("tenant_inactive", "Tenant is not active")
        if call.status is not CallSessionStatus.ACTIVE:
            raise CapabilityValidationError(
                "call_not_active", "Call does not allow capability execution"
            )
        revision = await self._configs.get(
            call.tenant_id, call.tenant_config_revision_id
        )
        if revision is None or revision.status is not ConfigRevisionStatus.PUBLISHED:
            raise CapabilityValidationError(
                "configuration_invalid", "Pinned configuration is unavailable"
            )
        config = TenantConfigV2.model_validate(revision.config)
        profile = config.capabilities.get(SEMANTIC_KEY)
        if not isinstance(profile, TenantCapabilityProfile) or not profile.enabled:
            raise CapabilityValidationError(
                "capability_disabled", "Capability is disabled"
            )
        semantic = definition(SEMANTIC_KEY, profile.semantic_version)
        if request.capability not in {semantic.semantic_key, semantic.tool_name}:
            raise CapabilityValidationError(
                "capability_not_found", "Capability is not available"
            )
        validate_agent_input(profile.agent_input_schema, request.agent_input)
        canonical = validate_business_input(
            normalize_input(profile.agent_input_schema, request.agent_input),
            config.localization.timezone,
        )
        if (
            profile.business_policy.requires_caller_phone
            and call.caller_phone_e164 is None
        ):
            raise CapabilityValidationError(
                "caller_phone_unavailable",
                "Caller phone is required for reservation submission",
                "metadata.caller_phone",
            )
        return call, revision, profile, semantic, canonical

    async def prepare_confirmation(
        self, call_id: UUID, request: CapabilityInvocationRequest
    ) -> CapabilityConfirmationResponse:
        call, revision, profile, semantic, canonical = await self._validate_request(
            call_id, request
        )
        if not profile.business_policy.requires_final_confirmation:
            raise CapabilityValidationError(
                "confirmation_not_required", "Capability does not require confirmation"
            )
        payload_hash = sha256(
            f"{revision.id}:{semantic.semantic_key}:{semantic.semantic_version}:".encode()
            + json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await self._invocations.get_confirmation_by_tool_call(
            call.tenant_id, call.id, request.tool_call_id
        )
        if (
            existing is not None
            and existing.status == "pending_confirmation"
            and existing.expires_at > datetime.now(UTC)
        ):
            return CapabilityConfirmationResponse(
                id=existing.id,
                summary=canonical,
                expires_at=existing.expires_at,
            )
        now = datetime.now(UTC)
        if existing is not None:
            existing.canonical_input = canonical
            existing.agent_input = request.agent_input
            existing.payload_hash = payload_hash
            existing.status = "pending_confirmation"
            existing.invocation_id = None
            existing.consumed_at = None
            existing.expires_at = now + timedelta(minutes=10)
            await self._invocations.flush()
            return CapabilityConfirmationResponse(
                id=existing.id,
                summary=canonical,
                expires_at=existing.expires_at,
            )
        confirmation = CapabilityConfirmation(
            tenant_id=call.tenant_id,
            call_id=call.id,
            tool_call_id=request.tool_call_id,
            semantic_key=semantic.semantic_key,
            semantic_version=semantic.semantic_version,
            tenant_config_revision_id=revision.id,
            canonical_input=canonical,
            agent_input=request.agent_input,
            payload_hash=payload_hash,
            status="pending_confirmation",
            expires_at=now + timedelta(minutes=10),
        )
        await self._invocations.add_confirmation(confirmation)
        return CapabilityConfirmationResponse(
            id=confirmation.id,
            summary=canonical,
            expires_at=confirmation.expires_at,
        )

    async def confirm(
        self, call_id: UUID, confirmation_id: UUID, tool_call_id: str
    ) -> tuple[CapabilityInvocation, bool]:
        confirmation = await self._invocations.get_confirmation(
            confirmation_id, for_update=True
        )
        if confirmation is None or confirmation.call_id != call_id:
            raise CapabilityValidationError(
                "confirmation_not_found", "Confirmation was not found"
            )
        if confirmation.status == "consumed" and confirmation.invocation_id is not None:
            invocation = await self._invocations.get(confirmation.invocation_id)
            if invocation is not None:
                return invocation, False
        if confirmation.status != "pending_confirmation":
            raise CapabilityValidationError(
                "confirmation_conflict", "Confirmation is no longer usable"
            )
        if confirmation.expires_at <= datetime.now(UTC):
            confirmation.status = "expired"
            raise CapabilityValidationError(
                "confirmation_expired", "Confirmation has expired"
            )
        request = CapabilityInvocationRequest(
            tool_call_id=tool_call_id,
            capability=confirmation.semantic_key,
            agent_input=confirmation.agent_input,
        )
        _, revision, _, semantic, canonical = await self._validate_request(
            call_id, request
        )
        payload_hash = sha256(
            f"{revision.id}:{semantic.semantic_key}:{semantic.semantic_version}:".encode()
            + json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if payload_hash != confirmation.payload_hash:
            confirmation.status = "cancelled"
            raise CapabilityValidationError(
                "confirmation_conflict", "Confirmation snapshot has changed"
            )
        invocation, created = await self.invoke(
            call_id, request, skip_confirmation=True
        )
        confirmation.status = "consumed"
        confirmation.invocation_id = invocation.id
        confirmation.consumed_at = datetime.now(UTC)
        return invocation, created

    async def invoke(
        self,
        call_id: UUID,
        request: CapabilityInvocationRequest,
        *,
        skip_confirmation: bool = False,
    ) -> tuple[CapabilityInvocation, bool]:
        call = await self._calls.get(call_id)
        if call is None:
            raise CapabilityValidationError("call_not_found", "Call does not exist")
        logger.info(
            "capability_invocation_received",
            extra={"tenant_id": str(call.tenant_id), "call_id": str(call.id)},
        )
        existing = await self._invocations.get_by_tool_call(
            call.tenant_id, call.id, request.tool_call_id
        )
        if existing is not None:
            logger.info(
                "capability_duplicate_reused",
                extra={
                    "tenant_id": str(call.tenant_id),
                    "call_id": str(call.id),
                    "invocation_id": str(existing.id),
                },
            )
            return existing, False
        tenant = await self._tenants.get(call.tenant_id)
        if tenant is None or tenant.status is not TenantStatus.ACTIVE:
            raise CapabilityValidationError("tenant_inactive", "Tenant is not active")
        if call.status is not CallSessionStatus.ACTIVE:
            raise CapabilityValidationError(
                "call_not_active", "Call does not allow capability execution"
            )
        revision = await self._configs.get(
            call.tenant_id, call.tenant_config_revision_id
        )
        if revision is None or revision.status is not ConfigRevisionStatus.PUBLISHED:
            raise CapabilityValidationError(
                "configuration_invalid", "Pinned configuration is unavailable"
            )
        config = TenantConfigV2.model_validate(revision.config)
        profile = config.capabilities.get(SEMANTIC_KEY)
        if not isinstance(profile, TenantCapabilityProfile) or not profile.enabled:
            raise CapabilityValidationError(
                "capability_disabled", "Capability is disabled"
            )
        semantic = definition(SEMANTIC_KEY, profile.semantic_version)
        if request.capability not in {semantic.semantic_key, semantic.tool_name}:
            raise CapabilityValidationError(
                "capability_not_found", "Capability is not available"
            )
        validate_agent_input(profile.agent_input_schema, request.agent_input)
        canonical = validate_business_input(
            normalize_input(profile.agent_input_schema, request.agent_input),
            config.localization.timezone,
        )
        if (
            profile.business_policy.requires_caller_phone
            and call.caller_phone_e164 is None
        ):
            raise CapabilityValidationError(
                "caller_phone_unavailable",
                "Caller phone is required for reservation submission",
                "metadata.caller_phone",
            )
        if (
            profile.business_policy.requires_final_confirmation
            and not skip_confirmation
        ):
            raise CapabilityValidationError(
                "confirmation_required",
                "Reservation confirmation is required before submission",
            )
        logger.info(
            "capability_input_validated",
            extra={
                "tenant_id": str(call.tenant_id),
                "call_id": str(call.id),
                "semantic_key": semantic.semantic_key,
                "semantic_version": semantic.semantic_version,
                "tenant_config_revision_id": str(revision.id),
            },
        )
        connection = await self._connections.get(
            call.tenant_id, profile.execution.connection_id
        )
        if connection is None:
            raise CapabilityValidationError(
                "connection_not_found", "Integration connection was not found"
            )
        if (
            connection.status is not IntegrationConnectionStatus.ACTIVE
            or connection.provider
            is not provider_for_plan_type(profile.execution.plan_type)
        ):
            raise CapabilityValidationError(
                "connection_disabled", "Integration connection is unavailable"
            )
        conversation = await self._conversations.get_for_call(call.id)
        if conversation is None:
            raise CapabilityValidationError(
                "configuration_invalid", "Conversation is unavailable"
            )

        invocation_id = uuid4()
        job_id = uuid4()
        now = datetime.now(UTC)
        plan = compile_plan(
            profile,
            canonical,
            operation_id=invocation_id,
            call_id=call.id,
            tool_call_id=request.tool_call_id,
            credential_ref=connection.credential_ref,
            caller_phone=call.caller_phone_e164 or "",
        )
        job = IntegrationJob(
            job_id=job_id,
            capability_invocation_id=invocation_id,
            execution_plan=plan,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        invocation = CapabilityInvocation(
            id=invocation_id,
            tenant_id=call.tenant_id,
            call_id=call.id,
            conversation_id=conversation.id,
            tool_call_id=request.tool_call_id,
            semantic_key=semantic.semantic_key,
            semantic_version=semantic.semantic_version,
            tenant_config_revision_id=revision.id,
            canonical_input=canonical,
            execution_plan=plan.model_dump(mode="json"),
            operation_id=invocation_id,
            job_id=job_id,
        )
        outbox = OutboxMessage(
            job_id=job_id,
            capability_invocation_id=invocation_id,
            payload=job.model_dump(mode="json"),
        )
        created_invocation, created = await self._invocations.add_with_outbox(
            invocation, outbox
        )
        if created:
            logger.info(
                "capability_plan_compiled",
                extra={
                    "tenant_id": str(call.tenant_id),
                    "call_id": str(call.id),
                    "invocation_id": str(invocation_id),
                    "job_id": str(job_id),
                    "semantic_key": semantic.semantic_key,
                    "semantic_version": semantic.semantic_version,
                    "tenant_config_revision_id": str(revision.id),
                    "plan_type": plan.plan_type,
                },
            )
        return created_invocation, created

    async def get(self, call_id: UUID, invocation_id: UUID) -> CapabilityInvocation:
        invocation = await self._invocations.get(invocation_id)
        if invocation is None or invocation.call_id != call_id:
            raise CapabilityValidationError(
                "capability_not_found", "Capability invocation was not found"
            )
        return invocation

    async def record_result(self, report: WorkerResultReport) -> CapabilityInvocation:
        invocation = await self._invocations.get(
            report.capability_invocation_id, for_update=True
        )
        if invocation is None or invocation.job_id != report.job_id:
            raise CapabilityValidationError(
                "capability_not_found", "Capability invocation was not found"
            )
        if invocation.status in {
            CapabilityInvocationStatus.SUCCEEDED,
            CapabilityInvocationStatus.FAILED,
            CapabilityInvocationStatus.EXPIRED,
        }:
            return invocation
        invocation.completed_at = report.completed_at
        if report.status == "succeeded":
            if report.result is None:
                raise CapabilityValidationError(
                    "result_missing", "Successful worker report has no result"
                )
            validate_result_for_plan(invocation.execution_plan, report.result)
            try:
                outcome = project_execution_outcome(report.result)
            except TechnicalResultProjectionError as error:
                raise CapabilityValidationError(
                    "unsupported_result_type", str(error)
                ) from error
            invocation.status = CapabilityInvocationStatus.SUCCEEDED
            invocation.technical_result = report.result.model_dump(mode="json")
            invocation.semantic_result = semantic_result(
                invocation.semantic_key, invocation.semantic_version, outcome
            ).model_dump(mode="json")
        else:
            if report.error is None:
                raise CapabilityValidationError(
                    "error_missing", "Failed worker report has no error"
                )
            invocation.status = CapabilityInvocationStatus.FAILED
            invocation.technical_result = {
                "error": report.error.model_dump(mode="json")
            }
            invocation.error_code = "execution_failed"
            invocation.error_message = "The reservation request could not be submitted"
        await self._invocations.flush()
        logger.info(
            "capability_result_reported",
            extra={
                "tenant_id": str(invocation.tenant_id),
                "call_id": str(invocation.call_id),
                "invocation_id": str(invocation.id),
                "job_id": str(invocation.job_id),
                "attempt": report.attempt,
                "status": report.status,
            },
        )
        logger.info(
            "capability_invocation_completed"
            if report.status == "succeeded"
            else "capability_invocation_failed",
            extra={
                "tenant_id": str(invocation.tenant_id),
                "call_id": str(invocation.call_id),
                "invocation_id": str(invocation.id),
                "job_id": str(invocation.job_id),
                "semantic_key": invocation.semantic_key,
                "semantic_version": invocation.semantic_version,
                "tenant_config_revision_id": str(invocation.tenant_config_revision_id),
                "status": invocation.status.value,
                "attempt": report.attempt,
                "latency_ms": round(
                    (report.completed_at - invocation.created_at).total_seconds() * 1000
                ),
            },
        )
        return invocation


def invocation_response(
    invocation: CapabilityInvocation,
) -> CapabilityInvocationResponse:
    return CapabilityInvocationResponse(
        id=invocation.id,
        call_id=invocation.call_id,
        semantic_key=invocation.semantic_key,
        semantic_version=invocation.semantic_version,
        status=invocation.status,
        semantic_result=(
            ReservationRequestSubmitted.model_validate(invocation.semantic_result)
            if invocation.semantic_result is not None
            else None
        ),
        error_code=invocation.error_code,
        error_message=invocation.error_message,
        created_at=invocation.created_at,
        completed_at=invocation.completed_at,
    )
