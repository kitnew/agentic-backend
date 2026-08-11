from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import Awaitable, Callable
from typing import cast

import httpx
from contracts import (
    CommandError,
    CommandResult,
    ExecutePostCallAction,
    GenerateCallSummary,
    MaterializeArtifactRepresentation,
    MessageEnvelope,
    parse_command,
)
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from job_worker.worker import (
    BackendClient,
    ExecutionError,
    ManagedWebhookPostJsonHandler,
    Settings,
)

CommandHandler = Callable[
    [
        GenerateCallSummary | ExecutePostCallAction | MaterializeArtifactRepresentation,
        MessageEnvelope,
    ],
    Awaitable[dict[str, object]],
]


class GenerateCallSummaryHandler:
    def __init__(
        self, settings: Settings, backend: BackendClient, client: httpx.AsyncClient
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._client = client

    async def __call__(
        self,
        command: GenerateCallSummary
        | ExecutePostCallAction
        | MaterializeArtifactRepresentation,
        envelope: MessageEnvelope,
    ) -> dict[str, object]:
        if not isinstance(command, GenerateCallSummary):
            raise ExecutionError(
                "invalid_command", "Invalid summary command", transient=False
            )
        if not all(
            (
                self._settings.azure_openai_api_key,
                self._settings.azure_openai_endpoint,
                self._settings.azure_openai_deployment,
                self._settings.azure_openai_api_version,
            )
        ):
            raise ExecutionError(
                "summary_provider_unconfigured",
                "Summary provider is not configured",
                transient=False,
            )
        context = await self._backend.finalization_context(
            command.call_id, command.finalization_id, envelope.message_id
        )
        response = await self._client.post(
            (
                f"{self._settings.azure_openai_endpoint.rstrip('/')}"
                f"/openai/deployments/{self._settings.azure_openai_deployment}"
                "/chat/completions"
            ),
            params={"api-version": self._settings.azure_openai_api_version},
            headers={"api-key": self._settings.azure_openai_api_key},
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": "Summarize this call accurately and concisely.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False),
                    },
                ]
            },
        )
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise ExecutionError(
                "summary_provider_transient_error",
                "Summary provider temporarily failed",
                transient=True,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ExecutionError(
                "summary_provider_error", "Summary generation failed", transient=False
            )
        try:
            summary = response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ExecutionError(
                "summary_response_invalid",
                "Summary provider response is invalid",
                transient=False,
            ) from error
        if not summary:
            raise ExecutionError(
                "summary_response_invalid", "Summary is empty", transient=False
            )
        return {"summary": summary}


class ExecutePostCallActionHandler:
    def __init__(
        self, backend: BackendClient, webhooks: ManagedWebhookPostJsonHandler
    ) -> None:
        self._backend = backend
        self._webhooks = webhooks

    async def __call__(
        self,
        command: GenerateCallSummary
        | ExecutePostCallAction
        | MaterializeArtifactRepresentation,
        envelope: MessageEnvelope,
    ) -> dict[str, object]:
        if not isinstance(command, ExecutePostCallAction):
            raise ExecutionError(
                "invalid_command", "Invalid action command", transient=False
            )
        plan = await self._backend.post_call_action(
            command.call_id,
            command.finalization_id,
            command.action_id,
            envelope.message_id,
        )
        if plan.body_bindings:
            result = await self._webhooks.execute(
                plan,
                {
                    binding.payload_path: self._backend.representation_content(
                        binding.representation_id, envelope.message_id
                    )
                    for binding in plan.body_bindings
                },
            )
        else:
            result = await self._webhooks.execute(plan)
        return {
            "reference": result.reference,
            "deduplicated": result.deduplicated,
            "data": result.data,
        }


class MaterializeArtifactRepresentationHandler:
    def __init__(self, backend: BackendClient) -> None:
        self._backend = backend

    async def __call__(
        self,
        command: GenerateCallSummary
        | ExecutePostCallAction
        | MaterializeArtifactRepresentation,
        envelope: MessageEnvelope,
    ) -> dict[str, object]:
        if not isinstance(command, MaterializeArtifactRepresentation):
            raise ExecutionError(
                "invalid_command", "Invalid materialization command", transient=False
            )
        source, artifact, target = await self._backend.materialization_source(
            command.representation_id, envelope.message_id
        )
        if (artifact, target) == ("call_recording", "base64_text"):
            content = b64encode(source)
        elif (artifact, target) == ("transcript", "plain_text"):
            try:
                messages = json.loads(source)
                content = "\n".join(
                    f"{item['role']}: {item['content']}" for item in messages
                ).encode()
            except (KeyError, TypeError, ValueError) as error:
                raise ExecutionError(
                    "artifact_source_invalid",
                    "Artifact source is invalid",
                    transient=False,
                ) from error
        else:
            raise ExecutionError(
                "representation_unsupported",
                "Artifact representation is unsupported",
                transient=False,
            )
        return await self._backend.store_representation(
            command.representation_id,
            envelope.message_id,
            content,
            "text/plain; charset=utf-8",
        )


class CommandWorker:
    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        handlers: dict[str, CommandHandler],
    ) -> None:
        if len(handlers) != len(set(handlers)):
            raise ValueError("each command type must have exactly one handler")
        self._settings = settings
        self._redis = redis
        self._handlers = handlers

    async def run(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._settings.command_stream,
                self._settings.command_group,
                id="0",
                mkstream=True,
            )
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        while True:
            await self.recover_stale()
            messages = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                await self._redis.xreadgroup(
                    self._settings.command_group,
                    self._settings.consumer,
                    {self._settings.command_stream: ">"},
                    count=10,
                    block=5000,
                ),
            )
            for _, batch in messages:
                for message_id, fields in batch:
                    await self.handle(message_id, fields)

    async def recover_stale(self) -> None:
        claimed = cast(
            tuple[str, list[tuple[str, dict[str, str]]], list[str]],
            await self._redis.xautoclaim(
                self._settings.command_stream,
                self._settings.command_group,
                self._settings.consumer,
                min_idle_time=self._settings.stale_idle_ms,
                start_id="0-0",
                count=10,
            ),
        )
        for message_id, fields in claimed[1]:
            await self.handle(message_id, fields)

    async def handle(self, message_id: str, fields: dict[str, str]) -> None:
        try:
            envelope = MessageEnvelope.model_validate_json(fields["message"])
            command = parse_command(envelope)
            attempt = int(fields.get("attempt", "1"))
            if attempt < 1 or attempt > self._settings.max_retries + 1:
                raise ValueError("invalid command attempt")
        except KeyError, ValueError, ValidationError:
            await self._dead_letter(message_id, "unknown", "invalid_command")
            return
        completed_key = f"application:commands:completed:{envelope.message_id}"
        completed = await self._redis.get(completed_key)
        if completed is not None:
            await self._redis.xadd(
                self._settings.command_result_stream, {"message": completed}
            )
            await self._ack(message_id)
            return
        handler = self._handlers.get(envelope.message_type)
        if handler is None:
            await self._terminal_failure(
                message_id,
                envelope,
                attempt,
                ExecutionError(
                    "unknown_command_type", "Command is unsupported", transient=False
                ),
            )
            return
        try:
            output = await handler(command, envelope)
        except httpx.HTTPError, OSError:
            execution_error = ExecutionError(
                "command_transport_error", "Command transport failed", transient=True
            )
            if attempt <= self._settings.max_retries:
                await self._redis.xadd(
                    self._settings.command_stream,
                    {
                        "message": envelope.model_dump_json(),
                        "attempt": str(attempt + 1),
                    },
                )
                await self._ack(message_id)
                return
            await self._terminal_failure(message_id, envelope, attempt, execution_error)
            return
        except ExecutionError as error:
            if error.transient and attempt <= self._settings.max_retries:
                await self._redis.xadd(
                    self._settings.command_stream,
                    {
                        "message": envelope.model_dump_json(),
                        "attempt": str(attempt + 1),
                    },
                )
                await self._ack(message_id)
                return
            await self._terminal_failure(message_id, envelope, attempt, error)
            return
        except Exception:  # noqa: BLE001 - command boundary returns a safe error
            await self._terminal_failure(
                message_id,
                envelope,
                attempt,
                ExecutionError(
                    "command_execution_error",
                    "Command execution failed",
                    transient=False,
                ),
            )
            return
        result = CommandResult(
            command_id=envelope.message_id,
            command_type=command.command_type,
            status="succeeded",
            output=output,
            attempt=attempt,
        )
        await self._publish_result(envelope, result, completed_key)
        await self._ack(message_id)

    async def _terminal_failure(
        self,
        message_id: str,
        envelope: MessageEnvelope,
        attempt: int,
        error: ExecutionError,
    ) -> None:
        result = CommandResult(
            command_id=envelope.message_id,
            command_type=envelope.message_type,  # type: ignore[arg-type]
            status="failed",
            error=CommandError(
                code=error.code,
                message=error.safe_message,
                transient=error.transient,
            ),
            attempt=attempt,
        )
        await self._publish_result(
            envelope,
            result,
            f"application:commands:completed:{envelope.message_id}",
        )
        await self._dead_letter(message_id, str(envelope.message_id), error.code)

    async def _publish_result(
        self, envelope: MessageEnvelope, result: CommandResult, completed_key: str
    ) -> None:
        message = MessageEnvelope(
            message_kind="command_result",
            message_type="command.result",
            correlation_id=envelope.correlation_id,
            causation_id=envelope.message_id,
            tenant_id=envelope.tenant_id,
            payload=result.model_dump(mode="json"),
        ).model_dump_json()
        await self._redis.xadd(
            self._settings.command_result_stream, {"message": message}
        )
        await self._redis.set(completed_key, message, ex=7 * 24 * 60 * 60)

    async def _dead_letter(
        self, message_id: str, command_id: str, error_code: str
    ) -> None:
        await self._redis.xadd(
            self._settings.command_dead_letter_stream,
            {
                "source_message_id": message_id,
                "command_id": command_id,
                "error_code": error_code,
            },
        )
        await self._ack(message_id)

    async def _ack(self, message_id: str) -> None:
        await self._redis.xack(
            self._settings.command_stream, self._settings.command_group, message_id
        )
