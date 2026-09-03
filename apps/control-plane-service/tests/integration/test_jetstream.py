import os
from datetime import UTC, datetime
from uuid import uuid4

import nats
import pytest
from contracts import (
    COMPONENT_PUBLISHED_SUBJECT,
    ComponentScope,
    ConfigurationComponentPublishedPayloadV1,
    ConfigurationComponentPublishedV1,
)
from control_plane.application.ports.messaging import OutboundMessage
from control_plane.infrastructure.messaging.nats import NatsMessagePublisher
from nats.js.errors import NotFoundError


@pytest.mark.asyncio
async def test_real_jetstream_provisioning_and_acknowledged_publication() -> None:
    url = os.getenv("TEST_NATS_URL")
    if not url:
        pytest.skip("set TEST_NATS_URL to run the JetStream integration test")

    observer = await nats.connect(url)
    jetstream = observer.jetstream()
    publisher = NatsMessagePublisher(url)
    stream_existed = True
    published_sequence: int | None = None
    try:
        try:
            await jetstream.stream_info(publisher.STREAM_NAME)
        except NotFoundError:
            stream_existed = False
        await publisher.connect()
        event = ConfigurationComponentPublishedV1(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            payload=ConfigurationComponentPublishedPayloadV1(
                component_id=uuid4(),
                component_kind="example.settings",
                component_scope=ComponentScope(type="tenant", key="jetstream-test"),
                revision_id=uuid4(),
                revision_number=1,
                schema_version=1,
                previous_active_revision_id=None,
                restored_from_revision_id=None,
            ),
        )
        await publisher.publish(
            OutboundMessage(
                COMPONENT_PUBLISHED_SUBJECT, event.to_bytes(), str(event.event_id)
            )
        )

        info = await jetstream.stream_info(publisher.STREAM_NAME)
        assert info.config.subjects == ["evt.configuration.>", "evt.control_plane.>"]
        message = await jetstream.get_last_msg(
            publisher.STREAM_NAME, COMPONENT_PUBLISHED_SUBJECT
        )
        published_sequence = message.seq
        assert message.subject == COMPONENT_PUBLISHED_SUBJECT
        assert message.headers["Nats-Msg-Id"] == str(event.event_id)
        assert (
            ConfigurationComponentPublishedV1.model_validate_json(message.data) == event
        )
    finally:
        await publisher.close()
        if stream_existed and published_sequence is not None:
            await jetstream.delete_msg(publisher.STREAM_NAME, published_sequence)
        elif not stream_existed:
            await jetstream.delete_stream(publisher.STREAM_NAME)
        await observer.close()
