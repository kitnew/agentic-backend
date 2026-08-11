from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    Tenant,
    TenantStatus,
)
from backend_core.runtime.voice.errors import VoiceRuntimeResolutionError
from backend_core.runtime.voice.models import (
    PlatformRuntime,
    PlatformRuntimeRevision,
    RuntimeRevisionStatus,
    TenantRuntime,
    TenantRuntimeRevision,
    VoiceRuntimeRevision,
)
from backend_core.runtime.voice.service import VoiceRuntimeUseCases


def policy(voice: str = "platform-voice") -> dict[str, object]:
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
            "voice_id": voice,
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


def config(locale: str = "sk-SK", *, business_name: str = "Hotel") -> object:
    return SimpleNamespace(
        schema_version=3,
        status=ConfigRevisionStatus.PUBLISHED,
        published_at=datetime.now(UTC),
        config={
            "schema_version": 3,
            "business": {"name": business_name, "type": "hotel"},
            "contact": {},
            "localization": {
                "default_locale": locale,
                "timezone": "Europe/Bratislava",
            },
            "agent": {
                "display_name": "Amelia",
                "greeting": "Dobrý deň",
                "profile": "hotel_assistant",
            },
            "conversation": {"scope": "property_only"},
            "capabilities": {},
        },
    )


def service_fixture(
    *,
    locale: str = "sk-SK",
    override: dict[str, object] | None = None,
    active: VoiceRuntimeRevision | None = None,
) -> tuple[VoiceRuntimeUseCases, AsyncMock, Tenant]:
    tenant = Tenant(
        id=uuid4(),
        slug="runtime-hotel",
        display_name="Runtime Hotel",
        business_type="hotel",
        status=TenantStatus.ACTIVE,
        active_config_revision_id=uuid4(),
        active_voice_runtime_revision_id=None if active is None else active.id,
    )
    tenants = AsyncMock()
    tenants.get.return_value = tenant
    configs = AsyncMock()
    configs.get.return_value = config(locale)
    runtimes = AsyncMock()
    platform = PlatformRuntime(id=uuid4(), key="default")
    platform_revision = PlatformRuntimeRevision(
        id=uuid4(),
        platform_runtime_id=platform.id,
        revision_number=1,
        policy=policy(),
    )
    runtimes.platform.return_value = platform
    runtimes.published_platform_revision.return_value = platform_revision
    if override is None:
        runtimes.tenant_runtime.return_value = None
        runtimes.published_tenant_revision.return_value = None
    else:
        tenant_runtime = TenantRuntime(id=uuid4(), tenant_id=tenant.id)
        runtimes.tenant_runtime.return_value = tenant_runtime
        runtimes.published_tenant_revision.return_value = TenantRuntimeRevision(
            id=uuid4(),
            tenant_runtime_id=tenant_runtime.id,
            tenant_id=tenant.id,
            revision_number=1,
            settings=override,
        )
    runtimes.voice_revision.return_value = active
    return VoiceRuntimeUseCases(tenants, configs, runtimes), runtimes, tenant


@pytest.mark.asyncio
async def test_platform_only_and_tenant_voice_resolution() -> None:
    platform_service, _, tenant = service_fixture()
    platform_plan = await platform_service.plan_voice_runtime(tenant.id)
    assert platform_plan.status == "missing-active"
    assert platform_plan.desired_settings.tts.voice_id == "platform-voice"

    tenant_service, _, tenant = service_fixture(
        override={"tts": {"voice_id": "tenant-voice"}}
    )
    tenant_plan = await tenant_service.plan_voice_runtime(tenant.id)
    assert tenant_plan.desired_settings.tts.voice_id == "tenant-voice"
    assert tenant_plan.tenant_runtime_revision_id is not None


@pytest.mark.asyncio
async def test_empty_override_uses_platform_and_plan_is_read_only() -> None:
    service, runtimes, tenant = service_fixture(override={})
    plan = await service.plan_voice_runtime(tenant.id)
    assert plan.desired_settings.tts.voice_id == "platform-voice"
    runtimes.add.assert_not_awaited()
    runtimes.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_config_change_does_not_create_runtime_drift() -> None:
    effective = {"locale": "sk-SK", **policy()}
    active = VoiceRuntimeRevision(
        id=uuid4(),
        voice_runtime_id=uuid4(),
        tenant_id=uuid4(),
        revision_number=4,
        platform_runtime_revision_id=uuid4(),
        effective_settings=effective,
        status=RuntimeRevisionStatus.PUBLISHED,
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    service, _, tenant = service_fixture(active=active)
    tenant.active_voice_runtime_revision_id = active.id
    plan = await service.plan_voice_runtime(tenant.id)
    assert plan.status == "unchanged"
    assert plan.changes == []


@pytest.mark.asyncio
async def test_locale_change_drifts_and_unsupported_locale_is_structured() -> None:
    effective = {"locale": "sk-SK", **policy()}
    active = VoiceRuntimeRevision(
        id=uuid4(),
        voice_runtime_id=uuid4(),
        tenant_id=uuid4(),
        revision_number=4,
        platform_runtime_revision_id=uuid4(),
        effective_settings=effective,
        status=RuntimeRevisionStatus.PUBLISHED,
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    service, _, tenant = service_fixture(active=active, locale="sk")
    tenant.active_voice_runtime_revision_id = active.id
    plan = await service.plan_voice_runtime(tenant.id)
    assert plan.status == "modified"
    assert [change.path for change in plan.changes] == ["locale"]

    service, _, tenant = service_fixture(active=active, locale="en-US")
    tenant.active_voice_runtime_revision_id = active.id
    with pytest.raises(VoiceRuntimeResolutionError) as raised:
        await service.plan_voice_runtime(tenant.id)
    assert raised.value.code == "unsupported_locale"
    assert raised.value.path == "localization.default_locale"


@pytest.mark.asyncio
async def test_missing_published_platform_runtime_is_structured() -> None:
    service, runtimes, tenant = service_fixture()
    runtimes.platform.return_value = None
    with pytest.raises(VoiceRuntimeResolutionError) as raised:
        await service.plan_voice_runtime(tenant.id)
    assert raised.value.code == "published_platform_runtime_not_found"
