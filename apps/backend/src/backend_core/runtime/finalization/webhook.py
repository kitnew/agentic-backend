import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from livekit import api

from backend_core.runtime.finalization.recording import RecordingCoordinator

logger = logging.getLogger(__name__)
router = APIRouter(tags=["livekit:webhook"])


@router.post("/webhooks/livekit", status_code=status.HTTP_204_NO_CONTENT)
async def livekit_webhook(request: Request) -> Response:
    body = await request.body()
    authorization = request.headers.get("authorization")
    if authorization is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing webhook signature")
    settings = request.app.state.settings
    try:
        event = api.WebhookReceiver(
            api.TokenVerifier(
                settings.livekit_api_key.get_secret_value(),
                settings.livekit_api_secret.get_secret_value(),
            )
        ).receive(body.decode(), authorization)
    except Exception as error:
        logger.warning("Rejected invalid LiveKit webhook", exc_info=error)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid webhook signature"
        ) from error
    if event.event not in {"egress_started", "egress_updated", "egress_ended"}:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if event.egress_info is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "missing egress info")
    try:
        await RecordingCoordinator(
            request.app.state.database,
            request.app.state.livekit,
            event_stream=settings.domain_event_stream,
            command_stream=settings.command_stream,
            tracer=getattr(request.app.state, "outbox_tracer", None),
        ).apply(request.app.state.livekit.egress_result(event.egress_info))
    except ValueError as error:
        logger.warning("Rejected conflicting LiveKit egress event", exc_info=error)
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
