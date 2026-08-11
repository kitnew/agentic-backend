import logging
from typing import Annotated
from uuid import UUID

from contracts import (
    CapabilityConfirmationConfirmRequest,
    CapabilityConfirmationResponse,
    CapabilityInvocationRequest,
    CapabilityInvocationResponse,
    WorkerResultReport,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.conversations.repository import ConversationRepository
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)
from backend_core.platform.auth import require_internal_scope
from backend_core.platform.database import DatabaseSession
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


def build_service(session: AsyncSession) -> CapabilityInvocationService:
    return CapabilityInvocationService(
        CapabilityInvocationRepository(session),
        CallSessionRepository(session),
        ConversationRepository(session),
        TenantRepository(session),
        ConfigRevisionRepository(session),
        IntegrationConnectionRepository(session),
    )


def service(session: DatabaseSession) -> CapabilityInvocationService:
    return build_service(session)


Service = Annotated[CapabilityInvocationService, Depends(service)]


def http_error(error: CapabilityValidationError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if error.code in {"call_not_found", "capability_not_found"}
        else status.HTTP_409_CONFLICT
    )
    if error.code in {"invalid_agent_input", "business_policy_rejected"}:
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
