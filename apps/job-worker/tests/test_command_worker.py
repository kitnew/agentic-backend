from uuid import UUID, uuid4

import httpx
import pytest
from contracts import (
    ExecutePostCallAction,
    GenerateCallSummary,
    HttpRequestPlanV1,
    HttpRequestResult,
    HttpRequestSpec,
    HttpResponseSpec,
    ManagedWebhookBodyBinding,
    ManagedWebhookCapability,
    ManagedWebhookPostJsonPlan,
    ManagedWebhookPostJsonResult,
    MaterializeArtifactRepresentation,
    RuntimeIntegrationMaterial,
    command_envelope,
)
from job_worker.command_worker import (
    CommandWorker,
    ExecutePostCallActionHandler,
    MaterializeArtifactRepresentationHandler,
    azure_endpoint,
)
from job_worker.worker import (
    MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES,
    BackendClient,
    ExecutionError,
    ManagedWebhookPostJsonHandler,
    RecordingStorage,
    Settings,
)


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://resource.openai.azure.com", "https://resource.openai.azure.com"),
        (
            "https://resource.openai.azure.com/openai/v1/",
            "https://resource.openai.azure.com",
        ),
    ],
)
def test_azure_endpoint_normalizes_openai_compatible_suffix(endpoint, expected):
    assert azure_endpoint(endpoint) == expected


@pytest.mark.asyncio
async def test_post_call_plan_client_parses_generic_http_plan() -> None:
    plan = HttpRequestPlanV1(
        integration_id=uuid4(),
        operation_id=uuid4(),
        method="POST",
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(codec="none"),
        payload={"ok": True},
        timeout_seconds=5,
    )

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=plan.model_dump(mode="json"), request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send), base_url="http://backend")
    try:
        result = await BackendClient(settings(), client).post_call_action(
            uuid4(), uuid4(), "notify", uuid4()
        )
    finally:
        await client.aclose()

    assert result == plan


class Redis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = {}
        self.values: dict[str, str] = {}
        self.acks: list[tuple[str, str, str]] = []

    async def xadd(self, stream, fields):
        self.streams.setdefault(stream, []).append(fields)
        return "1-0"

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.values[key] = value

    async def xack(self, stream, group, message_id):
        self.acks.append((stream, group, message_id))


def settings() -> Settings:
    return Settings(
        redis_url="redis://redis",
        stream="capability:jobs",
        group="capability-workers",
        consumer="worker-1",
        dead_letter_stream="capability:jobs:dead-letter",
        backend_url="http://backend",
        backend_audience="backend",
        service_secret="secret",
        max_retries=1,
    )


@pytest.mark.asyncio
async def test_recording_storage_streams_base64_without_buffering_whole_object() -> (
    None
):
    class Response:
        def __init__(self) -> None:
            self.chunks = [b"ab", b"cdef", b""]

        def read(self, size):
            return self.chunks.pop(0)

        def close(self):
            return None

        def release_conn(self):
            return None

    class Client:
        def get_object(self, bucket, key):
            assert (bucket, key) == ("call-recordings", "recordings/t/c/r.mp3")
            return Response()

    storage = RecordingStorage(settings())
    storage._client = Client()  # type: ignore[assignment]

    encoded = b"".join(
        [chunk async for chunk in storage.base64("recordings/t/c/r.mp3")]
    )

    assert encoded == b"YWJjZGVm"


@pytest.mark.asyncio
async def test_recording_storage_rejects_source_over_artifact_limit() -> None:
    class Response:
        def read(self, size):
            return b"x" * 4

        def close(self):
            return None

        def release_conn(self):
            return None

    class Client:
        def get_object(self, bucket, key):
            return Response()

    storage = RecordingStorage(settings())
    storage._client = Client()  # type: ignore[assignment]

    with pytest.raises(ExecutionError, match="Artifact source is too large"):
        async for _ in storage.base64("recordings/t/c/r.mp3", max_source_bytes=3):
            pass


@pytest.mark.asyncio
async def test_backend_client_rejects_declared_recording_source_before_download() -> None:
    downloaded = False

    class Storage:
        async def base64(self, storage_key, *, max_source_bytes):
            nonlocal downloaded
            downloaded = True
            yield b"unused"

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "storage_key": "recordings/t/c/r.mp3",
                "byte_size": MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES + 1,
            },
            request=request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(send), base_url="http://backend"
    )
    try:
        with pytest.raises(ExecutionError, match="Artifact source is too large"):
            async for _ in BackendClient(settings(), client, Storage()).representation_content(
                uuid4(), uuid4()
            ):
                pass
    finally:
        await client.aclose()

    assert downloaded is False


def message():
    call_id = uuid4()
    return command_envelope(
        GenerateCallSummary(call_id=call_id, finalization_id=uuid4()),
        tenant_id=uuid4(),
        correlation_id=call_id,
    )


@pytest.mark.asyncio
async def test_dispatches_by_type_publishes_result_and_deduplicates() -> None:
    redis = Redis()
    calls = 0

    async def handle(command, envelope):
        nonlocal calls
        calls += 1
        return {"summary": "done"}

    worker = CommandWorker(settings(), redis, {"call.generate_summary.v1": handle})
    envelope = message()
    fields = {"message": envelope.model_dump_json()}

    await worker.handle("1-0", fields)
    await worker.handle("2-0", fields)

    assert calls == 1
    assert len(redis.streams["application:command-results"]) == 2
    assert len(redis.acks) == 2


@pytest.mark.asyncio
async def test_transient_failure_retries_then_reports_and_dead_letters() -> None:
    redis = Redis()

    async def fail(command, envelope):
        raise ExecutionError("provider_timeout", "timed out", transient=True)

    worker = CommandWorker(settings(), redis, {"call.generate_summary.v1": fail})
    envelope = message()

    await worker.handle("1-0", {"message": envelope.model_dump_json()})
    retried = redis.streams["application:commands"][0]
    assert retried["attempt"] == "2"

    await worker.handle("2-0", retried)

    assert (
        redis.streams["application:commands:dead-letter"][0]["error_code"]
        == "provider_timeout"
    )
    assert len(redis.streams["application:command-results"]) == 1


@pytest.mark.asyncio
async def test_command_retry_result_and_dead_letter_keep_w3c_metadata_outside_payload() -> (
    None
):
    redis = Redis()

    async def fail(command, envelope):
        raise ExecutionError("provider_timeout", "timed out", transient=True)

    worker = CommandWorker(settings(), redis, {"call.generate_summary.v1": fail})
    envelope = message()
    encoded = envelope.model_dump_json()
    fields = {
        "message": encoded,
        "traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01",
        "tracestate": "vendor=value",
    }

    await worker.handle("1-0", fields)
    retried = redis.streams["application:commands"][0]
    await worker.handle("2-0", retried)

    assert envelope.model_dump_json() == encoded
    assert retried["traceparent"] == fields["traceparent"]
    assert retried["tracestate"] == fields["tracestate"]
    assert (
        redis.streams["application:command-results"][0]["traceparent"]
        == fields["traceparent"]
    )
    assert (
        redis.streams["application:commands:dead-letter"][0]["tracestate"]
        == fields["tracestate"]
    )


@pytest.mark.asyncio
async def test_post_call_action_stays_logical_and_uses_generic_webhook_handler() -> (
    None
):
    class Backend:
        integration_id = uuid4()

        async def post_call_action(
            self, call_id, finalization_id, action_id, command_id
        ):
            assert action_id == "notify"
            return HttpRequestPlanV1(
                integration_id=self.integration_id,
                operation_id=command_id,
                payload={"summary": "done"},
                method="POST",
                request=HttpRequestSpec(codec="json"),
                response=HttpResponseSpec(codec="none"),
                timeout_seconds=10,
            )

        async def post_call_action_material(self, *args):
            return RuntimeIntegrationMaterial(
                integration_id=self.integration_id,
                kind="http",
                provider="http",
                endpoint="https://example.test",
                allowed_hosts=["example.test"],
                secret={"api_key": "secret"},
                credential_version=1,
            )

    class Webhooks:
        async def execute(self, plan, material):
            assert material.integration_id == plan.integration_id
            return HttpRequestResult(
                result_type="http.request.v1",
                status="succeeded",
                operation_id=plan.operation_id,
                reference="accepted",
                deduplicated=False,
            )

    command = ExecutePostCallAction(
        call_id=uuid4(), finalization_id=uuid4(), action_id="notify"
    )
    envelope = command_envelope(
        command, tenant_id=uuid4(), correlation_id=command.call_id
    )

    output = await ExecutePostCallActionHandler(
        Backend(),
        Webhooks(),  # type: ignore[arg-type]
    )(command, envelope)

    assert output["reference"] == "accepted"
    assert "make" not in envelope.model_dump_json().lower()


@pytest.mark.asyncio
async def test_post_call_action_executes_generic_http_request() -> None:
    integration_id = uuid4()
    seen: dict[str, object] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, url=str(request.url), body=request.content)
        return httpx.Response(204, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))

    class Backend:
        async def post_call_action(self, *args):
            return HttpRequestPlanV1(
                integration_id=integration_id,
                operation_id=args[-1],
                method="POST",
                request=HttpRequestSpec(codec="json"),
                response=HttpResponseSpec(codec="none"),
                payload={"summary": "done"},
                timeout_seconds=5,
            )

        async def post_call_action_material(self, *args):
            return RuntimeIntegrationMaterial(
                integration_id=integration_id,
                kind="http",
                provider="http",
                endpoint="https://example.test/v1",
                static_headers={"X-Action": "post-call"},
                allowed_hosts=["example.test"],
            )

    command = ExecutePostCallAction(
        call_id=uuid4(), finalization_id=uuid4(), action_id="notify"
    )
    envelope = command_envelope(
        command, tenant_id=uuid4(), correlation_id=command.call_id
    )
    try:
        output = await ExecutePostCallActionHandler(
            Backend(), ManagedWebhookPostJsonHandler(client)
        )(command, envelope)
    finally:
        await client.aclose()

    assert output["reference"] is None
    assert seen == {
        "method": "POST",
        "url": "https://example.test/v1",
        "body": b'{"summary":"done"}',
    }


@pytest.mark.asyncio
async def test_post_call_action_retry_reuses_representation_binding() -> None:
    representation_id = uuid4()
    reads: list[UUID] = []
    delivered: list[bytes] = []

    class Backend:
        integration_id = uuid4()

        async def post_call_action(
            self, call_id, finalization_id, action_id, command_id
        ):
            return ManagedWebhookPostJsonPlan(
                plan_type="managed_webhook.post_json.v1",
                integration_id=self.integration_id,
                operation_id=command_id,
                capability=ManagedWebhookCapability(
                    semantic_key="post_call.notify", semantic_version=1
                ),
                payload={"recording": None},
                body_bindings=[
                    ManagedWebhookBodyBinding(
                        representation_id=representation_id,
                        payload_path="/recording",
                    )
                ],
                timeout_seconds=10,
            )

        async def post_call_action_material(self, *args):
            return RuntimeIntegrationMaterial(
                integration_id=self.integration_id,
                kind="http",
                provider="http",
                endpoint="https://example.test",
                allowed_hosts=["example.test"],
                secret={"api_key": "secret"},
                credential_version=1,
            )

        async def representation_content(self, requested_id, command_id):
            reads.append(requested_id)
            yield b"YXVkaW8="

    class Webhooks:
        async def execute(self, plan, material, bodies):
            assert material.integration_id == plan.integration_id
            delivered.append(b"".join([chunk async for chunk in bodies["/recording"]]))
            return ManagedWebhookPostJsonResult(
                result_type="managed_webhook.post_json.v1",
                status="succeeded",
                operation_id=plan.operation_id,
                reference="accepted",
                deduplicated=False,
            )

    command = ExecutePostCallAction(
        call_id=uuid4(), finalization_id=uuid4(), action_id="recording"
    )
    handler = ExecutePostCallActionHandler(  # type: ignore[arg-type]
        Backend(), Webhooks()
    )
    for _ in range(2):
        envelope = command_envelope(
            command, tenant_id=uuid4(), correlation_id=command.call_id
        )
        assert "YXVkaW8=" not in envelope.model_dump_json()
        await handler(command, envelope)

    assert reads == [representation_id, representation_id]
    assert delivered == [b"YXVkaW8=", b"YXVkaW8="]


@pytest.mark.asyncio
async def test_materialization_stores_base64_and_returns_metadata_only() -> None:
    class Backend:
        stored: bytes | None = None

        async def materialization_source(self, representation_id, command_id):
            return b"cmVjb3JkaW5n", "call_recording", "base64_text"

        async def store_representation(
            self, representation_id, command_id, content, content_type
        ):
            self.stored = content
            return {
                "representation_id": str(representation_id),
                "byte_size": len(content),
                "sha256": "digest",
            }

    backend = Backend()
    command = MaterializeArtifactRepresentation(
        call_id=uuid4(), finalization_id=uuid4(), representation_id=uuid4()
    )
    envelope = command_envelope(
        command, tenant_id=uuid4(), correlation_id=command.call_id
    )

    output = await MaterializeArtifactRepresentationHandler(  # type: ignore[arg-type]
        backend
    )(command, envelope)

    assert backend.stored == b"cmVjb3JkaW5n"
    assert "content" not in output
