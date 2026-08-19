from typing import Annotated
from uuid import UUID

from contracts import ManagedWebhookPostJsonPlan, RuntimeIntegrationMaterial
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from backend_core.modules.calls.models import CallSession
from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.models import IntegrationProvider
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.integrations.service import (
    IntegrationConnectionError,
    IntegrationConnectionService,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.platform.auth import require_internal_scope
from backend_core.platform.database import DatabaseSession
from backend_core.platform.messaging import TransactionalOutboxBus
from backend_core.runtime.finalization.service import (
    FinalizationError,
    FinalizationService,
)

router = APIRouter(prefix="/internal/v1/calls", tags=["internal:finalization"])
MAX_REPRESENTATION_BYTES = 32 * 1024 * 1024
_TRANSFER_CHUNK_BYTES = 64 * 1024


async def body(request: Request, max_bytes: int) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, "artifact is too large"
            )
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "artifact is empty")
    return bytes(content)


def chunks(content: bytes):
    for offset in range(0, len(content), _TRANSFER_CHUNK_BYTES):
        yield content[offset : offset + _TRANSFER_CHUNK_BYTES]


def service(session: DatabaseSession, request: Request) -> FinalizationService:
    return FinalizationService(
        session,
        TransactionalOutboxBus(
            session,
            request.app.state.settings.domain_event_stream,
            request.app.state.settings.command_stream,
            request.app.state.outbox_tracer,
        ),
    )


Service = Annotated[FinalizationService, Depends(service)]


def integration_service(
    session: DatabaseSession, request: Request
) -> IntegrationConnectionService:
    return IntegrationConnectionService(
        TenantRepository(session),
        IntegrationConnectionRepository(session),
        IntegrationSecretCipher(
            request.app.state.settings.integration_encryption_key.get_secret_value()
        ),
    )


IntegrationService = Annotated[
    IntegrationConnectionService, Depends(integration_service)
]


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


@router.get(
    "/{call_id}/post-call-actions/{action_id}/integration-material",
    response_model=RuntimeIntegrationMaterial,
    dependencies=[Depends(require_internal_scope("integration-material:read"))],
)
async def post_call_action_material(
    call_id: UUID,
    action_id: str,
    finalization_id: UUID,
    command_id: UUID,
    finalization: Service,
    integrations: IntegrationService,
    session: DatabaseSession,
) -> RuntimeIntegrationMaterial:
    try:
        plan = await finalization.action_plan(
            call_id, finalization_id, action_id, command_id
        )
        call = await session.get(CallSession, call_id)
        if call is None:
            raise FinalizationError("call not found")
        view = await integrations.get(call.tenant_id, plan.integration_id)
        if view.connection.provider is not IntegrationProvider.MANAGED_WEBHOOK:
            raise IntegrationConnectionError("connection_provider_mismatch")
        if view.credential is None:
            raise IntegrationConnectionError("credential_not_configured")
        return integrations.material(view.connection, view.credential)
    except FinalizationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except IntegrationConnectionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.get(
    "/artifact-representations/{representation_id}/source",
    dependencies=[Depends(require_internal_scope("artifact-representation:read"))],
)
async def materialization_source(
    representation_id: UUID,
    command_id: UUID,
    finalization: Service,
) -> Response:
    try:
        (
            representation,
            content,
            content_type,
        ) = await finalization.materialization_source(representation_id, command_id)
        return Response(
            content,
            media_type=content_type,
            headers={
                "X-Artifact-Type": representation.artifact_type,
                "X-Target-Representation": representation.representation,
            },
        )
    except FinalizationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get(
    "/artifact-representations/{representation_id}/content",
    dependencies=[Depends(require_internal_scope("artifact-representation:read"))],
)
async def representation_content(
    representation_id: UUID,
    command_id: UUID,
    finalization: Service,
) -> StreamingResponse:
    try:
        representation, content = await finalization.representation_content(
            representation_id, command_id
        )
        return StreamingResponse(
            chunks(content),
            media_type=representation.content_type,
            headers={"Content-Length": str(representation.byte_size)},
        )
    except FinalizationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get(
    "/artifact-representations/{representation_id}/recording-source",
    dependencies=[Depends(require_internal_scope("artifact-representation:read"))],
)
async def recording_source(
    representation_id: UUID,
    command_id: UUID,
    finalization: Service,
) -> dict[str, object]:
    try:
        representation, recording = await finalization.recording_source(
            representation_id, command_id
        )
        return {
            "representation_id": str(representation.id),
            "storage_key": recording.storage_key,
            "content_type": recording.content_type,
            "byte_size": recording.byte_size,
        }
    except FinalizationError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.put(
    "/artifact-representations/{representation_id}/content",
    dependencies=[Depends(require_internal_scope("artifact-representation:write"))],
)
async def store_representation(
    representation_id: UUID,
    command_id: UUID,
    request: Request,
    finalization: Service,
) -> dict[str, object]:
    try:
        representation = await finalization.store_representation(
            representation_id,
            command_id,
            await body(request, MAX_REPRESENTATION_BYTES),
            request.headers.get("content-type", "application/octet-stream")[:255],
        )
        return {
            "representation_id": str(representation.id),
            "byte_size": representation.byte_size,
            "sha256": representation.sha256,
        }
    except FinalizationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
