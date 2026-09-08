from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from control_plane.application.command_support import IdempotencyKeyReused, StoredReplay
from control_plane.application.platform_configuration import (
    PlatformConfigurationDesired,
    PlatformConfigurationError,
    PlatformConfigurationPreconditionFailed,
    PlatformConfigurationService,
)
from control_plane.domain.catalogs import (
    CatalogStatus,
    InteractionMode,
    Profile,
)
from control_plane.domain.components import ComponentDefinitionRegistry
from control_plane.domain.frozen_components import default_component_definition_registry

NOW = datetime.now(UTC)


def desired(*, system="system", profile="profile", interaction="interaction"):
    return PlatformConfigurationDesired.model_validate(
        {
            "system_prompt": {"content": system},
            "profiles": [
                {
                    "key": "sales",
                    "name": "Sales",
                    "description": "Sales profile",
                    "status": "enabled",
                    "prompt": {"content": profile},
                }
            ],
            "interaction_modes": [
                {
                    "key": "voice",
                    "name": "Voice",
                    "description": "Voice mode",
                    "status": "enabled",
                    "prompt": {"content": interaction},
                }
            ],
        }
    )


class Replays:
    def __init__(self):
        self.values = {}

    async def get(self, principal, operation, key):
        return self.values.get((principal, operation, key))

    async def add(self, principal, operation, key, fingerprint, result):
        self.values[(principal, operation, key)] = StoredReplay(fingerprint, result)


class Repository:
    def __init__(self):
        self.profiles = {}
        self.modes = {}
        self.components = {}
        self.revisions = {}
        self.fail_on_kind = None

    async def list_profiles(self, *, lock=False):
        return tuple(self.profiles.values())

    async def list_interaction_modes(self, *, lock=False):
        return tuple(self.modes.values())

    async def get_profile(self, key, *, lock=False):
        return self.profiles.get(key)

    async def get_interaction_mode(self, key, *, lock=False):
        return self.modes.get(key)

    async def put_profile(self, key, name, description, status, actor):
        current = self.profiles.get(key)
        stored = Profile(
            key,
            name,
            description,
            status,
            (current.generation + 1) if current else 1,
            current.created_at if current else NOW,
            NOW,
        )
        self.profiles[key] = stored
        return stored

    async def put_interaction_mode(self, key, name, description, status, actor):
        current = self.modes.get(key)
        stored = InteractionMode(
            key,
            name,
            description,
            status,
            (current.generation + 1) if current else 1,
            current.created_at if current else NOW,
            NOW,
        )
        self.modes[key] = stored
        return stored

    async def get_component(self, address, *, lock=False):
        draft, active = self.components.get(address, (None, None))
        return address in self.components, draft, active

    async def save_draft(
        self,
        address,
        value,
        schema_version,
        expected_draft_version,
        expected_active_revision_id,
        actor,
    ):
        if str(address.kind) == self.fail_on_kind:
            raise RuntimeError("injected final mutation failure")
        draft, active = self.components.get(address, (None, None))
        row = type("Draft", (), {})()
        row.schema_version = schema_version
        row.value = value
        row.version = (draft.version + 1) if draft else 1
        row.based_on_revision_id = active.id if active else None
        row.updated_at = NOW
        row.updated_by = actor
        self.components[address] = (row, active)
        return row

    async def discard_draft(self, address, expected_draft_version):
        _, active = self.components[address]
        self.components[address] = (None, active)

    async def publish_draft(self, address, expected_draft_version, actor, definition):
        if str(address.kind) == self.fail_on_kind:
            raise RuntimeError("injected final mutation failure")
        draft, active = self.components[address]
        row = type("Revision", (), {})()
        row.id = __import__("uuid").uuid4()
        row.revision_number = (active.revision_number + 1) if active else 1
        row.schema_version = draft.schema_version
        row.value = draft.value
        row.based_on_revision_id = active.id if active else None
        row.restored_from_revision_id = None
        row.created_at = NOW
        row.created_by = actor
        self.components[address] = (None, row)
        self.revisions.setdefault(address, []).append(row)
        return row

    async def get_draft(self, address):
        return self.components.get(address, (None, None))[0]

    async def get_active(self, address):
        return self.components.get(address, (None, None))[1]

    async def get_revision(self, address, revision_number):
        return next(
            (
                row
                for row in self.revisions.get(address, ())
                if row.revision_number == revision_number
            ),
            None,
        )

    async def list_revisions(self, address, limit):
        return tuple(reversed(self.revisions.get(address, ())[-limit:]))


def setup():
    repository, replays = Repository(), Replays()

    @asynccontextmanager
    async def scope():
        before = (
            dict(repository.profiles),
            dict(repository.modes),
            dict(repository.components),
            {key: list(value) for key, value in repository.revisions.items()},
            dict(replays.values),
        )
        try:
            yield repository, replays
        except Exception:
            (
                repository.profiles,
                repository.modes,
                repository.components,
                repository.revisions,
                replays.values,
            ) = before
            raise

    return (
        PlatformConfigurationService(default_component_definition_registry(), scope),
        repository,
        replays,
    )


@pytest.mark.asyncio
async def test_same_apply_catalog_entries_are_immediate_and_prompts_are_drafts() -> (
    None
):
    service, repository, _ = setup()
    requested = desired()

    plan = await service.plan(requested)
    assert plan.valid
    assert {change.path for change in plan.catalog_changes} == {
        "profiles.sales",
        "interaction_modes.voice",
    }
    assert len(plan.draft_changes) == 3
    assert repository.profiles == repository.modes == repository.components == {}

    result = await service.apply(requested, "*", "alice", "apply")
    assert result.catalogs_updated == (
        "profiles.sales",
        "interaction_modes.voice",
    )
    assert set(result.drafts_saved) == {
        "system_prompt",
        "profiles.sales.prompt",
        "interaction_modes.voice.prompt",
    }
    assert result.configuration.profiles[0].status is CatalogStatus.ENABLED
    assert result.configuration.profiles[0].prompt.active is None
    assert result.configuration.profiles[0].prompt.draft.content == "profile"
    assert all(active is None for _, active in repository.components.values())


@pytest.mark.asyncio
async def test_get_absent_platform_configuration_is_not_found() -> None:
    service, _, _ = setup()

    with pytest.raises(PlatformConfigurationError):
        await service.get()


@pytest.mark.asyncio
async def test_apply_is_atomic_and_replay_precedes_aggregate_concurrency() -> None:
    service, repository, _ = setup()
    repository.fail_on_kind = "InteractionPrompt"
    with pytest.raises(RuntimeError, match="final mutation"):
        await service.apply(desired(), "*", "alice", "failed")
    assert repository.profiles == repository.modes == repository.components == {}

    repository.fail_on_kind = None
    first = await service.apply(desired(), "*", "alice", "same")
    assert await service.apply(desired(), "*", "alice", "same") == first
    with pytest.raises(PlatformConfigurationPreconditionFailed):
        await service.apply(desired(system="changed"), "stale", "alice", "stale")


@pytest.mark.asyncio
async def test_publish_is_all_or_none_and_catalog_metadata_does_not_change_history() -> (
    None
):
    service, repository, _ = setup()
    applied = await service.apply(desired(), "*", "alice", "apply")
    repository.fail_on_kind = "InteractionPrompt"
    with pytest.raises(RuntimeError, match="final mutation"):
        await service.publish(
            service.concurrency_token(applied.configuration), "alice", "failed-publish"
        )
    assert all(active is None for _, active in repository.components.values())

    repository.fail_on_kind = None
    published = await service.publish(
        service.concurrency_token(applied.configuration), "alice", "publish"
    )
    assert len(published.published_components) == 3
    assert (
        await service.publish(
            service.concurrency_token(applied.configuration), "alice", "publish"
        )
        == published
    )
    with pytest.raises(IdempotencyKeyReused):
        await service.publish("different", "alice", "publish")
    history_before = {
        address: tuple(rows) for address, rows in repository.revisions.items()
    }

    changed_payload = desired().model_dump(mode="json")
    changed_payload["profiles"][0]["name"] = "Renamed"
    changed = PlatformConfigurationDesired.model_validate(changed_payload)
    await service.apply(
        changed,
        service.concurrency_token(published.configuration),
        "alice",
        "metadata",
    )
    assert repository.revisions == {
        address: list(rows) for address, rows in history_before.items()
    }


def test_platform_desired_rejects_duplicate_catalog_keys_and_invalid_schema() -> None:
    payload = desired().model_dump(mode="json")
    payload["profiles"].append(payload["profiles"][0])
    with pytest.raises(ValueError, match="duplicate profile key"):
        PlatformConfigurationDesired.model_validate(payload)

    payload = desired().model_dump(mode="json")
    payload["interaction_modes"][0]["unexpected"] = True
    with pytest.raises(ValueError):
        PlatformConfigurationDesired.model_validate(payload)


@pytest.mark.asyncio
async def test_complete_desired_document_cannot_implicitly_remove_catalog_entries() -> (
    None
):
    service, _, _ = setup()
    applied = await service.apply(desired(), "*", "alice", "apply")
    payload = desired().model_dump(mode="json")
    payload["profiles"] = []
    requested = PlatformConfigurationDesired.model_validate(payload)

    plan = await service.plan(requested)
    assert not plan.valid
    assert plan.errors[0].code == "catalog_entry_removal_unsupported"
    with pytest.raises(PlatformConfigurationError):
        await service.apply(
            requested,
            service.concurrency_token(applied.configuration),
            "alice",
            "remove",
        )


@pytest.mark.asyncio
async def test_plan_validates_prompts_through_component_registry() -> None:
    _, repository, replays = setup()

    @asynccontextmanager
    async def scope():
        yield repository, replays

    service = PlatformConfigurationService(ComponentDefinitionRegistry(), scope)
    plan = await service.plan(desired())
    assert not plan.valid
    assert {issue.path for issue in plan.errors} == {
        "system_prompt",
        "profiles.sales.prompt",
        "interaction_modes.voice.prompt",
    }
