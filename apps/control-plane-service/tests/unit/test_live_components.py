from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from control_plane.application.command_support import IdempotencyKeyReused, StoredReplay
from control_plane.application.live_components import (
    LiveComponentNotFound,
    LiveComponentPreconditionFailed,
    LiveComponentService,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    PlatformScope,
    SystemScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)
from control_plane.domain.frozen_components import default_component_definition_registry

NOW = datetime.now(UTC)


class Repository:
    def __init__(self) -> None:
        self.values = {}

    async def get(self, address, *, lock=False):
        return self.values.get(address)

    async def set(self, address, value, schema_version, actor):
        current = self.values.get(address)
        state = (
            replace(
                current,
                value=value,
                generation=current.generation + 1,
                updated_by=actor,
            )
            if current
            else __import__(
                "control_plane.domain.live_components", fromlist=["LiveComponentState"]
            ).LiveComponentState(address, value, schema_version, 1, NOW, actor)
        )
        self.values[address] = state
        return state


class Replays:
    def __init__(self) -> None:
        self.values = {}

    async def get(self, principal, operation, key):
        return self.values.get((principal, operation, key))

    async def add(self, principal, operation, key, fingerprint, result):
        self.values[(principal, operation, key)] = StoredReplay(fingerprint, result)


def service():
    repository, replays = Repository(), Replays()

    @asynccontextmanager
    async def scope(_address):
        yield repository, replays

    return (
        LiveComponentService(default_component_definition_registry(), scope),
        repository,
        replays,
    )


@pytest.mark.asyncio
async def test_live_component_create_updates_current_without_versioned_state() -> None:
    live, repository, _ = service()
    address = ComponentAddress(ComponentKind("TTSDefaults"), SystemScope())
    first = await live.set(
        address,
        {"deployment_ref": str(uuid4()), "default_voice_id": "marin"},
        "*",
        "alice",
        "create",
    )
    second = await live.set(
        address,
        {"deployment_ref": str(uuid4()), "default_voice_id": "alloy"},
        live.concurrency_token(first),
        "alice",
        "update",
    )

    assert await live.get(address) == second
    assert second.generation == 2
    assert len(repository.values) == 1
    assert not hasattr(second, "draft")
    assert not hasattr(second, "revision_number")


@pytest.mark.asyncio
async def test_live_component_rejects_wrong_lifecycle_scope_and_invalid_value() -> None:
    live, _, _ = service()
    with pytest.raises(ScopeNotAllowed):
        await live.set(
            ComponentAddress(ComponentKind("TTSDefaults"), PlatformScope()),
            {"deployment_ref": str(uuid4()), "default_voice_id": "marin"},
            "*",
            "alice",
            "wrong-scope",
        )
    with pytest.raises(ValueError, match="not a live component"):
        await live.set(
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()),
            {"content": "prompt"},
            "*",
            "alice",
            "wrong-lifecycle",
        )
    address = ComponentAddress(ComponentKind("TTSDefaults"), SystemScope())
    current = await live.set(
        address,
        {"deployment_ref": str(uuid4()), "default_voice_id": "marin"},
        "*",
        "alice",
        "valid",
    )
    with pytest.raises(InvalidComponentValue):
        await live.set(
            address,
            {"default_voice_id": "marin"},
            live.concurrency_token(current),
            "alice",
            "bad",
        )
    assert await live.get(address) == current


@pytest.mark.asyncio
async def test_live_component_replay_precedes_stale_concurrency() -> None:
    live, _, _ = service()
    address = ComponentAddress(ComponentKind("TTSDefaults"), SystemScope())
    payload = {"deployment_ref": str(uuid4()), "default_voice_id": "marin"}
    first = await live.set(address, payload, "*", "alice", "same")
    assert await live.set(address, payload, "*", "alice", "same") == first
    with pytest.raises(IdempotencyKeyReused):
        await live.set(
            address,
            {**payload, "default_voice_id": "changed"},
            "*",
            "alice",
            "same",
        )
    with pytest.raises(LiveComponentPreconditionFailed):
        await live.set(address, payload, "stale", "alice", "stale")
    with pytest.raises(LiveComponentNotFound):
        await live.get(ComponentAddress(ComponentKind("Policies"), SystemScope()))
