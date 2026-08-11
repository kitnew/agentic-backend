from typing import Annotated
from uuid import UUID

from contracts import ManagedWebhookPostJsonPlan
from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend_core.platform.auth import require_internal_scope
from backend_core.platform.database import DatabaseSession
from backend_core.platform.messaging import TransactionalOutboxBus
from backend_core.runtime.finalization.service import (
    FinalizationError,
    FinalizationService,
)

router = APIRouter(prefix="/internal/v1/calls", tags=["internal:finalization"])


def service(session: DatabaseSession, request: Request) -> FinalizationService:
    return FinalizationService(
        session,
        TransactionalOutboxBus(
            session,
            request.app.state.settings.domain_event_stream,
            request.app.state.settings.command_stream,
        ),
    )


Service = Annotated[FinalizationService, Depends(service)]


@router.get(
    "/{call_id}/finalization-context",
    dependencies=[Depends(require_internal_scope("finalization-context:read"))],
)
async def finalization_context(
    call_id: UUID,
    finalization_id: UUID,
    command_id: UUID,
    finalization: Service,
) -> dict[str, object]:
    try:
        return await finalization.summary_context(call_id, finalization_id, command_id)
    except FinalizationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get(
    "/{call_id}/post-call-actions/{action_id}",
    response_model=ManagedWebhookPostJsonPlan,
    dependencies=[Depends(require_internal_scope("post-call-action:read"))],
)
async def post_call_action(
    call_id: UUID,
    action_id: str,
    finalization_id: UUID,
    command_id: UUID,
    finalization: Service,
) -> ManagedWebhookPostJsonPlan:
    try:
        return await finalization.action_plan(
            call_id, finalization_id, action_id, command_id
        )
    except FinalizationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
