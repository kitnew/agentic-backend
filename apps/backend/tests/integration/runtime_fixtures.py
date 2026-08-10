from typing import Any

from httpx import AsyncClient


def platform_runtime_policy(*, voice_id: str = "voice-a") -> dict[str, Any]:
    return {
        "llm": {
            "provider": "azure_openai",
            "model": "model-a",
            "temperature": 0,
        },
        "stt": {
            "provider": "elevenlabs",
            "model": "scribe_v2_realtime",
            "server_vad": {
                "silence_threshold_seconds": 0.5,
                "activity_threshold": 0.35,
                "min_speech_ms": 100,
                "min_silence_ms": 500,
            },
        },
        "tts": {
            "provider": "elevenlabs",
            "model": "eleven_flash_v2_5",
            "voice_id": voice_id,
        },
        "local_vad": {
            "min_speech_seconds": 0.05,
            "min_silence_seconds": 0.25,
            "activation_threshold": 0.5,
        },
        "turn": {
            "detection": "stt",
            "min_endpointing_delay_seconds": 0.1,
            "max_endpointing_delay_seconds": 0.7,
        },
    }


async def ensure_platform_runtime(
    client: AsyncClient, *, headers: dict[str, str] | None = None
) -> str:
    desired = platform_runtime_policy()
    state = await client.get("/admin/v1/platform/runtime", headers=headers)
    assert state.status_code == 200
    current = state.json()["latest_published_revision"]
    if current is not None and current["policy"] == desired:
        return current["id"]
    draft = state.json()["draft_revision"]
    if draft is None:
        created = await client.post(
            "/admin/v1/platform/runtime/drafts",
            json={"policy": desired},
            headers=headers,
        )
        assert created.status_code == 201
        draft = created.json()
    elif draft["policy"] != desired:
        updated = await client.patch(
            f"/admin/v1/platform/runtime/drafts/{draft['id']}",
            json={"policy": desired},
            headers={**(headers or {}), "If-Match": f'"{draft["version"]}"'},
        )
        assert updated.status_code == 200
        draft = updated.json()
    published = await client.post(
        f"/admin/v1/platform/runtime/drafts/{draft['id']}/publish",
        headers=headers,
    )
    assert published.status_code == 200
    return published.json()["id"]


async def apply_voice_runtime(
    client: AsyncClient,
    tenant_id: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    await ensure_platform_runtime(client, headers=headers)
    response = await client.post(
        f"/admin/v1/tenants/{tenant_id}/voice-runtime/apply", headers=headers
    )
    assert response.status_code == 200
    return response.json()["voice_runtime"]
