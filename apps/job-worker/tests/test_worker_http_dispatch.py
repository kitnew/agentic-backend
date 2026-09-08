from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from contracts import (
    HttpRequestResult,
    IntegrationExecutionMaterial,
    IntegrationJob,
)
from job_worker.worker import (
    CapabilityWorker,
    HttpExecutionHandler,
    Settings,
)


class Redis:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def xack(self, _stream: str, _group: str, message_id: str) -> None:
        self.acked.append(message_id)


class Backend:
    def __init__(self, material: IntegrationExecutionMaterial) -> None:
        self.material = material
        self.material_job: IntegrationJob | None = None
        self.reported = None

    async def integration_material(
        self, _invocation_id, _job_id, job: IntegrationJob
    ) -> IntegrationExecutionMaterial:
        self.material_job = job
        return self.material

    async def report(self, report) -> None:
        self.reported = report


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
async def test_http_request_plan_dispatches_to_http_and_reports_generic_result() -> (
    None
):
    execution_id = uuid4()
    seen: dict[str, object] = {}

    async def send(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"accepted": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    redis = Redis()
    backend = Backend(
        IntegrationExecutionMaterial(
            integration_kind="http",
            config={
                "endpoint": "https://api.example.com/v1",
                "headers": {},
                "authentication": {"type": "none"},
                "security": {"additional_allowed_hosts": []},
            },
        )
    )
    now = datetime.now(UTC)
    job = IntegrationJob(
        job_id=uuid4(),
        capability_invocation_id=uuid4(),
        call_id=uuid4(),
        execution_id=execution_id,
        worker_context={
            "execution_id": str(execution_id),
            "tenant_id": "tenant-a",
            "action": {
                "key": "reservation.check_availability",
                "phase": "runtime",
                "definition": {
                    "agent_input_schema": {
                        "type": "object",
                        "properties": {"room_count": {"type": "integer"}},
                        "required": ["room_count"],
                        "additionalProperties": False,
                    },
                    "bindings": {},
                    "input_constraints": [],
                    "business_policy": {},
                    "result_schema": {
                        "type": "object",
                        "properties": {"accepted": {"type": "boolean"}},
                        "required": ["accepted"],
                    },
                },
                "execution_plan": {
                    "method": "PATCH",
                    "path": "/reservations",
                    "headers": {},
                    "request": {
                        "codec": "json",
                        "mapping": {"room_count": {"$expr": "inputs.room_count"}},
                    },
                    "response": {"codec": "json"},
                    "timeout_seconds": 5,
                },
                "integration": {"semantic_key": "reservation-api"},
            },
            "integration": {"semantic_key": "reservation-api"},
        },
        tool_args={"room_count": 1},
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    worker = CapabilityWorker(
        settings(),
        redis,
        backend,
        HttpExecutionHandler(client),
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
    assert backend.material_job.execution_id == execution_id
    assert "execution_plan" not in backend.material_job.model_fields_set
    assert isinstance(backend.reported.result, HttpRequestResult)
    assert backend.reported.result.result_type == "http.request.v1"
    assert backend.reported.result.data == {"accepted": True}
    assert redis.acked == ["1-0"]
