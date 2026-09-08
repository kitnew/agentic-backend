from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from control_plane.application.command_support import IdempotencyKeyReused, StoredReplay
from control_plane.application.tenant_configuration import (
    TenantConfigurationDesired,
    TenantConfigurationError,
    TenantConfigurationPreconditionFailed,
    TenantConfigurationService,
)
from control_plane.domain.catalogs import CatalogStatus, Profile
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ProfileScope,
)
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.domain.managed_resource_errors import ManagedResourceNotFound
from control_plane.domain.registries import ArchitectureRegistry

NOW = datetime.now(UTC)


def action() -> dict[str, object]:
    return {
        "phase": "post_call",
        "artifact_inputs": {},
        "execution": {
            "integration_key": "hotel",
            "method": "POST",
            "request": {"codec": "json", "mapping": {}},
            "response": {"codec": "json", "mapping": {}},
            "timeout_seconds": 10,
        },
    }


def desired(
    *,
    prompt: str = "tenant",
    actions: tuple[str, ...] = (),
    availability: dict[str, bool] | None = None,
    architecture: str = "cascade",
    profile: str = "sales",
    keyterms: list[str] | None = None,
) -> TenantConfigurationDesired:
    return TenantConfigurationDesired.model_validate(
        {
            "tenant_prompt": {"content": prompt},
            "knowledge": {"content": "knowledge"},
            "agent_personality": {
                "identity": "concierge",
                "display_name": "Concierge",
                "greeting": "Welcome",
                "conversation_scope": "property_only",
            },
            "business_info": {
                "business": {"name": "Hotel", "type": "hotel"},
                "contact": {"phones": [], "emails": []},
                "localization": {
                    "default_locale": "en-US",
                    "timezone": "Europe/Bucharest",
                },
            },
            "actions_definition": {"actions": {key: action() for key in actions}},
            "architecture": {"architecture_key": architecture},
            "profile_reference": {"profile_key": profile},
            "runtime_overrides": {
                "stt": {"keyterms": [] if keyterms is None else keyterms}
            },
            "actions_availability": {"actions": availability or {}},
        }
    )


class Replays:
    def __init__(self):
        self.values = {}
        self.fail = False

    async def get(self, principal, operation, key):
        return self.values.get((principal, operation, key))

    async def add(self, principal, operation, key, fingerprint, result):
        if self.fail:
            raise RuntimeError("replay failed")
        self.values[(principal, operation, key)] = StoredReplay(fingerprint, result)


class Repository:
    def __init__(self):
        self.components = {}
        self.live = {}
        self.revisions = {}
        self.fail_on_save = None
        self.fail_on_publish = None
        self.profile = Profile(
            "sales", "Sales", "Sales", CatalogStatus.ENABLED, 1, NOW, NOW
        )
        self.integrations = {"hotel"}
        address = ComponentAddress(
            ComponentKind("ProfilePrompt"), ProfileScope("sales")
        )
        self.components[address] = (None, self._revision({"content": "profile"}))

    @staticmethod
    def _revision(value, active=None):
        row = type("Revision", (), {})()
        row.id = uuid4()
        row.revision_number = active.revision_number + 1 if active else 1
        row.schema_version = 1
        row.value = value
        row.based_on_revision_id = active.id if active else None
        row.restored_from_revision_id = None
        row.created_at = NOW
        row.created_by = "alice"
        return row

    async def get_component(self, address, *, lock=False):
        draft, active = self.components.get(address, (None, None))
        return address in self.components, draft, active

    async def save_draft(self, address, value, schema_version, _dv, _active, actor):
        if str(address.kind) == self.fail_on_save:
            raise RuntimeError("injected final mutation failure")
        draft, active = self.components.get(address, (None, None))
        row = type("Draft", (), {})()
        row.schema_version = schema_version
        row.value = value
        row.version = draft.version + 1 if draft else 1
        row.based_on_revision_id = active.id if active else None
        row.updated_at = NOW
        row.updated_by = actor
        self.components[address] = (row, active)
        return row

    async def discard_draft(self, address, _version):
        _, active = self.components[address]
        self.components[address] = (None, active)

    async def publish_draft(self, address, _version, _actor, _definition):
        if str(address.kind) == self.fail_on_publish:
            raise RuntimeError("injected final publication failure")
        draft, active = self.components[address]
        row = self._revision(draft.value, active)
        self.components[address] = (None, row)
        self.revisions.setdefault(address, []).append(row)
        return row

    async def get_live(self, address, *, lock=False):
        return self.live.get(address)

    async def set_live(self, address, value, schema_version, actor):
        current = self.live.get(address)
        row = type("Live", (), {})()
        row.address = address
        row.value = value
        row.schema_version = schema_version
        row.generation = current.generation + 1 if current else 1
        row.updated_at = NOW
        row.updated_by = actor
        self.live[address] = row
        return row

    async def get_profile(self, key, *, lock=False):
        return self.profile if key == self.profile.key else None

    async def get_integration_by_key(self, _tenant_id, key, *, lock=False):
        if key not in self.integrations:
            raise ManagedResourceNotFound(key)
        return object()


def setup():
    repository, replays = Repository(), Replays()

    @asynccontextmanager
    async def scope(_tenant_id):
        before = (
            dict(repository.components),
            dict(repository.live),
            {key: list(value) for key, value in repository.revisions.items()},
            dict(replays.values),
        )
        try:
            yield repository, replays
        except Exception:
            (
                repository.components,
                repository.live,
                repository.revisions,
                replays.values,
            ) = before
            raise

    return (
        TenantConfigurationService(
            default_component_definition_registry(), ArchitectureRegistry(), scope
        ),
        repository,
        replays,
    )


@pytest.mark.asyncio
async def test_plan_is_non_mutating_and_apply_obeys_mixed_lifecycles() -> None:
    service, repository, _ = setup()
    before = (dict(repository.components), dict(repository.live))
    plan = await service.plan("tenant-a", desired())
    assert plan.valid and len(plan.changes.immediate) == 4
    assert len(plan.changes.draft) == 5
    assert (repository.components, repository.live) == before

    result = await service.apply("tenant-a", desired(), "*", "alice", "apply")
    assert result.configuration.live.runtime_overrides["stt"]["keyterms"] == []
    assert result.configuration.versioned.tenant_prompt.active is None
    assert result.configuration.versioned.tenant_prompt.draft.content == "tenant"


@pytest.mark.asyncio
async def test_mixed_live_and_versioned_apply_rolls_back_with_replay() -> None:
    service, repository, replays = setup()
    repository.fail_on_save = "ActionsDefinition"
    with pytest.raises(RuntimeError, match="final mutation"):
        await service.apply("tenant-a", desired(), "*", "alice", "failed")
    assert repository.live == {}
    assert not any(address.scope.key == "tenant-a" for address in repository.components)
    assert replays.values == {}

    repository.fail_on_save = None
    replays.fail = True
    with pytest.raises(RuntimeError, match="replay failed"):
        await service.apply("tenant-a", desired(), "*", "alice", "replay-failed")
    assert repository.live == {}


@pytest.mark.asyncio
async def test_draft_only_action_cannot_be_enabled_but_published_action_can() -> None:
    service, _, _ = setup()
    applied = await service.apply(
        "tenant-a", desired(actions=("existing_action",)), "*", "alice", "apply"
    )
    published = await service.publish(
        "tenant-a", service.concurrency_token(applied.configuration), "alice", "publish"
    )
    draft_only = desired(
        actions=("existing_action", "new_action"),
        availability={"new_action": True},
    )
    plan = await service.plan("tenant-a", draft_only)
    assert not plan.valid and plan.errors[-1].code == "unknown_action"

    draft = await service.apply(
        "tenant-a",
        desired(actions=("existing_action", "new_action")),
        service.concurrency_token(published.configuration),
        "alice",
        "draft",
    )
    published = await service.publish(
        "tenant-a",
        service.concurrency_token(draft.configuration),
        "alice",
        "publish-new",
    )
    enabled = await service.apply(
        "tenant-a",
        desired(
            actions=("existing_action", "new_action"),
            availability={"new_action": True},
        ),
        service.concurrency_token(published.configuration),
        "alice",
        "enable",
    )
    assert enabled.configuration.live.actions_availability.actions == {
        "new_action": True
    }


@pytest.mark.asyncio
async def test_missing_is_disabled_false_is_disabled_and_unknown_is_invalid() -> None:
    service, _, _ = setup()
    applied = await service.apply(
        "tenant-a", desired(actions=("existing_action",)), "*", "alice", "apply"
    )
    published = await service.publish(
        "tenant-a", service.concurrency_token(applied.configuration), "alice", "publish"
    )
    disabled = await service.apply(
        "tenant-a",
        desired(actions=("existing_action",), availability={"existing_action": False}),
        service.concurrency_token(published.configuration),
        "alice",
        "disable",
    )
    assert (
        disabled.configuration.live.actions_availability.actions.get("missing", False)
        is False
    )
    assert (
        disabled.configuration.live.actions_availability.actions["existing_action"]
        is False
    )
    invalid = await service.plan(
        "tenant-a",
        desired(actions=("existing_action",), availability={"unknown": True}),
    )
    assert not invalid.valid and invalid.errors[-1].code == "unknown_action"


@pytest.mark.asyncio
async def test_publish_is_atomic_and_only_publishes_versioned_components() -> None:
    service, repository, _ = setup()
    applied = await service.apply("tenant-a", desired(), "*", "alice", "apply")
    repository.fail_on_publish = "ActionsDefinition"
    with pytest.raises(RuntimeError, match="final publication"):
        await service.publish(
            "tenant-a",
            service.concurrency_token(applied.configuration),
            "alice",
            "failed",
        )
    tenant_rows = [
        values
        for address, values in repository.components.items()
        if address.scope.key == "tenant-a"
    ]
    assert all(active is None and draft is not None for draft, active in tenant_rows)
    assert len(repository.live) == 4


@pytest.mark.asyncio
async def test_publish_rejects_removing_an_action_still_present_in_availability() -> (
    None
):
    service, _, _ = setup()
    applied = await service.apply(
        "tenant-a",
        desired(actions=("existing_action",)),
        "*",
        "alice",
        "apply",
    )
    published = await service.publish(
        "tenant-a",
        service.concurrency_token(applied.configuration),
        "alice",
        "publish",
    )
    enabled = await service.apply(
        "tenant-a",
        desired(
            actions=("existing_action",),
            availability={"existing_action": False},
        ),
        service.concurrency_token(published.configuration),
        "alice",
        "availability",
    )
    removal = await service.apply(
        "tenant-a",
        desired(actions=(), availability={"existing_action": False}),
        service.concurrency_token(enabled.configuration),
        "alice",
        "remove",
    )
    with pytest.raises(
        TenantConfigurationError, match="invalidate ActionsAvailability"
    ):
        await service.publish(
            "tenant-a",
            service.concurrency_token(removal.configuration),
            "alice",
            "publish-removal",
        )


@pytest.mark.asyncio
async def test_aggregate_etag_and_replay_precede_concurrency() -> None:
    service, _, _ = setup()
    first = await service.apply("tenant-a", desired(), "*", "alice", "same")
    assert await service.apply("tenant-a", desired(), "*", "alice", "same") == first
    with pytest.raises(IdempotencyKeyReused):
        await service.apply(
            "tenant-a", desired(prompt="different"), "*", "alice", "same"
        )
    with pytest.raises(TenantConfigurationPreconditionFailed):
        await service.apply(
            "tenant-a", desired(prompt="different"), "stale", "alice", "stale"
        )


@pytest.mark.asyncio
async def test_profile_architecture_and_integration_references_are_validated() -> None:
    service, _, _ = setup()
    for value, code in (
        (desired(profile="missing"), "unknown_or_disabled_profile"),
        (desired(architecture="missing"), "unknown_architecture"),
        (desired(actions=("new",)), None),
    ):
        if code is None:
            value = value.model_copy(
                update={
                    "actions_definition": value.actions_definition.model_copy(
                        update={
                            "actions": {
                                "new": value.actions_definition.actions[
                                    "new"
                                ].model_copy(
                                    update={
                                        "execution": value.actions_definition.actions[
                                            "new"
                                        ].execution.model_copy(
                                            update={"integration_key": "missing"}
                                        )
                                    }
                                )
                            }
                        }
                    )
                }
            )
            code = "unknown_integration"
        plan = await service.plan("tenant-a", value)
        assert code in {error.code for error in plan.errors}


def test_exact_tenant_schema_rejects_legacy_and_preserves_absent_vs_empty() -> None:
    payload = desired().model_dump(mode="json")
    payload["runtime_overrides"] = {}
    assert TenantConfigurationDesired.model_validate(payload).runtime_overrides == {}
    payload["runtime_overrides"] = {"stt": {"keyterms": []}}
    assert TenantConfigurationDesired.model_validate(payload).runtime_overrides == {
        "stt": {"keyterms": []}
    }
    payload["runtime_overrides"]["llm"] = {"temperature": 0.5}
    with pytest.raises(ValueError):
        TenantConfigurationDesired.model_validate(payload)
