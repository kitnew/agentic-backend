from uuid import UUID

import httpx
import pytest
from contracts import GoogleSheetsAppendValuesPlan, RuntimeIntegrationMaterial
from job_worker.worker import (
    ExecutionError,
)
from job_worker.worker import (
    GoogleSheetsAppendValuesHandler as WorkerGoogleSheetsAppendValuesHandler,
)


class Credentials:
    async def access_token(self, reference: str) -> str:
        assert reference == "tenant-sheets"
        return "token"


def plan() -> GoogleSheetsAppendValuesPlan:
    operation_id = UUID("00000000-0000-0000-0000-000000000001")
    return GoogleSheetsAppendValuesPlan(
        plan_type="google_sheets.append_values.v1",
        integration_id=UUID("00000000-0000-0000-0000-000000000002"),
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


def material(
    value: GoogleSheetsAppendValuesPlan | None = None,
) -> RuntimeIntegrationMaterial:
    return RuntimeIntegrationMaterial(
        integration_id=(value or plan()).integration_id,
        provider="google_sheets",
        config={},
        secret={"service_account": {"client_email": "test@example.test"}},
        credential_version=1,
    )


class GoogleSheetsAppendValuesHandler(WorkerGoogleSheetsAppendValuesHandler):
    def __init__(self, _credentials: Credentials, client: httpx.AsyncClient) -> None:
        super().__init__(client)

    @staticmethod
    async def _access_token(
        value: GoogleSheetsAppendValuesPlan, runtime: RuntimeIntegrationMaterial
    ) -> str:
        if value.integration_id != runtime.integration_id:
            raise ExecutionError(
                "integration_material_invalid",
                "Google Sheets integration material is invalid",
                transient=False,
            )
        return "token"

    async def execute(self, value: GoogleSheetsAppendValuesPlan):
        return await super().execute(value, material(value))


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


@pytest.mark.asyncio
async def test_reservations_new_preserves_phone_strings_and_hidden_operation_column() -> (
    None
):
    operation = plan().idempotency.operation_id
    reservation_plan = plan().model_copy(
        update={
            "append_range": "A:K",
            "rows": [
                [
                    "2026-08-08",
                    "2026-08-09",
                    "Nikita Černý",
                    "+421944015686",
                    "+421944015686",
                    "",
                    4,
                    1,
                    "",
                    False,
                    str(operation),
                ]
            ],
            "idempotency": plan().idempotency.model_copy(
                update={"lookup_range": "K:K", "operation_id_column_index": 10}
            ),
        }
    )
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"values": []})
        return httpx.Response(
            200,
            json={
                "updates": {
                    "updatedRange": "reservations_new!A42:K42",
                    "updatedRows": 1,
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await GoogleSheetsAppendValuesHandler(Credentials(), client).execute(
            reservation_plan
        )
    assert result.deduplicated is False
    assert requests[1].content and b"+421944015686" in requests[1].content
    assert b'"4"' not in requests[1].content


@pytest.mark.asyncio
async def test_missing_operation_appends_compiled_rows_payload() -> None:
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


@pytest.mark.asyncio
async def test_rate_limit_is_classified_as_transient() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ExecutionError) as captured:
            await GoogleSheetsAppendValuesHandler(Credentials(), client).execute(plan())  # type: ignore[arg-type]
    assert captured.value.code == "provider_rate_limited"
    assert captured.value.transient is True
