from uuid import UUID

import httpx
import pytest
from contracts import GoogleSheetsAppendValuesPlan
from job_worker.worker import (
    ExecutionError,
    GoogleSheetsAppendValuesHandler,
    MountedSecretFileCredentialResolver,
)


class Credentials:
    async def access_token(self, reference: str) -> str:
        assert reference == "tenant-sheets"
        return "token"


def plan() -> GoogleSheetsAppendValuesPlan:
    operation_id = UUID("00000000-0000-0000-0000-000000000001")
    return GoogleSheetsAppendValuesPlan(
        plan_type="google_sheets.append_values.v1",
        credential_ref="tenant-sheets",
        spreadsheet_id="sheet-id",
        sheet_name="Reservations",
        append_range="A:D",
        value_input_option="RAW",
        rows=[[str(operation_id), "Alice", "2026-08-12", "2026-08-15"]],
        idempotency={
            "operation_id": operation_id,
            "lookup_range": "A:A",
            "operation_id_column_index": 0,
        },
    )


@pytest.mark.asyncio
async def test_credential_refs_are_allowlisted() -> None:
    resolver = MountedSecretFileCredentialResolver("{}")
    with pytest.raises(ExecutionError) as captured:
        await resolver.access_token("unknown")
    assert captured.value.code == "credential_resolution_failed"
    with pytest.raises(ValueError, match="invalid reference"):
        MountedSecretFileCredentialResolver('{"ENV NAME": {}}')


@pytest.mark.asyncio
async def test_existing_operation_is_deduplicated_without_append() -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"values": [[str(plan().idempotency.operation_id)]]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await GoogleSheetsAppendValuesHandler(Credentials(), client).execute(
            plan()
        )  # type: ignore[arg-type]
    assert result.deduplicated is True
    assert result.updated_range == "Reservations!A1:D1"
    assert [request.method for request in requests] == ["GET"]


@pytest.mark.asyncio
async def test_deduplicated_range_accounts_for_lookup_row_offset() -> None:
    value = plan().model_copy(
        update={
            "idempotency": plan().idempotency.model_copy(
                update={"lookup_range": "A2:A"}
            )
        }
    )

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"values": [[str(value.idempotency.operation_id)]]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await GoogleSheetsAppendValuesHandler(Credentials(), client).execute(
            value
        )  # type: ignore[arg-type]
    assert result.updated_range == "Reservations!A2:D2"


@pytest.mark.asyncio
async def test_missing_operation_appends_compiled_rows() -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"values": []})
        return httpx.Response(
            200,
            json={
                "updates": {"updatedRange": "Reservations!A42:D42", "updatedRows": 1}
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await GoogleSheetsAppendValuesHandler(Credentials(), client).execute(
            plan()
        )  # type: ignore[arg-type]
    assert result.deduplicated is False
    assert result.updated_range == "Reservations!A42:D42"
    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[1].read() == (
        b'{"majorDimension":"ROWS","values":[["00000000-0000-0000-0000-000000000001",'
        b'"Alice","2026-08-12","2026-08-15"]]}'
    )


@pytest.mark.asyncio
async def test_rate_limit_is_classified_as_transient() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ExecutionError) as captured:
            await GoogleSheetsAppendValuesHandler(Credentials(), client).execute(plan())  # type: ignore[arg-type]
    assert captured.value.code == "provider_rate_limited"
    assert captured.value.transient is True
