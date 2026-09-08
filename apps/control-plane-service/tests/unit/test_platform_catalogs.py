from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from control_plane.application.platform_catalogs import (
    CatalogConflict,
    CatalogPreconditionFailed,
    InteractionModeCreate,
    InteractionModeUpdate,
    PlatformCatalogService,
    ProfileCreate,
    ProfileUpdate,
)
from control_plane.domain.catalogs import CatalogStatus, InteractionMode, Profile

NOW = datetime.now(UTC)


class Replays:
    def __init__(self):
        self.values = {}

    async def get(self, principal, operation, key):
        return self.values.get((principal, operation, key))

    async def add(self, principal, operation, key, fingerprint, result):
        from control_plane.application.command_support import StoredReplay

        self.values[(principal, operation, key)] = StoredReplay(fingerprint, result)


class Repository:
    def __init__(self):
        self.profiles = {}
        self.interaction_modes = {}

    async def get_profile(self, key, *, lock=False):
        return self.profiles.get(key)

    async def list_profiles(self, *, lock=False):
        return tuple(self.profiles.values())

    async def put_profile(self, key, name, description, status, actor):
        current = self.profiles.get(key)
        stored = Profile(
            key,
            name,
            description,
            status,
            current.generation + 1 if current else 1,
            current.created_at if current else NOW,
            NOW,
        )
        self.profiles[key] = stored
        return stored

    async def get_interaction_mode(self, key, *, lock=False):
        return self.interaction_modes.get(key)

    async def list_interaction_modes(self, *, lock=False):
        return tuple(self.interaction_modes.values())

    async def put_interaction_mode(self, key, name, description, status, actor):
        current = self.interaction_modes.get(key)
        stored = InteractionMode(
            key,
            name,
            description,
            status,
            current.generation + 1 if current else 1,
            current.created_at if current else NOW,
            NOW,
        )
        self.interaction_modes[key] = stored
        return stored


def service():
    repository, replays = Repository(), Replays()

    @asynccontextmanager
    async def scope():
        yield repository, replays

    return PlatformCatalogService(scope), repository


@pytest.mark.asyncio
async def test_profile_crud_is_immediate_stable_keyed_and_retry_safe() -> None:
    catalog, repository = service()
    created = await catalog.create_profile(
        ProfileCreate(key="sales", name="Sales", description="Sell"),
        "alice",
        "create",
    )
    assert created.status is CatalogStatus.ENABLED
    assert (await catalog.get_profile("sales")) == created
    assert (
        await catalog.create_profile(
            ProfileCreate(key="sales", name="Sales", description="Sell"),
            "alice",
            "create",
        )
        == created
    )

    updated = await catalog.update_profile(
        "sales",
        ProfileUpdate(name="Revenue", description="Sell more"),
        catalog.concurrency_token(created),
        "alice",
        "update",
    )
    assert updated.key == "sales" and updated.name == "Revenue"
    assert repository.profiles["sales"] == updated

    disabled = await catalog.set_profile_enabled(
        "sales",
        False,
        catalog.concurrency_token(updated),
        "alice",
        "disable",
    )
    assert disabled.status is CatalogStatus.DISABLED
    with pytest.raises(CatalogPreconditionFailed):
        await catalog.update_profile(
            "sales",
            ProfileUpdate(name="Stale", description="stale"),
            "stale",
            "alice",
            "stale",
        )


@pytest.mark.asyncio
async def test_profile_key_cannot_be_recreated_or_changed_by_update() -> None:
    catalog, _ = service()
    created = await catalog.create_profile(
        ProfileCreate(key="sales", name="Sales", description="Sell"),
        "alice",
        "create",
    )
    with pytest.raises(CatalogConflict):
        await catalog.create_profile(
            ProfileCreate(key="sales", name="Other", description="Other"),
            "alice",
            "other-key",
        )
    assert "key" not in ProfileUpdate.model_fields
    assert catalog.concurrency_token(created)


@pytest.mark.asyncio
async def test_interaction_mode_crud_is_immediate_stable_keyed_and_retry_safe() -> None:
    catalog, repository = service()
    created = await catalog.create_interaction_mode(
        InteractionModeCreate(key="voice", name="Voice", description="Calls"),
        "alice",
        "create-mode",
    )
    assert created.status is CatalogStatus.ENABLED
    updated = await catalog.update_interaction_mode(
        "voice",
        InteractionModeUpdate(name="Telephone", description="Voice calls"),
        catalog.concurrency_token(created),
        "alice",
        "update-mode",
    )
    assert updated.key == "voice" and updated.name == "Telephone"
    assert repository.interaction_modes["voice"] == updated
    assert "key" not in InteractionModeUpdate.model_fields
