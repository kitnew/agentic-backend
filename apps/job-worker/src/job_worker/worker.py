import asyncio
import ipaddress
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote, urlparse

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
    allow_insecure_webhooks: bool = False
    credential_secrets_dir: str = "/run/secrets"
    provider_timeout_seconds: float = 10.0
    max_retries: int = 3
    stale_idle_ms: int = 30_000

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
        )


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
        root = Path(secrets_dir).resolve()
        if not root.is_absolute():
            raise ValueError("credential secrets directory must be absolute")
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
    def __init__(self, encoded_map: str, secrets_dir: str = "/run/secrets") -> None:
        try:
            value = json.loads(encoded_map)
        except json.JSONDecodeError as error:
            raise ValueError(
                "MANAGED_WEBHOOK_CONNECTION_MAP must be valid JSON"
            ) from error
        if not isinstance(value, dict):
            raise TypeError("MANAGED_WEBHOOK_CONNECTION_MAP must be an object")
        root = Path(secrets_dir).resolve()
        self._connections: dict[str, dict[str, object]] = {}
        for reference, raw in value.items():
            if not isinstance(reference, str) or not re.fullmatch(
                r"[a-z][a-z0-9_.-]{0,127}", reference
            ):
                raise ValueError("managed webhook map contains an invalid reference")
            if not isinstance(raw, dict):
                raise TypeError("managed webhook connection values must be objects")
            url_file = self._safe_path(raw.get("url_file"), root)
            api_key_file = self._safe_path(raw.get("api_key_file"), root)
            header = raw.get("api_key_header", "x-api-key")
            if not isinstance(header, str) or not re.fullmatch(
                r"[A-Za-z0-9-]{1,64}", header
            ):
                raise ValueError("managed webhook API key header is invalid")
            allowed_hosts = raw.get("allowed_hosts", [])
            if not isinstance(allowed_hosts, list) or not all(
                isinstance(host, str) and host for host in allowed_hosts
            ):
                raise ValueError("managed webhook allowed_hosts must be a string list")
            self._connections[reference] = {
                "url_file": url_file,
                "api_key_file": api_key_file,
                "api_key_header": header,
                "allowed_hosts": set(allowed_hosts),
            }

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

    def resolve(self, reference: str) -> tuple[str, str, str, set[str]]:
        connection = self._connections.get(reference)
        if connection is None:
            raise ExecutionError(
                "connection_resolution_failed",
                "Managed webhook connection could not be resolved",
                transient=False,
            )
        try:
            url = Path(str(connection["url_file"])).read_text(encoding="utf-8").strip()
            api_key = (
                Path(str(connection["api_key_file"]))
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError as error:
            raise ExecutionError(
                "credential_resolution_failed",
                "Managed webhook credentials could not be loaded",
                transient=False,
            ) from error
        if not url or not api_key:
            raise ExecutionError(
                "credential_resolution_failed",
                "Managed webhook credentials are empty",
                transient=False,
            )
        return (
            url,
            api_key,
            str(connection["api_key_header"]),
            connection["allowed_hosts"],  # type: ignore[return-value]
        )


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
        self, plan: ManagedWebhookPostJsonPlan
    ) -> ManagedWebhookPostJsonResult:
        url, api_key, header, allowed_hosts = self._connections.resolve(
            plan.connection_ref
        )
        parsed = urlparse(url)
        if parsed.scheme != "https" and not self._allow_insecure:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook requires HTTPS",
                transient=False,
            )
        if not parsed.hostname or parsed.username or parsed.password:
            raise ExecutionError(
                "provider_permanent_error",
                "Managed webhook URL is invalid",
                transient=False,
            )
        if not self._allow_insecure and parsed.hostname not in allowed_hosts:
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                address = None
            if address is not None and (
                address.is_private or address.is_loopback or address.is_link_local
            ):
                raise ExecutionError(
                    "provider_permanent_error",
                    "Managed webhook destination is not allowed",
                    transient=False,
                )
        envelope = {
            "contract_version": 1,
            "operation_id": str(plan.operation_id),
            "capability": plan.capability.model_dump(mode="json"),
            "payload": plan.payload,
        }
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 64_000:
            raise ExecutionError(
                "request_too_large",
                "Managed webhook request is too large",
                transient=False,
            )
        try:
            response = await self._client.post(
                url,
                headers={header: api_key, "Content-Type": "application/json"},
                content=encoded.encode(),
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
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            raise ExecutionError(
                "response_contract_invalid",
                "Managed webhook response must be JSON",
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
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _token(self) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": self._settings.consumer,
                "service": "job-worker",
                "aud": self._settings.backend_audience,
                "iat": now,
                "exp": now.timestamp() + 60,
                "scopes": ["capability-result:write"],
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
                "tenant_id": str(job.tenant_id),
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
                    "tenant_id": str(job.tenant_id),
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
                    "tenant_id": str(job.tenant_id),
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
                        "tenant_id": str(job.tenant_id),
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
                settings.managed_webhook_map_json, settings.credential_secrets_dir
            ),
            provider_client,
            allow_insecure=settings.allow_insecure_webhooks,
        )
        worker = CapabilityWorker(
            settings,
            redis,
            BackendClient(settings, backend_client),
            GoogleSheetsAppendValuesHandler(credentials, provider_client),
            webhooks,
        )
        try:
            await worker.run()
        finally:
            await redis.aclose()
