import asyncio

import pytest
from contracts import ConfigurationComponentPublishedV1
from control_plane.application.components import ComponentService
from control_plane.application.ports.messaging import OutboundMessage
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinition,
    ComponentKind,
    ComponentRegistry,
    ScopeType,
    TenantScope,
)
from control_plane.infrastructure.messaging.outbox import OutboxRelay
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.models import OutboxMessage
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from pydantic import BaseModel
from sqlalchemy import func, select


class ExampleSettings(BaseModel):
    enabled: bool


def components(
    database: Database,
) -> tuple[ComponentService, SqlAlchemyComponentRepository]:
    registry = ComponentRegistry()
    registry.register(
        ComponentDefinition(
            ComponentKind("example.settings"),
            ExampleSettings,
            frozenset({ScopeType.TENANT}),
            1,
        )
    )
    repository = SqlAlchemyComponentRepository(database.sessions)
    return ComponentService(registry, repository), repository  # type: ignore[arg-type]


async def publish(service: ComponentService, address: ComponentAddress, enabled: bool):
    active = await service.get_active(address) if enabled is False else None
    draft = await service.save_draft(
        address,
        {"enabled": enabled},
        1,
        None,
        active.revision_id if active else None,
        "test",
    )
    return await service.publish_draft(address, draft.version, "test")


@pytest.mark.asyncio
async def test_lifecycle_mutations_create_outbox_atomically(
    migrated_database_url: str, monkeypatch
) -> None:
    database = Database(migrated_database_url)
    service, repository = components(database)
    address = ComponentAddress(ComponentKind("example.settings"), TenantScope("one"))
    failed = ComponentAddress(ComponentKind("example.settings"), TenantScope("failed"))
    try:
        draft = await service.save_draft(
            address, {"enabled": True}, 1, None, None, "test"
        )
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == 0
            )
        await service.discard_draft(address, draft.version)
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(OutboxMessage))
                == 0
            )

        first = await publish(service, address, True)
        restored = await service.rollback(address, first.revision_number, "test")
        async with database.sessions() as session:
            rows = (
                await session.scalars(
                    select(OutboxMessage).order_by(OutboxMessage.revision_number)
                )
            ).all()
        assert len(rows) == 2
        normal = ConfigurationComponentPublishedV1.model_validate(rows[0].payload)
        rollback = ConfigurationComponentPublishedV1.model_validate(rows[1].payload)
        assert normal.payload.component_id == rows[0].component_id
        assert normal.payload.revision_id == first.revision_id
        assert normal.payload.previous_active_revision_id is None
        assert normal.payload.restored_from_revision_id is None
        assert rollback.payload.revision_id == restored.revision_id
        assert rollback.payload.previous_active_revision_id == first.revision_id
        assert rollback.payload.restored_from_revision_id == first.revision_id

        await service.save_draft(failed, {"enabled": True}, 1, None, None, "test")

        def fail_outbox(*_args) -> None:
            raise RuntimeError("outbox insert failed")

        monkeypatch.setattr(repository, "_add_outbox", fail_outbox)
        with pytest.raises(RuntimeError, match="outbox insert failed"):
            await service.publish_draft(failed, 1, "test")
        exists, failed_draft, active = await repository.get_component(failed)
        assert exists and failed_draft is not None and active is None
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.component_id != rows[0].component_id)
                )
                == 0
            )
    finally:
        await database.close()


class RecordingPublisher:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.messages: list[OutboundMessage] = []

    async def publish(self, message: OutboundMessage) -> None:
        self.messages.append(message)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary failure")


@pytest.mark.asyncio
async def test_relay_retries_same_event_and_preserves_component_order(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service, _ = components(database)
    address = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("ordered")
    )
    try:
        await publish(service, address, True)
        await publish(service, address, False)
        publisher = RecordingPublisher(failures=1)
        relay = OutboxRelay(database.sessions, publisher)

        assert await relay.relay_once()
        async with database.sessions() as session:
            first = await session.scalar(
                select(OutboxMessage).order_by(OutboxMessage.revision_number)
            )
            assert first is not None
            assert first.published_at is None
            assert first.attempt_count == 1
            assert first.last_error == "temporary failure"

        assert await relay.relay_once()
        assert await relay.relay_once()
        events = [
            ConfigurationComponentPublishedV1.model_validate_json(message.payload)
            for message in publisher.messages
        ]
        assert [event.payload.revision_number for event in events] == [1, 1, 2]
        assert publisher.messages[0].message_id == publisher.messages[1].message_id
        assert publisher.messages[2].message_id != publisher.messages[1].message_id
        async with database.sessions() as session:
            rows = (await session.scalars(select(OutboxMessage))).all()
            assert all(row.published_at is not None for row in rows)
    finally:
        await database.close()


class BlockingPublisher:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, _message: OutboundMessage) -> None:
        self.started.set()
        await self.release.wait()


@pytest.mark.asyncio
async def test_two_relays_do_not_claim_same_component_event(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service, _ = components(database)
    address = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("claimed-once")
    )
    publisher = BlockingPublisher()
    first = OutboxRelay(database.sessions, publisher)
    second = OutboxRelay(database.sessions, RecordingPublisher())
    try:
        await publish(service, address, True)
        in_flight = asyncio.create_task(first.relay_once())
        await publisher.started.wait()
        assert not await second.relay_once()
        publisher.release.set()
        assert await in_flight
    finally:
        publisher.release.set()
        await database.close()


@pytest.mark.asyncio
async def test_relay_shutdown_is_graceful_and_idempotent(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    relay = OutboxRelay(database.sessions, RecordingPublisher(), 0.01)
    try:
        await relay.start()
        assert relay.ready
        await relay.stop()
        await relay.stop()
        assert not relay.ready
    finally:
        await database.close()
