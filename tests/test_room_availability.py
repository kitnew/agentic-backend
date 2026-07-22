import json
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.application.capabilities.executor import BackendCapabilityExecutor
from app.capabilities.providers.google_sheets import GoogleSheetsReservationProvider
from app.capabilities.registry import CapabilityRegistry
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import (
    GoogleSheetsReadRequest,
    GoogleSheetsReadResult,
)
from app.tenants.loader import TenantConfigLoader
from app.tenants.schemas import TenantContext, spreadsheet_column_span
from app.tenants.policies import stay_nights


TABLE_WIDTH = 31


def availability_row(date_value, *, free_columns=(), values=None):
    row = ["occupied"] * TABLE_WIDTH
    row[0] = date_value
    row[1:4] = [999, 999, 999]
    for column in free_columns:
        start, _ = spreadsheet_column_span(f"{column}:{column}")
        row[start] = ""
    for column, value in (values or {}).items():
        start, _ = spreadsheet_column_span(f"{column}:{column}")
        row[start] = value
    return row


def table(*rows):
    return [["header"] * TABLE_WIDTH, *rows]


class FakeGoogleSheetsClient:
    def __init__(self, values=None, error=None):
        self.values = values or []
        self.error = error
        self.read_requests = []
        self.append_calls = 0

    def read_values(self, request):
        self.read_requests.append(request)
        if self.error:
            raise self.error
        return GoogleSheetsReadResult(values=self.values)

    def append_row(self, _request):
        self.append_calls += 1
        raise AssertionError("availability must never write to Google Sheets")


def execute(values, **request_values):
    tenant = TenantConfigLoader().load("penzion_grand")
    client = FakeGoogleSheetsClient(values)
    result = GoogleSheetsReservationProvider(client).execute(
        tenant,
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "check_in": "2026-08-10",
                "check_out": "2026-08-12",
                "room_type": "two_bed",
                "room_count": 1,
                **request_values,
            },
        ),
    )
    assert client.append_calls == 0
    return result


class CountingAvailabilityProvider:
    provider_name = "google_sheets"

    def __init__(self):
        self.calls = []

    def execute(self, tenant_context, request):
        self.calls.append(request)
        return CapabilityResult(
            name=request.name,
            status=CapabilityStatus.SUCCESS,
            provider=self.provider_name,
            output={"status": "available"},
        )


def routed_availability(check_in, clock, *, language=None):
    tenant = TenantConfigLoader().load("penzion_grand")
    provider = CountingAvailabilityProvider()
    registry = CapabilityRegistry()
    registry.providers["google_sheets"] = provider
    result = CapabilityRouter(registry, clock=clock).execute(
        tenant,
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "check_in": check_in,
                "check_out": "2026-07-22",
                "room_type": "two_bed",
                "room_count": 1,
            },
            metadata={"language": language} if language else None,
        ),
    )
    return result, provider


def test_one_room_continuously_free_is_available():
    result = execute(
        table(
            availability_row("2026-08-10", free_columns=["E"]),
            availability_row("2026-08-11", free_columns=["E"]),
        )
    )

    assert result.output == {
        "status": "available",
        "room_type": "two_bed",
        "check_in": "2026-08-10",
        "check_out": "2026-08-12",
        "requested_rooms": 1,
        "available_rooms": 1,
    }
    assert "rezervované ani blokované" in result.user_message


def test_different_free_room_each_night_is_unavailable():
    result = execute(
        table(
            availability_row("2026-08-10", free_columns=["E"]),
            availability_row("2026-08-11", free_columns=["F"]),
        )
    )

    assert result.output["status"] == "unavailable"
    assert result.output["available_rooms"] == 0


@pytest.mark.parametrize(
    ("free_columns", "expected_status", "available_rooms"),
    [(["E", "F"], "available", 2), (["E"], "unavailable", 1)],
)
def test_multiple_rooms_require_distinct_continuously_free_columns(
    free_columns, expected_status, available_rooms
):
    result = execute(
        table(
            availability_row("2026-08-10", free_columns=free_columns),
            availability_row("2026-08-11", free_columns=free_columns),
        ),
        room_count=2,
    )

    assert result.output["status"] == expected_status
    assert result.output["available_rooms"] == available_rooms


def test_checkout_date_is_excluded():
    result = execute(
        table(
            availability_row("2026-07-29", free_columns=["E"]),
            availability_row("2026-07-30", free_columns=["E"]),
            availability_row("2026-07-31"),
        ),
        check_in="2026-07-29",
        check_out="2026-07-31",
    )

    assert result.output["status"] == "available"


def test_checkout_row_may_be_absent():
    result = execute(
        table(
            availability_row("2026-07-29", free_columns=["E"]),
            availability_row("2026-07-30", free_columns=["E"]),
        ),
        check_in="2026-07-29",
        check_out="2026-07-31",
    )

    assert result.output["status"] == "available"
    assert stay_nights(date(2026, 7, 29), date(2026, 7, 31)) == (
        date(2026, 7, 29),
        date(2026, 7, 30),
    )


def test_missing_actual_stay_night_is_data_not_covered():
    result = execute(
        table(availability_row("2026-07-29", free_columns=["E"])),
        check_in="2026-07-29",
        check_out="2026-07-31",
    )

    assert result.output["status"] == "data_not_covered"


def test_one_night_stay_checks_exactly_one_date():
    result = execute(
        table(availability_row("2026-08-10", free_columns=["E"])),
        check_out="2026-08-11",
    )

    assert result.output["status"] == "available"
    assert stay_nights(date(2026, 8, 10), date(2026, 8, 11)) == (
        date(2026, 8, 10),
    )


@pytest.mark.parametrize(
    ("check_in", "expected_status", "provider_calls"),
    [
        ("2026-07-19", "skipped", 0),
        ("2026-07-20", "success", 1),
        ("2026-07-21", "success", 1),
    ],
)
def test_past_today_and_future_check_in_validation(
    check_in, expected_status, provider_calls
):
    result, provider = routed_availability(
        check_in,
        lambda: datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
    )

    assert result.status == expected_status
    assert len(provider.calls) == provider_calls
    if expected_status == "skipped":
        assert result.error == "past_check_in_not_allowed"
        assert result.provider == "validation"
        assert result.output is None


def test_past_validation_uses_bratislava_date_at_utc_boundary():
    result, provider = routed_availability(
        "2026-07-19",
        lambda: datetime(2026, 7, 19, 22, 30, tzinfo=timezone.utc),
    )

    assert result.status == "skipped"
    assert result.error == "past_check_in_not_allowed"
    assert provider.calls == []


def test_past_validation_uses_localized_guest_message():
    result, provider = routed_availability(
        "2026-07-19",
        lambda: datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
        language="en-GB",
    )

    assert result.user_message == "I can only check availability for today or a future date."
    assert "past_check_in_not_allowed" not in result.user_message
    assert provider.calls == []


@pytest.mark.parametrize(
    ("check_in", "check_out"),
    [(date(2026, 7, 20), date(2026, 7, 20)), (date(2026, 7, 21), date(2026, 7, 20))],
)
def test_stay_nights_rejects_invalid_intervals(check_in, check_out):
    with pytest.raises(ValueError, match="check_out must be later"):
        stay_nights(check_in, check_out)


@pytest.mark.parametrize(
    "rows",
    [
        [availability_row("2026-08-10", free_columns=["E"])],
        [availability_row("2026-09-01", free_columns=["E"])],
    ],
)
def test_missing_or_outside_dates_are_data_not_covered(rows):
    result = execute(table(*rows))

    assert result.output["status"] == "data_not_covered"
    assert result.output["available_rooms"] is None


@pytest.mark.parametrize(
    ("cell_value", "expected_status"),
    [
        ("", "available"),
        ("   ", "available"),
        ("//", "unavailable"),
        ("Private Guest", "unavailable"),
        (12345, "unavailable"),
        ("formula result", "unavailable"),
    ],
)
def test_room_cell_interpretation(cell_value, expected_status):
    result = execute(
        table(availability_row("2026-08-10", values={"E": cell_value})),
        check_out="2026-08-11",
    )

    assert result.output["status"] == expected_status


def test_trailing_omitted_cells_are_padded_as_free():
    result = execute(
        table(["2026-08-10", 0, 0, 0]),
        check_out="2026-08-11",
    )

    assert result.output["status"] == "available"
    assert result.output["available_rooms"] == 19


def test_duplicate_dates_are_rejected_without_raw_cells_in_error():
    result = execute(
        table(
            availability_row("2026-08-10", values={"E": "PRIVATE-GUEST"}),
            availability_row("2026-08-10", free_columns=["E"]),
        ),
        check_out="2026-08-11",
    )

    assert result.status == "failed"
    assert "Duplicate availability date" in result.error
    assert "PRIVATE-GUEST" not in result.error


@pytest.mark.parametrize("date_value", ["not-a-date", 1.5, True])
def test_malformed_dates_are_provider_errors(date_value):
    result = execute(
        table(availability_row(date_value, values={"E": "PRIVATE-GUEST"})),
        check_out="2026-08-11",
    )

    assert result.status == "failed"
    assert result.output is None
    assert result.error == "Malformed date in availability row 2."
    assert "PRIVATE-GUEST" not in result.error


@pytest.mark.parametrize(
    "sheet_date",
    [
        "10.08.2026",
        (date(2026, 8, 10) - date(1899, 12, 30)).days,
    ],
)
def test_configured_date_formats_and_spreadsheet_serial_are_supported(sheet_date):
    result = execute(
        table(availability_row(sheet_date, free_columns=["E"])),
        check_out="2026-08-11",
    )

    assert result.output["status"] == "available"


@pytest.mark.parametrize(
    "overrides",
    [
        {"room_type": "twin"},
        {"check_out": "2026-08-10"},
        {"check_out": "2026-08-09"},
        {"room_count": 0},
        {"room_count": -1},
    ],
)
def test_invalid_requests_fail_without_reading(overrides):
    tenant = TenantConfigLoader().load("penzion_grand")
    client = FakeGoogleSheetsClient(error=AssertionError("must not read"))
    result = GoogleSheetsReservationProvider(client).execute(
        tenant,
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "check_in": "2026-08-10",
                "check_out": "2026-08-12",
                "room_type": "two_bed",
                "room_count": 1,
                **overrides,
            },
        ),
    )

    assert result.status == "failed"
    assert client.read_requests == []


def test_inventory_range_width_mismatch_is_rejected():
    tenant_data = TenantConfigLoader().load("penzion_grand").model_dump()
    tenant_data["capabilities"]["reservation.check_availability"]["config"][
        "room_type_columns"
    ]["two_bed"] = "E:V"

    with pytest.raises(ValidationError, match="width does not match two_bed inventory"):
        TenantContext.model_validate(tenant_data)


def test_unsupported_stay_interval_is_rejected():
    tenant_data = TenantConfigLoader().load("penzion_grand").model_dump()
    tenant_data["capabilities"]["reservation.check_availability"]["config"][
        "stay_interval"
    ] = "check_in_and_check_out_inclusive"

    with pytest.raises(ValidationError, match="stay_interval"):
        TenantContext.model_validate(tenant_data)


def test_penzion_grand_column_mapping_and_aggregates():
    config = TenantConfigLoader().load("penzion_grand").availability_config

    assert spreadsheet_column_span(config.room_type_columns["two_bed"]) == (4, 22)
    assert spreadsheet_column_span(config.room_type_columns["three_bed"]) == (23, 24)
    assert spreadsheet_column_span(config.room_type_columns["four_bed"]) == (25, 30)

    first = availability_row("2026-08-10", free_columns=["E"])
    second = availability_row("2026-08-11", free_columns=["E"])
    first[1:4] = [0, 0, 0]
    second[1:4] = [999, 999, 999]
    assert execute(table(first, second)).output["status"] == "available"


@pytest.mark.parametrize(
    "source_error",
    [
        TimeoutError("PRIVATE-GUEST"),
        PermissionError("PRIVATE-GUEST"),
        RuntimeError("PRIVATE-GUEST"),
    ],
)
def test_provider_failure_is_not_unavailability_and_hides_source_values(source_error):
    tenant = TenantConfigLoader().load("penzion_grand")
    client = FakeGoogleSheetsClient(error=source_error)
    result = GoogleSheetsReservationProvider(client).execute(
        tenant,
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "check_in": "2026-08-10",
                "check_out": "2026-08-12",
                "room_type": "two_bed",
                "room_count": 1,
            },
        ),
    )

    assert result.status == "failed"
    assert result.output is None
    assert "PRIVATE-GUEST" not in result.error


def test_safe_result_is_all_that_is_persisted_and_tenant_id_is_trusted():
    tenant = TenantConfigLoader().load("penzion_grand")
    provider = GoogleSheetsReservationProvider(
        FakeGoogleSheetsClient(
            table(availability_row("2026-08-10", values={"E": "PRIVATE-GUEST"}))
        )
    )
    registry = CapabilityRegistry()
    registry.providers["google_sheets"] = provider
    repository = type(
        "Repository",
        (),
        {"calls": [], "create": lambda self, call: self.calls.append(call) or call},
    )()
    executor = BackendCapabilityExecutor(
        tenant_context=tenant,
        message=Message(
            id="message-1",
            tenant_id="penzion_grand",
            conversation_id="conversation-1",
            channel="chat",
            role=MessageRole.USER,
            content="availability request",
            status=MessageStatus.PROCESSING,
            created_at=datetime.now(),
        ),
        capability_router=CapabilityRouter(registry),
        tool_call_repository=repository,
    )

    execution = executor.execute(
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "tenant_id": "untrusted-tenant",
                "check_in": "2026-08-10",
                "check_out": "2026-08-11",
                "room_type": "two_bed",
                "room_count": 1,
            },
        )
    )

    persisted = repository.calls[0]
    assert execution.request.input["tenant_id"] == "penzion_grand"
    assert persisted.input["tenant_id"] == "penzion_grand"
    assert "PRIVATE-GUEST" not in json.dumps(persisted.model_dump(mode="json"))
    assert "PRIVATE-GUEST" not in json.dumps(execution.result.model_dump(mode="json"))


def test_google_sheets_client_read_boundary_is_one_read_only_request(monkeypatch):
    calls = []

    class Request:
        def execute(self):
            return {"values": [["Date"], ["2026-08-10"]]}

    class Values:
        def get(self, **kwargs):
            calls.append(kwargs)
            return Request()

    class Service:
        def spreadsheets(self):
            return self

        def values(self):
            return Values()

    client = GoogleSheetsClient("/tmp/not-read.json")
    scopes = []
    monkeypatch.setattr(
        client,
        "_build_service",
        lambda selected_scopes: scopes.extend(selected_scopes) or Service(),
    )

    result = client.read_values(
        GoogleSheetsReadRequest(
            spreadsheet_id="sheet-id",
            sheet_name="availability",
            table_range="A:AE",
        )
    )

    assert result.values == [["Date"], ["2026-08-10"]]
    assert scopes == ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    assert calls == [
        {
            "spreadsheetId": "sheet-id",
            "range": "availability!A:AE",
            "majorDimension": "ROWS",
            "valueRenderOption": "UNFORMATTED_VALUE",
            "dateTimeRenderOption": "SERIAL_NUMBER",
        }
    ]
