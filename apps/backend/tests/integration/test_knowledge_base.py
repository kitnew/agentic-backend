from uuid import UUID

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.models import (
    KnowledgeBase,
    KnowledgeBaseRevision,
    KnowledgeBaseRevisionDocument,
    KnowledgeDocument,
    KnowledgeDocumentRevision,
    Tenant,
)
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError


def desired(**documents: str) -> dict[str, object]:
    return {
        "documents": [
            {"key": key, "media_type": "text/markdown", "content": content}
            for key, content in documents.items()
        ]
    }


async def create_tenant(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/admin/v1/tenants",
        json={"slug": slug, "display_name": slug, "business_type": "hotel"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def push(
    client: AsyncClient, tenant_id: str, body: dict[str, object]
) -> dict[str, object]:
    plan = await client.post(
        f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan", json=body
    )
    assert plan.status_code == 200
    response = await client.post(
        f"/admin/v1/tenants/{tenant_id}/knowledge-base/push",
        json=body,
        headers={"If-Match": f'"{plan.json()["base_version"]}"'},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_document_revision_reuse_snapshot_history_and_tenant_isolation(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    transport = ASGITransport(app=app)
    slugs = ("knowledge-hotel", "other-knowledge-hotel")
    try:
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=admin_headers
        ) as client:
            tenant_id = await create_tenant(client, slugs[0])
            assert (await push(client, tenant_id, desired()))["changed"] is False
            async with database.transaction() as session:
                assert (
                    await session.scalar(
                        select(func.count(KnowledgeBase.id)).where(
                            KnowledgeBase.tenant_id == UUID(tenant_id)
                        )
                    )
                    == 0
                )
            first_body = desired(rooms="Rooms one", knowledge="General")
            first_plan = await client.post(
                f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan",
                json=first_body,
            )
            assert first_plan.status_code == 200
            assert first_plan.json()["base_version"] == 0
            assert [item["key"] for item in first_plan.json()["documents"]] == [
                "knowledge",
                "rooms",
            ]
            first = await push(client, tenant_id, first_body)
            assert first["changed"] is True
            assert [item["key"] for item in first["draft"]["documents"]] == [
                "knowledge",
                "rooms",
            ]
            first_revision_id = first["draft"]["revision"]["id"]
            stale = await client.post(
                f"/admin/v1/tenants/{tenant_id}/knowledge-base/push",
                json=desired(knowledge="stale"),
                headers={"If-Match": '"0"'},
            )
            assert stale.status_code == 412

            equivalent = await push(
                client, tenant_id, desired(knowledge="General\n", rooms="Rooms one")
            )
            assert equivalent["changed"] is False

            changed_body = desired(
                policies="Policies", rooms="Rooms two", knowledge="General"
            )
            changed_plan = await client.post(
                f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan",
                json=changed_body,
            )
            changes = {
                item["key"]: item["status"] for item in changed_plan.json()["documents"]
            }
            assert changes == {
                "knowledge": "unchanged",
                "policies": "local-only",
                "rooms": "modified",
            }
            changed = await push(client, tenant_id, changed_body)
            assert changed["draft"]["revision"]["id"] == first_revision_id
            assert {
                item["key"]: item["document_revision_number"]
                for item in changed["draft"]["documents"]
            } == {"knowledge": 1, "policies": 1, "rooms": 2}
            published_one = await client.post(
                f"/admin/v1/tenants/{tenant_id}/knowledge-base/publish"
            )
            assert published_one.status_code == 200

            renamed = await push(
                client,
                tenant_id,
                desired(
                    accommodation="Rooms two",
                    knowledge="General",
                    policies="Policies",
                ),
            )
            assert renamed["draft"]["revision"]["revision_number"] == 2
            assert {
                item["key"]: item["document_revision_number"]
                for item in renamed["draft"]["documents"]
            } == {"accommodation": 1, "knowledge": 1, "policies": 1}
            assert (
                await client.post(
                    f"/admin/v1/tenants/{tenant_id}/knowledge-base/publish"
                )
            ).status_code == 200

            history = await client.get(
                f"/admin/v1/tenants/{tenant_id}/knowledge-base/revisions"
            )
            assert [item["revision_number"] for item in history.json()] == [1, 2]
            assert [item["document_count"] for item in history.json()] == [3, 3]

            other_tenant_id = await create_tenant(client, slugs[1])
            other = await push(client, other_tenant_id, desired(knowledge="Other"))
            other_revision_id = UUID(other["draft"]["revision"]["id"])

        async with database.transaction() as session:
            first_snapshot = list(
                (
                    await session.execute(
                        select(KnowledgeDocument.key)
                        .join(
                            KnowledgeBaseRevisionDocument,
                            KnowledgeBaseRevisionDocument.knowledge_document_id
                            == KnowledgeDocument.id,
                        )
                        .where(
                            KnowledgeBaseRevisionDocument.knowledge_base_revision_id
                            == UUID(first_revision_id)
                        )
                        .order_by(KnowledgeBaseRevisionDocument.position)
                    )
                ).scalars()
            )
            assert first_snapshot == ["knowledge", "policies", "rooms"]
            assert (
                await session.scalar(
                    select(func.count(KnowledgeDocumentRevision.id)).where(
                        KnowledgeDocumentRevision.tenant_id == UUID(tenant_id)
                    )
                )
            ) == 5
            first_revision = await session.get(
                KnowledgeBaseRevision, UUID(first_revision_id)
            )
            other_link = await session.scalar(
                select(KnowledgeBaseRevisionDocument).where(
                    KnowledgeBaseRevisionDocument.knowledge_base_revision_id
                    == other_revision_id
                )
            )
            assert first_revision is not None
            assert other_link is not None
            first_owner = (
                first_revision.tenant_id,
                first_revision.knowledge_base_id,
            )
            other_document = (
                other_link.knowledge_document_id,
                other_link.knowledge_document_revision_id,
            )

        with pytest.raises(IntegrityError):
            async with database.transaction() as session:
                session.add(
                    KnowledgeBaseRevisionDocument(
                        knowledge_base_revision_id=UUID(first_revision_id),
                        knowledge_document_revision_id=other_document[1],
                        tenant_id=first_owner[0],
                        knowledge_base_id=first_owner[1],
                        knowledge_document_id=other_document[0],
                        position=99,
                    )
                )
    finally:
        async with database.transaction() as session:
            await session.execute(delete(Tenant).where(Tenant.slug.in_(slugs)))
        await database.close()
