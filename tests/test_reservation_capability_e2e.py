from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from contracts import (
    IntegrationExecutionMaterial,
    IntegrationJob,
    WorkerExecutionContext,
)
from job_worker.worker import HttpExecutionHandler, _target_http_plan


def job(tenant_id: str, guest_name: str) -> IntegrationJob:
    execution_id = uuid4()
    return IntegrationJob(
        job_id=uuid4(),
        capability_invocation_id=uuid4(),
        execution_id=execution_id,
        worker_context=WorkerExecutionContext(
            execution_id=execution_id,
            tenant_id=tenant_id,
            action={
                "key": "reservation.submit_request",
                "phase": "runtime",
                "definition": {
                    "agent_input_schema": {
                        "type": "object",
                        "properties": {"guest_name": {"type": "string"}},
                        "required": ["guest_name"],
                        "additionalProperties": False,
                    },
                    "bindings": {"guest_name": "guest.name"},
                    "input_constraints": [],
                    "business_policy": {},
                    "result_schema": {
                        "type": "object",
                        "properties": {"accepted": {"type": "boolean"}},
                        "required": ["accepted"],
                    },
                },
                "execution_plan": {
                    "method": "POST",
                    "path": "reservations",
                    "request": {
                        "codec": "json",
                        "mapping": {"guest": {"$expr": "business.guest.name"}},
                    },
                    "response": {"codec": "json"},
                    "timeout_seconds": 5,
                },
                "integration": {"semantic_key": "reservation-api"},
            },
            integration={"semantic_key": "reservation-api"},
        ),
        tool_args={"guest_name": guest_name},
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_two_tenants_execute_only_their_frozen_worker_context() -> None:
    seen: list[tuple[str, object]] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.content))
        return httpx.Response(200, json={"accepted": True}, request=request)

    tenant_a = job("tenant-a", "Alice")
    tenant_b = job("tenant-b", "Bob")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        handler = HttpExecutionHandler(client)
        for value in (tenant_a, tenant_b):
            context = value.worker_context
            plan = _target_http_plan(value, context)
            result = await handler.execute(
                plan,
                IntegrationExecutionMaterial(
                    integration_kind="http",
                    config={
                        "endpoint": f"https://api.example/{context.tenant_id}",
                        "headers": {},
                        "authentication": {"type": "none"},
                        "security": {"additional_allowed_hosts": []},
                    },
                ),
            )
            handler._validate_output(plan.result_schema or {}, result.data)

    assert seen == [
        ("https://api.example/tenant-a/reservations", b'{"guest":"Alice"}'),
        ("https://api.example/tenant-b/reservations", b'{"guest":"Bob"}'),
    ]
