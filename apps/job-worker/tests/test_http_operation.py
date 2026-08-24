import json
from base64 import b64encode
from uuid import uuid4

import httpx
import pytest
from contracts import (
    HttpBodyBinding,
    HttpOperation,
    HttpRequestPlanV1,
    HttpRequestSpec,
    HttpResponseSpec,
    RuntimeIntegrationMaterial,
)
from job_worker.worker import ExecutionError, ManagedWebhookPostJsonHandler


@pytest.mark.asyncio
async def test_generic_http_operation_uses_method_path_query_and_response_mapping() -> None:
    integration_id, operation_id = uuid4(), uuid4()
    seen: dict[str, object] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, url=str(request.url), headers=request.headers)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        result = await ManagedWebhookPostJsonHandler(client).execute(
            HttpRequestPlanV1(
                integration_id=integration_id,
                operation_id=operation_id,
                method="PATCH",
                path="/v1/check",
                query={"q": "a b"},
                request=HttpRequestSpec(codec="json"),
                response=HttpResponseSpec(codec="json", mapping={"ok": {"$expr": "response.body.ok"}}),
                payload={"value": 1},
                timeout_seconds=5,
            ),
            RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://api.example.com",
                allowed_hosts=["api.example.com"],
                connection_revision=2,
                credential_version=1,
            ),
        )
    finally:
        await client.aclose()

    assert result.data == {"ok": True}
    assert seen["method"] == "PATCH"
    assert seen["url"] == "https://api.example.com/v1/check?q=a+b"


@pytest.mark.asyncio
async def test_generic_http_operation_streams_nested_and_multiple_artifact_values() -> None:
    integration_id = uuid4()
    seen: dict[str, object] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = await request.aread()
        return httpx.Response(204, request=request)

    async def stream(*chunks: bytes):
        for chunk in chunks:
            yield chunk

    plan = HttpRequestPlanV1(
        integration_id=integration_id,
        operation_id=uuid4(),
        method="PUT",
        query={"source": "post-call"},
        headers={"X-Action": "recording"},
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(codec="none"),
        payload={
            "ok": True,
            "data": {"recording": None},
            "items": [{"content": None}],
            "second": None,
        },
        body_bindings=[
            HttpBodyBinding(representation_id=uuid4(), payload_path="/data/recording"),
            HttpBodyBinding(representation_id=uuid4(), payload_path="/items/0/content"),
            HttpBodyBinding(representation_id=uuid4(), payload_path="/second"),
        ],
        timeout_seconds=5,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        await ManagedWebhookPostJsonHandler(client).execute(
            plan,
            RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://api.example.com/v1",
                static_headers={"Accept": "application/json"},
                allowed_hosts=["api.example.com"],
                secret={"api_key": "secret"},
                authentication_header="X-API-Key",
                connection_revision=2,
                credential_version=1,
            ),
            {
                "/data/recording": stream(b"YW", b"Jj"),
                "/items/0/content": stream(b"c2Vj"),
                "/second": stream(b"bG9uZw=="),
            },
        )
    finally:
        await client.aclose()

    assert seen["method"] == "PUT"
    assert seen["url"] == "https://api.example.com/v1?source=post-call"
    assert seen["body"] == (
        b'{"ok":true,"data":{"recording":"YWJj"},'
        b'"items":[{"content":"c2Vj"}],"second":"bG9uZw=="}'
    )


@pytest.mark.asyncio
async def test_generic_http_structured_request_enforces_size_limit() -> None:
    integration_id = uuid4()
    called = False

    async def send(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(204, request=request)

    plan = HttpRequestPlanV1(
        integration_id=integration_id,
        operation_id=uuid4(),
        method="POST",
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(codec="none"),
        payload={"value": "x" * 64_000},
        timeout_seconds=5,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        with pytest.raises(ExecutionError, match="HTTP structured payload is too large"):
            await ManagedWebhookPostJsonHandler(client).execute(
                plan,
                RuntimeIntegrationMaterial(
                    integration_id=integration_id,
                    kind="http",
                    provider="http",
                    endpoint="https://api.example.com",
                    allowed_hosts=["api.example.com"],
                    connection_revision=1,
                ),
            )
    finally:
        await client.aclose()

    assert called is False


@pytest.mark.asyncio
async def test_generic_http_artifact_stream_can_exceed_structured_limit() -> None:
    integration_id = uuid4()
    raw = b"abc" * 20_000
    encoded = b64encode(raw)
    seen: dict[str, bytes] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen["body"] = await request.aread()
        return httpx.Response(204, request=request)

    async def body():
        for offset in range(0, len(encoded), 4096):
            yield encoded[offset : offset + 4096]

    plan = HttpRequestPlanV1(
        integration_id=integration_id,
        operation_id=uuid4(),
        method="POST",
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(codec="none"),
        payload={"recording": None},
        body_bindings=[HttpBodyBinding(representation_id=uuid4(), payload_path="/recording")],
        timeout_seconds=5,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        await ManagedWebhookPostJsonHandler(client).execute(
            plan,
            RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://api.example.com",
                allowed_hosts=["api.example.com"],
                connection_revision=1,
            ),
            {"/recording": body()},
        )
    finally:
        await client.aclose()

    assert len(seen["body"]) > 64_000
    assert json.loads(seen["body"])["recording"] == encoded.decode()


@pytest.mark.asyncio
async def test_generic_http_stream_retry_uses_a_new_body_stream() -> None:
    integration_id = uuid4()
    attempts = 0
    streams = 0

    async def send(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        await request.aread()
        if attempts == 1:
            raise httpx.TransportError("connection reset")
        return httpx.Response(204, request=request)

    def new_body():
        nonlocal streams
        streams += 1

        async def body():
            yield b"x" * 64_001

        return body()

    plan = HttpRequestPlanV1(
        integration_id=integration_id,
        operation_id=uuid4(),
        method="POST",
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(codec="none"),
        payload={"recording": None},
        body_bindings=[HttpBodyBinding(representation_id=uuid4(), payload_path="/recording")],
        timeout_seconds=5,
    )
    material = RuntimeIntegrationMaterial(
        integration_id=integration_id,
        kind="http",
        provider="http",
        endpoint="https://api.example.com",
        allowed_hosts=["api.example.com"],
        connection_revision=1,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        with pytest.raises(ExecutionError, match="HTTP transport failed"):
            await ManagedWebhookPostJsonHandler(client).execute(
                plan, material, {"/recording": new_body()}
            )
        await ManagedWebhookPostJsonHandler(client).execute(
            plan, material, {"/recording": new_body()}
        )
    finally:
        await client.aclose()

    assert attempts == 2
    assert streams == 2


@pytest.mark.asyncio
async def test_generic_http_artifact_bindings_require_json_request() -> None:
    integration_id = uuid4()
    plan = HttpRequestPlanV1(
        integration_id=integration_id,
        operation_id=uuid4(),
        method="POST",
        request=HttpRequestSpec(codec="none"),
        response=HttpResponseSpec(codec="none"),
        body_bindings=[HttpBodyBinding(representation_id=uuid4(), payload_path="/recording")],
        timeout_seconds=5,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(204, request=request)))
    try:
        with pytest.raises(ExecutionError, match="require a JSON request"):
            await ManagedWebhookPostJsonHandler(client).execute(
                plan,
                RuntimeIntegrationMaterial(
                    integration_id=integration_id,
                    kind="http",
                    provider="http",
                    endpoint="https://api.example.com",
                    allowed_hosts=["api.example.com"],
                    connection_revision=1,
                ),
            )
    finally:
        await client.aclose()


def test_http_operation_path_preserves_base_path_and_rejects_foreign_origins() -> None:
    assert ManagedWebhookPostJsonHandler._operation_url(
        "https://api.example.com/v1", "/reservations"
    ) == "https://api.example.com/v1/reservations"
    for path in ("https://evil.example/x", "//evil.example/x", "/x#fragment"):
        with pytest.raises(Exception, match="relative|invalid"):
            ManagedWebhookPostJsonHandler._operation_url("https://api.example.com/v1", path)
    with pytest.raises(ValueError, match="relative"):
        HttpOperation(connection="x", method="GET", path="https://evil.example", timeout_seconds=5)


@pytest.mark.asyncio
async def test_http_operation_system_and_auth_headers_win_case_insensitively() -> None:
    integration_id, operation_id = uuid4(), uuid4()
    seen: dict[str, str] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen.update({key.lower(): value for key, value in request.headers.items()})
        return httpx.Response(200, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        await ManagedWebhookPostJsonHandler(client).execute(
            HttpRequestPlanV1(
                integration_id=integration_id,
                operation_id=operation_id,
                method="POST",
                headers={"content-type": "text/plain", "x-operation-id": "spoof", "x-api-key": "spoof"},
                request=HttpRequestSpec(codec="json"),
                response=HttpResponseSpec(codec="none"),
                payload={"ok": True},
                timeout_seconds=5,
            ),
            RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://api.example.com",
                static_headers={"CONTENT-TYPE": "text/plain", "X-Operation-Id": "spoof", "X-API-Key": "spoof"},
                authentication_header="X-API-Key",
                allowed_hosts=["api.example.com"],
                secret={"api_key": "real-secret"},
                connection_revision=2,
                credential_version=1,
            ),
        )
    finally:
        await client.aclose()

    assert seen["content-type"] == "application/json"
    assert seen["x-operation-id"] == str(operation_id)
    assert seen["x-api-key"] == "real-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "codec", "body", "content_type", "expected"),
    [(200, "none", b"Accepted", None, None), (204, "none", b"", None, None), (200, "text", b"available", None, "available"), (200, "json", b'{"ok":true}', None, {"ok": True})],
)
async def test_http_response_codec_does_not_require_response_content_type(
    status: int, codec: str, body: bytes, content_type: str | None, expected: object
) -> None:
    integration_id = uuid4()

    async def send(request: httpx.Request) -> httpx.Response:
        headers = {} if content_type is None else {"Content-Type": content_type}
        return httpx.Response(status, content=body, headers=headers, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        result = await ManagedWebhookPostJsonHandler(client).execute(
            HttpRequestPlanV1(
                integration_id=integration_id,
                operation_id=uuid4(),
                method="GET",
                request=HttpRequestSpec(codec="none"),
                response=HttpResponseSpec(codec=codec),
                timeout_seconds=5,
            ),
            RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://api.example.com",
                allowed_hosts=["api.example.com"],
                connection_revision=1,
                credential_version=1,
            ),
        )
    finally:
        await client.aclose()

    assert result.data == expected


@pytest.mark.asyncio
async def test_none_response_codec_keeps_status_available_to_mapping() -> None:
    integration_id = uuid4()

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"Accepted", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        result = await ManagedWebhookPostJsonHandler(client).execute(
            HttpRequestPlanV1(
                integration_id=integration_id,
                operation_id=uuid4(),
                method="GET",
                request=HttpRequestSpec(codec="none"),
                response=HttpResponseSpec(codec="none", mapping={"accepted": {"$expr": "response.status_code = 200"}}),
                timeout_seconds=5,
            ),
            RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://api.example.com",
                allowed_hosts=["api.example.com"],
                connection_revision=1,
                credential_version=1,
            ),
        )
    finally:
        await client.aclose()

    assert result.data == {"accepted": True}
