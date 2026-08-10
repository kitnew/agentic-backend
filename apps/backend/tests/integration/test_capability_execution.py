import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.calls.models import CallSession
from backend_core.modules.calls.router import build_call_session_service
from backend_core.modules.capabilities.models import CapabilityInvocation, OutboxMessage
from backend_core.modules.capabilities.retention import CapabilityRetentionService
from backend_core.modules.conversations.models import Conversation
from backend_core.modules.integrations.models import IntegrationConnection
from backend_core.modules.tenants.models import (
    KnowledgeBase,
    KnowledgeBaseRevision,
    ProfilePrompt,
    ProfilePromptRevision,
    PromptSet,
    PromptSetRevision,
    SystemPrompt,
    SystemPromptRevision,
    Tenant,
    TenantConfigRevision,
    TenantPrompt,
    TenantPromptRevision,
)
from backend_core.platform.database import Database
from backend_core.platform.outbox import OutboxDispatcher
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from runtime_fixtures import apply_voice_runtime
from sqlalchemy import delete, func, select


def agent_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "guest_name": {
                "type": "string",
                "minLength": 1,
                "x-canonical-field": "guest.name",
            },
            "check_in": {
                "type": "string",
                "format": "date",
                "x-canonical-field": "stay.check_in",
            },
            "check_out": {
                "type": "string",
                "format": "date",
                "x-canonical-field": "stay.check_out",
            },
        },
        "required": ["guest_name", "check_in", "check_out"],
        "additionalProperties": False,
    }


class FakeRedis:
    def __init__(self, *, raise_after_publish: bool = False) -> None:
        self.jobs: list[tuple[str, dict[str, str]]] = []
        self.raise_after_publish = raise_after_publish

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.jobs.append((stream, fields))
        if self.raise_after_publish:
            self.raise_after_publish = False
            raise RedisError("connection lost after publish")
        return "1-0"


@pytest.mark.asyncio
async def test_invocation_outbox_duplicate_and_result_are_idempotent(
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token,
) -> None:
    database = Database(str(app_settings.database_url))
    app = create_app(settings=app_settings, database=database)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        tenant_response = await client.post(
            "/admin/v1/tenants",
            headers=admin_headers,
            json={
                "slug": "capability-test",
                "display_name": "Capability Test",
                "business_type": "hospitality",
            },
        )
        assert tenant_response.status_code == 201
        tenant_id = UUID(tenant_response.json()["id"])
        system = await client.post(
            "/admin/v1/platform/prompts/system/drafts",
            headers=admin_headers,
            json={"key": "default", "text": "Help the caller."},
        )
        assert system.status_code == 201
        assert (
            await client.post(
                f"/admin/v1/platform/prompts/system/drafts/{system.json()['id']}/publish",
                headers=admin_headers,
            )
        ).status_code == 200
        profile = await client.post(
            "/admin/v1/platform/prompts/profiles/drafts",
            headers=admin_headers,
            json={"key": "hotel_assistant", "text": "Assist the caller."},
        )
        assert profile.status_code == 201
        assert (
            await client.post(
                f"/admin/v1/platform/prompts/profiles/drafts/{profile.json()['id']}/publish",
                headers=admin_headers,
            )
        ).status_code == 200
        tenant_prompt = await client.post(
            f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts",
            headers=admin_headers,
            json={"text": "Use the tenant's reservation workflow."},
        )
        assert tenant_prompt.status_code == 201
        assert (
            await client.post(
                f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts/{tenant_prompt.json()['id']}/publish",
                headers=admin_headers,
            )
        ).status_code == 200
        documents = {
            "documents": [
                {
                    "key": "knowledge",
                    "media_type": "text/markdown",
                    "content": (
                        "Reservation requests are handled by the reservations team."
                    ),
                }
            ]
        }
        knowledge_plan = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan",
            headers=admin_headers,
            json=documents,
        )
        assert knowledge_plan.status_code == 200
        knowledge = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/push",
            headers={
                **admin_headers,
                "If-Match": f'"{knowledge_plan.json()["base_version"]}"',
            },
            json=documents,
        )
        assert knowledge.status_code == 200
        knowledge_published = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/publish",
            headers=admin_headers,
        )
        assert knowledge_published.status_code == 200
        prompt_set = await client.post(
            f"/admin/v1/tenants/{tenant_id}/prompt-set/drafts",
            headers=admin_headers,
            json={
                "system_prompt_revision_id": system.json()["id"],
                "profile_prompt_revision_id": profile.json()["id"],
                "tenant_prompt_revision_id": tenant_prompt.json()["id"],
                "knowledge_base_revision_id": knowledge_published.json()["published"][
                    "revision"
                ]["id"],
            },
        )
        assert prompt_set.status_code == 201
        assert (
            await client.post(
                f"/admin/v1/tenants/{tenant_id}/prompt-set/drafts/{prompt_set.json()['id']}/publish",
                headers=admin_headers,
            )
        ).status_code == 200
        connection = await client.post(
            f"/admin/v1/tenants/{tenant_id}/integration-connections",
            headers=admin_headers,
            json={
                "key": "reservations",
                "provider": "google_sheets",
                "credential_ref": "capability-test-sheets",
            },
        )
        assert connection.status_code == 201
        other_tenant = await client.post(
            "/admin/v1/tenants",
            headers=admin_headers,
            json={
                "slug": "capability-other",
                "display_name": "Capability Other",
                "business_type": "hospitality",
            },
        )
        assert other_tenant.status_code == 201
        other_tenant_id = UUID(other_tenant.json()["id"])
        assert (
            await client.patch(
                f"/admin/v1/tenants/{other_tenant_id}/integration-connections/{connection.json()['id']}",
                headers=admin_headers,
                json={"status": "disabled"},
            )
        ).status_code == 404
        connection_url = (
            f"/admin/v1/tenants/{tenant_id}/integration-connections/"
            f"{connection.json()['id']}"
        )
        assert (
            await client.patch(
                connection_url,
                headers=admin_headers,
                json={"status": "disabled"},
            )
        ).status_code == 200
        config = {
            "schema_version": 3,
            "business": {"name": "Capability Test", "type": "hotel"},
            "contact": {},
            "localization": {
                "default_locale": "sk-SK",
                "timezone": "Europe/Bratislava",
            },
            "agent": {
                "display_name": "Agent",
                "greeting": "Hello",
                "profile": "hotel_assistant",
            },
            "conversation": {"scope": "property_only"},
            "capabilities": {
                "reservation.submit_request": {
                    "enabled": True,
                    "semantic_version": 1,
                    "description": "Submit a reservation request.",
                    "announcement": "I will submit your reservation request now.",
                    "agent_input_schema": agent_schema(),
                    "business_policy": {},
                    "execution": {
                        "plan_type": "google_sheets.append_values.v1",
                        "mapping_language": "jsonata",
                        "mapping_contract_version": 1,
                        "mapping_engine": "jsonata-python",
                        "mapping_engine_version": "0.7.0",
                        "connection_id": connection.json()["id"],
                        "spreadsheet_id": "sheet-id",
                        "sheet_name": "Reservations",
                        "append_range": "A:D",
                        "value_input_option": "RAW",
                        "idempotency": {
                            "lookup_range": "A:A",
                            "operation_id_column_index": 0,
                        },
                        "request_mapping": '{"rows": [[metadata.operation_id, business.guest.name, business.stay.check_in, business.stay.check_out]]}',
                    },
                    "validation_fixtures": [
                        {
                            "guest_name": "Fixture",
                            "check_in": "2030-01-01",
                            "check_out": "2030-01-02",
                        },
                        {
                            "guest_name": "Fixture",
                            "check_in": "2031-01-01",
                            "check_out": "2031-01-02",
                        },
                    ],
                }
            },
        }
        draft = await client.post(
            f"/admin/v1/tenants/{tenant_id}/config/drafts",
            headers=admin_headers,
            json={"schema_version": 3, "config": config},
        )
        assert draft.status_code == 201
        draft_id = draft.json()["id"]
        validation = await client.post(
            f"/admin/v1/tenants/{tenant_id}/config/drafts/{draft_id}/validate",
            headers=admin_headers,
        )
        assert validation.json()["errors"][0]["code"] == "connection_disabled"
        assert (
            await client.patch(
                connection_url,
                headers=admin_headers,
                json={"status": "active"},
            )
        ).status_code == 200
        validation = await client.post(
            f"/admin/v1/tenants/{tenant_id}/config/drafts/{draft_id}/validate",
            headers=admin_headers,
        )
        assert validation.json() == {"valid": True, "errors": []}
        assert (
            await client.post(
                f"/admin/v1/tenants/{tenant_id}/config/drafts/{draft_id}/publish",
                headers=admin_headers,
            )
        ).status_code == 200

        await apply_voice_runtime(client, str(tenant_id), headers=admin_headers)

        async with database.transaction() as session:
            call, _ = await build_call_session_service(session).create_manual(tenant_id)
            await build_call_session_service(session).activate(call.id)

        voice_headers = {
            "Authorization": "Bearer "
            + service_token(
                service="voice-agent",
                scopes=["capability-invocation:create", "capability-invocation:read"],
                secret=app_settings.voice_agent_service_secret.get_secret_value(),
            )
        }
        request = {
            "tool_call_id": "tool-call-1",
            "capability": "reservation_submit_request",
            "agent_input": {
                "guest_name": "Alice",
                "check_in": "2030-08-12",
                "check_out": "2030-08-15",
            },
        }
        first, second = await asyncio.gather(
            client.post(
                f"/internal/v1/calls/{call.id}/capability-invocations",
                headers=voice_headers,
                json=request,
            ),
            client.post(
                f"/internal/v1/calls/{call.id}/capability-invocations",
                headers=voice_headers,
                json=request,
            ),
        )
        assert {first.status_code, second.status_code} <= {200, 202}
        assert first.json()["id"] == second.json()["id"]
        invocation_id = UUID(first.json()["id"])
        async with database.transaction() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(CapabilityInvocation)
                )
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == 1
            )
            invocation = await session.get(CapabilityInvocation, invocation_id)
            assert invocation is not None
            rows = invocation.execution_plan.get("rows")
            assert isinstance(rows, list) and isinstance(rows[0], list)
            assert rows[0][1:] == [
                "Alice",
                "2030-08-12",
                "2030-08-15",
            ]
            job_id = invocation.job_id

        redis = FakeRedis(raise_after_publish=True)
        dispatcher = OutboxDispatcher(database, redis, "capability:jobs", 1)  # type: ignore[arg-type]
        assert await dispatcher.dispatch_once() == 0
        assert await dispatcher.dispatch_once() == 1
        assert len(redis.jobs) == 2
        assert redis.jobs[0][1]["job"] == redis.jobs[1][1]["job"]

        worker_headers = {
            "Authorization": "Bearer "
            + service_token(
                service="job-worker",
                scopes=["capability-result:write"],
                secret=app_settings.job_worker_service_secret.get_secret_value(),
            )
        }
        now = datetime.now(UTC).isoformat()
        success = {
            "job_id": str(job_id),
            "capability_invocation_id": str(invocation_id),
            "status": "succeeded",
            "result": {
                "result_type": "google_sheets.append_values.v1",
                "status": "succeeded",
                "updated_range": "Reservations!A42:D42",
                "updated_rows": 1,
                "deduplicated": False,
            },
            "attempt": 1,
            "started_at": now,
            "completed_at": now,
        }
        reported = await client.post(
            "/internal/v1/capability-results",
            headers=worker_headers,
            json=success,
        )
        assert reported.json()["semantic_result"]["status"] == "request_submitted"
        failed_replay = {
            **success,
            "status": "failed",
            "result": None,
            "error": {
                "code": "provider_timeout",
                "message": "timeout",
                "transient": True,
            },
        }
        replayed = await client.post(
            "/internal/v1/capability-results",
            headers=worker_headers,
            json=failed_replay,
        )
        assert replayed.json()["status"] == "succeeded"

        async with database.transaction() as session:
            invocation = await session.get(CapabilityInvocation, invocation_id)
            outbox = await session.scalar(select(OutboxMessage))
            assert invocation is not None and outbox is not None
            old = datetime.now(UTC) - timedelta(days=31)
            invocation.completed_at = old
            outbox.dispatched_at = old
            await session.flush()
            purged, deleted = await CapabilityRetentionService(session).purge_once(
                invocation_retention=timedelta(days=30),
                outbox_retention=timedelta(days=7),
            )
            assert purged == 1
            assert deleted == 1
            assert invocation.canonical_input == {}
            assert invocation.execution_plan == {}
            assert invocation.semantic_result is not None
            await session.execute(
                delete(CapabilityInvocation).where(
                    CapabilityInvocation.id == invocation_id
                )
            )
            await session.execute(
                delete(Conversation).where(Conversation.call_session_id == call.id)
            )
            await session.execute(delete(CallSession).where(CallSession.id == call.id))
            tenant = await session.get(Tenant, tenant_id)
            assert tenant is not None
            tenant.active_prompt_set_revision_id = None
            tenant.active_config_revision_id = None
            tenant.active_voice_runtime_revision_id = None
            await session.flush()
            await session.execute(
                delete(PromptSetRevision).where(
                    PromptSetRevision.tenant_id == tenant_id
                )
            )
            await session.execute(
                delete(TenantPromptRevision).where(
                    TenantPromptRevision.tenant_id == tenant_id
                )
            )
            await session.execute(
                delete(KnowledgeBaseRevision).where(
                    KnowledgeBaseRevision.tenant_id == tenant_id
                )
            )
            await session.execute(
                delete(PromptSet).where(PromptSet.tenant_id == tenant_id)
            )
            await session.execute(
                delete(TenantPrompt).where(TenantPrompt.tenant_id == tenant_id)
            )
            await session.execute(
                delete(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id)
            )
            await session.execute(
                delete(TenantConfigRevision).where(
                    TenantConfigRevision.tenant_id == tenant_id
                )
            )
            await session.execute(
                delete(IntegrationConnection).where(
                    IntegrationConnection.tenant_id == tenant_id
                )
            )
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
            await session.execute(
                delete(SystemPromptRevision).where(
                    SystemPromptRevision.id == UUID(system.json()["id"])
                )
            )
            await session.execute(
                delete(ProfilePromptRevision).where(
                    ProfilePromptRevision.id == UUID(profile.json()["id"])
                )
            )
            await session.execute(
                delete(SystemPrompt).where(
                    SystemPrompt.id == UUID(system.json()["prompt_id"])
                )
            )
            await session.execute(
                delete(ProfilePrompt).where(
                    ProfilePrompt.id == UUID(profile.json()["prompt_id"])
                )
            )

    await database.close()
