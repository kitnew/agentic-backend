import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from backend_core.modules.calls.errors import (
    CallSessionTelephonyNotReadyError,
    HumanHandoffError,
)
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.conversations.models import Conversation
from backend_core.modules.conversations.repository import ConversationRepository
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationKind,
)
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.platform_release_repository import (
    PlatformReleaseRepository,
)
from backend_core.modules.tenants.platform_release_service import (
    PlatformPublishSnapshot,
    PlatformReleaseUseCases,
)
from backend_core.modules.tenants.release_compiler import compile_runtime_bundle
from backend_core.modules.tenants.release_models import (
    ActivePhoneClaim,
    RuntimeBundleRecord,
    TenantRelease,
    TenantTelephonyProvisioning,
)
from backend_core.modules.tenants.release_repository import (
    DraftConflictError,
    DraftExpectation,
    TenantComponent,
    TenantReleaseRepository,
)
from backend_core.modules.tenants.release_service import (
    ReleaseComponents,
    TenantReleaseUseCases,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.platform.database import Database
from backend_core.runtime.bundle_store import RuntimeBundleStore
from backend_core.runtime.capabilities.models import OutboxMessage
from backend_core.runtime.capabilities.repository import CapabilityInvocationRepository
from backend_core.runtime.capabilities.service import CapabilityInvocationService
from contracts import (
    CapabilityInvocationRequest,
    HttpRequestSpec,
    HttpResponseSpec,
    RuntimeCapabilityBinding,
    RuntimeCapabilityPolicy,
    RuntimeHttpExecution,
)
from contracts.runtime_bundle import (
    RuntimeBundlePayload,
    RuntimeBundleProvenance,
    RuntimeHandoffDestination,
    RuntimeTelephony,
)
from contracts.voice import (
    HumanHandoffRequest,
    InboundSipClaimRequest,
    VoiceAgentPrompt,
)
from contracts.voice_runtime import (
    EffectiveVoiceRuntime,
    LLMRuntimeSettings,
    LocalVADRuntimeSettings,
    PlatformRuntimePolicy,
    ServerVADRuntimeSettings,
    STTRuntimeSettings,
    TTSRuntimeSettings,
    TurnRuntimeSettings,
)
from sqlalchemy import select


class _Conversations:
    async def create_for_call(self, call_id: UUID, tenant_id: UUID) -> None:
        return None


class _Events:
    async def publish(self, event: object) -> None:
        return None


def _call_service(session) -> CallSessionService:
    return CallSessionService(
        CallSessionRepository(session),
        None,  # type: ignore[arg-type]
        TenantRepository(session),
        _Conversations(),  # type: ignore[arg-type]
        _Events(),  # type: ignore[arg-type]
        TenantReleaseRepository(session),
        RuntimeBundleStore(session),
    )


def _runtime_payload(
    telephony: RuntimeTelephony | None = None,
) -> RuntimeBundlePayload:
    return RuntimeBundlePayload(
        voice_runtime=EffectiveVoiceRuntime(
            llm=LLMRuntimeSettings(
                provider="azure_openai", model="gpt-4.1", temperature=0.1
            ),
            stt=STTRuntimeSettings(
                provider="elevenlabs",
                model="scribe",
                server_vad=ServerVADRuntimeSettings(
                    silence_threshold_seconds=1,
                    activity_threshold=0.5,
                    min_speech_ms=100,
                    min_silence_ms=100,
                ),
            ),
            tts=TTSRuntimeSettings(
                provider="elevenlabs", model="flash", voice_id="voice"
            ),
            turn=TurnRuntimeSettings(
                detection="stt",
                min_endpointing_delay_seconds=0.1,
                max_endpointing_delay_seconds=1,
            ),
            local_vad=LocalVADRuntimeSettings(
                min_speech_seconds=0.1,
                min_silence_seconds=0.1,
                activation_threshold=0.5,
            ),
            locale="en",
        ),
        locale="en",
        timezone="Europe/Bucharest",
        agent_display_name="Agent",
        greeting="Hello",
        conversation_scope="property_only",
        prompt=VoiceAgentPrompt(system_prompt="System"),
        telephony=telephony or RuntimeTelephony(),
    )


def _platform_policy() -> PlatformRuntimePolicy:
    return PlatformRuntimePolicy(
        llm=LLMRuntimeSettings(
            provider="azure_openai", model="gpt-4.1", temperature=0.1
        ),
        stt=STTRuntimeSettings(
            provider="elevenlabs",
            model="scribe",
            server_vad=ServerVADRuntimeSettings(
                silence_threshold_seconds=1,
                activity_threshold=0.5,
                min_speech_ms=100,
                min_silence_ms=100,
            ),
        ),
        tts=TTSRuntimeSettings(
            provider="elevenlabs", model="flash", voice_id="voice"
        ),
        turn=TurnRuntimeSettings(
            detection="stt",
            min_endpointing_delay_seconds=0.1,
            max_endpointing_delay_seconds=1,
        ),
        local_vad=LocalVADRuntimeSettings(
            min_speech_seconds=0.1,
            min_silence_seconds=0.1,
            activation_threshold=0.5,
        ),
    )


@pytest.mark.asyncio
async def test_platform_release_pins_exact_runtime_and_profile_prompt(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.transaction() as session:
            platform = PlatformReleaseUseCases(PlatformReleaseRepository(session))
            runtime = await platform.save_runtime(_platform_policy(), None)
            system = await platform.save_system_prompt("System", None)
            profile = await platform.save_profile_prompt(
                "hotel_assistant", "Profile", None
            )
            release = await platform.publish(
                PlatformPublishSnapshot(
                    runtime_version=runtime.version,
                    system_prompt_version=system.version,
                    profile_prompt_versions={"hotel_assistant": profile.version},
                )
            )
            bundle_input = await platform.input_for_profile("hotel_assistant")

        assert release.release_number == 1
        assert bundle_input.runtime_revision_id == release.runtime_revision_id
        assert bundle_input.system_prompt == "System"
        assert bundle_input.profile_prompt == "Profile"
    finally:
        await database.close()


def _bundle_factory(
    tenant_id: UUID,
    telephony: RuntimeTelephony | None = None,
    payload: RuntimeBundlePayload | None = None,
):
    platform_runtime_revision_id = uuid4()
    system_prompt_revision_id = uuid4()
    profile_prompt_revision_id = uuid4()

    def build(components: ReleaseComponents):
        return compile_runtime_bundle(
            tenant_id=tenant_id,
            payload=payload or _runtime_payload(telephony),
            provenance=RuntimeBundleProvenance(
                runtime_revision_id=components.runtime.id,
                agent_revision_id=components.agent.id,
                prompt_revision_id=components.prompt.id,
                knowledge_revision_id=components.knowledge.id,
                capabilities_revision_id=components.capabilities.id,
                post_call_revision_id=components.post_call.id,
                telephony_revision_id=components.telephony.id,
                platform_runtime_revision_id=platform_runtime_revision_id,
                system_prompt_revision_id=system_prompt_revision_id,
                profile_prompt_revision_id=profile_prompt_revision_id,
            ),
            compiler_build_id="test",
        )

    return build


def _initial_payloads() -> dict[TenantComponent, dict[str, object]]:
    return {
        TenantComponent.RUNTIME: {},
        TenantComponent.AGENT: {
            "business": {"name": "Release Hotel", "type": "hotel"},
            "contact": {},
            "localization": {
                "default_locale": "en",
                "timezone": "Europe/Bucharest",
            },
            "agent": {
                "display_name": "Agent",
                "greeting": "Hello",
                "profile": "hotel_assistant",
            },
            "conversation": {"scope": "property_only"},
            "handoff": {"destinations": {}},
        },
        TenantComponent.PROMPT: {"text": ""},
        TenantComponent.KNOWLEDGE: {},
        TenantComponent.CAPABILITIES: {"capabilities": {}},
        TenantComponent.POST_CALL: {"actions": []},
        TenantComponent.TELEPHONY: {"phone_number": None},
    }


async def _publish_ready_tenant(
    database: Database,
    *,
    slug: str,
    phone_number: str | None,
) -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    bundle_factory = _bundle_factory(tenant_id)
    async with database.transaction() as session:
        session.add(
            Tenant(
                id=tenant_id,
                slug=slug,
                display_name=slug,
                business_type="hotel",
            )
        )
        repository = TenantReleaseRepository(session)
        payloads = _initial_payloads()
        payloads[TenantComponent.TELEPHONY] = {
            "phone_number": phone_number,
        }
        expectations = []
        for component, payload in payloads.items():
            draft = await repository.save_draft(
                component=component,
                tenant_id=tenant_id,
                payload=payload,
                expected_version=None,
            )
            expectations.append(DraftExpectation(component, draft.id, draft.version))
        release = await TenantReleaseUseCases(repository).publish(
            tenant_id, expectations, bundle_factory, publish_all=True
        )
        state = await session.get(TenantTelephonyProvisioning, tenant_id)
        assert state is not None
        state.applied_revision_id = state.desired_revision_id
        state.status = "ready"
        return tenant_id, release.id, release.runtime_bundle_id


@pytest.mark.asyncio
async def test_capability_invocation_preserves_pinned_runtime_bundle_identity(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    tenant_id = uuid4()
    connection_id = uuid4()
    binding = RuntimeCapabilityBinding(
        semantic_key="reservation.check_reservation",
        semantic_version=1,
        tool_name="reservation_check_reservation",
        enabled=True,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["check_in", "check_out", "room_type", "room_count"],
            "properties": {
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "room_type": {"type": "integer"},
                "room_count": {"type": "integer"},
            },
        },
        bindings={
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
            "room_type": "allocation.room_type",
            "room_count": "allocation.room_count",
        },
        policy=RuntimeCapabilityPolicy(),
        execution=RuntimeHttpExecution(
            connection_id=connection_id,
            method="POST",
            request=HttpRequestSpec(codec="none"),
            response=HttpResponseSpec(codec="none"),
            timeout_seconds=10,
        ),
    )
    payload = _runtime_payload().model_copy(update={"capability_bindings": [binding]})
    try:
        async with database.transaction() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug=f"capability-bundle-{tenant_id.hex[:8]}",
                    display_name="Capability Bundle Hotel",
                    business_type="hotel",
                )
            )
            repository = TenantReleaseRepository(session)
            expectations = []
            for component, component_payload in _initial_payloads().items():
                draft = await repository.save_draft(
                    component=component,
                    tenant_id=tenant_id,
                    payload=component_payload,
                    expected_version=None,
                )
                expectations.append(DraftExpectation(component, draft.id, draft.version))
            release = await TenantReleaseUseCases(repository).publish(
                tenant_id,
                expectations,
                _bundle_factory(tenant_id, payload=payload),
                publish_all=True,
            )
            session.add(
                IntegrationConnection(
                    id=connection_id,
                    tenant_id=tenant_id,
                    key="check-availability",
                    kind=IntegrationKind.HTTP,
                    configuration={},
                    enabled=True,
                )
            )
            call = CallSession(
                tenant_id=tenant_id,
                tenant_release_id=release.id,
                runtime_bundle_id=release.runtime_bundle_id,
                channel=CallChannel.WEB,
                direction=CallDirection.INBOUND,
                provider="test",
                provider_call_id=f"capability-bundle-{tenant_id.hex}",
                room_name="capability-bundle-room",
                status=CallSessionStatus.CONNECTED,
                started_at=datetime.now(UTC),
                connected_at=datetime.now(UTC),
            )
            session.add(call)
            await session.flush()
            session.add(Conversation(tenant_id=tenant_id, call_session_id=call.id))

        async with database.transaction() as session:
            service = CapabilityInvocationService(
                CapabilityInvocationRepository(session),
                CallSessionRepository(session),
                ConversationRepository(session),
                IntegrationConnectionRepository(session),
                RuntimeBundleStore(session),
            )
            invocation, created = await service.invoke(
                call.id,
                CapabilityInvocationRequest(
                    tool_call_id="bundle-identity-tool-call",
                    capability="reservation_check_reservation",
                    agent_input={
                        "check_in": "2030-08-10",
                        "check_out": "2030-08-12",
            "room_type": 1,
                        "room_count": 1,
                    },
                ),
            )
            outbox = await session.scalar(
                select(OutboxMessage).where(
                    OutboxMessage.capability_invocation_id == invocation.id
                )
            )

        assert created
        assert invocation.runtime_bundle_id == release.runtime_bundle_id
        assert invocation.tenant_release_id == release.id
        assert outbox is not None
        assert outbox.payload["runtime_bundle_id"] == str(release.runtime_bundle_id)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_component_release_publish_rollback_and_telephony_projection(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    tenant_id = uuid4()
    bundle_factory = _bundle_factory(tenant_id)
    try:
        async with database.transaction() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug="release-hotel",
                    display_name="Release Hotel",
                    business_type="hotel",
                )
            )
            repository = TenantReleaseRepository(session)
            expectations = []
            for component, payload in _initial_payloads().items():
                draft = await repository.save_draft(
                    component=component,
                    tenant_id=tenant_id,
                    payload=payload,
                    expected_version=None,
                )
                expectations.append(
                    DraftExpectation(component, draft.id, draft.version)
                )
            release_one = await TenantReleaseUseCases(repository).publish(
                tenant_id, expectations, bundle_factory, publish_all=True
            )
            release_one_id = release_one.id
            release_one_bundle_id = release_one.runtime_bundle_id
            release_one_telephony_revision_id = release_one.telephony_revision_id

        async with database.transaction() as session:
            repository = TenantReleaseRepository(session)
            telephony_draft = await repository.save_draft(
                component=TenantComponent.TELEPHONY,
                tenant_id=tenant_id,
                payload={"phone_number": "+421551234567"},
                expected_version=None,
            )
            release_two = await TenantReleaseUseCases(repository).publish(
                tenant_id,
                [
                    DraftExpectation(
                        TenantComponent.TELEPHONY,
                        telephony_draft.id,
                        telephony_draft.version,
                    )
                ],
                bundle_factory,
            )
            release_two_id = release_two.id
            release_two_telephony_revision_id = release_two.telephony_revision_id

        async with database.transaction() as session:
            rollback = await TenantReleaseUseCases(
                TenantReleaseRepository(session)
            ).rollback(tenant_id, release_one_id)
            rollback_id = rollback.id

        async with database.transaction() as session:
            tenant = await session.get(Tenant, tenant_id)
            releases = (
                await session.scalars(
                    select(TenantRelease)
                    .where(TenantRelease.tenant_id == tenant_id)
                    .order_by(TenantRelease.release_number)
                )
            ).all()
            provisioning = await session.get(TenantTelephonyProvisioning, tenant_id)
            phone_claim = await session.get(ActivePhoneClaim, "+421551234567")
            bundles = (
                await session.scalars(
                    select(RuntimeBundleRecord).where(
                        RuntimeBundleRecord.tenant_id == tenant_id
                    )
                )
            ).all()

        assert tenant is not None
        assert tenant.active_release_id == rollback_id
        assert [(release.release_number, release.id) for release in releases] == [
            (1, release_one_id),
            (2, release_two_id),
            (3, rollback_id),
        ]
        assert releases[2].source_release_id == release_one_id
        assert releases[2].runtime_bundle_id == release_one_bundle_id
        assert releases[1].telephony_revision_id == release_two_telephony_revision_id
        assert releases[2].telephony_revision_id == release_one_telephony_revision_id
        assert provisioning is not None
        assert provisioning.desired_revision_id == release_one_telephony_revision_id
        assert provisioning.status == "pending"
        assert phone_claim is None
        assert len(bundles) == 2
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_publish_rejects_a_stale_draft_snapshot(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    tenant_id = uuid4()
    try:
        async with database.transaction() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug="stale-release-hotel",
                    display_name="Stale Release Hotel",
                    business_type="hotel",
                )
            )
            repository = TenantReleaseRepository(session)
            draft = await repository.save_draft(
                component=TenantComponent.PROMPT,
                tenant_id=tenant_id,
                payload={"text": "first"},
                expected_version=None,
            )
            stale_version = draft.version
            await repository.save_draft(
                component=TenantComponent.PROMPT,
                tenant_id=tenant_id,
                payload={"text": "second"},
                expected_version=draft.version,
            )

            with pytest.raises(DraftConflictError):
                await TenantReleaseUseCases(repository).publish(
                    tenant_id,
                    [DraftExpectation(TenantComponent.PROMPT, draft.id, stale_version)],
                    _bundle_factory(tenant_id),
                )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_publish_and_web_call_creation_pin_one_atomic_release(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        tenant_id, _, _ = await _publish_ready_tenant(
            database, slug="web-race-hotel", phone_number=None
        )
        async with database.transaction() as session:
            repository = TenantReleaseRepository(session)
            draft = await repository.save_draft(
                component=TenantComponent.PROMPT,
                tenant_id=tenant_id,
                payload={"text": "changed"},
                expected_version=None,
            )
            expectation = DraftExpectation(TenantComponent.PROMPT, draft.id, draft.version)

        async def publish() -> None:
            async with database.transaction() as session:
                await TenantReleaseUseCases(TenantReleaseRepository(session)).publish(
                    tenant_id,
                    [expectation],
                    _bundle_factory(tenant_id),
                )

        async def create_call():
            async with database.transaction() as session:
                return await _call_service(session).create_manual(tenant_id)

        _, (call, created) = await asyncio.gather(publish(), create_call())
        assert created
        assert call.tenant_release_id is not None
        assert call.runtime_bundle_id is not None

        async with database.transaction() as session:
            pinned = await session.get(TenantRelease, call.tenant_release_id)
        assert pinned is not None
        assert pinned.release_number in (1, 2)
        assert call.runtime_bundle_id == pinned.runtime_bundle_id
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_telephony_publish_race_fails_closed_or_pins_old_inbound_release(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    phone_number = "+421551234569"
    try:
        tenant_id, first_release_id, first_bundle_id = await _publish_ready_tenant(
            database, slug="sip-race-hotel", phone_number=phone_number
        )
        async with database.transaction() as session:
            repository = TenantReleaseRepository(session)
            draft = await repository.save_draft(
                component=TenantComponent.TELEPHONY,
                tenant_id=tenant_id,
                payload={"phone_number": phone_number},
                expected_version=None,
            )
            expectation = DraftExpectation(
                TenantComponent.TELEPHONY, draft.id, draft.version
            )

        async def publish() -> None:
            async with database.transaction() as session:
                await TenantReleaseUseCases(TenantReleaseRepository(session)).publish(
                    tenant_id,
                    [expectation],
                    _bundle_factory(tenant_id),
                )

        async def claim():
            try:
                async with database.transaction() as session:
                    return await _call_service(session).claim_inbound_sip(
                        InboundSipClaimRequest(
                            sip_call_id="sip-race",
                            trunk_id="trunk",
                            dispatch_rule_id="rule",
                            caller_number="+421551234568",
                            called_number=phone_number,
                            room_name="sip-race-room",
                            participant_identity="sip-race-participant",
                        )
                    )
            except CallSessionTelephonyNotReadyError:
                return None

        _, result = await asyncio.gather(publish(), claim())
        if result is not None:
            call, created = result
            assert created
            assert (call.tenant_release_id, call.runtime_bundle_id) == (
                first_release_id,
                first_bundle_id,
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_pinned_handoff_fails_closed_when_telephony_changes(
    migrated_database_url: str,
) -> None:
    class Routes:
        async def platform(self):
            return SimpleNamespace(
                outbound_trunk_id="outbound",
                provisioning_status=SimpleNamespace(value="ready"),
            )

    class LiveKit:
        def __init__(self) -> None:
            self.calls = 0
            self.request: dict[str, object] | None = None

        async def create_sip_participant(self, **kwargs):
            self.calls += 1
            self.request = kwargs
            return "handoff-participant", "handoff-sip"

    database = Database(migrated_database_url)
    phone_number = "+421551234570"
    tenant_id = uuid4()
    telephony = RuntimeTelephony(
        caller_number=phone_number,
        handoff_destinations={
            "front_desk": RuntimeHandoffDestination(
                description="Front desk", phone_number="+421551234568"
            )
        },
    )
    try:
        async with database.transaction() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug="pinned-handoff-hotel",
                    display_name="Pinned Handoff Hotel",
                    business_type="hotel",
                )
            )
            repository = TenantReleaseRepository(session)
            expectations = []
            for component, payload in _initial_payloads().items():
                if component is TenantComponent.TELEPHONY:
                    payload = {"phone_number": phone_number}
                draft = await repository.save_draft(
                    component=component,
                    tenant_id=tenant_id,
                    payload=payload,
                    expected_version=None,
                )
                expectations.append(DraftExpectation(component, draft.id, draft.version))
            release = await TenantReleaseUseCases(repository).publish(
                tenant_id,
                expectations,
                _bundle_factory(tenant_id, telephony),
                publish_all=True,
            )
            state = await session.get(TenantTelephonyProvisioning, tenant_id)
            assert state is not None
            state.applied_revision_id = release.telephony_revision_id
            state.status = "ready"
            call = CallSession(
                tenant_id=tenant_id,
                tenant_release_id=release.id,
                runtime_bundle_id=release.runtime_bundle_id,
                channel=CallChannel.SIP,
                direction=CallDirection.INBOUND,
                provider="livekit",
                provider_call_id="pinned-handoff-call",
                room_name="pinned-handoff-room",
                livekit_participant_identity="caller",
                status=CallSessionStatus.CONNECTED,
                started_at=datetime.now(UTC),
                connected_at=datetime.now(UTC),
            )
            session.add(call)

        livekit = LiveKit()
        async with database.transaction() as session:
            service = CallSessionService(
                CallSessionRepository(session),
                Routes(),  # type: ignore[arg-type]
                TenantRepository(session),
                _Conversations(),  # type: ignore[arg-type]
                _Events(),  # type: ignore[arg-type]
                TenantReleaseRepository(session),
                RuntimeBundleStore(session),
            )
            await service.transfer_to_human(
                call.id,
                HumanHandoffRequest(tool_call_id="handoff-1", destination="front_desk"),
                livekit,  # type: ignore[arg-type]
            )
        assert livekit.calls == 1
        assert livekit.request == {
            "room_name": "pinned-handoff-room",
            "participant_identity": f"handoff-{call.id}",
            "phone_number": "+421551234568",
            "caller_number": phone_number,
            "outbound_trunk_id": "outbound",
        }

        async with database.transaction() as session:
            repository = TenantReleaseRepository(session)
            draft = await repository.save_draft(
                component=TenantComponent.TELEPHONY,
                tenant_id=tenant_id,
                payload={"phone_number": phone_number},
                expected_version=None,
            )
            next_release = await TenantReleaseUseCases(repository).publish(
                tenant_id,
                [DraftExpectation(TenantComponent.TELEPHONY, draft.id, draft.version)],
                _bundle_factory(tenant_id, telephony),
            )
            state = await session.get(TenantTelephonyProvisioning, tenant_id)
            assert state is not None
            state.applied_revision_id = next_release.telephony_revision_id
            state.status = "ready"
            pinned = await session.get(CallSession, call.id)
            assert pinned is not None
            pinned.handoff_tool_call_id = None
            service = CallSessionService(
                CallSessionRepository(session),
                Routes(),  # type: ignore[arg-type]
                TenantRepository(session),
                _Conversations(),  # type: ignore[arg-type]
                _Events(),  # type: ignore[arg-type]
                TenantReleaseRepository(session),
                RuntimeBundleStore(session),
            )
            with pytest.raises(HumanHandoffError, match="telephony_not_ready"):
                await service.transfer_to_human(
                    call.id,
                    HumanHandoffRequest(tool_call_id="handoff-2", destination="front_desk"),
                    livekit,  # type: ignore[arg-type]
                )
        assert livekit.calls == 1
    finally:
        await database.close()
