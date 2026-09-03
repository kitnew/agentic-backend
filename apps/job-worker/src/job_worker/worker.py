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
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
import jsonata  # type: ignore[import-untyped]
import jwt
from agentic_observability.bootstrap import TelemetryProviders, bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.domain import CoreMetrics, domain_span
from agentic_observability.logging import install_trace_context_filter
from agentic_observability.propagation import process_message_span, trace_context_fields
from contracts import (
    GoogleSheetsAppendValuesPlan,
    GoogleSheetsAppendValuesResult,
    HttpRequestPlanV1,
    HttpRequestResult,
    IntegrationJob,
    ManagedWebhookFailureResponse,
    ManagedWebhookPostJsonPlan,
    ManagedWebhookPostJsonResult,
    ManagedWebhookSuccessResponse,
    RuntimeIntegrationMaterial,
    WorkerError,
    WorkerResultReport,
)
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
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
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
MAX_STRUCTURED_PAYLOAD_BYTES = 64_000
MAX_OUTBOUND_ARTIFACT_SOURCE_BYTES = 32 * 1024 * 1024
MAX_WEBHOOK_RESPONSE_BYTES = 64_000


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
    allow_insecure_webhooks: bool = False
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
            allow_insecure_webhooks=os.getenv(
                "ALLOW_INSECURE_MANAGED_WEBHOOKS", "false"
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
class ResolvedManagedWebhookConnection:
    url: str
    api_key: str | None
    api_key_header: str | None
    static_headers: dict[str, str]
    allowed_hosts: frozenset[str]


class ManagedWebhookPostJsonHandler:
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
        plan: ManagedWebhookPostJsonPlan | HttpRequestPlanV1,
        material: RuntimeIntegrationMaterial,
        bodies: dict[str, AsyncIterator[bytes]] | None = None,
    ) -> ManagedWebhookPostJsonResult | HttpRequestResult:
        if isinstance(plan, HttpRequestPlanV1):
            return await self._execute_http(plan, material, bodies)
        connection = self._connection(plan, material)
        parsed = urlparse(connection.url)
        if parsed.scheme not in (
            {"https", "http"} if self._allow_insecure else {"https"}
        ):
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook requires HTTPS",
                transient=False,
            )
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook URL is invalid",
                transient=False,
            )
        try:
            hostname = self._normalized_hostname(parsed.hostname)
            port = parsed.port
        except ValueError as error:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook URL is invalid",
                transient=False,
            ) from error
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if port not in {None, 443 if parsed.scheme == "https" else 80}:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook URL port is not allowed",
                transient=False,
            )
        if address is not None or hostname not in connection.allowed_hosts:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook destination is not allowed",
                transient=False,
            )
        encoded = self._bounded_payload(plan)
        if len(encoded.encode()) > 64_000:
            raise ExecutionError(
                "request_too_large",
                "Managed webhook request is too large",
                transient=False,
            )
        if plan.body_bindings:
            body_streams = bodies or {}
            if {binding.payload_path for binding in plan.body_bindings} != set(
                body_streams
            ):
                raise ExecutionError(
                    "artifact_body_unavailable",
                    "Managed webhook artifact body is unavailable",
                    transient=False,
                )
            content: bytes | AsyncIterator[bytes] = self._stream_payload(
                plan, body_streams
            )
        else:
            content = encoded.encode()
        headers = dict(connection.static_headers)
        headers.update({
            "Content-Type": "application/json",
            "X-Operation-Id": str(plan.operation_id),
        })
        if connection.api_key and connection.api_key_header:
            headers[connection.api_key_header] = connection.api_key
        try:
            async with self._client.stream(
                "POST",
                connection.url,
                headers=headers,
                content=content,
                timeout=plan.timeout_seconds,
                follow_redirects=False,
            ) as response:
                self._validate_status(response.status_code)
                return await self._result(plan, response)
        except httpx.TimeoutException as error:
            raise ExecutionError(
                "provider_timeout", "Managed webhook timed out", transient=True
            ) from error
        except httpx.TransportError as error:
            raise ExecutionError(
                "provider_transient_error",
                "Managed webhook transport failed",
                transient=True,
            ) from error

    async def _execute_http(
        self,
        plan: HttpRequestPlanV1,
        material: RuntimeIntegrationMaterial,
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
                    body_paths = {binding.payload_path for binding in plan.body_bindings}
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
                raise ExecutionError("request_mapping_failed", "Text request must evaluate to a string", transient=False)
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
                params=plan.query,
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
            raise ExecutionError("provider_timeout", "HTTP request timed out", transient=True) from error
        except httpx.TransportError as error:
            raise ExecutionError("provider_transient_error", "HTTP transport failed", transient=True) from error

    @staticmethod
    def _operation_url(endpoint: str, path: object) -> str:
        if path is None:
            return endpoint
        if not isinstance(path, str) or not path or path.startswith("//"):
            raise ExecutionError("invalid_http_path", "HTTP operation path is invalid", transient=False)
        parsed = urlparse(path)
        if parsed.scheme or parsed.netloc or parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ExecutionError("invalid_http_path", "HTTP operation path must be relative", transient=False)
        base = urlparse(endpoint)
        return base._replace(path=base.path.rstrip("/") + "/" + path.lstrip("/")).geturl()

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
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ExecutionError("provider_permanent_error", "HTTP URL is invalid", transient=False)
        try:
            hostname = ManagedWebhookPostJsonHandler._normalized_hostname(parsed.hostname)
            port = parsed.port
        except ValueError as error:
            raise ExecutionError("provider_permanent_error", "HTTP URL is invalid", transient=False) from error
        try:
            ipaddress.ip_address(hostname)
            is_ip = True
        except ValueError:
            is_ip = False
        if port not in {None, 443} or is_ip or hostname not in allowed_hosts:
            raise ExecutionError("provider_permanent_error", "HTTP destination is not allowed", transient=False)
        return url

    @staticmethod
    def _validate_http_status(status_code: int, accepted: list[int] | None) -> None:
        if 200 <= status_code < 300 or (accepted and status_code in accepted):
            return
        if status_code in {408, 429} or status_code >= 500:
            raise ExecutionError("provider_transient_error", "HTTP request returned a retryable error", transient=True)
        raise ExecutionError("provider_permanent_error", "HTTP request returned an unsupported status", transient=False)

    async def _decode_http_response(self, plan: HttpRequestPlanV1, response: httpx.Response) -> object | None:
        if plan.response.codec == "none":
            body: object = None
        else:
            raw = await self._bounded_response(response)
            try:
                body = json.loads(raw) if plan.response.codec == "json" else raw.decode()
            except (ValueError, UnicodeDecodeError) as error:
                raise ExecutionError("response_decode_failed", "HTTP response does not match its codec", transient=False) from error
        if plan.response.mapping is None:
            return body
        context = {"response": {"status_code": response.status_code, "content_type": response.headers.get("content-type", ""), "body": body}}
        return self._evaluate_template(plan.response.mapping, context)

    @staticmethod
    def _evaluate_template(template: object, context: dict[str, object]) -> object:
        if isinstance(template, dict):
            if set(template) == {"$expr"} and isinstance(template["$expr"], str):
                return jsonata.Jsonata(template["$expr"]).evaluate(context)
            return {key: ManagedWebhookPostJsonHandler._evaluate_template(value, context) for key, value in template.items()}
        if isinstance(template, list):
            return [ManagedWebhookPostJsonHandler._evaluate_template(value, context) for value in template]
        return template

    @staticmethod
    def _connection(
        plan: ManagedWebhookPostJsonPlan, material: RuntimeIntegrationMaterial
    ) -> ResolvedManagedWebhookConnection:
        if (
            material.integration_id != plan.integration_id
            or material.provider != "http"
        ):
            raise ExecutionError(
                "integration_material_invalid",
                "Managed webhook integration material is invalid",
                transient=False,
            )
        url = material.endpoint
        api_key = (material.secret or {}).get("api_key")
        allowed_hosts = material.allowed_hosts
        header = material.authentication_header
        if (
            not isinstance(url, str)
            or not url
            or (api_key is not None and not isinstance(api_key, str))
            or (header is not None and not isinstance(header, str))
            or not isinstance(allowed_hosts, list)
        ):
            raise ExecutionError(
                "integration_material_invalid",
                "Managed webhook integration material is invalid",
                transient=False,
            )
        try:
            hosts = frozenset(
                ManagedWebhookPostJsonHandler._normalized_hostname(host)
                for host in allowed_hosts
            )
        except (TypeError, ValueError) as error:
            raise ExecutionError(
                "integration_material_invalid",
                "Managed webhook integration material is invalid",
                transient=False,
            ) from error
        return ResolvedManagedWebhookConnection(url, api_key, header, material.static_headers, hosts)

    @staticmethod
    def _normalized_hostname(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("managed webhook allowed_hosts must be a string list")
        hostname = value.rstrip(".").lower()
        if not hostname or not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            hostname,
        ):
            raise ValueError("managed webhook allowed host is invalid")
        return hostname

    @staticmethod
    def _validate_status(status_code: int) -> None:
        if status_code == 429 or status_code == 408 or status_code >= 500:
            raise ExecutionError(
                "provider_transient_error",
                "Managed webhook returned a retryable error",
                transient=True,
            )
        if status_code in {400, 401, 403, 404, 410}:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook rejected the request",
                transient=False,
            )
        if status_code < 200 or status_code >= 300:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook returned an unsupported status",
                transient=False,
            )

    async def _result(
        self, plan: ManagedWebhookPostJsonPlan, response: httpx.Response
    ) -> ManagedWebhookPostJsonResult:
        if plan.response is not None:
            if plan.response.mode == "status_only":
                assert plan.response.success_output is not None
            data: dict[str, object] | str = (
                cast(dict[str, object], plan.response.success_output)
                if plan.response.mode == "status_only"
                else self._map_response(
                    plan,
                    response,
                    await self._bounded_response(response),
                )
            )
            self._validate_output(plan.response.output_schema, data)
            return ManagedWebhookPostJsonResult(
                result_type="managed_webhook.post_json.v1",
                status="succeeded",
                operation_id=plan.operation_id,
                reference=None,
                deduplicated=False,
                data=data,
            )
        if plan.response_contract == "http_2xx":
            return ManagedWebhookPostJsonResult(
                result_type="managed_webhook.post_json.v1",
                status="succeeded",
                operation_id=plan.operation_id,
                reference=None,
                deduplicated=False,
            )
        content = await self._bounded_response(response)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            raise ExecutionError(
                "response_contract_invalid",
                "Managed webhook response must be JSON",
                transient=False,
            )
        try:
            raw = json.loads(content)
            if raw.get("status") == "failed":
                failure = ManagedWebhookFailureResponse.model_validate(raw)
                raise ExecutionError(
                    failure.error.code,
                    failure.error.message,
                    transient=failure.error.retryable,
                )
            success = ManagedWebhookSuccessResponse.model_validate(raw)
        except ExecutionError:
            raise
        except Exception as error:
            raise ExecutionError(
                "response_contract_invalid",
                "Managed webhook response contract is invalid",
                transient=False,
            ) from error
        if success.operation_id != plan.operation_id:
            raise ExecutionError(
                "operation_id_mismatch",
                "Managed webhook operation ID mismatch",
                transient=False,
            )
        return ManagedWebhookPostJsonResult(
            result_type="managed_webhook.post_json.v1",
            status="succeeded",
            operation_id=success.operation_id,
            reference=success.result.reference,
            deduplicated=success.result.deduplicated,
            data=success.result.data,
        )

    @staticmethod
    async def _bounded_response(response: httpx.Response) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_WEBHOOK_RESPONSE_BYTES:
                raise ExecutionError(
                    "response_too_large",
                    "Managed webhook response is too large",
                    transient=False,
                )
        return bytes(content)

    @staticmethod
    def _map_response(
        plan: ManagedWebhookPostJsonPlan,
        response: httpx.Response,
        content: bytes,
    ) -> dict[str, object] | str:
        configured = plan.response
        if configured is None or configured.mapping is None:
            raise ExecutionError(
                "response_contract_invalid",
                "Managed webhook response configuration is invalid",
                transient=False,
            )
        content_type = response.headers.get("content-type", "")
        media_type = content_type.partition(";")[0].strip().lower()
        try:
            if configured.mode == "json":
                if media_type != "application/json" and not media_type.endswith(
                    "+json"
                ):
                    raise ValueError
                body: object = json.loads(content)
            elif configured.mode == "text":
                if media_type != "text/plain":
                    raise ValueError
                body = content.decode("utf-8")
            else:
                raise ValueError
        except (UnicodeDecodeError, ValueError) as error:
            raise ExecutionError(
                "response_contract_invalid",
                "Managed webhook response does not match the configured mode",
                transient=False,
            ) from error
        context = {
            "response": {
                "status_code": response.status_code,
                "content_type": media_type,
                "body": body,
            }
        }
        try:
            encoded = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode()) > MAX_WEBHOOK_RESPONSE_BYTES:
                raise ValueError
            mapped = jsonata.Jsonata(configured.mapping).evaluate(json.loads(encoded))
            output = json.dumps(mapped, ensure_ascii=False, separators=(",", ":"))
            if len(output.encode()) > MAX_WEBHOOK_RESPONSE_BYTES:
                raise ValueError
            decoded = json.loads(output)
            if not isinstance(decoded, (dict, str)):
                raise TypeError
        except Exception as error:
            raise ExecutionError(
                "response_mapping_failed",
                "Managed webhook response mapping failed",
                transient=False,
            ) from error
        return cast(dict[str, object] | str, decoded)

    @staticmethod
    def _validate_output(schema: dict[str, object], output: object) -> None:
        try:
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(
                output
            )
        except JsonSchemaValidationError as error:
            raise ExecutionError(
                "response_output_invalid",
                "Managed webhook semantic result is invalid",
                transient=False,
            ) from error

    @staticmethod
    def _bounded_payload(plan: ManagedWebhookPostJsonPlan) -> str:
        return json.dumps(plan.payload, ensure_ascii=False, separators=(",", ":"))

    async def _stream_payload(
        self,
        plan: ManagedWebhookPostJsonPlan,
        bodies: dict[str, AsyncIterator[bytes]],
    ) -> AsyncIterator[bytes]:
        async for chunk in self._stream_json(plan.payload, "", bodies):
            yield chunk

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
                    "Managed webhook artifact body is not UTF-8 text",
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


class GoogleSheetsAppendValuesHandler:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def execute(
        self, plan: GoogleSheetsAppendValuesPlan, material: RuntimeIntegrationMaterial
    ) -> GoogleSheetsAppendValuesResult:
        token = await self._access_token(plan, material)
        headers = {"Authorization": f"Bearer {token}"}
        lookup = self._range(plan.sheet_name, plan.idempotency.lookup_range)
        lookup_started = time.perf_counter()
        try:
            response = await self._client.get(
                self._values_url(plan.spreadsheet_id, lookup),
                headers=headers,
                params={"majorDimension": "ROWS"},
            )
            self._raise_provider_error(response, lookup=True)
            rows = response.json().get("values", [])
            for row_index, row in enumerate(rows, start=1):
                column = plan.idempotency.operation_id_column_index
                if len(row) > column and str(row[column]) == str(
                    plan.idempotency.operation_id
                ):
                    logger.info(
                        "capability_provider_idempotency_lookup_completed",
                        extra={
                            "plan_type": plan.plan_type,
                            "latency_ms": round(
                                (time.perf_counter() - lookup_started) * 1000
                            ),
                            "found": True,
                        },
                    )
                    return GoogleSheetsAppendValuesResult(
                        result_type=plan.plan_type,
                        status="succeeded",
                        updated_range=self._existing_range(plan, row_index),
                        updated_rows=1,
                        deduplicated=True,
                    )
            logger.info(
                "capability_provider_idempotency_lookup_completed",
                extra={
                    "plan_type": plan.plan_type,
                    "latency_ms": round((time.perf_counter() - lookup_started) * 1000),
                    "found": False,
                },
            )
            target = self._range(plan.sheet_name, plan.append_range)
            append_started = time.perf_counter()
            response = await self._client.post(
                f"{self._values_url(plan.spreadsheet_id, target)}:append",
                headers=headers,
                params={
                    "valueInputOption": plan.value_input_option,
                    "insertDataOption": "INSERT_ROWS",
                },
                json={"majorDimension": "ROWS", "values": plan.rows},
            )
            self._raise_provider_error(response, lookup=False)
            updates = response.json().get("updates", {})
            updated_range = updates.get("updatedRange")
            updated_rows = updates.get("updatedRows")
            if (
                not isinstance(updated_range, str)
                or not isinstance(updated_rows, int)
                or updated_rows < 1
            ):
                raise ExecutionError(
                    "provider_permanent_error",
                    "Google Sheets returned an invalid append result",
                    transient=False,
                )
            logger.info(
                "capability_provider_append_completed",
                extra={
                    "plan_type": plan.plan_type,
                    "latency_ms": round((time.perf_counter() - append_started) * 1000),
                    "status": "succeeded",
                },
            )
            return GoogleSheetsAppendValuesResult(
                result_type=plan.plan_type,
                status="succeeded",
                updated_range=updated_range,
                updated_rows=updated_rows,
                deduplicated=False,
            )
        except httpx.TimeoutException as error:
            raise ExecutionError(
                "provider_timeout", "Google Sheets request timed out", transient=True
            ) from error
        except httpx.TransportError as error:
            raise ExecutionError(
                "provider_transient_error",
                "Google Sheets transport failed",
                transient=True,
            ) from error

    @staticmethod
    async def _access_token(
        plan: GoogleSheetsAppendValuesPlan, material: RuntimeIntegrationMaterial
    ) -> str:
        account = (material.secret or {}).get("service_account")
        if (
            material.integration_id != plan.integration_id
            or material.provider != "google_sheets"
            or not isinstance(account, dict)
        ):
            raise ExecutionError(
                "integration_material_invalid",
                "Google Sheets integration material is invalid",
                transient=False,
            )
        try:
            credentials = service_account.Credentials.from_service_account_info(
                account, scopes=[SHEETS_SCOPE]
            )
            await asyncio.to_thread(credentials.refresh, GoogleAuthRequest())
        except Exception as error:
            raise ExecutionError(
                "credential_resolution_failed",
                "Google credential could not be refreshed",
                transient=False,
            ) from error
        if credentials.token is None:
            raise ExecutionError(
                "credential_resolution_failed",
                "Google credential returned no access token",
                transient=False,
            )
        return credentials.token

    @staticmethod
    def _range(sheet_name: str, cell_range: str) -> str:
        escaped = sheet_name.replace("'", "''")
        return f"'{escaped}'!{cell_range}"

    @staticmethod
    def _values_url(spreadsheet_id: str, cell_range: str) -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/{quote(cell_range, safe='')}"

    @staticmethod
    def _existing_range(plan: GoogleSheetsAppendValuesPlan, row_index: int) -> str:
        columns = plan.append_range.split(":", 1)
        start = re.sub(r"[^A-Za-z]", "", columns[0]) or "A"
        end = re.sub(r"[^A-Za-z]", "", columns[-1]) or start
        lookup_start = plan.idempotency.lookup_range.split(":", 1)[0]
        match = re.search(r"([1-9][0-9]*)$", lookup_start)
        sheet_row = row_index + (int(match.group(1)) - 1 if match else 0)
        return f"{plan.sheet_name}!{start}{sheet_row}:{end}{sheet_row}"

    @staticmethod
    def _raise_provider_error(response: httpx.Response, *, lookup: bool) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {401, 403}:
            code = "provider_authentication_failed"
            transient = False
        elif response.status_code == 429:
            code = "provider_rate_limited"
            transient = True
        elif response.status_code >= 500:
            code = "provider_transient_error"
            transient = True
        else:
            code = "idempotency_lookup_failed" if lookup else "provider_permanent_error"
            transient = False
        raise ExecutionError(
            code, "Google Sheets operation failed", transient=transient
        )


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
    ) -> RuntimeIntegrationMaterial:
        try:
            response = await self._client.get(
                f"{self._settings.backend_url}/internal/v1/capability-invocations/"
                f"{invocation_id}/integration-material",
                params={
                    "job_id": str(job_id),
                    "call_id": str(job.call_id) if job.call_id else None,
                    "execution_snapshot_id": str(job.execution_snapshot_id)
                    if job.execution_snapshot_id
                    else None,
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
    ) -> HttpRequestPlanV1:
        response = await self._client.get(
            f"{self._settings.backend_url}/internal/v1/calls/{call_id}/post-call-actions/{action_id}",
            params={
                "finalization_id": str(finalization_id),
                "command_id": str(command_id),
            },
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response.raise_for_status()
        return HttpRequestPlanV1.model_validate(response.json())

    async def post_call_action_material(
        self,
        call_id: UUID,
        finalization_id: UUID,
        action_id: str,
        command_id: UUID,
    ) -> RuntimeIntegrationMaterial:
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
    def _material_response(response: httpx.Response) -> RuntimeIntegrationMaterial:
        if response.is_error:
            raise ExecutionError(
                "integration_material_unavailable",
                "Integration material is unavailable",
                transient=response.status_code >= 500,
            )
        try:
            return RuntimeIntegrationMaterial.model_validate(response.json())
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


class CapabilityWorker:
    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        backend: BackendClient,
        sheets: GoogleSheetsAppendValuesHandler,
        webhooks: ManagedWebhookPostJsonHandler | None = None,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._settings = settings
        self._redis = redis
        self._backend = backend
        self._sheets = sheets
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
                "plan_type": job.execution_plan.plan_type,
                "attempt": job.attempt,
                "latency_ms": round((started - job.created_at).total_seconds() * 1000),
            },
        )
        provider_started = time.perf_counter()
        capability_name, capability_version, operation_id = _capability_identity(job)
        try:
            with domain_span(
                self._tracer,
                "capability.execute",
                {
                    "capability.name": capability_name,
                    "capability.version": capability_version,
                    "operation.id": operation_id,
                },
            ):
                plan_type = job.execution_plan.plan_type
                if plan_type not in {
                    "google_sheets.append_values.v1",
                    "http.request.v1",
                    "managed_webhook.post_json.v1",
                }:
                    raise ExecutionError(
                        "unknown_plan_type",
                        "Execution plan type is unsupported",
                        transient=False,
                    )
                logger.info(
                    "capability_provider_call_started",
                    extra={
                        "invocation_id": str(job.capability_invocation_id),
                        "job_id": str(job.job_id),
                        "plan_type": job.execution_plan.plan_type,
                        "attempt": job.attempt,
                    },
                )
                material = await self._backend.integration_material(
                    job.capability_invocation_id, job.job_id, job
                )
                result: (
                    GoogleSheetsAppendValuesResult
                    | HttpRequestResult
                    | ManagedWebhookPostJsonResult
                )
                if plan_type == "google_sheets.append_values.v1":
                    result = await self._sheets.execute(job.execution_plan, material)
                elif plan_type == "http.request.v1":
                    if self._webhooks is None:
                        raise ExecutionError(
                            "unknown_plan_type",
                            "HTTP handler is unavailable",
                            transient=False,
                        )
                    result = await self._webhooks.execute(job.execution_plan, material)
                elif plan_type == "managed_webhook.post_json.v1":
                    if self._webhooks is None:
                        raise ExecutionError(
                            "unknown_plan_type",
                            "Webhook handler is unavailable",
                            transient=False,
                        )
                    result = await self._webhooks.execute(job.execution_plan, material)
                else:
                    raise ExecutionError(
                        "unknown_plan_type",
                        "Webhook handler is unavailable",
                        transient=False,
                    )
                logger.info(
                    "capability_provider_call_completed",
                    extra={
                        "invocation_id": str(job.capability_invocation_id),
                        "job_id": str(job.job_id),
                        "plan_type": job.execution_plan.plan_type,
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
                        "plan_type": job.execution_plan.plan_type,
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
            provider_reference=(
                result.updated_range
                if isinstance(result, GoogleSheetsAppendValuesResult)
                else result.reference
            ),
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
    plan = job.execution_plan
    if isinstance(plan, HttpRequestPlanV1):
        capability = plan.capability or {}
        return (
            str(capability.get("semantic_key", "http")),
            str(capability.get("semantic_version", "v1")),
            str(plan.operation_id),
        )
    if isinstance(plan, ManagedWebhookPostJsonPlan):
        return (
            plan.capability.semantic_key,
            str(plan.capability.semantic_version),
            str(plan.operation_id),
        )
    return "google_sheets.append_values", "v1", str(plan.idempotency.operation_id)


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
            webhooks = ManagedWebhookPostJsonHandler(
                provider_client,
                allow_insecure=settings.allow_insecure_webhooks,
            )
            backend = BackendClient(
                settings, backend_client, RecordingStorage(settings)
            )
            worker = CapabilityWorker(
                settings,
                redis,
                backend,
                GoogleSheetsAppendValuesHandler(provider_client),
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
