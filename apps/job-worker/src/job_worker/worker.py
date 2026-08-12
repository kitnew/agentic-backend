from __future__ import annotations

import asyncio
import codecs
import ipaddress
import json
import logging
import os
import re
import time
from base64 import b64encode
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
import jwt
from contracts import (
    GoogleSheetsAppendValuesPlan,
    GoogleSheetsAppendValuesResult,
    IntegrationJob,
    ManagedWebhookFailureResponse,
    ManagedWebhookPostJsonPlan,
    ManagedWebhookPostJsonResult,
    ManagedWebhookSuccessResponse,
    WorkerError,
    WorkerResultReport,
)
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from minio import Minio
from minio.error import MinioException
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


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
    credential_file_map_json: str
    managed_webhook_map_json: str = "{}"
    managed_webhook_map_file: str = "/secrets/managed-webhooks.json"
    allow_insecure_webhooks: bool = False
    credential_secrets_dir: str = "/run/secrets"
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
            credential_file_map_json=os.getenv(
                "GOOGLE_SHEETS_CREDENTIAL_FILE_MAP", "{}"
            ),
            managed_webhook_map_json=os.getenv("MANAGED_WEBHOOK_CONNECTION_MAP", "{}"),
            managed_webhook_map_file=os.getenv(
                "MANAGED_WEBHOOK_CONNECTION_MAP_FILE", "/secrets/managed-webhooks.json"
            ),
            allow_insecure_webhooks=os.getenv(
                "ALLOW_INSECURE_MANAGED_WEBHOOKS", "false"
            ).lower()
            == "true",
            credential_secrets_dir=os.getenv(
                "GOOGLE_SHEETS_CREDENTIAL_SECRETS_DIR", "/run/secrets"
            ),
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

    async def base64(self, storage_key: str) -> AsyncIterator[bytes]:
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
            while chunk := response.read(64 * 1024):
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


class MountedSecretFileCredentialResolver:
    def __init__(self, encoded_map: str, secrets_dir: str = "/run/secrets") -> None:
        try:
            value = json.loads(encoded_map)
        except json.JSONDecodeError as error:
            raise ValueError(
                "GOOGLE_SHEETS_CREDENTIAL_FILE_MAP must be valid JSON"
            ) from error
        if not isinstance(value, dict):
            raise TypeError("GOOGLE_SHEETS_CREDENTIAL_FILE_MAP must be an object")
        if not Path(secrets_dir).is_absolute():
            raise ValueError("credential secrets directory must be absolute")
        root = Path(secrets_dir).resolve()
        self._credential_files: dict[str, Path] = {}
        for key, credential_path in value.items():
            if not isinstance(key, str) or not re.fullmatch(
                r"[a-z][a-z0-9_.-]{0,127}", key
            ):
                raise ValueError("credential map contains an invalid reference")
            if not isinstance(credential_path, str):
                raise TypeError("credential map values must be file paths")
            path = Path(credential_path)
            if not path.is_absolute():
                raise ValueError("credential file paths must be absolute")
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError(
                    "credential file must be under the secrets directory"
                ) from error
            self._credential_files[key] = resolved

    async def access_token(self, reference: str) -> str:
        credential_path = self._credential_files.get(reference)
        if credential_path is None:
            raise ExecutionError(
                "credential_resolution_failed",
                "Credential reference could not be resolved",
                transient=False,
            )
        try:
            credentials = service_account.Credentials.from_service_account_file(
                str(credential_path),
                scopes=[SHEETS_SCOPE],
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


class ManagedWebhookConnectionResolver:
    def __init__(
        self,
        encoded_map: str,
        secrets_dir: str = "/run/secrets",
        map_file: str | None = None,
    ) -> None:
        if map_file:
            try:
                encoded_map = Path(map_file).read_text(encoding="utf-8")
            except FileNotFoundError:
                pass
            except OSError as error:
                raise ValueError(
                    "managed webhook connection map file could not be read"
                ) from error
        try:
            value = json.loads(encoded_map)
        except json.JSONDecodeError as error:
            raise ValueError(
                "MANAGED_WEBHOOK_CONNECTION_MAP must be valid JSON"
            ) from error
        if not isinstance(value, dict):
            raise TypeError("MANAGED_WEBHOOK_CONNECTION_MAP must be an object")
        if not Path(secrets_dir).is_absolute():
            raise ValueError("managed webhook secrets directory must be absolute")
        self._root = Path(secrets_dir).resolve()
        self._connections: dict[str, ManagedWebhookConnectionConfig] = {}
        for reference, raw in value.items():
            if not isinstance(reference, str) or not re.fullmatch(
                r"[a-z][a-z0-9_.-]{0,127}", reference
            ):
                raise ValueError("managed webhook map contains an invalid reference")
            if not isinstance(raw, dict):
                raise TypeError("managed webhook connection values must be objects")
            url_file = self._safe_path(raw.get("url_file"), self._root)
            raw_api_key_file = raw.get("api_key_file")
            api_key_file = (
                self._safe_path(raw_api_key_file, self._root)
                if raw_api_key_file is not None
                else None
            )
            header = raw.get("api_key_header", "x-api-key")
            if not isinstance(header, str) or not re.fullmatch(
                r"[A-Za-z0-9-]{1,64}", header
            ):
                raise ValueError("managed webhook API key header is invalid")
            allowed_hosts = raw.get("allowed_hosts")
            if not isinstance(allowed_hosts, list) or not allowed_hosts:
                raise ValueError("managed webhook allowed_hosts must be a string list")
            self._connections[reference] = ManagedWebhookConnectionConfig(
                url_file=url_file,
                api_key_file=api_key_file,
                api_key_header=header,
                allowed_hosts=frozenset(
                    self._normalized_hostname(host) for host in allowed_hosts
                ),
            )

    @staticmethod
    def _safe_path(value: object, root: Path) -> Path:
        if not isinstance(value, str) or not value:
            raise TypeError("managed webhook secret file is required")
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("managed webhook secret file must be absolute")
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "managed webhook secret file must be under secrets directory"
            ) from error
        return resolved

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

    def _read_secret(self, path: Path) -> str:
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self._root)
            return resolved.read_text(encoding="utf-8").strip()
        except (OSError, ValueError) as error:
            raise ExecutionError(
                "credential_resolution_failed",
                "Managed webhook credentials could not be loaded",
                transient=False,
            ) from error

    def resolve(self, reference: str) -> ResolvedManagedWebhookConnection:
        connection = self._connections.get(reference)
        if connection is None:
            raise ExecutionError(
                "connection_resolution_failed",
                "Managed webhook connection could not be resolved",
                transient=False,
            )
        url = self._read_secret(connection.url_file)
        api_key = (
            self._read_secret(connection.api_key_file)
            if connection.api_key_file is not None
            else ""
        )
        if not url or connection.api_key_file is not None and not api_key:
            raise ExecutionError(
                "credential_resolution_failed",
                "Managed webhook credentials are empty",
                transient=False,
            )
        return ResolvedManagedWebhookConnection(
            url=url,
            api_key=api_key,
            api_key_header=connection.api_key_header,
            allowed_hosts=connection.allowed_hosts,
        )


@dataclass(frozen=True)
class ManagedWebhookConnectionConfig:
    url_file: Path
    api_key_file: Path | None
    api_key_header: str
    allowed_hosts: frozenset[str]


@dataclass(frozen=True)
class ResolvedManagedWebhookConnection:
    url: str
    api_key: str
    api_key_header: str
    allowed_hosts: frozenset[str]


class CredentialResolver(Protocol):
    async def access_token(self, reference: str) -> str: ...


class ManagedWebhookPostJsonHandler:
    def __init__(
        self,
        connections: ManagedWebhookConnectionResolver,
        client: httpx.AsyncClient,
        *,
        allow_insecure: bool = False,
    ) -> None:
        self._connections = connections
        self._client = client
        self._allow_insecure = allow_insecure

    async def execute(
        self,
        plan: ManagedWebhookPostJsonPlan,
        bodies: dict[str, AsyncIterator[bytes]] | None = None,
    ) -> ManagedWebhookPostJsonResult:
        connection = self._connections.resolve(plan.connection_ref)
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
            hostname = self._connections._normalized_hostname(parsed.hostname)
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
        headers = {
            "Content-Type": "application/json",
            "X-Operation-Id": str(plan.operation_id),
        }
        if connection.api_key:
            headers[connection.api_key_header] = connection.api_key
        try:
            response = await self._client.post(
                connection.url,
                headers=headers,
                content=content,
                timeout=plan.timeout_seconds,
                follow_redirects=False,
            )
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
        if len(response.content) > 64_000:
            raise ExecutionError(
                "response_too_large",
                "Managed webhook response is too large",
                transient=False,
            )
        if (
            response.status_code == 429
            or response.status_code in {408}
            or response.status_code >= 500
        ):
            raise ExecutionError(
                "provider_transient_error",
                "Managed webhook returned a retryable error",
                transient=True,
            )
        if response.status_code in {400, 401, 403, 404, 410}:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook rejected the request",
                transient=False,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook returned an unsupported status",
                transient=False,
            )
        if plan.response_contract == "http_2xx":
            return ManagedWebhookPostJsonResult(
                result_type="managed_webhook.post_json.v1",
                status="succeeded",
                operation_id=plan.operation_id,
                reference=None,
                deduplicated=False,
            )
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            raise ExecutionError(
                "response_contract_invalid",
                "Managed webhook response must be JSON",
                transient=False,
            )
        try:
            raw = response.json()
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
    def __init__(
        self,
        credentials: CredentialResolver,
        client: httpx.AsyncClient,
    ) -> None:
        self._credentials = credentials
        self._client = client

    async def execute(
        self, plan: GoogleSheetsAppendValuesPlan
    ) -> GoogleSheetsAppendValuesResult:
        token = await self._credentials.access_token(plan.credential_ref)
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
    ) -> ManagedWebhookPostJsonPlan:
        response = await self._client.get(
            f"{self._settings.backend_url}/internal/v1/calls/{call_id}/post-call-actions/{action_id}",
            params={
                "finalization_id": str(finalization_id),
                "command_id": str(command_id),
            },
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response.raise_for_status()
        return ManagedWebhookPostJsonPlan.model_validate(response.json())

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
            if not isinstance(storage_key, str) or not storage_key:
                raise ExecutionError(
                    "recording_source_invalid",
                    "Recording source is invalid",
                    transient=False,
                )
            async for chunk in self._recording_storage.base64(storage_key):
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
            async for chunk in response.aiter_bytes():
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
    ) -> None:
        self._settings = settings
        self._redis = redis
        self._backend = backend
        self._sheets = sheets
        self._webhooks = webhooks

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
        try:
            job = IntegrationJob.model_validate_json(fields["job"])
        except KeyError, ValidationError:
            await self._dead_letter(message_id, None, "invalid_execution_plan")
            return
        if job.expires_at <= datetime.now(UTC):
            await self._report_failure(
                message_id, job, "job_expired", "Capability job expired", False
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
        try:
            if job.execution_plan.plan_type not in {
                "google_sheets.append_values.v1",
                "managed_webhook.post_json.v1",
            }:
                raise ExecutionError(
                    "unknown_plan_type",
                    "Execution plan type is unsupported",
                    transient=False,
                )
            provider_started = time.perf_counter()
            logger.info(
                "capability_provider_call_started",
                extra={
                    "invocation_id": str(job.capability_invocation_id),
                    "job_id": str(job.job_id),
                    "plan_type": job.execution_plan.plan_type,
                    "attempt": job.attempt,
                },
            )
            result: GoogleSheetsAppendValuesResult | ManagedWebhookPostJsonResult
            if job.execution_plan.plan_type == "google_sheets.append_values.v1":
                result = await self._sheets.execute(job.execution_plan)
            elif self._webhooks is not None:
                result = await self._webhooks.execute(job.execution_plan)
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
            if error.transient and job.attempt <= self._settings.max_retries:
                retried = job.model_copy(update={"attempt": job.attempt + 1})
                await self._redis.xadd(
                    self._settings.stream,
                    {"job": retried.model_dump_json()},
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
            )
            return
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

    async def _report_failure(
        self,
        message_id: str,
        job: IntegrationJob,
        code: str,
        message: str,
        transient: bool,
        started_at: datetime | None = None,
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
        await self._dead_letter(message_id, job, code)

    async def _dead_letter(
        self, message_id: str, job: IntegrationJob | None, error_code: str
    ) -> None:
        await self._redis.xadd(
            self._settings.dead_letter_stream,
            {
                "source_message_id": message_id,
                "job_id": str(job.job_id) if job else "unknown",
                "invocation_id": str(job.capability_invocation_id)
                if job
                else "unknown",
                "error_code": error_code,
            },
        )
        await self._redis.xack(self._settings.stream, self._settings.group, message_id)


async def run_worker(settings: Settings) -> None:
    from job_worker.command_worker import (
        CommandWorker,
        ExecutePostCallActionHandler,
        GenerateCallSummaryHandler,
        MaterializeArtifactRepresentationHandler,
    )

    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=None,
    )
    async with (
        httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as provider_client,
        httpx.AsyncClient(timeout=10.0) as backend_client,
    ):
        credentials = MountedSecretFileCredentialResolver(
            settings.credential_file_map_json, settings.credential_secrets_dir
        )
        webhooks = ManagedWebhookPostJsonHandler(
            ManagedWebhookConnectionResolver(
                settings.managed_webhook_map_json,
                settings.credential_secrets_dir,
                settings.managed_webhook_map_file,
            ),
            provider_client,
            allow_insecure=settings.allow_insecure_webhooks,
        )
        backend = BackendClient(settings, backend_client, RecordingStorage(settings))
        worker = CapabilityWorker(
            settings,
            redis,
            backend,
            GoogleSheetsAppendValuesHandler(credentials, provider_client),
            webhooks,
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
        )
        try:
            await asyncio.gather(worker.run(), command_worker.run())
        finally:
            await redis.aclose()
