import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from contracts import (
    AppendConversationMessage,
    ConversationMessageRole,
)
from livekit.agents import llm

from voice_agent.backend import BackendClient

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 128
DRAIN_TIMEOUT_SECONDS = 5.0
MESSAGE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "agent-platform/voice/conversation-message/v1",
)


@dataclass(frozen=True)
class PersistableMessage:
    payload: AppendConversationMessage


def message_from_event(call_id: UUID, event: object) -> PersistableMessage | None:
    item = getattr(event, "item", None)
    if not isinstance(item, llm.ChatMessage):
        raise TypeError("unsupported committed conversation item")
    if item.role not in ("user", "assistant"):
        raise TypeError("unsupported committed message role")
    content = item.raw_text_content
    if not content:
        return None
    return PersistableMessage(
        payload=AppendConversationMessage(
            message_id=uuid5(MESSAGE_NAMESPACE, f"{call_id}:{item.id}"),
            role=ConversationMessageRole(item.role),
            content=content,
            interrupted=item.interrupted,
            source_created_at=datetime.fromtimestamp(item.created_at, UTC),
        )
    )


class ConversationPersistence:
    def __init__(self, backend: BackendClient, call_id: UUID) -> None:
        self._backend = backend
        self._call_id = call_id
        self._queue: asyncio.Queue[PersistableMessage | None] = asyncio.Queue(
            maxsize=QUEUE_MAXSIZE
        )
        self._writer = asyncio.create_task(self._write())
        self._accepting = True
        self._incomplete = False

    @property
    def incomplete(self) -> bool:
        return self._incomplete

    def on_conversation_item_added(self, event: object) -> None:
        if not self._accepting:
            self._incomplete = True
            return
        try:
            message = message_from_event(self._call_id, event)
        except TypeError, ValueError:
            self._incomplete = True
            logger.warning("unsupported committed conversation item")
            return
        if message is None:
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            self._incomplete = True
            logger.error("conversation persistence queue overflow")

    async def finish(self) -> bool:
        self._accepting = False
        try:
            await asyncio.wait_for(
                self._queue.join(),
                timeout=DRAIN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            self._incomplete = True
            self._writer.cancel()
            await asyncio.gather(self._writer, return_exceptions=True)
            return False
        await self._queue.put(None)
        await self._writer
        return not self._incomplete

    async def _write(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                if message is None:
                    return
                try:
                    await self._backend.append_conversation_message(
                        self._call_id,
                        message.payload,
                    )
                except Exception:
                    self._incomplete = True
                    logger.exception(
                        "conversation message persistence failed",
                        extra={
                            "message_id": str(message.payload.message_id),
                            "role": message.payload.role.value,
                        },
                    )
            finally:
                self._queue.task_done()
