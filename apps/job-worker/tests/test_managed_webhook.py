import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from contracts import ManagedWebhookCapability, ManagedWebhookPostJsonPlan
from job_worker.worker import (
    ExecutionError,
    ManagedWebhookConnectionResolver,
    ManagedWebhookPostJsonHandler,
)

OPERATION_ID = UUID("00000000-0000-0000-0000-000000000001")


def webhook_plan() -> ManagedWebhookPostJsonPlan:
    return ManagedWebhookPostJsonPlan(
        plan_type="managed_webhook.post_json.v1",
        connection_ref="tenant-hook",
        operation_id=OPERATION_ID,
        capability=ManagedWebhookCapability(
            semantic_key="reservation.submit_request", semantic_version=1
        ),
        payload={"guest_name": "Alice"},
        timeout_seconds=10,
    )


def resolver(tmp_path: Path) -> ManagedWebhookConnectionResolver:
    (tmp_path / "url").write_text("https://example.test/hook", encoding="utf-8")
    (tmp_path / "key").write_text("secret", encoding="utf-8")
    return ManagedWebhookConnectionResolver(
        json.dumps(
            {
                "tenant-hook": {
                    "url_file": str(tmp_path / "url"),
                    "api_key_file": str(tmp_path / "key"),
                    "api_key_header": "x-make-apikey",
                    "allowed_hosts": ["example.test"],
                }
            }
        ),
        str(tmp_path),
    )


@pytest.mark.asyncio
async def test_managed_webhook_posts_generic_envelope_without_logging_payload(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "contract_version": 1,
                "operation_id": str(OPERATION_ID),
                "status": "succeeded",
                "result": {
                    "reference": "accepted-1",
                    "deduplicated": False,
                    "data": {},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(tmp_path), client
        ).execute(webhook_plan())
    assert result.reference == "accepted-1"
    assert requests[0].headers["x-make-apikey"] == "secret"
    assert requests[0].headers["content-type"] == "application/json"
    assert json.loads(requests[0].content)["operation_id"] == str(OPERATION_ID)


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
                webhook_plan()
            )


def test_managed_webhook_secret_paths_are_allowlisted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="under secrets directory"):
        ManagedWebhookConnectionResolver(
            json.dumps(
                {
                    "tenant-hook": {
                        "url_file": "/etc/passwd",
                        "api_key_file": str(tmp_path / "key"),
                        "allowed_hosts": ["example.test"],
                    }
                }
            ),
            str(tmp_path),
        )
