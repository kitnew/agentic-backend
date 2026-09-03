import json
import logging
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from agentic_observability.domain import CoreMetrics, domain_span
from agentic_observability.propagation import inject_trace_context
from contracts import (
    CapabilityConfirmationResponse,
    CapabilityInvocationRequest,
    CapabilityInvocationResponse,
    CapabilityInvocationStatus,
    IntegrationJob,
    RuntimeCapabilityBinding,
    WorkerResultReport,
)
from opentelemetry.trace import Tracer
from pydantic import BaseModel

from backend_core.modules.calls.models import CallSessionStatus
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.conversations.repository import ConversationRepository
from backend_core.runtime.capabilities.domain import (
    CapabilityValidationError,
    compile_plan,
    enforce_input_constraints,
    normalize_input,
    semantic_result,
    validate_agent_input,
    validate_result_for_plan,
)
from backend_core.runtime.capabilities.execution import (
    TechnicalResultProjectionError,
    project_execution_outcome,
)
from backend_core.runtime.capabilities.models import (
    CapabilityConfirmation,
    CapabilityInvocation,
    OutboxMessage,
)
from backend_core.runtime.capabilities.repository import CapabilityInvocationRepository
from backend_core.runtime.execution_context import ExecutionContextReader

logger = logging.getLogger(__name__)


class CapabilityInvocationService:
    def __init__(
        self,
        invocations: CapabilityInvocationRepository,
        calls: CallSessionRepository,
        conversations: ConversationRepository,
        execution_context: ExecutionContextReader,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._invocations = invocations
        self._calls = calls
        self._conversations = conversations
        self._execution_context = execution_context
        self._tracer = tracer
        self._metrics = metrics

    async def _validate_request(
        self, call_id: UUID, request: CapabilityInvocationRequest
    ) -> tuple[Any, UUID, RuntimeCapabilityBinding, dict[str, object]]:
        call = await self._calls.get(call_id)
        if call is None:
            raise CapabilityValidationError("call_not_found", "Call does not exist")
        if call.status is not CallSessionStatus.CONNECTED:
            raise CapabilityValidationError(
                "call_not_active", "Call does not allow capability execution"
            )
        try:
            runtime_profile = await self._execution_context.capability(call, request.capability)
            payload_timezone = (await self._execution_context.snapshot(call)).agent or {}
            timezone = str(payload_timezone.get("timezone", "UTC"))
        except ValueError as error:
            raise CapabilityValidationError(
                "configuration_invalid", "Execution snapshot is unavailable"
            ) from error
        pin_id = call.execution_snapshot_id
        if not runtime_profile.enabled:
            raise CapabilityValidationError(
                "capability_disabled", "Capability is disabled"
            )
        validate_agent_input(runtime_profile.input_schema, request.agent_input)
        canonical = normalize_input(
            request.agent_input,
            runtime_profile.bindings,
        )
        enforce_input_constraints(
            canonical,
            timezone,
            runtime_profile.input_constraints,
        )
        if (
            runtime_profile.policy.requires_caller_phone
            and call.caller_phone_e164 is None
        ):
            raise CapabilityValidationError(
                "caller_phone_unavailable",
                "Caller phone is required for capability execution",
                "metadata.caller_phone",
            )
        assert pin_id is not None
        return call, pin_id, runtime_profile, canonical

    async def prepare_confirmation(
        self, call_id: UUID, request: CapabilityInvocationRequest
    ) -> CapabilityConfirmationResponse:
        call, pin_id, profile, canonical = await self._validate_request(call_id, request)
        policy = profile.policy
        if not policy.requires_final_confirmation:
            raise CapabilityValidationError(
                "confirmation_not_required", "Capability does not require confirmation"
            )
        payload_hash = sha256(
            f"{pin_id}:{profile.semantic_key}:{profile.semantic_version}:".encode()
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
            semantic_key=profile.semantic_key,
            semantic_version=profile.semantic_version,
            execution_snapshot_id=call.execution_snapshot_id,
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
        _, _, _, pin_id, profile, canonical = await self._validate_request(
            call_id, request
        )
        payload_hash = sha256(
            f"{pin_id}:{profile.semantic_key}:{profile.semantic_version}:".encode()
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
        with domain_span(
            self._tracer, "capability.prepare", {"call.id": str(call_id)}
        ) as span:
            invocation, created = await self._invoke(
                call_id, request, skip_confirmation=skip_confirmation
            )
            if span is not None:
                span.set_attribute("tenant.id", str(invocation.tenant_id))
                span.set_attribute("conversation.id", str(invocation.conversation_id))
                span.set_attribute("capability.name", invocation.semantic_key)
                span.set_attribute("capability.version", invocation.semantic_version)
            return invocation, created

    async def _invoke(
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
        call, _pin_id, profile, canonical = await self._validate_request(call_id, request)
        semantic_key = profile.semantic_key
        policy = profile.policy
        if policy.requires_final_confirmation and not skip_confirmation:
            raise CapabilityValidationError(
                "confirmation_required",
                "Capability confirmation is required before execution",
            )
        logger.info(
            "capability_input_validated",
            extra={
                "tenant_id": str(call.tenant_id),
                "call_id": str(call.id),
                "semantic_key": profile.semantic_key,
                "semantic_version": profile.semantic_version,
                "execution_snapshot_id": str(call.execution_snapshot_id),
            },
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
            integration_id=profile.execution.connection_id,
            caller_phone=call.caller_phone_e164 or "",
            semantic_key=semantic_key,
        )
        job = IntegrationJob(
            job_id=job_id,
            capability_invocation_id=invocation_id,
            call_id=call.id,
            execution_snapshot_id=call.execution_snapshot_id,
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
            semantic_key=profile.semantic_key,
            semantic_version=profile.semantic_version,
            execution_snapshot_id=call.execution_snapshot_id,
            canonical_input=canonical,
            execution_plan=plan.model_dump(mode="json"),
            operation_id=invocation_id,
            job_id=job_id,
        )
        metadata: dict[str, str] = {}
        scope = (
            self._tracer.start_as_current_span(
                "messaging.outbox.create",
                attributes={
                    "messaging.system": "redis",
                },
            )
            if self._tracer is not None
            else nullcontext()
        )
        with scope:
            if self._tracer is not None:
                inject_trace_context(metadata)
            outbox = OutboxMessage(
                job_id=job_id,
                capability_invocation_id=invocation_id,
                payload=job.model_dump(mode="json"),
                transport_metadata=metadata,
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
                    "semantic_key": profile.semantic_key,
                    "semantic_version": profile.semantic_version,
                    "execution_snapshot_id": str(call.execution_snapshot_id),
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
            projected_result = semantic_result(outcome)
            invocation.semantic_result = (
                projected_result.model_dump(mode="json")
                if isinstance(projected_result, BaseModel)
                else projected_result
            )
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
            invocation.error_message = "Capability execution failed"
        await self._invocations.flush()
        if self._metrics is not None:
            self._metrics.capability_completed(
                name=invocation.semantic_key,
                version=str(invocation.semantic_version),
                status="succeeded" if report.status == "succeeded" else "failed",
                duration_seconds=max(
                    0.0,
                    (report.completed_at - invocation.created_at).total_seconds(),
                ),
                error_type=report.error.code if report.error is not None else None,
            )
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
                "execution_snapshot_id": str(invocation.execution_snapshot_id),
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
        semantic_result=invocation.semantic_result,
        error_code=invocation.error_code,
        error_message=invocation.error_message,
        created_at=invocation.created_at,
        completed_at=invocation.completed_at,
    )
