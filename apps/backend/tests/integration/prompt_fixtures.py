from uuid import uuid4

from httpx import AsyncClient
from runtime_fixtures import apply_voice_runtime


async def _publish_platform_prompt(
    client: AsyncClient,
    resource: str,
    key: str,
    text: str,
) -> dict[str, str]:
    draft = await client.post(
        f"/admin/v1/platform/prompts/{resource}/drafts",
        json={"key": key, "text": text},
    )
    assert draft.status_code == 201
    published = await client.post(
        f"/admin/v1/platform/prompts/{resource}/drafts/{draft.json()['id']}/publish"
    )
    assert published.status_code == 200
    return published.json()


async def publish_prompt_set(
    client: AsyncClient,
    tenant_id: str,
    *,
    system_text: str = "You are a hotel assistant.",
) -> dict[str, str]:
    system = await _publish_platform_prompt(client, "system", "default", system_text)
    profile = await _publish_platform_prompt(
        client, "profiles", "hotel_assistant", "Be concise."
    )
    tenant_prompt = await client.post(
        f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts",
        json={"text": "Answer for this tenant."},
    )
    assert tenant_prompt.status_code == 201
    tenant_prompt_published = await client.post(
        f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts/"
        f"{tenant_prompt.json()['id']}/publish"
    )
    assert tenant_prompt_published.status_code == 200
    documents = {
        "documents": [
            {
                "key": "knowledge",
                "media_type": "text/markdown",
                "content": "Breakfast starts at seven.",
            }
        ]
    }
    knowledge_plan = await client.post(
        f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan", json=documents
    )
    assert knowledge_plan.status_code == 200
    knowledge_push = await client.post(
        f"/admin/v1/tenants/{tenant_id}/knowledge-base/push",
        json=documents,
        headers={"If-Match": f'"{knowledge_plan.json()["base_version"]}"'},
    )
    assert knowledge_push.status_code == 200
    if knowledge_push.json()["draft"] is None:
        knowledge_snapshot = await client.get(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/published"
        )
    else:
        published = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/publish"
        )
        assert published.status_code == 200
        knowledge_snapshot = published
    assert knowledge_snapshot.status_code == 200
    prompt_set = await client.post(
        f"/admin/v1/tenants/{tenant_id}/prompt-set/drafts",
        json={
            "system_prompt_revision_id": system["id"],
            "profile_prompt_revision_id": profile["id"],
            "tenant_prompt_revision_id": tenant_prompt_published.json()["id"],
            "knowledge_base_revision_id": (
                knowledge_snapshot.json().get("published", knowledge_snapshot.json())[
                    "revision"
                ]["id"]
            ),
        },
    )
    assert prompt_set.status_code == 201
    published_prompt_set = await client.post(
        f"/admin/v1/tenants/{tenant_id}/prompt-set/drafts/"
        f"{prompt_set.json()['id']}/publish"
    )
    assert published_prompt_set.status_code == 200
    return {
        "system_revision_id": system["id"],
        "profile_revision_id": profile["id"],
        "tenant_prompt_revision_id": tenant_prompt_published.json()["id"],
        "knowledge_base_revision_id": (
            knowledge_snapshot.json().get("published", knowledge_snapshot.json())[
                "revision"
            ]["id"]
        ),
        "prompt_set_revision_id": published_prompt_set.json()["id"],
    }


def tenant_config_v3(
    *, greeting: str, profile: str = "hotel_assistant"
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "business": {"name": "Fixture Hotel", "type": "hotel"},
        "contact": {},
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {
            "display_name": "Amelia",
            "greeting": greeting,
            "profile": profile,
        },
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


async def publish_config(
    client: AsyncClient,
    tenant_id: str,
    *,
    greeting: str,
) -> str:
    drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
    draft = await client.post(
        drafts_url,
        json={"schema_version": 3, "config": tenant_config_v3(greeting=greeting)},
    )
    assert draft.status_code == 201
    published = await client.post(f"{drafts_url}/{draft.json()['id']}/publish")
    assert published.status_code == 200
    return published.json()["id"]


async def create_voice_ready_tenant(
    client: AsyncClient,
    slug: str,
) -> tuple[str, str]:
    tenant = await client.post(
        "/admin/v1/tenants",
        json={"slug": slug, "display_name": slug, "business_type": "hotel"},
    )
    assert tenant.status_code == 201
    tenant_id = tenant.json()["id"]
    await publish_prompt_set(client, tenant_id)
    await publish_config(client, tenant_id, greeting="Dobrý deň")
    await apply_voice_runtime(client, tenant_id)
    did = f"+421{uuid4().int % 10**9:09d}"
    telephony = await client.put(
        f"/admin/v1/tenants/{tenant_id}/telephony",
        json={"phone_number": did, "handoff": {"destinations": {}}},
    )
    assert telephony.status_code == 200
    draft_id = telephony.json()["draft_revision_id"]
    assert (
        await client.post(f"/admin/v1/tenants/{tenant_id}/config/drafts/{draft_id}/publish")
    ).status_code == 200
    return tenant_id, did
