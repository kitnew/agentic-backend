from uuid import uuid4

import httpx
import pytest
from contracts import (
    HttpRequestPlanV1,
    HttpRequestSpec,
    HttpResponseSpec,
    IntegrationExecutionMaterial,
)
from job_worker.worker import ExecutionError, HttpExecutionHandler


def material(*, secret: str | None = None) -> IntegrationExecutionMaterial:
    return IntegrationExecutionMaterial(
        integration_kind="http",
        config={
            "endpoint": "https://api.example.com/v1",
            "headers": {"X-Static": "yes"},
            "authentication": (
                {"type": "api_key_header", "header_name": "X-API-Key"}
                if secret
                else {"type": "none"}
            ),
            "security": {"additional_allowed_hosts": []},
        },
        secret=secret,
    )


@pytest.mark.asyncio
async def test_target_http_operation_maps_request_and_response() -> None:
    seen: dict[str, object] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen.update(
            method=request.method,
            url=str(request.url),
            body=request.content,
            headers=request.headers,
        )
        return httpx.Response(200, json={"accepted": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    plan = HttpRequestPlanV1(
        operation_id=uuid4(),
        method="POST",
        path="reservations",
        query={"source": "voice"},
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(
            codec="json", mapping={"ok": {"$expr": "response.body.accepted"}}
        ),
        payload={"room_count": 1},
        timeout_seconds=5,
    )
    try:
        result = await HttpExecutionHandler(client).execute(
            plan, material(secret="secret")
        )
    finally:
        await client.aclose()

    assert result.data == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.example.com/v1/reservations?source=voice"
    assert seen["body"] == b'{"room_count":1}'
    assert seen["headers"]["x-api-key"] == "secret"  # type: ignore[index]


@pytest.mark.asyncio
async def test_target_http_operation_rejects_unrelated_destination() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(204, request=request)
        )
    )
    plan = HttpRequestPlanV1(
        operation_id=uuid4(),
        method="GET",
        path="https://evil.example/x",
        request=HttpRequestSpec(codec="none"),
        response=HttpResponseSpec(codec="none"),
        timeout_seconds=5,
    )
    try:
        with pytest.raises((ExecutionError, ValueError), match="relative|invalid"):
            await HttpExecutionHandler(client).execute(plan, material())
    finally:
        await client.aclose()
