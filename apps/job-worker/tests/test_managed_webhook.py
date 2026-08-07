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


def resolver(
    tmp_path: Path,
    *,
    url: str = "https://example.test/hook",
    allowed_hosts: list[str] | None = None,
) -> ManagedWebhookConnectionResolver:
    (tmp_path / "url").write_text(url, encoding="utf-8")
    (tmp_path / "key").write_text("secret", encoding="utf-8")
    return ManagedWebhookConnectionResolver(
        json.dumps(
            {
                "tenant-hook": {
                    "url_file": str(tmp_path / "url"),
                    "api_key_file": str(tmp_path / "key"),
                    "api_key_header": "x-make-apikey",
                    "allowed_hosts": (
                        ["example.test"] if allowed_hosts is None else allowed_hosts
                    ),
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
    envelope = json.loads(requests[0].content)
    assert envelope == {
        "contract_version": 1,
        "operation_id": str(OPERATION_ID),
        "capability": {
            "semantic_key": "reservation.submit_request",
            "semantic_version": 1,
        },
        "payload": {"guest_name": "Alice"},
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
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "contract_version": 1,
                "operation_id": str(OPERATION_ID),
                "status": "succeeded",
                "result": {"deduplicated": True, "data": {}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await ManagedWebhookPostJsonHandler(
            resolver(
                tmp_path,
                url="https://EXAMPLE.TEST./hook",
                allowed_hosts=["example.test."],
            ),
            client,
        ).execute(webhook_plan())
        assert result.deduplicated is True
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
async def test_webhook_does_not_follow_redirects_or_accept_invalid_2xx_response(
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
                webhook_plan()
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


def test_webhook_resolver_rejects_empty_hosts_and_symlink_escape(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="string list"):
        resolver(tmp_path, allowed_hosts=[])
    connection = resolver(tmp_path)
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("https://example.test/hook", encoding="utf-8")
    (tmp_path / "url").unlink()
    (tmp_path / "url").symlink_to(outside)
    with pytest.raises(ExecutionError, match="credentials could not be loaded"):
        connection.resolve("tenant-hook")
