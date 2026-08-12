import base64
import hashlib
from types import SimpleNamespace

import pytest
from backend_core.runtime.finalization.webhook import router
from fastapi import FastAPI
from google.protobuf.json_format import MessageToJson
from httpx import ASGITransport, AsyncClient
from livekit import api
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_livekit_webhook_requires_signature_and_uses_verified_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applied: list[object] = []

    class Coordinator:
        def __init__(self, *args, **kwargs):
            pass

        async def apply(self, result):
            applied.append(result)

    monkeypatch.setattr(
        "backend_core.runtime.finalization.webhook.RecordingCoordinator", Coordinator
    )
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(
        livekit_api_key=SecretStr("test-key"),
        livekit_api_secret=SecretStr("test-livekit-secret-at-least-32-bytes"),
        domain_event_stream="events",
        command_stream="commands",
    )
    app.state.database = object()
    app.state.livekit = SimpleNamespace(egress_result=lambda info: info.egress_id)
    body = MessageToJson(
        api.WebhookEvent(
            event="egress_started",
            egress_info=api.EgressInfo(
                egress_id="EG_verified",
                room_name="room",
                status=api.EgressStatus.EGRESS_STARTING,
            ),
        ),
        preserving_proto_field_name=True,
    )
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    token = (
        api.AccessToken("test-key", "test-livekit-secret-at-least-32-bytes")
        .with_identity("livekit-webhook")
        .with_sha256(digest)
        .to_jwt()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post("/webhooks/livekit", content=body)).status_code == 401
        response = await client.post(
            "/webhooks/livekit",
            content=body,
            headers={"Authorization": token},
        )

    assert response.status_code == 204
    assert applied == ["EG_verified"]
