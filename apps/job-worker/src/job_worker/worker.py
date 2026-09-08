from __future__ import annotations

import asyncio
import codecs
import ipaddress
import json
import logging
import os
import re
import signal
import time
from base64 import b64encode
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import jsonata  # type: ignore[import-untyped]
import jwt
from agentic_observability.bootstrap import TelemetryProviders, bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.domain import CoreMetrics, domain_span
from agentic_observability.logging import install_trace_context_filter
from agentic_observability.propagation import process_message_span, trace_context_fields
from contracts import (
    CANONICAL_FIELD_NORMALIZERS,
    HttpBodyBinding,
    HttpRequestPlanV1,
    HttpRequestResult,
    IntegrationExecutionMaterial,
    IntegrationJob,
    WorkerError,
    WorkerExecutionContext,
    WorkerResultReport,
)
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    ValidationError as JsonSchemaValidationError,
)
from minio import Minio
from minio.error import MinioException
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.trace import Tracer
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)
MAX_STRUCTURED_PAYLOAD_BYTES = 64_000
MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES = 32 * 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 64_000


class ExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.transient = transient


@dataclass(frozen=True)
class Settings:
    redis_url: str
    stream: str
    group: str
    consumer: str
    dead_letter_stream: str
    backend_url: str
    backend_audience: str
    service_secret: str
    allow_insecure_http_execution: bool = False
    provider_timeout_seconds: float = 10.0
    max_retries: int = 3
    stale_idle_ms: int = 30_000
    command_stream: str = "application:commands"
    command_group: str = "job-workers"
    command_result_stream: str = "application:command-results"
    command_dead_letter_stream: str = "application:commands:dead-letter"
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = ""
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "call-recordings"
    minio_secure: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= 9:
            raise ValueError("CAPABILITY_JOB_MAX_RETRIES must be between 0 and 9")
        if self.provider_timeout_seconds <= 0 or self.stale_idle_ms <= 0:
            raise ValueError("Worker timeouts must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            redis_url=os.environ["REDIS_URL"],
            stream=os.getenv("CAPABILITY_JOB_STREAM", "capability:jobs"),
            group=os.getenv("CAPABILITY_JOB_CONSUMER_GROUP", "capability-workers"),
            consumer=os.getenv("CAPABILITY_JOB_CONSUMER_NAME", f"worker-{os.getpid()}"),
            dead_letter_stream=os.getenv(
                "CAPABILITY_JOB_DEAD_LETTER_STREAM", "capability:jobs:dead-letter"
            ),
            backend_url=os.environ["BACKEND_CORE_URL"].rstrip("/"),
            backend_audience=os.getenv("INTERNAL_API_AUDIENCE", "backend-core"),
            service_secret=os.environ["JOB_WORKER_SERVICE_SECRET"],
            allow_insecure_http_execution=os.getenv(
                "ALLOW_INSECURE_HTTP_EXECUTION", "false"
            ).lower()
            == "true",
            provider_timeout_seconds=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "10")),
            max_retries=int(os.getenv("CAPABILITY_JOB_MAX_RETRIES", "3")),
            stale_idle_ms=int(os.getenv("CAPABILITY_JOB_STALE_IDLE_MS", "30000")),
            command_stream=os.getenv("COMMAND_STREAM", "application:commands"),
            command_group=os.getenv("COMMAND_CONSUMER_GROUP", "job-workers"),
            command_result_stream=os.getenv(
                "COMMAND_RESULT_STREAM", "application:command-results"
            ),
            command_dead_letter_stream=os.getenv(
                "COMMAND_DEAD_LETTER_STREAM", "application:commands:dead-letter"
            ),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
            azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", ""),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", ""),
            minio_access_key=os.getenv("MINIO_WORKER_ACCESS_KEY", ""),
            minio_secret_key=os.getenv("MINIO_WORKER_SECRET_KEY", ""),
            minio_bucket=os.getenv("MINIO_BUCKET", "call-recordings"),
            minio_secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )


class RecordingStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.minio_bucket
        self._client = (
            Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            if settings.minio_endpoint
            and settings.minio_access_key
            and settings.minio_secret_key
            else None
        )

    async def base64(
        self,
        storage_key: str,
        *,
        max_source_bytes: int = MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES,
    ) -> AsyncIterator[bytes]:
        if self._client is None:
            raise ExecutionError(
                "recording_storage_unconfigured",
                "Recording storage is not configured",
                transient=False,
            )
        response = None
        try:
            response = self._client.get_object(self._bucket, storage_key)
            remainder = b""
            source_size = 0
            while chunk := response.read(64 * 1024):
                source_size += len(chunk)
                if source_size > max_source_bytes:
                    raise ExecutionError(
                        "artifact_too_large",
                        "Artifact source is too large",
                        transient=False,
                    )
                data = remainder + chunk
                usable = len(data) - len(data) % 3
                if usable:
                    yield b64encode(data[:usable])
                remainder = data[usable:]
            if remainder:
                yield b64encode(remainder)
        except MinioException as error:
            raise ExecutionError(
                "recording_storage_unavailable",
                "Recording storage is unavailable",
                transient=True,
            ) from error
        finally:
            if response is not None:
                response.close()
                response.release_conn()


@dataclass(frozen=True)
class ResolvedHttpConnection:
    url: str
    api_key: str | None
    api_key_header: str | None
    static_headers: dict[str, str]
    allowed_hosts: frozenset[str]


class HttpExecutionHandler:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        allow_insecure: bool = False,
    ) -> None:
        self._client = client
        self._allow_insecure = allow_insecure

    async def execute(
        self,
        plan: HttpRequestPlanV1,
        material: IntegrationExecutionMaterial,
        bodies: dict[str, AsyncIterator[bytes]] | None = None,
    ) -> HttpRequestResult:
        result = await self._execute_http(plan, material, bodies)
        if plan.result_schema is not None:
            self._validate_output(plan.result_schema, result.data)
        return result

    async def _execute_http(
        self,
        plan: HttpRequestPlanV1,
        material: IntegrationExecutionMaterial,
        bodies: dict[str, AsyncIterator[bytes]] | None,
    ) -> HttpRequestResult:
        connection = self._connection(plan, material)
        url = self._operation_url(connection.url, plan.path)
        parsed = self._validate_url(url, connection.allowed_hosts)
        headers: dict[str, str] = {}
        for source in (connection.static_headers, plan.headers):
            for name, value in source.items():
                self._set_header(headers, name, value)
        if plan.body_bindings and plan.request.codec != "json":
            raise ExecutionError(
                "artifact_body_unsupported",
                "HTTP artifact body bindings require a JSON request",
                transient=False,
            )
        body: bytes | AsyncIterator[bytes] | None = None
        if plan.request.codec != "none":
            if plan.request.codec == "json":
                structured = json.dumps(
                    plan.payload, ensure_ascii=False, separators=(",", ":")
                ).encode()
                if len(structured) > MAX_STRUCTURED_PAYLOAD_BYTES:
                    raise ExecutionError(
                        "request_too_large",
                        "HTTP structured payload is too large",
                        transient=False,
                    )
                if plan.body_bindings:
                    body_paths = {
                        binding.payload_path for binding in plan.body_bindings
                    }
                    if len(body_paths) != len(plan.body_bindings):
                        raise ExecutionError(
                            "artifact_body_invalid",
                            "HTTP artifact body bindings are duplicated",
                            transient=False,
                        )
                    if bodies is None or body_paths != set(bodies):
                        raise ExecutionError(
                            "artifact_body_unavailable",
                            "HTTP artifact body is unavailable",
                            transient=False,
                        )
                    body = self._stream_json(plan.payload, "", bodies)
                else:
                    body = structured
                self._set_header(headers, "Content-Type", "application/json")
            elif not isinstance(plan.payload, str):
                raise ExecutionError(
                    "request_mapping_failed",
                    "Text request must evaluate to a string",
                    transient=False,
                )
            else:
                body = plan.payload.encode()
                if plan.request.content_type:
                    self._set_header(headers, "Content-Type", plan.request.content_type)
        self._set_header(headers, "X-Operation-Id", str(plan.operation_id))
        if connection.api_key and connection.api_key_header:
            self._set_header(headers, connection.api_key_header, connection.api_key)
        if (
            isinstance(body, bytes)
            and plan.request.codec != "json"
            and len(body) > MAX_STRUCTURED_PAYLOAD_BYTES
        ):
            raise ExecutionError(
                "request_too_large",
                "HTTP structured payload is too large",
                transient=False,
            )
        try:
            async with self._client.stream(
                plan.method,
                parsed,
                params=cast(Any, plan.query),
                headers=headers,
                content=body,
                timeout=plan.timeout_seconds,
                follow_redirects=False,
            ) as response:
                self._validate_http_status(response.status_code, plan.success_statuses)
                data = await self._decode_http_response(plan, response)
                return HttpRequestResult(
                    result_type="http.request.v1",
                    status="succeeded",
                    operation_id=plan.operation_id,
                    data=data,
                )
        except httpx.TimeoutException as error:
            raise ExecutionError(
                "provider_timeout", "HTTP request timed out", transient=True
            ) from error
        except httpx.TransportError as error:
            raise ExecutionError(
                "provider_transient_error", "HTTP transport failed", transient=True
            ) from error

    @staticmethod
    def _operation_url(endpoint: str, path: object) -> str:
        if path is None:
            return endpoint
        if not isinstance(path, str) or not path or path.startswith("//"):
            raise ExecutionError(
                "invalid_http_path", "HTTP operation path is invalid", transient=False
            )
        parsed = urlparse(path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.query
        ):
            raise ExecutionError(
                "invalid_http_path",
                "HTTP operation path must be relative",
                transient=False,
            )
        base = urlparse(endpoint)
        return base._replace(
            path=base.path.rstrip("/") + "/" + path.lstrip("/")
        ).geturl()

    @staticmethod
    def _set_header(headers: dict[str, str], name: str, value: str) -> None:
        lowered = name.lower()
        for existing in tuple(headers):
            if existing.lower() == lowered:
                del headers[existing]
        headers[name] = value

    @staticmethod
    def _validate_url(url: str, allowed_hosts: frozenset[str]) -> str:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ExecutionError(
                "provider_permanent_error", "HTTP URL is invalid", transient=False
            )
        try:
            hostname = HttpExecutionHandler._normalized_hostname(parsed.hostname)
            port = parsed.port
        except ValueError as error:
            raise ExecutionError(
                "provider_permanent_error", "HTTP URL is invalid", transient=False
            ) from error
        try:
            ipaddress.ip_address(hostname)
            is_ip = True
        except ValueError:
            is_ip = False
        if port not in {None, 443} or is_ip or hostname not in allowed_hosts:
            raise ExecutionError(
                "provider_permanent_error",
                "HTTP destination is not allowed",
                transient=False,
            )
        return url

    @staticmethod
    def _validate_http_status(status_code: int, accepted: list[int] | None) -> None:
        if 200 <= status_code < 300 or (accepted and status_code in accepted):
            return
        if status_code in {408, 429} or status_code >= 500:
            raise ExecutionError(
                "provider_transient_error",
                "HTTP request returned a retryable error",
                transient=True,
            )
        raise ExecutionError(
            "provider_permanent_error",
            "HTTP request returned an unsupported status",
            transient=False,
        )

    async def _decode_http_response(
        self, plan: HttpRequestPlanV1, response: httpx.Response
    ) -> object | None:
        if plan.response.codec == "none":
            body: object = None
        else:
            raw = await self._bounded_response(response)
            try:
                body = (
                    json.loads(raw) if plan.response.codec == "json" else raw.decode()
                )
            except (ValueError, UnicodeDecodeError) as error:
                raise ExecutionError(
                    "response_decode_failed",
                    "HTTP response does not match its codec",
                    transient=False,
                ) from error
        if plan.response.mapping is None:
            return body
        context: dict[str, object] = {
            "response": {
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "body": body,
            }
        }
        return self._evaluate_template(plan.response.mapping, context)

    @staticmethod
    def _evaluate_template(template: object, context: dict[str, object]) -> object:
        if isinstance(template, dict):
            if set(template) == {"$expr"} and isinstance(template["$expr"], str):
                return jsonata.Jsonata(template["$expr"]).evaluate(context)
            return {
                key: HttpExecutionHandler._evaluate_template(value, context)
                for key, value in template.items()
            }
        if isinstance(template, list):
            return [
                HttpExecutionHandler._evaluate_template(value, context)
                for value in template
            ]
        return template

    @staticmethod
    def _connection(
        plan: HttpRequestPlanV1,
        material: IntegrationExecutionMaterial,
    ) -> ResolvedHttpConnection:
        config = material.config
        authentication = config.get("authentication", {})
        security = config.get("security", {})
        url = config.get("endpoint")
        header = (
            authentication.get("header_name")
            if isinstance(authentication, dict)
            and authentication.get("type") == "api_key_header"
            else None
        )
        headers = config.get("headers", {})
        additional_hosts = (
            security.get("additional_allowed_hosts", [])
            if isinstance(security, dict)
            else []
        )
        if (
            not isinstance(url, str)
            or not isinstance(headers, dict)
            or not isinstance(additional_hosts, list)
        ):
            raise ExecutionError(
                "integration_material_invalid",
                "HTTP integration material is invalid",
                transient=False,
            )
        endpoint_host = urlparse(url).hostname
        try:
            hosts = frozenset(
                HttpExecutionHandler._normalized_hostname(host)
                for host in [endpoint_host, *additional_hosts]
            )
        except (TypeError, ValueError) as error:
            raise ExecutionError(
                "integration_material_invalid",
                "HTTP integration material is invalid",
                transient=False,
            ) from error
        return ResolvedHttpConnection(
            url,
            material.secret,
            header if isinstance(header, str) else None,
            {str(name): str(value) for name, value in headers.items()},
            hosts,
        )

    @staticmethod
    def _normalized_hostname(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("HTTP allowed_hosts must be a string list")
        hostname = value.rstrip(".").lower()
        if not hostname or not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            hostname,
        ):
            raise ValueError("HTTP allowed host is invalid")
        return hostname

    @staticmethod
    async def _bounded_response(response: httpx.Response) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_HTTP_RESPONSE_BYTES:
                raise ExecutionError(
                    "response_too_large",
                    "HTTP response is too large",
                    transient=False,
                )
        return bytes(content)

    @staticmethod
    def _validate_output(schema: dict[str, object], output: object) -> None:
        try:
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(
                output
            )
        except JsonSchemaValidationError as error:
            raise ExecutionError(
                "response_output_invalid",
                "HTTP semantic result is invalid",
                transient=False,
            ) from error

    async def _stream_json(
        self,
        value: object,
        path: str,
        bodies: dict[str, AsyncIterator[bytes]],
    ) -> AsyncIterator[bytes]:
        body = bodies.get(path)
        if body is not None:
            yield b'"'
            decoder = codecs.getincrementaldecoder("utf-8")()
            try:
                async for chunk in body:
                    text = decoder.decode(chunk)
                    if text:
                        yield json.dumps(text, ensure_ascii=False)[1:-1].encode()
                text = decoder.decode(b"", final=True)
                if text:
                    yield json.dumps(text, ensure_ascii=False)[1:-1].encode()
            except UnicodeDecodeError as error:
                raise ExecutionError(
                    "artifact_body_invalid",
                    "HTTP artifact body is not UTF-8 text",
                    transient=False,
                ) from error
            yield b'"'
            return
        if isinstance(value, dict):
            yield b"{"
            for index, (key, child) in enumerate(value.items()):
                if index:
                    yield b","
                yield json.dumps(key, ensure_ascii=False).encode()
                yield b":"
                escaped = key.replace("~", "~0").replace("/", "~1")
                async for chunk in self._stream_json(
                    child, f"{path}/{escaped}", bodies
                ):
                    yield chunk
            yield b"}"
            return
        if isinstance(value, list):
            yield b"["
            for index, child in enumerate(value):
                if index:
                    yield b","
                async for chunk in self._stream_json(child, f"{path}/{index}", bodies):
                    yield chunk
            yield b"]"
            return
        yield json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class BackendClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        recording_storage: RecordingStorage | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._recording_storage = recording_storage or RecordingStorage(settings)

    def _token(self) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": self._settings.consumer,
                "service": "job-worker",
                "aud": self._settings.backend_audience,
                "iat": now,
                "exp": now.timestamp() + 60,
                "scopes": [
                    "capability-result:write",
                    "integration-material:read",
                    "finalization-context:read",
                    "post-call-action:read",
                    "artifact-representation:read",
                    "artifact-representation:write",
                ],
            },
            self._settings.service_secret,
            algorithm="HS256",
        )

    async def report(self, report: WorkerResultReport) -> None:
        response = await self._client.post(
            f"{self._settings.backend_url}/internal/v1/capability-results",
            headers={"Authorization": f"Bearer {self._token()}"},
            json=report.model_dump(mode="json"),
        )
        response.raise_for_status()

    async def integration_material(
        self, invocation_id: UUID, job_id: UUID, job: IntegrationJob
    ) -> IntegrationExecutionMaterial:
        try:
            response = await self._client.get(
                f"{self._settings.backend_url}/internal/v1/capability-invocations/"
                f"{invocation_id}/integration-material",
                params={
                    "job_id": str(job_id),
                    "call_id": str(job.call_id) if job.call_id else None,
                    "execution_id": str(job.execution_id),
                },
                headers={"Authorization": f"Bearer {self._token()}"},
            )
        except httpx.HTTPError as error:
            raise ExecutionError(
                "integration_material_unavailable",
                "Integration material is temporarily unavailable",
                transient=True,
            ) from error
        if response.is_error:
            raise ExecutionError(
                "integration_material_unavailable",
                "Integration material is unavailable",
                transient=response.status_code >= 500,
            )
        try:
            return IntegrationExecutionMaterial.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise ExecutionError(
                "integration_material_invalid",
                "Integration material is invalid",
                transient=False,
            ) from error

    async def finalization_context(
        self, call_id: UUID, finalization_id: UUID, command_id: UUID
    ) -> dict[str, object]:
        response = await self._client.get(
            f"{self._settings.backend_url}/internal/v1/calls/{call_id}/finalization-context",
            params={
                "finalization_id": str(finalization_id),
                "command_id": str(command_id),
            },
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ExecutionError(
                "finalization_context_invalid",
                "Finalization context is invalid",
                transient=False,
            )
        return value

    async def post_call_action(
        self,
        call_id: UUID,
        finalization_id: UUID,
        action_id: str,
        command_id: UUID,
    ) -> tuple[WorkerExecutionContext, dict[str, object]]:
        response = await self._client.get(
            f"{self._settings.backend_url}/internal/v1/calls/{call_id}/post-call-actions/{action_id}",
            params={
                "finalization_id": str(finalization_id),
                "command_id": str(command_id),
            },
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response.raise_for_status()
        value = response.json()
        try:
            if not isinstance(value, dict) or not isinstance(
                value["mapping_context"], dict
            ):
                raise TypeError
            return (
                WorkerExecutionContext.model_validate(value["worker_context"]),
                value["mapping_context"],
            )
        except (KeyError, TypeError, ValidationError) as error:
            raise ExecutionError(
                "execution_context_invalid",
                "Post-call execution context is invalid",
                transient=False,
            ) from error

    async def post_call_action_material(
        self,
        call_id: UUID,
        finalization_id: UUID,
        action_id: str,
        command_id: UUID,
    ) -> IntegrationExecutionMaterial:
        try:
            response = await self._client.get(
                f"{self._settings.backend_url}/internal/v1/calls/{call_id}/"
                f"post-call-actions/{action_id}/integration-material",
                params={
                    "finalization_id": str(finalization_id),
                    "command_id": str(command_id),
                },
                headers={"Authorization": f"Bearer {self._token()}"},
            )
        except httpx.HTTPError as error:
            raise ExecutionError(
                "integration_material_unavailable",
                "Integration material is temporarily unavailable",
                transient=True,
            ) from error
        return self._material_response(response)

    @staticmethod
    def _material_response(response: httpx.Response) -> IntegrationExecutionMaterial:
        if response.is_error:
            raise ExecutionError(
                "integration_material_unavailable",
                "Integration material is unavailable",
                transient=response.status_code >= 500,
            )
        try:
            return IntegrationExecutionMaterial.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise ExecutionError(
                "integration_material_invalid",
                "Integration material is invalid",
                transient=False,
            ) from error

    async def representation_content(
        self, representation_id: UUID, command_id: UUID
    ) -> AsyncIterator[bytes]:
        source = await self._client.get(
            f"{self._settings.backend_url}/internal/v1/calls/"
            f"artifact-representations/{representation_id}/recording-source",
            params={"command_id": str(command_id)},
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        if source.status_code == 200:
            value = source.json()
            storage_key = value.get("storage_key") if isinstance(value, dict) else None
            source_size = value.get("byte_size") if isinstance(value, dict) else None
            if (
                not isinstance(storage_key, str)
                or not storage_key
                or not isinstance(source_size, int)
                or source_size <= 0
            ):
                raise ExecutionError(
                    "recording_source_invalid",
                    "Recording source is invalid",
                    transient=False,
                )
            if source_size > MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES:
                raise ExecutionError(
                    "artifact_too_large",
                    "Artifact source is too large",
                    transient=False,
                )
            async for chunk in self._recording_storage.base64(
                storage_key, max_source_bytes=MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES
            ):
                yield chunk
            return
        if source.status_code != 404:
            source.raise_for_status()
        request = self._client.build_request(
            "GET",
            f"{self._settings.backend_url}/internal/v1/calls/"
            f"artifact-representations/{representation_id}/content",
            params={"command_id": str(command_id)},
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response = await self._client.send(request, stream=True)
        try:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size is not None:
                try:
                    if int(declared_size) > MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES:
                        raise ExecutionError(
                            "artifact_too_large",
                            "Artifact source is too large",
                            transient=False,
                        )
                except ValueError as error:
                    raise ExecutionError(
                        "artifact_source_invalid",
                        "Artifact content length is invalid",
                        transient=False,
                    ) from error
            source_size = 0
            async for chunk in response.aiter_bytes():
                source_size += len(chunk)
                if source_size > MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES:
                    raise ExecutionError(
                        "artifact_too_large",
                        "Artifact source is too large",
                        transient=False,
                    )
                yield chunk
        finally:
            await response.aclose()

    async def materialization_source(
        self, representation_id: UUID, command_id: UUID
    ) -> tuple[bytes, str, str]:
        response = await self._client.get(
            f"{self._settings.backend_url}/internal/v1/calls/"
            f"artifact-representations/{representation_id}/source",
            params={"command_id": str(command_id)},
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response.raise_for_status()
        return (
            response.content,
            response.headers["X-Artifact-Type"],
            response.headers["X-Target-Representation"],
        )

    async def store_representation(
        self,
        representation_id: UUID,
        command_id: UUID,
        content: bytes,
        content_type: str,
    ) -> dict[str, object]:
        response = await self._client.put(
            f"{self._settings.backend_url}/internal/v1/calls/"
            f"artifact-representations/{representation_id}/content",
            params={"command_id": str(command_id)},
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": content_type,
            },
            content=content,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ExecutionError(
                "representation_response_invalid",
                "Representation response is invalid",
                transient=False,
            )
        return value


def _nested(value: dict[str, object], path: str) -> object:
    current: object = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ExecutionError(
                "input_constraint_rejected",
                "Constrained input is unavailable",
                transient=False,
            )
        current = current[part]
    return current


def _bind_input(
    definition: dict[str, object], tool_args: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    schema = definition.get("agent_input_schema")
    if not isinstance(schema, dict):
        raise ExecutionError(
            "execution_context_invalid",
            "Action input schema is invalid",
            transient=False,
        )
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(tool_args)
    except JsonSchemaValidationError as error:
        raise ExecutionError(
            "invalid_agent_input", "Action input is invalid", transient=False
        ) from error
    inputs = dict(tool_args)
    business: dict[str, object] = {}
    bindings = definition.get("bindings", {})
    if not isinstance(bindings, dict):
        raise ExecutionError(
            "execution_context_invalid", "Action bindings are invalid", transient=False
        )
    for source, target_value in bindings.items():
        if (
            not isinstance(source, str)
            or not isinstance(target_value, str)
            or source not in inputs
        ):
            raise ExecutionError(
                "execution_context_invalid",
                "Action binding is invalid",
                transient=False,
            )
        value = inputs[source]
        normalizer = CANONICAL_FIELD_NORMALIZERS.get(target_value)
        if normalizer == "trim" and isinstance(value, str):
            value = value.strip()
        elif normalizer == "e164":
            if not isinstance(value, str):
                raise ExecutionError(
                    "invalid_canonical_field",
                    "Phone number must be a string",
                    transient=False,
                )
            value = re.sub(r"[\s()-]", "", value)
            if value.startswith("00"):
                value = f"+{value[2:]}"
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
                raise ExecutionError(
                    "invalid_canonical_field",
                    "Phone number must be E.164",
                    transient=False,
                )
        inputs[source] = value
        current = business
        parts = target_value.split(".")
        for part in parts[:-1]:
            child = current.setdefault(part, {})
            if not isinstance(child, dict):
                raise ExecutionError(
                    "execution_context_invalid",
                    "Action binding is invalid",
                    transient=False,
                )
            current = child
        current[parts[-1]] = value
    return inputs, business


def _target_http_plan(
    job: IntegrationJob, context: WorkerExecutionContext
) -> HttpRequestPlanV1:
    action = context.action
    definition = action.get("definition")
    execution = action.get("execution_plan")
    if not isinstance(definition, dict) or not isinstance(execution, dict):
        raise ExecutionError(
            "execution_context_invalid",
            "Action execution context is invalid",
            transient=False,
        )
    inputs, business = _bind_input(definition, job.tool_args)
    mapping_context: dict[str, object] = {
        "inputs": inputs,
        "business": business,
        "metadata": job.metadata,
    }
    constraints = definition.get("input_constraints", [])
    if not isinstance(constraints, list):
        raise ExecutionError(
            "execution_context_invalid",
            "Action constraints are invalid",
            transient=False,
        )
    timezone = str(job.metadata.get("timezone", "UTC"))
    for constraint in constraints:
        if not isinstance(constraint, dict) or constraint.get("kind") != "date_range":
            raise ExecutionError(
                "execution_context_invalid",
                "Action constraint is invalid",
                transient=False,
            )
        try:
            start = date.fromisoformat(str(_nested(business, str(constraint["start"]))))
            end = date.fromisoformat(str(_nested(business, str(constraint["end"]))))
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise ExecutionError(
                "input_constraint_rejected", "Date range is invalid", transient=False
            ) from error
        if end <= start or (
            constraint.get("start_not_in_past")
            and start < datetime.now(ZoneInfo(timezone)).date()
        ):
            raise ExecutionError(
                "input_constraint_rejected", "Date range is invalid", transient=False
            )
    policy = definition.get("business_policy", {})
    if not isinstance(policy, dict):
        raise ExecutionError(
            "execution_context_invalid", "Action policy is invalid", transient=False
        )
    if policy.get("requires_caller_phone") and not job.metadata.get("caller_phone"):
        raise ExecutionError(
            "business_policy_rejected", "Caller phone is required", transient=False
        )
    if policy.get("requires_final_confirmation") and not job.confirmed:
        raise ExecutionError(
            "business_policy_rejected",
            "Final confirmation is required",
            transient=False,
        )
    request = execution.get("request", {"codec": "none"})
    if not isinstance(request, dict):
        raise ExecutionError(
            "execution_context_invalid", "HTTP request is invalid", transient=False
        )
    payload = None
    if request.get("codec") != "none":
        mapping = request.get("mapping")
        if mapping is None:
            raise ExecutionError(
                "request_mapping_failed",
                "HTTP request mapping is required",
                transient=False,
            )
        payload = HttpExecutionHandler._evaluate_template(mapping, mapping_context)
    raw_path = execution.get("path")
    path = HttpExecutionHandler._evaluate_template(raw_path, mapping_context)
    if path is not None and not isinstance(path, str):
        raise ExecutionError(
            "request_mapping_failed", "HTTP path mapping is invalid", transient=False
        )
    raw_query = execution.get("query")
    query = None
    if raw_query is not None:
        if not isinstance(raw_query, dict):
            raise ExecutionError(
                "execution_context_invalid", "HTTP query is invalid", transient=False
            )
        query = {
            str(name): HttpExecutionHandler._evaluate_template(value, mapping_context)
            for name, value in raw_query.items()
        }
    return HttpRequestPlanV1(
        operation_id=job.capability_invocation_id,
        method=execution["method"],
        path=path,
        query=cast(Any, query),
        headers=execution.get("headers", {}),
        request=cast(Any, request),
        response=execution.get("response", {"codec": "none"}),
        payload=payload,
        timeout_seconds=execution["timeout_seconds"],
        success_statuses=execution.get("success_statuses"),
        result_schema=definition.get("result_schema"),
    )


def _post_call_http_plan(
    context: WorkerExecutionContext,
    mapping_context: dict[str, object],
    operation_id: UUID,
) -> HttpRequestPlanV1:
    action = context.action
    definition = action.get("definition")
    execution = action.get("execution_plan")
    if (
        action.get("phase") != "post_call"
        or not isinstance(definition, dict)
        or not isinstance(execution, dict)
    ):
        raise ExecutionError(
            "execution_context_invalid",
            "Post-call execution context is invalid",
            transient=False,
        )
    request = execution.get("request", {"codec": "none"})
    if not isinstance(request, dict):
        raise ExecutionError(
            "execution_context_invalid", "HTTP request is invalid", transient=False
        )
    payload: object | None = None
    if request.get("codec") != "none":
        mapping = request.get("mapping")
        if mapping is None:
            raise ExecutionError(
                "request_mapping_failed",
                "HTTP request mapping is required",
                transient=False,
            )
        payload = HttpExecutionHandler._evaluate_template(mapping, mapping_context)
    bindings: list[HttpBodyBinding] = []

    def body_references(value: object, path: str = "") -> object:
        if isinstance(value, dict):
            if set(value) == {"artifact_representation_id"}:
                try:
                    bindings.append(
                        HttpBodyBinding(
                            representation_id=UUID(
                                str(value["artifact_representation_id"])
                            ),
                            payload_path=path,
                        )
                    )
                except ValueError as error:
                    raise ExecutionError(
                        "artifact_body_invalid",
                        "Artifact body reference is invalid",
                        transient=False,
                    ) from error
                return None
            return {
                key: body_references(
                    child, f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
                )
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [
                body_references(child, f"{path}/{index}")
                for index, child in enumerate(value)
            ]
        return value

    payload = body_references(payload)
    path = HttpExecutionHandler._evaluate_template(
        execution.get("path"), mapping_context
    )
    if path is not None and not isinstance(path, str):
        raise ExecutionError(
            "request_mapping_failed", "HTTP path mapping is invalid", transient=False
        )
    raw_query = execution.get("query")
    query = (
        {
            str(name): HttpExecutionHandler._evaluate_template(value, mapping_context)
            for name, value in raw_query.items()
        }
        if isinstance(raw_query, dict)
        else None
    )
    return HttpRequestPlanV1(
        operation_id=operation_id,
        method=execution["method"],
        path=path,
        query=cast(Any, query),
        headers=execution.get("headers", {}),
        request=cast(Any, request),
        response=execution.get("response", {"codec": "none"}),
        payload=payload,
        body_bindings=bindings,
        timeout_seconds=execution["timeout_seconds"],
        success_statuses=execution.get("success_statuses"),
        result_schema=definition.get("result_schema"),
    )


class CapabilityWorker:
    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        backend: BackendClient,
        webhooks: HttpExecutionHandler | None = None,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._settings = settings
        self._redis = redis
        self._backend = backend
        self._webhooks = webhooks
        self._tracer = tracer
        self._metrics = metrics

    async def run(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._settings.stream,
                self._settings.group,
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
                    self._settings.group,
                    self._settings.consumer,
                    {self._settings.stream: ">"},
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
                self._settings.stream,
                self._settings.group,
                self._settings.consumer,
                min_idle_time=self._settings.stale_idle_ms,
                start_id="0-0",
                count=10,
            ),
        )
        for message_id, fields in claimed[1]:
            await self.handle(message_id, fields)

    async def handle(self, message_id: str, fields: dict[str, str]) -> None:
        with process_message_span(
            self._tracer,
            fields,
            stream=self._settings.stream,
            group=self._settings.group,
            message_id=message_id,
        ):
            await self._handle(message_id, fields)

    async def _handle(self, message_id: str, fields: dict[str, str]) -> None:
        try:
            job = IntegrationJob.model_validate_json(fields["job"])
        except KeyError, ValidationError:
            await self._dead_letter(message_id, None, "invalid_execution_plan", fields)
            return
        if job.expires_at <= datetime.now(UTC):
            await self._report_failure(
                message_id,
                job,
                "job_expired",
                "Capability job expired",
                False,
                fields=fields,
            )
            return
        started = datetime.now(UTC)
        logger.info(
            "capability_job_started",
            extra={
                "invocation_id": str(job.capability_invocation_id),
                "job_id": str(job.job_id),
                "redis_message_id": message_id,
                "plan_type": "http.request.v1",
                "attempt": job.attempt,
                "latency_ms": round((started - job.created_at).total_seconds() * 1000),
            },
        )
        provider_started = time.perf_counter()
        capability_name, capability_version, operation_id = _capability_identity(job)
        try:
            context = WorkerExecutionContext.model_validate(job.worker_context)
            if (
                context.execution_id != job.execution_id
                or context.action.get("phase") != "runtime"
            ):
                raise ExecutionError(
                    "execution_context_invalid",
                    "Worker execution context is invalid",
                    transient=False,
                )
            plan = _target_http_plan(job, context)
            with domain_span(
                self._tracer,
                "capability.execute",
                {
                    "capability.name": capability_name,
                    "capability.version": capability_version,
                    "operation.id": operation_id,
                },
            ):
                logger.info(
                    "capability_provider_call_started",
                    extra={
                        "invocation_id": str(job.capability_invocation_id),
                        "job_id": str(job.job_id),
                        "plan_type": "http.request.v1",
                        "attempt": job.attempt,
                    },
                )
                material = await self._backend.integration_material(
                    job.capability_invocation_id, job.job_id, job
                )
                result: HttpRequestResult
                if self._webhooks is None:
                    raise ExecutionError(
                        "unknown_plan_type",
                        "HTTP handler is unavailable",
                        transient=False,
                    )
                result = await self._webhooks.execute(plan, material)
                logger.info(
                    "capability_provider_call_completed",
                    extra={
                        "invocation_id": str(job.capability_invocation_id),
                        "job_id": str(job.job_id),
                        "plan_type": "http.request.v1",
                        "attempt": job.attempt,
                        "latency_ms": round(
                            (time.perf_counter() - provider_started) * 1000
                        ),
                        "status": "succeeded",
                    },
                )
        except ExecutionError as error:
            self._record_capability_attempt(
                job,
                (
                    "retry"
                    if error.transient and job.attempt <= self._settings.max_retries
                    else "failed"
                ),
                provider_started,
            )
            if error.transient and job.attempt <= self._settings.max_retries:
                if self._metrics is not None:
                    self._metrics.command_retry("capability_execution")
                retried = job.model_copy(update={"attempt": job.attempt + 1})
                retried_fields = {"job": retried.model_dump_json()}
                retried_fields.update(trace_context_fields(fields))
                await self._redis.xadd(
                    self._settings.stream, cast(dict[Any, Any], retried_fields)
                )
                logger.info(
                    "capability_job_requeued",
                    extra={
                        "invocation_id": str(job.capability_invocation_id),
                        "job_id": str(job.job_id),
                        "redis_message_id": message_id,
                        "plan_type": "http.request.v1",
                        "attempt": retried.attempt,
                    },
                )
                await self._redis.xack(
                    self._settings.stream, self._settings.group, message_id
                )
                return
            await self._report_failure(
                message_id,
                job,
                error.code,
                error.safe_message,
                error.transient,
                started,
                fields,
            )
            return
        self._record_capability_attempt(job, "ok", provider_started)
        report = WorkerResultReport(
            job_id=job.job_id,
            capability_invocation_id=job.capability_invocation_id,
            status="succeeded",
            result=result,
            attempt=job.attempt,
            started_at=started,
            completed_at=datetime.now(UTC),
            provider_reference=result.reference,
            trace_context=job.trace_context,
        )
        try:
            await self._backend.report(report)
        except httpx.HTTPError, OSError:
            logger.exception(
                "capability result reporting failed",
                extra={
                    "invocation_id": str(job.capability_invocation_id),
                    "job_id": str(job.job_id),
                    "redis_message_id": message_id,
                },
            )
            return
        await self._redis.xack(self._settings.stream, self._settings.group, message_id)

    def _record_capability_attempt(
        self, job: IntegrationJob, status: str, started: float
    ) -> None:
        if self._metrics is not None:
            self._metrics.capability_attempt(
                name=_capability_identity(job)[0],
                version=_capability_identity(job)[1],
                status=status,
                duration_seconds=max(0.0, time.perf_counter() - started),
            )

    async def _report_failure(
        self,
        message_id: str,
        job: IntegrationJob,
        code: str,
        message: str,
        transient: bool,
        started_at: datetime | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        report = WorkerResultReport(
            job_id=job.job_id,
            capability_invocation_id=job.capability_invocation_id,
            status="failed",
            error=WorkerError(code=code, message=message, transient=transient),
            attempt=job.attempt,
            started_at=started_at or datetime.now(UTC),
            completed_at=datetime.now(UTC),
            trace_context=job.trace_context,
        )
        try:
            await self._backend.report(report)
        except httpx.HTTPError, OSError:
            return
        await self._dead_letter(message_id, job, code, fields or {})

    async def _dead_letter(
        self,
        message_id: str,
        job: IntegrationJob | None,
        error_code: str,
        fields: dict[str, str],
    ) -> None:
        dead_letter = {
            "source_message_id": message_id,
            "job_id": str(job.job_id) if job else "unknown",
            "invocation_id": str(job.capability_invocation_id) if job else "unknown",
            "error_code": error_code,
        }
        dead_letter.update(trace_context_fields(fields))
        await self._redis.xadd(
            self._settings.dead_letter_stream, cast(dict[Any, Any], dead_letter)
        )
        if self._metrics is not None:
            self._metrics.command_dlq("capability_execution", error_code)
        await self._redis.xack(self._settings.stream, self._settings.group, message_id)


def _capability_identity(job: IntegrationJob) -> tuple[str, str, str]:
    action = job.worker_context.action
    return (
        str(action.get("key", "http")) if isinstance(action, dict) else "http",
        "frozen",
        str(job.capability_invocation_id),
    )


async def run_worker(settings: Settings) -> None:
    from job_worker.command_worker import (
        CommandWorker,
        ExecutePostCallActionHandler,
        GenerateCallSummaryHandler,
        MaterializeArtifactRepresentationHandler,
    )

    telemetry: TelemetryProviders | None = None
    redis: Redis | None = None
    sigterm_installed = False
    try:
        if os.getenv("OTEL_ENABLED", "").lower() == "true":
            telemetry = bootstrap(
                TelemetryConfig.from_env(default_service_name="job-worker")
            )
            install_trace_context_filter(logging.getLogger().handlers)
        tracer = telemetry.tracer(__name__) if telemetry is not None else None
        meter = telemetry.meter(__name__) if telemetry is not None else None
        metrics = CoreMetrics(meter) if meter is not None else None
        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=None,
        )
        if telemetry is not None and telemetry.tracer_provider is not None:
            RedisInstrumentor.instrument_client(
                redis,
                tracer_provider=telemetry.tracer_provider,  # type: ignore[arg-type]
            )
        async with (
            httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as provider_client,
            httpx.AsyncClient(timeout=10.0) as backend_client,
        ):
            if (
                telemetry is not None
                and telemetry.tracer_provider is not None
                and telemetry.meter_provider is not None
            ):
                HTTPXClientInstrumentor.instrument_client(
                    provider_client,
                    tracer_provider=telemetry.tracer_provider,  # type: ignore[arg-type]
                    meter_provider=telemetry.meter_provider,  # type: ignore[arg-type]
                )
                HTTPXClientInstrumentor.instrument_client(
                    backend_client,
                    tracer_provider=telemetry.tracer_provider,  # type: ignore[arg-type]
                    meter_provider=telemetry.meter_provider,  # type: ignore[arg-type]
                )
            webhooks = HttpExecutionHandler(
                provider_client,
                allow_insecure=settings.allow_insecure_http_execution,
            )
            backend = BackendClient(
                settings, backend_client, RecordingStorage(settings)
            )
            worker = CapabilityWorker(
                settings,
                redis,
                backend,
                webhooks,
                tracer,
                metrics,
            )
            command_worker = CommandWorker(
                settings,
                redis,
                {
                    "call.generate_summary.v1": GenerateCallSummaryHandler(
                        settings, backend, provider_client
                    ),
                    "call.execute_post_call_action.v1": ExecutePostCallActionHandler(
                        backend, webhooks
                    ),
                    "artifact.materialize_representation.v1": (
                        MaterializeArtifactRepresentationHandler(backend)
                    ),
                },
                tracer,
                metrics,
            )
            sigterm_installed = _cancel_on_sigterm()
            await asyncio.gather(worker.run(), command_worker.run())
    finally:
        if sigterm_installed:
            asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)
        if redis is not None:
            await redis.aclose()
        if telemetry is not None:
            telemetry.shutdown()


def _cancel_on_sigterm() -> bool:
    task = asyncio.current_task()
    if task is None:
        return False
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    except NotImplementedError, RuntimeError:
        return False
    return True
