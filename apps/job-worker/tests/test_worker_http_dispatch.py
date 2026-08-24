from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from contracts import (
    HttpRequestPlanV1,
    HttpRequestResult,
    HttpRequestSpec,
    HttpResponseSpec,
    IntegrationJob,
    RuntimeIntegrationMaterial,
)
from job_worker.worker import (
    CapabilityWorker,
    ManagedWebhookPostJsonHandler,
    Settings,
)


class Redis:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def xack(self, _stream: str, _group: str, message_id: str) -> None:
        self.acked.append(message_id)


class Backend:
    def __init__(self, material: RuntimeIntegrationMaterial) -> None:
        self.material = material
        self.material_job: IntegrationJob | None = None
        self.reported = None

    async def integration_material(
        self, _invocation_id, _job_id, job: IntegrationJob
    ) -> RuntimeIntegrationMaterial:
        self.material_job = job
        return self.material

    async def report(self, report) -> None:
        self.reported = report


class Sheets:
    async def execute(self, *_args) -> None:
        raise AssertionError("generic HTTP dispatch must not use Sheets")


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
    )


@pytest.mark.asyncio
async def test_http_request_plan_dispatches_to_http_and_reports_generic_result() -> None:
    integration_id = uuid4()
    operation_id = uuid4()
    seen: dict[str, object] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"accepted": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    redis = Redis()
    backend = Backend(
        RuntimeIntegrationMaterial(
            integration_id=integration_id,
            kind="http",
            provider="http",
            endpoint="https://api.example.com/v1",
            allowed_hosts=["api.example.com"],
            connection_revision=2,
            credential_version=1,
        )
    )
    plan = HttpRequestPlanV1(
        integration_id=integration_id,
        operation_id=operation_id,
        capability={"semantic_key": "reservation.check_availability", "semantic_version": 1},
        method="PATCH",
        path="/reservations",
        request=HttpRequestSpec(codec="json"),
        response=HttpResponseSpec(codec="json"),
        payload={"room_count": 1},
        timeout_seconds=5,
    )
    now = datetime.now(UTC)
    job = IntegrationJob(
        job_id=uuid4(),
        capability_invocation_id=uuid4(),
        call_id=uuid4(),
        tenant_release_id=uuid4(),
        runtime_bundle_id=uuid4(),
        execution_plan=plan,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    worker = CapabilityWorker(
        settings(),
        redis,
        backend,
        Sheets(),
        ManagedWebhookPostJsonHandler(client),
    )

    try:
        await worker._handle("1-0", {"job": job.model_dump_json()})
    finally:
        await client.aclose()

    assert seen == {
        "method": "PATCH",
        "url": "https://api.example.com/v1/reservations",
    }
    assert backend.material_job is not None
    assert backend.material_job.execution_plan.plan_type == "http.request.v1"
    assert isinstance(backend.reported.result, HttpRequestResult)
    assert backend.reported.result.result_type == "http.request.v1"
    assert backend.reported.result.data == {"accepted": True}
    assert redis.acked == ["1-0"]
