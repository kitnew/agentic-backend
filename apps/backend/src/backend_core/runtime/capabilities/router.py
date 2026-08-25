import logging
from typing import Annotated
from uuid import UUID

from agentic_observability.domain import CoreMetrics
from contracts import (
    CapabilityConfirmationConfirmRequest,
    CapabilityConfirmationResponse,
    CapabilityInvocationRequest,
    CapabilityInvocationResponse,
    RuntimeIntegrationMaterial,
    WorkerResultReport,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from opentelemetry.trace import Tracer
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.conversations.repository import ConversationRepository
from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.service import (
    CapabilityIntegrationResolver,
    IntegrationConnectionError,
    IntegrationConnectionService,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.platform.auth import require_internal_scope
from backend_core.platform.database import DatabaseSession
from backend_core.runtime.bundle_store import RuntimeBundleStore
from backend_core.runtime.capabilities.domain import CapabilityValidationError
from backend_core.runtime.capabilities.repository import CapabilityInvocationRepository
from backend_core.runtime.capabilities.service import (
    CapabilityInvocationService,
    invocation_response,
)

logger = logging.getLogger(__name__)
voice_router = APIRouter(prefix="/internal/v1/calls", tags=["internal:capabilities"])
worker_router = APIRouter(
    prefix="/internal/v1/capability-results", tags=["internal:capabilities"]
)
runtime_router = APIRouter(
    prefix="/internal/v1/capability-invocations", tags=["internal:integrations"]
)


def build_service(
    session: AsyncSession,
    tracer: Tracer | None = None,
    metrics: CoreMetrics | None = None,
) -> CapabilityInvocationService:
    return CapabilityInvocationService(
        CapabilityInvocationRepository(session),
        CallSessionRepository(session),
        ConversationRepository(session),
        IntegrationConnectionRepository(session),
        RuntimeBundleStore(session),
        tracer,
        metrics,
    )


def service(session: DatabaseSession, request: Request) -> CapabilityInvocationService:
    return build_service(
        session, request.app.state.outbox_tracer, request.app.state.core_metrics
    )


Service = Annotated[CapabilityInvocationService, Depends(service)]


def integration_resolver(
    session: DatabaseSession, request: Request
) -> CapabilityIntegrationResolver:
    connections = IntegrationConnectionRepository(session)
    integrations = IntegrationConnectionService(
        TenantRepository(session),
        connections,
        IntegrationSecretCipher(
            request.app.state.settings.integration_encryption_key.get_secret_value()
        ),
    )
    return CapabilityIntegrationResolver(
        CapabilityInvocationRepository(session), connections, integrations
    )


IntegrationResolver = Annotated[
    CapabilityIntegrationResolver, Depends(integration_resolver)
]


def http_error(error: CapabilityValidationError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if error.code in {"call_not_found", "capability_not_found"}
        else status.HTTP_409_CONFLICT
    )
    if error.code in {
        "invalid_agent_input",
        "business_policy_rejected",
        "input_constraint_rejected",
    }:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        code, {"code": error.code, "path": error.path, "message": error.message}
    )


@voice_router.post(
    "/{call_id}/capability-confirmations",
    response_model=CapabilityConfirmationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_internal_scope("capability-confirmation:create"))],
)
async def prepare_confirmation(
    call_id: UUID,
    data: CapabilityInvocationRequest,
    invocations: Service,
) -> CapabilityConfirmationResponse:
    try:
        return await invocations.prepare_confirmation(call_id, data)
    except CapabilityValidationError as error:
        raise http_error(error) from error


@voice_router.post(
    "/{call_id}/capability-confirmations/{confirmation_id}/confirm",
    response_model=CapabilityInvocationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_internal_scope("capability-confirmation:confirm"))],
)
async def confirm_capability(
    call_id: UUID,
    confirmation_id: UUID,
    data: CapabilityConfirmationConfirmRequest,
    invocations: Service,
    response: Response,
) -> CapabilityInvocationResponse:
    try:
        invocation, created = await invocations.confirm(
            call_id, confirmation_id, data.tool_call_id
        )
    except CapabilityValidationError as error:
        raise http_error(error) from error
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return invocation_response(invocation)


@voice_router.post(
    "/{call_id}/capability-invocations",
    response_model=CapabilityInvocationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_internal_scope("capability-invocation:create"))],
)
async def create_invocation(
    call_id: UUID,
    data: CapabilityInvocationRequest,
    invocations: Service,
    response: Response,
) -> CapabilityInvocationResponse:
    try:
        invocation, created = await invocations.invoke(call_id, data)
    except CapabilityValidationError as error:
        logger.warning(
            "capability_input_rejected",
            extra={"call_id": str(call_id), "code": error.code, "path": error.path},
        )
        raise http_error(error) from error
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return invocation_response(invocation)


@voice_router.get(
    "/{call_id}/capability-invocations/{invocation_id}",
    response_model=CapabilityInvocationResponse,
    dependencies=[Depends(require_internal_scope("capability-invocation:read"))],
)
async def get_invocation(
    call_id: UUID, invocation_id: UUID, invocations: Service
) -> CapabilityInvocationResponse:
    try:
        return invocation_response(await invocations.get(call_id, invocation_id))
    except CapabilityValidationError as error:
        raise http_error(error) from error


@runtime_router.get(
    "/{invocation_id}/integration-material",
    response_model=RuntimeIntegrationMaterial,
    dependencies=[Depends(require_internal_scope("integration-material:read"))],
)
async def integration_material(
    invocation_id: UUID,
    job_id: UUID,
    integrations: IntegrationResolver,
    call_id: UUID | None = None,
    runtime_bundle_id: UUID | None = None,
) -> RuntimeIntegrationMaterial:
    try:
        return await integrations.resolve(
            invocation_id,
            job_id,
            call_id=call_id,
            runtime_bundle_id=runtime_bundle_id,
        )
    except IntegrationConnectionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@worker_router.post(
    "",
    response_model=CapabilityInvocationResponse,
    dependencies=[Depends(require_internal_scope("capability-result:write"))],
)
async def report_result(
    report: WorkerResultReport, invocations: Service
) -> CapabilityInvocationResponse:
    try:
        return invocation_response(await invocations.record_result(report))
    except CapabilityValidationError as error:
        raise http_error(error) from error
