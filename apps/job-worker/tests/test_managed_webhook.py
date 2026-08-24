import json
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
import pytest
from contracts import (
    ManagedWebhookBodyBinding,
    ManagedWebhookCapability,
    ManagedWebhookPostJsonPlan,
    ManagedWebhookResponseConfig,
    RuntimeIntegrationMaterial,
)
from job_worker.worker import (
    ExecutionError,
)
from job_worker.worker import (
    ManagedWebhookPostJsonHandler as WorkerManagedWebhookPostJsonHandler,
)

OPERATION_ID = UUID("00000000-0000-0000-0000-000000000001")


def webhook_plan(
    *,
    response_contract: Literal["http_2xx", "managed_webhook_envelope.v1"] = "http_2xx",
    response: ManagedWebhookResponseConfig | None = None,
) -> ManagedWebhookPostJsonPlan:
    return ManagedWebhookPostJsonPlan(
        plan_type="managed_webhook.post_json.v1",
        integration_id=UUID("00000000-0000-0000-0000-000000000003"),
        operation_id=OPERATION_ID,
        capability=ManagedWebhookCapability(
            semantic_key="reservation.submit_request", semantic_version=1
        ),
        payload={"guest_name": "Alice"},
        response_contract=response_contract,
        response=response,
        timeout_seconds=10,
    )


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {
        "status": {"type": "string"},
        "request_id": {"type": "string"},
        "message": {"type": "string"},
    },
}


def resolver(
    _tmp_path: object,
    *,
    url: str = "https://example.test/hook",
    allowed_hosts: list[str] | None = None,
) -> RuntimeIntegrationMaterial:
    return RuntimeIntegrationMaterial(
        integration_id=webhook_plan().integration_id,
        kind="http",
        provider="http",
        endpoint=url,
        authentication_header="x-make-apikey",
        allowed_hosts=["example.test"] if allowed_hosts is None else allowed_hosts,
        secret={"api_key": "secret"},
        credential_version=1,
    )


class ManagedWebhookPostJsonHandler:
    """Keeps provider-behaviour tests focused on already-scoped runtime material."""

    def __init__(
        self, material: RuntimeIntegrationMaterial, client: httpx.AsyncClient
    ) -> None:
        self._material = material
        self._handler = WorkerManagedWebhookPostJsonHandler(client)

    async def execute(
        self,
        plan: ManagedWebhookPostJsonPlan,
        bodies: dict[str, object] | None = None,
    ):
        return await self._handler.execute(plan, self._material, bodies)


@pytest.mark.asyncio
async def test_managed_webhook_posts_mapping_as_root_body_without_internal_metadata(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(tmp_path), client
        ).execute(webhook_plan())
    assert result.reference is None
    assert requests[0].headers["x-make-apikey"] == "secret"
    assert requests[0].headers["content-type"] == "application/json"
    assert requests[0].headers["x-operation-id"] == str(OPERATION_ID)
    assert json.loads(requests[0].content) == {"guest_name": "Alice"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 204])
async def test_status_only_response_returns_configured_semantic_result(
    tmp_path: Path, status_code: int
) -> None:
    plan = webhook_plan(
        response=ManagedWebhookResponseConfig(
            mode="status_only",
            success_output={"status": "submitted"},
            output_schema=OUTPUT_SCHEMA,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, content=b"ignored")
        )
    ) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(tmp_path), client
        ).execute(plan)

    assert result.data == {"status": "submitted"}


@pytest.mark.asyncio
async def test_plain_text_response_is_mapped_without_exposing_provider_data(
    tmp_path: Path,
) -> None:
    plan = webhook_plan(
        response=ManagedWebhookResponseConfig(
            mode="text",
            mapping='{"status": "created", "message": response.body}',
            output_schema=OUTPUT_SCHEMA,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="Reservation request 1842 created",
                headers={"content-type": "text/plain", "x-provider-secret": "hidden"},
            )
        )
    ) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(tmp_path), client
        ).execute(plan)

    assert result.data == {
        "status": "created",
        "message": "Reservation request 1842 created",
    }
    assert "hidden" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_json_response_is_mapped_and_validated(tmp_path: Path) -> None:
    plan = webhook_plan(
        response=ManagedWebhookResponseConfig(
            mode="json",
            mapping=(
                '{"status": response.status_code = 200 and response.body.success '
                '? "created" : "failed", '
                '"request_id": response.body.reservation_request_id, '
                '"message": response.content_type}'
            ),
            output_schema=OUTPUT_SCHEMA,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"success": True, "reservation_request_id": "REQ-1842"},
            )
        )
    ) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(tmp_path), client
        ).execute(plan)

    assert result.data == {
        "status": "created",
        "request_id": "REQ-1842",
        "message": "application/json",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "content_type", "body"),
    [
        ("json", "application/json", b"not-json"),
        ("json", "text/plain", b"{}"),
        ("text", "application/json", b'"text"'),
    ],
)
async def test_configured_response_rejects_malformed_or_unexpected_content(
    tmp_path: Path, mode: Literal["text", "json"], content_type: str, body: bytes
) -> None:
    plan = webhook_plan(
        response=ManagedWebhookResponseConfig(
            mode=mode,
            mapping='{"status": "created"}',
            output_schema=OUTPUT_SCHEMA,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=body, headers={"content-type": content_type}
            )
        )
    ) as client:
        with pytest.raises(ExecutionError) as raised:
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                plan
            )
    assert raised.value.code == "response_contract_invalid"


@pytest.mark.asyncio
async def test_mapped_response_must_match_output_schema(tmp_path: Path) -> None:
    plan = webhook_plan(
        response=ManagedWebhookResponseConfig(
            mode="json",
            mapping='{"unexpected": true}',
            output_schema=OUTPUT_SCHEMA,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as client:
        with pytest.raises(ExecutionError) as raised:
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                plan
            )
    assert raised.value.code == "response_output_invalid"


@pytest.mark.asyncio
async def test_managed_webhook_rejects_oversized_response_while_streaming(
    tmp_path: Path,
) -> None:
    plan = webhook_plan(
        response=ManagedWebhookResponseConfig(
            mode="text",
            mapping='{"status": "created", "message": response.body}',
            output_schema=OUTPUT_SCHEMA,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * 64_001,
                headers={"content-type": "text/plain"},
            )
        )
    ) as client:
        with pytest.raises(ExecutionError) as raised:
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                plan
            )
    assert raised.value.code == "response_too_large"


@pytest.mark.asyncio
async def test_managed_webhook_streams_generic_artifact_body_binding(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def body():
        yield b"YXV"
        yield b"kaW8="

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    plan = webhook_plan().model_copy(
        update={
            "payload": {"recording": None, "kind": "completed"},
            "body_bindings": [
                ManagedWebhookBodyBinding(
                    representation_id=UUID("00000000-0000-0000-0000-000000000099"),
                    payload_path="/recording",
                )
            ],
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
            plan, {"/recording": body()}
        )

    assert json.loads(requests[0].content) == {
        "recording": "YXVkaW8=",
        "kind": "completed",
    }


@pytest.mark.asyncio
async def test_managed_webhook_rejects_operation_id_mismatch(tmp_path: Path) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "contract_version": 1,
                "operation_id": str(UUID("00000000-0000-0000-0000-000000000002")),
                "status": "succeeded",
                "result": {"reference": None, "deduplicated": False, "data": {}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ExecutionError, match="operation ID mismatch"):
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                webhook_plan(response_contract="managed_webhook_envelope.v1")
            )


@pytest.mark.asyncio
async def test_managed_webhook_can_omit_api_key(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    material = resolver(tmp_path).model_copy(
        update={"secret": {"url": "https://example.test/hook"}}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        await ManagedWebhookPostJsonHandler(material, client).execute(webhook_plan())

    assert "x-api-key" not in requests[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body", "transient"),
    [
        (408, "timeout", True),
        (429, "rate limited", True),
        (503, "<html>down</html>", True),
        (400, "bad request", False),
        (409, "conflict", False),
    ],
)
async def test_http_status_is_classified_before_success_contract_validation(
    tmp_path: Path, status_code: int, body: str, transient: bool
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, text=body)
        )
    ) as client:
        with pytest.raises(ExecutionError) as raised:
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                webhook_plan()
            )
    assert raised.value.transient is transient


@pytest.mark.asyncio
async def test_webhook_requires_exact_allowlisted_hostname(tmp_path: Path) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        with pytest.raises(ExecutionError, match="destination is not allowed"):
            await ManagedWebhookPostJsonHandler(
                resolver(
                    tmp_path,
                    url="https://public.example/hook",
                    allowed_hosts=["example.test"],
                ),
                client,
            ).execute(webhook_plan())


@pytest.mark.asyncio
async def test_webhook_normalizes_allowlisted_hostname_and_rejects_literal_ip(
    tmp_path: Path,
) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(
                tmp_path,
                url="https://EXAMPLE.TEST./hook",
                allowed_hosts=["example.test."],
            ),
            client,
        ).execute(webhook_plan())
        assert result.deduplicated is False
        with pytest.raises(ExecutionError, match="destination is not allowed"):
            await ManagedWebhookPostJsonHandler(
                resolver(
                    tmp_path,
                    url="https://127.0.0.1/hook",
                    allowed_hosts=["127.0.0.1"],
                ),
                client,
            ).execute(webhook_plan())


@pytest.mark.asyncio
async def test_webhook_does_not_follow_redirects_and_strict_contract_is_opt_in(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(ExecutionError, match="unsupported status"):
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                webhook_plan()
            )
    assert len(requests) == 1

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="no"))
    ) as client:
        with pytest.raises(ExecutionError, match="must be JSON"):
            await ManagedWebhookPostJsonHandler(resolver(tmp_path), client).execute(
                webhook_plan(response_contract="managed_webhook_envelope.v1")
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/hook",
        "https://user@example.test/hook",
        "https://example.test/hook#fragment",
        "https://example.test:444/hook",
    ],
)
async def test_webhook_rejects_unsafe_url_components(tmp_path: Path, url: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        with pytest.raises(ExecutionError):
            await ManagedWebhookPostJsonHandler(
                resolver(tmp_path, url=url), client
            ).execute(webhook_plan())
