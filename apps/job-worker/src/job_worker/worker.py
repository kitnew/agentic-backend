import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote

import httpx
import jwt
from contracts import (
    GoogleSheetsAppendValuesPlan,
    GoogleSheetsAppendValuesResult,
    IntegrationJob,
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
            credential_file_map_json=os.getenv("GOOGLE_SHEETS_CREDENTIAL_FILE_MAP", "{}"),
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
                raise ValueError("credential file must be under the secrets directory") from error
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


class CredentialResolver(Protocol):
    async def access_token(self, reference: str) -> str: ...


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
    ) -> None:
        self._settings = settings
        self._redis = redis
        self._backend = backend
        self._sheets = sheets

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
            if job.execution_plan.plan_type != "google_sheets.append_values.v1":
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
            result = await self._sheets.execute(job.execution_plan)
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
            provider_reference=result.updated_range,
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
        worker = CapabilityWorker(
            settings,
            redis,
            BackendClient(settings, backend_client),
            GoogleSheetsAppendValuesHandler(credentials, provider_client),
        )
        try:
            await worker.run()
        finally:
            await redis.aclose()
